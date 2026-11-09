# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
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

import httpx
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


# #305: the continuation prompt for the single auto-resume after a model
# request timeout. History/plan/steps persist in the DB, so "continue" is
# enough for the agent to pick up where the dead request left off.
_TIMEOUT_RESUME_PROMPT = (
    'The previous attempt was cut off by a model request timeout mid-run. '
    'Continue the task from the last completed step; do not restart '
    'completed work.'
)


def _is_transport_timeout(exc: Exception) -> bool:
    """#305: the model-request timeout family — the one failure pydantic-ai
    neither retries nor falls back on (R25 retries cover tools only).

    Matches the concrete httpx timeouts, plain TimeoutError, and the exact
    wording pydantic-ai flattens a model-request timeout to. Tool/command
    timeouts say e.g. "command timed out after 300s" — those are R25
    retryable tool failures and must NOT trigger a run resume."""
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return True
    return 'request timed out' in str(exc).lower()


async def _finish_run(engine, args, on_event, outcome=None, exc=None) -> int:
    """Emit the terminal event immediately — no tail drain first (R30).

    Draining before the terminal event made the UI wait ~90s on memory
    extraction after every run. The terminal event goes out as soon as the
    engine has persisted; the pending tail drains afterwards, in
    drain_after_terminal (called by run() once the sender has forwarded the
    terminal event), so the worker still exits clean — the tail is never
    cancelled at asyncio.run teardown.

    Returns the run's end code (0 clean, 1 failed/halted) so run() can exit
    non-zero on a halt even when the terminal was delivered (#295 M4).
    """
    if exc is not None:
        from .exceptions import BudgetExceeded

        terminal: dict[str, object] = {
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
    elif outcome.status == 'halted':
        # REQ-5 (#295): the operator pulled AGENT_STOP — the run did NOT
        # finish; say so truthfully and exit non-zero (M4).
        terminal = {
            'type': 'WORKER_HALTED',
            'message': outcome.output,
        }
        end_status, end_code = 'halted', 1
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
    # R31 provenance: every traced event names its run — terminal events
    # were the only un-stamped ones (#305 post-mortem) and broke run-scoped
    # trace queries.
    terminal['run_id'] = getattr(args, 'run_id', None)
    trace_terminal(args.session, terminal)
    # Single writer: queued, so ordering with other events is preserved.
    on_event(terminal)
    return end_code



async def drain_after_terminal(engine) -> None:
    """Drain any pending post-run tail, bounded, before the worker exits.

    Called after the sender has forwarded the terminal event: the UI is
    already settled, so extraction latency here is invisible. Bounded so a
    wedged tail cannot hang shutdown.
    """
    await engine.drain_post_run(timeout=_DRAIN_BEFORE_TERMINAL_S)


async def _resolve_worker_slots(config):
    """The config-driven model slots — (extraction, vision) — via one seam.

    Both slots resolve through engine._model_from_name WITH
    config.models.fallback_base_url (#212: worker and engine must never
    disagree on provider routing). R72 #265: the extraction slot previously
    omitted fallback_base_url, so a coding-plan-only key made every run-end
    memory extraction POST to the standard Z.ai endpoint and 400.
    """
    log = logging.getLogger('codingdude.worker')
    extraction = None
    try:
        extraction = await _resolve_model(
            config.models.subagent, config.models.fallback_base_url,
            config.providers,
        )
    except Exception:  # noqa: BLE001 — extraction is best-effort
        log.warning(
            'extraction model unavailable; memory extraction disabled',
            exc_info=True)
    vision = None
    if config.models.vision:
        try:
            vision = await _resolve_model(
                config.models.vision, config.models.fallback_base_url,
                config.providers,
            )
        except Exception:  # noqa: BLE001 — image input is best-effort
            vision = None
    return extraction, vision


async def _resolve_model(
    name: str | None, base_url: str | None = None, providers: dict | None = None,
):
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
    if name == 'codingdude-test:ask2':
        import json as _json

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

        # Two sequential ask_user calls (the live long-run failure shape:
        # first ask resolves, second never does). Deterministic.
        def ask2_response(messages):
            returns = [
                str(p.content)
                for m in messages
                for p in m.parts
                if isinstance(p, ToolReturnPart)
            ]
            if not returns:
                return MR(parts=[ToolCallPart(tool_name='ask_user', args={
                    'questions': _json.dumps(
                        [{'question': 'q-one?', 'options': ['a-one', 'x'], 'multi': False}]),
                })])
            if len(returns) == 1:
                return MR(parts=[ToolCallPart(tool_name='ask_user', args={
                    'questions': _json.dumps(
                        [{'question': 'q-two?', 'options': ['a-two', 'y'], 'multi': False}]),
                })])
            ok = ('a-one' in returns[0]) and ('a-two' in returns[1])
            return MR(parts=[TP(content='ask2-ok' if ok else f'ask2-bad {returns}')])

        def ask2(messages, info):
            return ask2_response(messages)

        async def ask2_stream(messages, info):
            response = ask2_response(messages)
            for i, part in enumerate(response.parts):
                if hasattr(part, 'tool_name'):
                    from pydantic_ai.models.function import DeltaToolCall

                    args = part.args
                    if not isinstance(args, str):
                        args = _json.dumps(args)
                    yield {i: DeltaToolCall(name=part.tool_name, json_args=args)}
                elif hasattr(part, 'content') and isinstance(part.content, str):
                    yield part.content

        return FunctionModel(ask2, stream_function=ask2_stream, model_name='test-ask2')
    if name == 'codingdude-test:timeout-once':
        # #305: the first model request raises a transport timeout (the live
        # long-run failure shape — provider stall, then ModelSettings
        # timeout surfaces as "Request timed out."), every later request
        # answers normally. Proves the worker's single auto-resume turns one
        # dead request into a finished run.
        import httpx as _httpx
        from pydantic_ai.messages import ModelResponse as MR
        from pydantic_ai.messages import TextPart as TP
        from pydantic_ai.models.function import FunctionModel

        state = {'raised': False}

        def flaky_response(messages):
            if not state['raised']:
                state['raised'] = True
                raise _httpx.ReadTimeout('Request timed out.')
            return MR(parts=[TP(content='timeout-recovered')])

        def flaky(messages, info):
            return flaky_response(messages)

        async def flaky_stream(messages, info):
            response = flaky_response(messages)
            yield response.parts[0].content

        return FunctionModel(
            flaky, stream_function=flaky_stream, model_name='test-timeout-once')
    if name == 'codingdude-test:timeout-always':
        # #305: every model request raises the timeout — the resume must be
        # bounded, so the second failure is a terminal RUN_ERROR.
        import httpx as _httpx
        from pydantic_ai.models.function import FunctionModel

        def always_timeout(messages, info):
            raise _httpx.ReadTimeout('Request timed out.')

        async def always_timeout_stream(messages, info):
            raise _httpx.ReadTimeout('Request timed out.')
            yield  # pragma: no cover - unreachable, keeps it a generator

        return FunctionModel(
            always_timeout, stream_function=always_timeout_stream,
            model_name='test-timeout-always')
    if name == 'codingdude-test:tool-timeout-text':
        # #305 pin: a TOOL-origin failure whose message embeds a timeout
        # ("command timed out") is R25-retryable tool territory, NOT the
        # model-request family — the worker must NOT burn its resume on it.
        from pydantic_ai.models.function import FunctionModel

        def tool_text_timeout(messages, info):
            raise RuntimeError('command timed out after 300s')

        async def tool_text_timeout_stream(messages, info):
            raise RuntimeError('command timed out after 300s')
            yield  # pragma: no cover - unreachable, keeps it a generator

        return FunctionModel(
            tool_text_timeout, stream_function=tool_text_timeout_stream,
            model_name='test-tool-timeout-text')
    if providers or base_url:
        # #212: route through the engine's single resolution seam so the
        # worker, CLI, and engine can never disagree on provider routing.
        from codingdude.engine import _model_from_name

        return _model_from_name(name, base_url, providers)
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
        # #266: same endpoint routing as run()'s slots — without
        # fallback_base_url a coding-plan-only key 400'd review-mode
        # extraction and review_diff_findings reported a silent CLEAN.
        engine.extraction_model = await _resolve_model(
            config.models.subagent, config.models.fallback_base_url,
            config.providers)
    except Exception:  # noqa: BLE001 — Engine falls back to its own resolution
        logging.getLogger('codingdude.worker').warning(
            'extraction model unavailable; review falls back to engine '
            'resolution', exc_info=True)
    findings = await engine.review(args.review)
    print(json.dumps({'findings': findings}))
    return 0


async def _sender_loop(ws, queue: 'asyncio.Queue') -> bool:
    """Forward queued events over the ws; report delivery truth (#285).

    #73: a mid-run connection drop (server bounce) must not crash the worker.
    Once the socket is dead we stop sending (events are dropped; the engine
    persists trace/messages itself) but keep draining the queue so the runner
    never blocks, and return on the terminal event as before.
    Returns True when the terminal event was actually sent, False after a
    WS_LOST — run() turns that into WORKER_TERMINAL_DROPPED and a non-zero
    exit instead of logging 'terminal delivered' on a dead socket.
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
            return not dead


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


async def ask_user_interaction(on_event, trace, run_id, payload, fut, timeout=1800):
    """#147: surface an interactive question, persist request+resolution.

    The ASK_USER event rides the UI queue as before, but is also appended to
    the session trace (run_id stamped) so a page refresh can restore the
    pending card while the run is still alive. The resolution is traced too,
    so a restored card is only shown while the question is still open.
    """
    event = {'type': 'ASK_USER', 'questions': payload}
    on_event(event)
    trace(event)
    try:
        answers = await asyncio.wait_for(fut, timeout)
    except TimeoutError:
        answers = {'error': 'no answer (timed out)'}
    trace({'type': 'ASK_USER_RESOLVED', 'run_id': run_id, 'timed_out': 'error' in answers})
    return answers


async def gate_interaction(on_event, trace, run_id, command, fut, timeout=600):
    """#147: gated-command approval with durable trace (see ask_user_interaction)."""
    event = {'type': 'GATE_REQUEST', 'command': command}
    on_event(event)
    trace(event)
    try:
        decision = await asyncio.wait_for(fut, timeout)
    except TimeoutError:
        decision = 'deny'
    trace({'type': 'GATE_RESOLVED', 'run_id': run_id, 'decision': decision})
    return decision


def wire_interactions(policy, args, engine, loop, on_event, pending_gate, pending_ask):
    """Wire ask/gate/ask_user handlers onto the approval policy.

    One seam so the closure wiring is testable. `trace_interaction` must be
    defined unconditionally: ask_user_fn is attached in yolo mode too, and
    when this lived inside `if not args.yolo:` every ask_user call in yolo
    mode raised NameError (free variable never bound).
    """

    def trace_interaction(event: dict) -> None:
        # #147: persist the interaction so a refresh can restore the
        # pending card while this run is still alive.
        run_id = getattr(args, 'run_id', None)
        trace_terminal(args.session, {**event, 'run_id': run_id})

    async def ask(command: str) -> str:
        fut = loop.create_future()
        pending_gate['fut'] = fut
        decision = await gate_interaction(
            on_event, trace_interaction, getattr(args, 'run_id', None),
            command, fut)
        if decision == 'pattern':
            engine.approve_pattern(args.session, command)
        return decision

    async def ask_user_fn(payload):
        """Surface an interactive question form and wait for the user's answers."""
        fut = loop.create_future()
        pending_ask['fut'] = fut
        return await ask_user_interaction(
            on_event, trace_interaction, getattr(args, 'run_id', None),
            payload, fut)

    policy.ask = ask
    policy.ask_user = ask_user_fn


def trace_terminal(session_id: str, event: dict) -> None:
    """Emit the terminal trace event for a finished run."""
    from codingdude.traces import append_trace_line

    # Atomic single-line append (#79) — never interleaves with the engine
    # tracer writing to the same session trace.
    append_trace_line(
        config_home() / 'traces' / f'{session_id}.jsonl', event,
    )


async def run(args) -> int:
    """Worker entry: run one agent turn for a session and persist the trace."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import apply_project_models, load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    config = load_config()
    # #210: per-project [models] overrides from the workdir's .codingdude.toml.
    if args.workdir:
        config = apply_project_models(config, Path(args.workdir).resolve())
    engine = Engine(
        config=config,
        db=Database.connect(config_home()),
        budget_cap_usd=args.budget,
        extraction_model=None,
    )
    # Config-driven slots (extraction, vision) resolve through the shared
    # slots seam (#265: same endpoint routing as the engine's own slots).
    extraction_model, vision_model = await _resolve_worker_slots(config)
    engine.extraction_model = extraction_model
    model = await _resolve_model(
        args.model, config.models.fallback_base_url, config.providers)

    log = logging.getLogger('codingdude.worker')
    log.info('WORKER_START pid=%s session=%s model=%s', os.getpid(), args.session, args.model)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pending_gate: dict[str, asyncio.Future] = {}
    pending_ask: dict[str, asyncio.Future] = {}

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    policy = ApprovalPolicy(yolo=args.yolo)
    wire_interactions(policy, args, engine, loop, on_event, pending_gate, pending_ask)

    server_url = args.server
    worker_token = os.environ.get('CODEDUDE_WORKER_TOKEN')
    if worker_token:
        server_url += ('&' if '?' in server_url else '?') + 'token=' + worker_token
    async with websockets.connect(server_url) as ws:
        sender_task = asyncio.create_task(_sender_loop(ws, queue))
        reader_task = asyncio.create_task(_reader_loop(ws, pending_gate, pending_ask))

        halted = False
        end_code: dict[str, int] = {'code': 0}

        async def runner():
            nonlocal halted
            # #305: one bounded auto-resume. The model-request timeout family
            # is the one failure pydantic-ai neither retries nor falls back on
            # (R25 retries cover tools); a single provider stall killed the
            # whole live long-run (run WwDMwohNfhU, 2026-11-09). History/plan
            # state persists, so a continuation prompt picks up where the
            # dead request left off. Second timeout is terminal, never a loop.
            kwargs = engine_run_kwargs(args, model, vision_model)
            resumed = False
            while True:
                try:
                    outcome = await engine.run(
                        **kwargs, approvals=policy, emit=on_event,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 — reported to the UI, not crashed
                    if resumed or not _is_transport_timeout(exc):
                        end_code['code'] = await _finish_run(
                            engine, args, on_event, exc=exc)
                        return
                    resumed = True
                    event = {
                        'type': 'AUTO_RESUMED',
                        'run_id': getattr(args, 'run_id', None),
                        'error': str(exc)[:200],
                    }
                    trace_terminal(args.session, event)
                    log.info(
                        'WORKER_AUTO_RESUME pid=%s — model request timed out; '
                        'resuming once from persisted state', os.getpid())
                    on_event(event)
                    kwargs = {**kwargs, 'prompt': _TIMEOUT_RESUME_PROMPT}
            halted = getattr(outcome, 'status', '') == 'halted'
            end_code['code'] = await _finish_run(engine, args, on_event, outcome=outcome)


        runner_task = asyncio.create_task(runner())
        # The sender exits when it forwards the terminal event — or reports
        # that the socket died before it could (#285). Log the truth either
        # way: 'delivered' on a dead socket made every bounce look like a
        # clean finish, and the server reaped an unexplained RUN_ERROR.
        delivered = await sender_task
        if delivered:
            log.info(
                'WORKER_TERMINAL_SENT pid=%s — terminal event delivered, draining tail',
                os.getpid(),
            )
        else:
            log.warning(
                'WORKER_TERMINAL_DROPPED pid=%s — ws died mid-run; the run is '
                'persisted locally but the server never received the terminal '
                'event, exiting non-zero so the reaper reports the loss',
                os.getpid(),
            )
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

    # #285: a run whose terminal never reached the server did not finish for
    # the user — exit non-zero so the reaper's message tells the truth.
    # #295 M4: an operator halt (AGENT_STOP) is not a clean finish either —
    # the worker exits non-zero even when the terminal was delivered.
    # #305: a delivered terminal's exit code IS the run outcome (failed → 1)
    # so the reaper's process-code record agrees with the worker's own
    # record_run_end instead of overwriting its truthful 1 with a delivered 0
    # (live symptom: status=failed with exit_code=0 on run WwDMwohNfhU).
    return 0 if delivered and end_code['code'] == 0 and not halted else 1


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
        'long_run': getattr(args, 'long_run', None),
    }


def workdir_path(args):
    """Resolve the session workdir path argument."""
    from pathlib import Path

    return Path(args.workdir).resolve()


def image_path_arg(args):
    """Validate/normalize an image path CLI argument."""
    from pathlib import Path

    return Path(args.image).resolve() if args.image else None


def config_home():
    """Resolve the config home for this worker process."""
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
    """Worker process entry point (spawned by the server per run)."""
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
    parser.add_argument(
        '--long-run',
        choices=('assisted', 'unattended'),
        default=None,
        help='long-run work-mode level (#297): sandbox lane + honest tier '
             'reporting; absent = today\'s interactive behavior',
    )
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
