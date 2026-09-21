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
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed

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
    log = logging.getLogger('codingdude.worker')

    def _fire() -> None:
        log.error(
            'WATCHDOG_FIRED pid=%s: forced exit after %.0fs — graceful '
            'teardown never completed', os.getpid(), timeout)
        os._exit(0)

    if _exit_watchdog is not None:
        _exit_watchdog.cancel()
    _exit_watchdog = threading.Timer(timeout, _fire)
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
        end_status, end_code = 'failed', 1
    elif outcome.status == 'gate_aborted':
        terminal = {
            'type': 'RUN_ERROR',
            'code': 'gate',
            'message': outcome.output,
        }
        end_status, end_code = 'gate_aborted', 0
    else:
        # Only after persistence: the UI reading messages must see
        # the full exchange when RUN_FINISHED lands.
        terminal = {'type': 'RUN_FINISHED'}
        end_status, end_code = 'completed', 0
    # R31: durable run end-state — a bounce after this point still leaves a
    # terminal status in the DB, not a phantom 'running' row.
    run_id = getattr(args, 'run_id', None)
    if run_id:
        try:
            engine._db.record_run_end(run_id, end_status, exit_code=end_code)
        except Exception:  # noqa: BLE001 — bookkeeping must never fail the run
            logging.getLogger('codingdude.worker').warning(
                'RUN_END_RECORD_FAILED run=%s', run_id, exc_info=True)
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


async def _sender_loop(ws, queue: 'asyncio.Queue') -> None:
    """Forward queued events over the ws.

    #73: a mid-run connection drop (server bounce) must not crash the worker.
    Once the socket is dead we stop sending (events are dropped; the engine
    persists trace/messages itself) but keep draining the queue so the runner
    never blocks, and return on the terminal event as before.
    """
    log = logging.getLogger('codingdude.worker')
    dead = False
    while True:
        event = await queue.get()
        if not dead:
            try:
                await ws.send(json.dumps(event))
            except ConnectionClosed:
                dead = True
                log.warning(
                    'WORKER_WS_LOST pid=%s — server connection dropped mid-run; '
                    'letting the engine finish, dropping further UI events',
                    os.getpid(),
                )
        if event.get('type') in TERMINAL_EVENTS:
            return


async def _reader_loop(ws, pending_gate: dict, pending_ask: dict) -> None:
    """Consume server messages (approval/ask-user responses).

    #73: connection drops end the iteration with ConnectionClosedError; that
    is expected once the server is gone — return instead of raising (which
    surfaced as 'Task exception was never retrieved' and exit 1).
    """
    log = logging.getLogger('codingdude.worker')
    try:
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
    except ConnectionClosed:
        log.warning('WORKER_WS_LOST pid=%s — reader exiting (server gone)', os.getpid())


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

    log = logging.getLogger('codingdude.worker')
    log.info('WORKER_START pid=%s session=%s model=%s', os.getpid(), args.session, args.model)

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
        sender_task = asyncio.create_task(_sender_loop(ws, queue))
        reader_task = asyncio.create_task(_reader_loop(ws, pending_gate, pending_ask))

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

        runner_task = asyncio.create_task(runner())

        # Sender exits when it forwards the terminal event. The UI is
        # settled by then; drain the pending tail before teardown (R30).
        await sender_task
        log.info('WORKER_TERMINAL_SENT pid=%s — terminal event delivered, draining tail', os.getpid())
        # The watchdog must cover the drain too: a drain that never returns
        # (blocked event loop, un-cancellable shielded cleanup) would never
        # reach the arm_exit_watchdog() call below and the worker would hang
        # forever — observed live as a 1647s stall after MEMORY_EXTRACTED.
        # Long timer during the drain, re-armed short for teardown.
        arm_exit_watchdog(_DRAIN_BEFORE_TERMINAL_S + _EXIT_WATCHDOG_S)
        await drain_after_terminal(engine)
        log.info('WORKER_DRAIN_DONE pid=%s — tail drained, cancelling tasks', os.getpid())
        for t in (reader_task, runner_task):
            t.cancel()

    # Everything is persisted and the ws is closed; only interpreter teardown
    # remains. Arm the watchdog so a wedged Proactor close can't hang the UI.
    arm_exit_watchdog()
    log.info('WORKER_EXITING pid=%s — run() returning, interpreter teardown next', os.getpid())

    return 0


def trace_terminal(session_id: str, event: dict) -> None:
    from codingdude.traces import append_trace_line

    # Atomic single-line append (#79) — never interleaves with the engine
    # tracer writing to the same session trace.
    append_trace_line(
        config_home() / 'traces' / f'{session_id}.jsonl', event,
    )


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
        'run_id': getattr(args, 'run_id', None),
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


def load_prompt_file(args):
    """--prompt-file: read the prompt from a file instead of argv.

    Windows caps a process command line at ~32k chars; long prompts blew up
    CreateProcess (WinError 206). The file is consumed (deleted) after read.
    """
    pf = getattr(args, 'prompt_file', None)
    if not pf:
        return args
    args.prompt = Path(pf).read_text(encoding='utf-8')
    try:
        Path(pf).unlink()
    except OSError:
        pass  # a leftover file is harmless; never fail the run over it
    return args


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
    parser.add_argument(
        '--prompt-file',
        help='read the prompt from this file (long prompts cannot ride on argv)',
    )
    parser.add_argument('--model', default=None)
    parser.add_argument('--yolo', action='store_true')
    parser.add_argument('--fix-loop', action='store_true')
    parser.add_argument('--image', default=None, help='path to an image to include with the prompt')
    parser.add_argument('--budget', type=float, default=None)
    parser.add_argument('--run-id', default=None, help='run id for durable lifecycle records (R31)')
    args = load_prompt_file(parser.parse_args(argv))
    # Lifecycle diagnostics (R31): always mirror worker logs to a file under
    # ~/.codingdude/logs/ so post-run forensics don't depend on a console.
    try:
        log_dir = Path.home() / '.codingdude' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        # NOTE: uv's venv python.exe is a trampoline — os.getpid() here is the
        # real interpreter's pid, which differs from the server-recorded
        # Popen pid. Key the file on session id (unique, matches RUN_START).
        session_tag = (args.session or f'pid{os.getpid()}')[:16]
        handler = logging.FileHandler(
            log_dir / f'worker-{session_tag}.log', encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s %(message)s'))
        logging.getLogger().addHandler(handler)
    except OSError:
        pass  # console logging still works
    # NOTE: basicConfig no-ops now that root already has our file handler
    # (it only configures an empty root), so set level/format explicitly.
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.getLogger('codingdude.worker').info(
        'WORKER_BOOT pid=%s session=%s argv=%s', os.getpid(), args.session,
        ' '.join(sys.argv[1:])[:200])
    try:
        return asyncio.run(review(args) if args.review else run(args))
    except Exception as exc:  # noqa: BLE001 — last-resort report
        logging.getLogger(__name__).exception('worker failed')
        print(f'worker error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
