"""Worker subprocess (ADR-0002): runs the engine, streams events to the server.

One worker per accepted run. Connects back to the server over a local WebSocket,
sends AG-UI-shaped JSON events, waits for approval decisions on interactive
gates, and exits when the run ends. Being a separate process means a wedged run
dies alone and kill = cancel.

All worker→server traffic flows through ONE sender task — concurrent ws.send
calls from multiple tasks can interleave frames and corrupt the event stream.
"""

import argparse
import asyncio
import json
import logging
import sys

import websockets

from .events import TERMINAL_EVENTS


async def _resolve_model(name: str | None):
    if not name:
        return None
    # Test hook: deterministic scripted models so subprocess tests need no keys.
    if name == 'codingdude-test:echo':
        from pydantic_ai.messages import ModelResponse, TextPart
        from pydantic_ai.models.function import FunctionModel

        def echo(messages, info):
            return ModelResponse(parts=[TextPart(content='worker-echo-ok')])

        async def echo_stream(messages, info):
            yield 'worker-echo-ok'

        return FunctionModel(echo, stream_function=echo_stream, model_name='test-echo')
    if name == 'codingdude-test:sleep':
        import asyncio as _aio

        from pydantic_ai.messages import ModelResponse as MR
        from pydantic_ai.messages import TextPart as TP
        from pydantic_ai.models.function import FunctionModel

        async def sleepy(messages, info):
            await _aio.sleep(60)
            return MR(parts=[TP(content='finally')])

        async def sleepy_stream(messages, info):
            await _aio.sleep(60)
            yield 'finally'

        return FunctionModel(sleepy, stream_function=sleepy_stream, model_name='test-sleep')
    if name == 'codingdude-test:gated':
        from pydantic_ai.messages import (
            ModelResponse as MR,
        )
        from pydantic_ai.messages import (
            TextPart as TP,
        )
        from pydantic_ai.messages import (
            ToolCallPart,
            ToolReturnPart,
        )
        from pydantic_ai.models.function import FunctionModel

        def gated_response(messages):
            if not any(
                isinstance(p, ToolCallPart) for m in messages for p in m.parts
            ):
                return MR(
                    parts=[ToolCallPart(tool_name='shell', args={'command': 'printf gated-ok'})]
                )
            returns = [
                str(p.content)
                for m in messages
                for p in m.parts
                if isinstance(p, ToolReturnPart)
            ]
            answer = 'gated-ran' if any('gated-ok' in r for r in returns) else 'gated-no'
            return MR(parts=[TP(content=answer)])

        def gated(messages, info):
            return gated_response(messages)

        async def gated_stream(messages, info):
            if not any(
                isinstance(p, ToolCallPart) for m in messages for p in m.parts
            ):
                from pydantic_ai.models.function import DeltaToolCall

                yield {
                    0: DeltaToolCall(
                        name='shell', json_args='{"command": "printf gated-ok"}'
                    )
                }
            else:
                yield gated_response(messages).parts[0].content

        return FunctionModel(gated, stream_function=gated_stream, model_name='test-gated')
    from pydantic_ai.models import infer_model

    return infer_model(name)


async def run(args) -> int:
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    config = load_config()
    engine = Engine(
        config=config,
        db=Database.connect(config_home()),
        budget_cap_usd=args.budget,
        extraction_model=None,
    )
    # Memory extraction runs on the cheap subagent model when configured.
    try:
        engine._extraction_model = await _resolve_model(config.models.subagent)
    except Exception:  # noqa: BLE001 — extraction is best-effort
        pass
    model = await _resolve_model(args.model)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pending_gate: dict[str, asyncio.Future] = {}

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    policy = ApprovalPolicy(yolo=args.yolo)
    if not args.yolo:

        async def ask(command: str) -> str:
            fut = loop.create_future()
            pending_gate['fut'] = fut
            # Single writer: gate requests flow through the same queue as
            # every other event, so frames can never interleave.
            on_event({'type': 'GATE_REQUEST', 'command': command})
            try:
                decision = await asyncio.wait_for(fut, timeout=600)
            except TimeoutError:
                decision = 'deny'
            if decision == 'pattern':
                engine.approve_pattern(args.session, command)
            return decision

        policy.ask = ask

    async with websockets.connect(args.server) as ws:
        async def sender():
            while True:
                event = await queue.get()
                await ws.send(json.dumps(event))
                if event.get('type') in TERMINAL_EVENTS:
                    return

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get('type') == 'APPROVAL_RESPONSE':
                    fut = pending_gate.pop('fut', None)
                    if fut and not fut.done():
                        fut.set_result(msg.get('decision', 'deny'))

        async def runner():
            try:
                outcome = await engine.run(
                    prompt=args.prompt,
                    workdir=workdir_path(args),
                    session_id=args.session,
                    model=model,
                    approvals=policy,
                    emit=on_event,
                    image_path=image_path_arg(args),
                )
                if outcome.status == 'gate_aborted':
                    terminal = {
                        'type': 'RUN_ERROR',
                        'code': 'gate',
                        'message': outcome.output,
                    }
                else:
                    # Only after persistence: the UI reading messages must see
                    # the full exchange when RUN_FINISHED lands.
                    terminal = {'type': 'RUN_FINISHED'}
            except Exception as exc:  # noqa: BLE001 — reported to the UI, not crashed
                from .exceptions import BudgetExceeded

                terminal = {
                    'type': 'RUN_ERROR',
                    'code': 'budget' if isinstance(exc, BudgetExceeded) else 'error',
                    'message': str(exc),
                }
            trace_terminal(args.session, terminal)
            # Single writer: queued, so ordering with other events is preserved.
            on_event(terminal)

        sender_task = asyncio.create_task(sender())
        reader_task = asyncio.create_task(reader())
        runner_task = asyncio.create_task(runner())
        # Sender exits when it forwards the terminal event.
        await sender_task
        for t in (reader_task, runner_task):
            t.cancel()

    return 0


def trace_terminal(session_id: str, event: dict) -> None:
    import json as _json
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    trace_dir = config_home() / 'traces'
    trace_dir.mkdir(parents=True, exist_ok=True)
    with open(trace_dir / f'{session_id}.jsonl', 'a', encoding='utf-8') as f:
        f.write(_json.dumps({'ts': _dt.now(_UTC).isoformat(), **event}) + '\n')


def workdir_path(args):
    from pathlib import Path

    return Path(args.workdir).resolve()


def image_path_arg(args):
    from pathlib import Path

    return Path(args.image).resolve() if args.image else None


def config_home():
    from codingdude.config import config_home

    return config_home()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='codingdude-worker')
    parser.add_argument('--server', required=True, help='ws:// URL of the server')
    parser.add_argument('--session', required=True)
    parser.add_argument('--workdir', required=True)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--model', default=None)
    parser.add_argument('--yolo', action='store_true')
    parser.add_argument('--fix-loop', action='store_true')
    parser.add_argument('--image', default=None, help='path to an image to include with the prompt')
    parser.add_argument('--budget', type=float, default=None)
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001 — last-resort report
        logging.getLogger(__name__).exception('worker failed')
        print(f'worker error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
