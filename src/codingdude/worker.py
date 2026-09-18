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
import os
import sys
import threading

import websockets

from .events import TERMINAL_EVENTS

# Bounded tail drain after the terminal event: each tail pass is already capped by
# run_pipeline._POST_RUN_LLM_TIMEOUT_S and they run concurrently, so ~one pass
# plus slack. Keeps shutdown deterministic — nothing pending to cancel. Runs
# AFTER RUN_FINISHED so extraction latency is invisible to the user (R30).
_DRAIN_BEFORE_TERMINAL_S = 150.0

# #62: hard-exit watchdog. Worker state is fully persisted before the drain
# ends, so interpreter teardown is not critical — but a wedged asyncio.run
# (Windows IocpProactor.close waiting on pending ops) hangs the process and
# the UI with it. A daemon timer force-exits if graceful shutdown doesn't
# complete in time. R31.
_EXIT_WATCHDOG_S = 20.0
_exit_watchdog = None


def arm_exit_watchdog(timeout: float = _EXIT_WATCHDOG_S) -> None:
    """Arm (or re-arm) the hard-exit watchdog.

    Called right before worker.run() returns: everything is drained and the
    websocket is closed, so the only thing left is interpreter shutdown. If
    that wedges, the timer fires os._exit(0) and the run settles.
    """
    global _exit_watchdog
    if _exit_watchdog is not None:
        _exit_watchdog.cancel()
    _exit_watchdog = threading.Timer(timeout, os._exit, args=(0,))
    _exit_watchdog.daemon = True
    _exit_watchdog.start()


async def _finish_run(engine, args, on_event, outcome=None, exc=None) -> None:
    """Emit the terminal event immediately — no tail drain first (R30).

    Draining before the terminal event made the UI wait ~90s on memory
    extraction after every run. The terminal event goes out as soon as the
    engine has persisted; the pending tail drains afterwards, in
    drain_after_terminal (called by run() once the sender has forwarded the
    terminal event), so the worker still exits clean — the tail is never
    cancelled at asyncio.run teardown.
    """
    if exc is not None:
        from .exceptions import BudgetExceeded

        terminal = {
            'type': 'RUN_ERROR',
            'code': 'budget' if isinstance(exc, BudgetExceeded) else 'error',
            'message': str(exc),
        }
    elif outcome.status == 'gate_aborted':
        terminal = {
            'type': 'RUN_ERROR',
            'code': 'gate',
            'message': outcome.output,
        }
    else:
        # Only after persistence: the UI reading messages must see
        # the full exchange when RUN_FINISHED lands.
        terminal = {'type': 'RUN_FINISHED'}
    trace_terminal(args.session, terminal)
    # Single writer: queued, so ordering with other events is preserved.
    on_event(terminal)


async def drain_after_terminal(engine) -> None:
    """Drain any pending post-run tail, bounded, before the worker exits.

    Called after the sender has forwarded the terminal event: the UI is
    already settled, so extraction latency here is invisible. Bounded so a
    wedged tail cannot hang shutdown.
    """
    await engine.drain_post_run(timeout=_DRAIN_BEFORE_TERMINAL_S)


async def _resolve_model(name: str | None, base_url: str | None = None):
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
    if name.startswith('zai:') and base_url:
        from codingdude.engine import _model_from_name

        return _model_from_name(name, base_url)
    from pydantic_ai.models import infer_model

    return infer_model(name)


async def review(args) -> int:
    """--review mode: run a one-shot review in THIS process (short-lived
    subprocess spawned by the server) and print findings JSON on stdout.

    Honors ADR-0002: the long-running server process itself never
    executes an agent run.
    """
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    config = load_config()
    engine = Engine(config=config, db=Database.connect(config_home()))
    try:
        engine.extraction_model = await _resolve_model(config.models.subagent)
    except Exception:  # noqa: BLE001 — Engine falls back to its own resolution
        pass
    findings = await engine.review(args.review)
    print(json.dumps({'findings': findings}))
    return 0


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
        engine.extraction_model = await _resolve_model(config.models.subagent)
    except Exception:  # noqa: BLE001 — extraction is best-effort
        pass
    model = await _resolve_model(args.model, config.models.fallback_base_url)
    vision_model = None
    if config.models.vision:
        try:
            vision_model = await _resolve_model(
                config.models.vision, config.models.fallback_base_url
            )
        except Exception:  # noqa: BLE001 — image input is best-effort
            vision_model = None

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pending_gate: dict[str, asyncio.Future] = {}
    pending_ask: dict[str, asyncio.Future] = {}

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

    async def ask_user_fn(payload):
        """Surface an interactive question form and wait for the user's answers."""
        fut = loop.create_future()
        pending_ask['fut'] = fut
        on_event({'type': 'ASK_USER', 'questions': payload})
        try:
            return await asyncio.wait_for(fut, timeout=1800)
        except TimeoutError:
            return {'error': 'no answer (timed out)'}

    policy.ask_user = ask_user_fn

    server_url = args.server
    worker_token = os.environ.get('CODEDUDE_WORKER_TOKEN')
    if worker_token:
        server_url += ('&' if '?' in server_url else '?') + 'token=' + worker_token
    async with websockets.connect(server_url) as ws:
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
                elif msg.get('type') == 'ASK_USER_RESPONSE':
                    fut = pending_ask.pop('fut', None)
                    if fut and not fut.done():
                        fut.set_result(msg.get('answers', {}))

        async def runner():
            try:
                outcome = await engine.run(
                    **engine_run_kwargs(args, model, vision_model),
                    approvals=policy,
                    emit=on_event,
                )
            except Exception as exc:  # noqa: BLE001 — reported to the UI, not crashed
                await _finish_run(engine, args, on_event, exc=exc)
                return
            await _finish_run(engine, args, on_event, outcome=outcome)

        sender_task = asyncio.create_task(sender())
        reader_task = asyncio.create_task(reader())
        runner_task = asyncio.create_task(runner())
        # Sender exits when it forwards the terminal event. The UI is
        # settled by then; drain the pending tail before teardown (R30).
        await sender_task
        # The watchdog must cover the drain too: a drain that never returns
        # (blocked event loop, un-cancellable shielded cleanup) would never
        # reach the arm_exit_watchdog() call below and the worker would hang
        # forever — observed live as a 1647s stall after MEMORY_EXTRACTED.
        # Long timer during the drain, re-armed short for teardown.
        arm_exit_watchdog(_DRAIN_BEFORE_TERMINAL_S + _EXIT_WATCHDOG_S)
        await drain_after_terminal(engine)
        for t in (reader_task, runner_task):
            t.cancel()

    # Everything is persisted and the ws is closed; only interpreter teardown
    # remains. Arm the watchdog so a wedged Proactor close can't hang the UI.
    arm_exit_watchdog()

    return 0


def trace_terminal(session_id: str, event: dict) -> None:
    import json as _json
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    trace_dir = config_home() / 'traces'
    trace_dir.mkdir(parents=True, exist_ok=True)
    with open(trace_dir / f'{session_id}.jsonl', 'a', encoding='utf-8') as f:
        f.write(_json.dumps({'ts': _dt.now(_UTC).isoformat(), **event}) + '\n')


def engine_run_kwargs(args, model, vision_model=None) -> dict:
    """The engine.run(...) keyword arguments for a worker invocation.

    Kept in one place so a new engine parameter can't be silently dropped
    between the worker's CLI and the engine (self-review H2: `--fix-loop` was
    parsed but never forwarded, so the UI's "fix until green" did nothing).
    """
    return {
        'prompt': args.prompt,
        'workdir': workdir_path(args),
        'session_id': args.session,
        'model': model,
        'fix_loop': args.fix_loop,
        'image_path': image_path_arg(args),
        'vision_model': vision_model,
    }


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
    parser.add_argument(
        '--review',
        metavar='SESSION',
        default=None,
        help='review a session\'s working-tree diff, print findings JSON, exit',
    )
    parser.add_argument('--server', help='ws:// URL of the server')
    parser.add_argument('--session')
    parser.add_argument('--workdir')
    parser.add_argument('--prompt')
    parser.add_argument('--model', default=None)
    parser.add_argument('--yolo', action='store_true')
    parser.add_argument('--fix-loop', action='store_true')
    parser.add_argument('--image', default=None, help='path to an image to include with the prompt')
    parser.add_argument('--budget', type=float, default=None)
    args = parser.parse_args(argv)
    try:
        return asyncio.run(review(args) if args.review else run(args))
    except Exception as exc:  # noqa: BLE001 — last-resort report
        logging.getLogger(__name__).exception('worker failed')
        print(f'worker error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
