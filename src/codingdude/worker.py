"""Worker subprocess (ADR-0002): runs the engine, streams events to the server.

One worker per accepted run. Connects back to the server over a local WebSocket,
sends AG-UI-shaped JSON events, and exits when the run ends. Being a separate
process means a wedged run dies alone and kill = cancel.
"""

import argparse
import asyncio
import json
import sys

import websockets

from .events import TERMINAL_EVENTS


async def _resolve_model(name: str | None):
    if not name:
        return None
    # Test hook: deterministic scripted models so subprocess tests need no keys.
    if name == 'codingdude-test:echo':
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse, TextPart

        def echo(messages, info):
            return ModelResponse(parts=[TextPart(content='worker-echo-ok')])

        async def echo_stream(messages, info):
            yield 'worker-echo-ok'

        return FunctionModel(echo, stream_function=echo_stream, model_name='test-echo')
    if name == 'codingdude-test:sleep':
        import asyncio as _aio

        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse as MR, TextPart as TP

        async def sleepy(messages, info):
            await _aio.sleep(60)
            return MR(parts=[TP(content='finally')])

        return FunctionModel(sleepy, model_name='test-sleep')
    from pydantic_ai.models import infer_model

    return infer_model(name)


async def run(args) -> int:
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    config = load_config()
    engine = Engine(config=config, db=Database.connect(config_home()))
    model = await _resolve_model(args.model)
    approvals = ApprovalPolicy(yolo=args.yolo)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async with websockets.connect(args.server) as ws:
        async def sender():
            while True:
                event = await queue.get()
                await ws.send(json.dumps(event))
                if event.get('type') in TERMINAL_EVENTS:
                    return

        async def runner():
            try:
                outcome = await engine.run(
                    prompt=args.prompt,
                    workdir=workdir_path(args),
                    session_id=args.session,
                    model=model,
                    approvals=approvals,
                    emit=on_event,
                )
                if outcome.status == 'gate_aborted':
                    await ws.send(json.dumps({
                        'type': 'RUN_ERROR',
                        'code': 'gate',
                        'message': outcome.output,
                    }))
                else:
                    # Only after persistence: the UI reading messages must see
                    # the full exchange when RUN_FINISHED lands.
                    await ws.send(json.dumps({'type': 'RUN_FINISHED'}))
            except Exception as exc:  # noqa: BLE001 — reported to the UI, not crashed
                await ws.send(json.dumps({
                    'type': 'RUN_ERROR',
                    'message': str(exc),
                }))

        tasks = [asyncio.create_task(sender()), asyncio.create_task(runner())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        # Drain whatever the runner queued after sender returned.
        while not queue.empty():
            await ws.send(json.dumps(queue.get_nowait()))
    return 0


def workdir_path(args):
    from pathlib import Path

    return Path(args.workdir).resolve()


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
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001 — last-resort report
        print(f'worker error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
