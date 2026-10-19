"""CodingDude web server: sessions + runs, bridging worker events to SSE.

Per ADR-0002 the server never runs the agent itself: each accepted run spawns a
worker subprocess that connects back over a local WebSocket; the server bridges
those events to browser-facing SSE in AG-UI shape and persists state to SQLite
(the worker shares the same DB).
"""

import asyncio
import json
import logging
import os
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__
from .config import config_home
from .db import Database
from .events import TERMINAL_EVENTS

HOST = '127.0.0.1'  # localhost only, by design

# When this server process started — surfaced in the UI so a restart is
# visible (a stale server shows an old boot time).
_STARTED_AT = datetime.now(UTC).isoformat()

# How long a finished run's channel stays reapable-but-replayable after the
# worker exits with a delivered terminal. Long enough that any EventSource
# auto-reconnect replays the terminal and settles (frontend hardening rides
# on this); short enough not to leak channels all session.
_TERMINAL_REPLAY_GRACE_S = 300
# #148 janitor: independent watchdog over spawned workers. Interval between
# sweeps; boot timeout = how long a live worker may stay without connecting
# its WebSocket before we conclude it never booted (silent spawn failure).
_JANITOR_INTERVAL_S = 2.0
_BOOT_TIMEOUT_S = 60.0


def _git_sha() -> str:
    """Short git SHA of the running checkout, or '' if unavailable."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _image_extension(data: bytes) -> str:
    """Sniff the real media type so a JPEG upload isn't stored as `.png`."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg'
    return '.png'


class RunChannel:
    """Bridges worker WebSocket events to SSE subscribers.

    Broadcast semantics (R31): every subscriber gets the full event stream —
    a second tab or a late reattach must never steal the terminal event and
    starve another consumer into a perpetual 'still working' state. Events
    are kept in a replay history so subscribers attaching mid-run catch up.
    """

    _HISTORY_CAP = 5000

    def __init__(self, run_id: str, session_id: str, registry: dict):
        self.run_id = run_id
        self.session_id = session_id
        self.registry = registry
        self.history: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.inbox: asyncio.Queue = asyncio.Queue()  # server → worker (approvals)
        self.worker: subprocess.Popen | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        # #148: worker-lifecycle visibility that does not depend on the ws.
        self.boot_seen = False       # worker connected its WebSocket
        self.created = time.monotonic()
        self.reaped = False          # _reap_worker already handled this run

    def _broadcast(self, event: dict) -> None:
        self.history.append(event)
        if len(self.history) > self._HISTORY_CAP:
            del self.history[: len(self.history) - self._HISTORY_CAP]
        for q in list(self.subscribers):
            q.put_nowait(event)

    def push(self, event: dict) -> None:
        # Sync endpoints run in threadpool threads: marshal onto the loop once
        # it exists, before that rely on single-producer safety.
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._broadcast, event)
        else:
            self._broadcast(event)

    def saw_terminal(self) -> bool:
        return any(e.get('type') in TERMINAL_EVENTS for e in self.history)

    def send_to_worker(self, message: dict) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.inbox.put_nowait, message)
        else:
            self.inbox.put_nowait(message)

    async def sse(self):
        loop = asyncio.get_running_loop()
        self.loop = loop
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(queue)
        logging.getLogger('codingdude.server').info(
            'SSE_ATTACH run=%s subscribers=%d', self.run_id, len(self.subscribers))
        try:
            for event in list(self.history):
                yield f'data: {json.dumps(event)}\n\n'
                if event.get('type') in TERMINAL_EVENTS:
                    return
            while True:
                event = await queue.get()
                yield f'data: {json.dumps(event)}\n\n'
                if event.get('type') in TERMINAL_EVENTS:
                    return
        finally:
            self.subscribers.discard(queue)
            logging.getLogger('codingdude.server').info(
                'SSE_DETACH run=%s subscribers=%d terminal_seen=%s',
                self.run_id, len(self.subscribers), self.saw_terminal())
            # Reap only dead runs: a live worker must stay cancellable even if
            # the browser's EventSource dropped (reconnect, refresh, sleep).
            if self.worker is None or self.worker.poll() is not None:
                logging.getLogger('codingdude.server').info(
                    'WORKER_GONE run=%s worker_pid=%s exit=%s',
                    self.run_id,
                    self.worker.pid if self.worker else None,
                    self.worker.poll() if self.worker else None,
                )
                self.registry.pop(self.run_id, None)


async def _reap_worker(channel, db: 'Database | None' = None) -> None:
    """Watch a run's worker process after its ws closes; reap on exit (R31).

    If the worker exited without delivering a terminal event, synthesize a
    RUN_ERROR so any attached consumer settles instead of waiting forever on
    a dead run (live symptom: UI 'still working' 300s+ after the worker died).
    Idempotent (#148): the janitor and the ws teardown may both call this.
    """
    log = logging.getLogger('codingdude.server')
    if channel.reaped:
        return
    worker = channel.worker
    if worker is None:
        return
    channel.reaped = True
    while worker.poll() is None:
        await asyncio.sleep(0.5)
    log.info(
        'WORKER_EXITED run=%s worker_pid=%s exit=%s terminal_seen=%s',
        channel.run_id, worker.pid, worker.returncode, channel.saw_terminal())
    if db is not None:
        db.record_run_end(
            channel.run_id, _terminal_status(channel),
            exit_code=worker.returncode)
    if not channel.saw_terminal():
        channel.push({
            'type': 'RUN_ERROR',
            'code': 'worker_died',
            'message': f'worker exited unexpectedly (code {worker.returncode}) '
                       'without finishing the run',
        })
        # Brief grace so subscribers consume the synthesized terminal, then reap.
        await asyncio.sleep(2.0)
    else:
        # Terminal already delivered: keep the channel so EventSource
        # auto-reconnects REPLAY the history (incl. the terminal) and settle
        # idempotently instead of 404-ing into the frontend error loop.
        await asyncio.sleep(_TERMINAL_REPLAY_GRACE_S)
    channel.registry.pop(channel.run_id, None)


def _terminal_status(channel) -> str:
    """Durable end-state for the runs row, derived from channel history."""
    terminals = [e['type'] for e in channel.history
                 if e['type'] in TERMINAL_EVENTS]
    if terminals and terminals[-1] == 'RUN_FINISHED':
        return 'completed'
    if terminals and terminals[-1] == 'RUN_CANCELLED':
        # 'cancelled' is not in the runs CHECK constraint (db.py) — mapping to
        # 'interrupted' keeps record_run_end from crashing the reaper on every
        # user-cancelled run.
        return 'interrupted'
    return 'failed'


async def _run_janitor(channels: dict, db: Database) -> None:
    """#148: sweep channels so no run can hang invisibly.

    The R31 reaper was armed only in the worker-ws endpoint's `finally` — a
    worker that died before ever connecting (silent spawn failure after a
    bounce, live run -cnQwMpicBI) armed nothing: no reaper, no RUN_ERROR, a
    runs row stuck 'running', a UI waiting forever. The janitor covers both
    halves without depending on the ws lifecycle:

    - exited worker → run the (idempotent) reaper;
    - live worker that never connected within _BOOT_TIMEOUT_S → treat as a
      failed boot, terminate it (the reaper then settles the run).
    """
    log = logging.getLogger('codingdude.server')
    while True:
        await asyncio.sleep(_JANITOR_INTERVAL_S)
        for channel in list(channels.values()):
            worker = channel.worker
            if worker is None:
                continue
            if worker.poll() is not None:
                if not channel.reaped:
                    asyncio.create_task(_reap_worker(channel, db))
            elif (not channel.boot_seen
                    and time.monotonic() - channel.created > _BOOT_TIMEOUT_S):
                log.info(
                    'WORKER_NEVER_BOOTED run=%s worker_pid=%s — terminating',
                    channel.run_id, worker.pid)
                worker.terminate()


def _project_codegraph_boot(workdir: Path, boot=None) -> dict:
    """Boot the codegraph index for a project (module-level so tests can
    stub it); best-effort — a failure is reported and logged, never raised."""
    if boot is None:
        from .codegraph_boot import boot_codegraph
        boot = boot_codegraph
    try:
        # Bounded at 120s: this runs in the POST /projects request path.
        return boot(workdir, timeout=120)
    except Exception as exc:  # noqa: BLE001 -- project creation must not fail on indexing
        logging.getLogger(__name__).warning(
            'PROJECT_CODEGRAPH_BOOT_FAILED workdir=%s: %s: %s',
            workdir, type(exc).__name__, exc)
        return {'status': 'failed', 'reason': f'{type(exc).__name__}: {exc}'}


def create_app(
    home: Path | None = None, token: str | None = None, allow_testclient: bool = False
) -> FastAPI:
    """Build the Starlette app: routes, static dist serving, and auth middleware."""
    home = home or config_home()
    token = token or secrets.token_urlsafe(16)
    from .mcp_config import ensure_default_mcp
    from .seed import seed_config_home

    ensure_default_mcp(home)
    seed_config_home(home)
    app = FastAPI()
    db = Database.connect(home)
    # R31: runs still marked 'running' from a previous server life can never
    # finish — give them a deterministic 'interrupted' end state at boot.
    interrupted = db.reconcile_interrupted_runs()
    if interrupted:
        logging.getLogger('codingdude.server').info(
            'RUNS_RECONCILED interrupted=%s', interrupted)
    # #148 follow-up: process rows stuck at 'running' whose pid died with a
    # previous server life get a durable 'exited (no capture)' end state too.
    orphaned = db.reconcile_dead_processes()
    if orphaned:
        logging.getLogger('codingdude.server').info(
            'PROCESSES_RECONCILED orphaned=%s', orphaned)
    channels: dict[str, RunChannel] = {}

    @app.on_event('startup')
    async def _start_run_janitor() -> None:
        # #148: independent worker-lifecycle watchdog (see _run_janitor).
        app.state.janitor_task = asyncio.create_task(_run_janitor(channels, db))
    # Stale prompt files (run 500'd before the worker consumed them) would
    # otherwise linger forever holding full prompt text on disk.
    for stale in (home / 'prompts').glob('*.prompt'):
        try:
            if stale.stat().st_mtime < (datetime.now(UTC).timestamp() - 86_400):
                stale.unlink()
        except OSError:
            pass

    def authorize(request: Request) -> None:
        """Bearer header (headless/tests), session cookie (browser login),
        or query param (EventSource) all authenticate."""
        auth_header = request.headers.get('authorization', '')
        cookie = request.cookies.get('cd_session', '')
        query_token = request.query_params.get('token', '')
        if auth_header != f'Bearer {token}' and cookie != token and query_token != token:
            raise HTTPException(status_code=401, detail='invalid token')
        host = request.client.host if request.client else ''
        local = ('127.0.0.1', '::1') + (('testclient',) if allow_testclient else ())
        if host not in local:
            raise HTTPException(status_code=403, detail='local only')

    def _session_cookie(response: Response) -> Response:
        response.set_cookie(
            'cd_session', token, httponly=True, samesite='lax', path='/',
            max_age=365 * 24 * 3600,
        )
        return response

    def _local_browser(request: Request) -> bool:
        """True when a browser attests this is a same-origin, local page.

        Sec-Fetch-Site (sent by all modern browsers) proves the request wasn't
        fired from another site, and the Host allowlist defeats DNS rebinding.
        Together they make a passwordless cookie grant safe on a loopback-only
        server, so the local user never has to paste a token.
        """
        site = request.headers.get('sec-fetch-site', '')
        if site not in ('same-origin', 'none'):
            return False
        host_header = request.headers.get('host', '')
        hostname = host_header.rsplit(':', 1)[0] if ':' in host_header else host_header
        allowed = {'127.0.0.1', 'localhost', '[::1]'}
        if allow_testclient:
            allowed.add('testserver')
        if hostname not in allowed:
            return False
        origin = request.headers.get('origin', '')
        if origin and origin != f'http://{host_header}':
            return False
        client = request.client.host if request.client else ''
        local = ('127.0.0.1', '::1') + (('testclient',) if allow_testclient else ())
        return client in local

    class LoginIn(BaseModel):
        password: str

    @app.get('/auth/check')
    def auth_check(request: Request) -> dict:
        cookie = request.cookies.get('cd_session', '')
        if cookie == token:
            return {'ok': True}
        raise HTTPException(status_code=401, detail='not logged in')

    @app.post('/auth/local')
    def auth_local(request: Request) -> Response:
        """Passwordless session for the local user's browser (see _local_browser)."""
        if not _local_browser(request):
            raise HTTPException(status_code=403, detail='local same-origin only')
        return _session_cookie(Response(content='{"ok": true}', media_type='application/json'))

    @app.post('/login')
    def login(body: LoginIn) -> Response:
        if body.password != token:
            raise HTTPException(status_code=401, detail='wrong password')
        # The cookie holds the same secret as the bearer token: localhost-only,
        # HttpOnly so page JS can't read it, same-origin by construction.
        return _session_cookie(Response(content='{"ok": true}', media_type='application/json'))

    class SessionIn(BaseModel):
        workdir: str
        title: str | None = None

    def _validated_workdir(raw: str) -> Path:
        import re

        if re.match(r'^[A-Za-z]:(?!\\)', raw):
            raise HTTPException(
                status_code=422,
                detail=(
                    f'drive-relative path rejected: {raw!r} — a backslash is missing '
                    f'after the drive letter (did you mean {raw[0]}:\\{raw[2:]}?)'
                ),
            )
        return Path(raw).resolve()

    class RunIn(BaseModel):
        prompt: str
        model: str | None = None
        yolo: bool = False
        budget: float | None = None
        fix_loop: bool = False
        image_b64: str | None = None  # base64 data-URL payload (no prefix)

    @app.post('/sessions')
    def create_session(body: SessionIn, _: None = Depends(authorize)) -> dict:
        resolved = _validated_workdir(body.workdir)
        if not resolved.is_dir():
            raise HTTPException(
                status_code=422,
                detail=f'no such directory: {resolved} — create it (or fix the path) first',
            )
        session_id = db.create_session(resolved, title=body.title)
        return {'session_id': session_id}

    @app.get('/sessions')
    def list_sessions(workdir: str, _: None = Depends(authorize)) -> list[dict]:
        import dataclasses

        rows = db.list_sessions(Path(workdir).resolve())
        return [dataclasses.asdict(r) for r in rows]

    @app.get('/sessions/{session_id}/messages')
    def session_messages(
        session_id: str, limit: int = 200, _: None = Depends(authorize)
    ) -> list[dict]:
        limit = max(1, min(limit, 2000))
        import time as _time

        from pydantic_ai.messages import ModelMessagesTypeAdapter
        from pydantic_core import ValidationError

        from .messages import decode_messages

        for attempt in range(5):
            try:
                payloads = db.load_messages(session_id, limit=limit)
                out = []
                for payload in payloads:
                    out.extend(
                        json.loads(
                            ModelMessagesTypeAdapter.dump_json(decode_messages([payload]))
                        )
                    )
                return out
            except ValidationError:
                # The worker may be mid-commit; brief retry beats a 500.
                if attempt == 4:
                    raise
                _time.sleep(0.1)
        raise AssertionError('unreachable')  # pragma: no cover

    @app.post('/sessions/{session_id}/runs')
    def start_run(session_id: str, body: RunIn, _: None = Depends(authorize)) -> dict:
        workdir = db.session_workdir(session_id)
        if workdir is None:
            raise HTTPException(status_code=404, detail='no such session')

        # One live worker per session: a resume/redo supersedes the previous
        # run. Two live workers interleave trace/checkpoint/DB writes and the
        # browser ends up watching a dead run's event stream. The channel
        # stays (unconsumed) so a late-attaching viewer still sees the
        # terminal RUN_CANCELLED; the SSE consumer reaps it.
        for existing in list(channels.values()):
            if existing.session_id != session_id:
                continue
            if existing.worker is not None and existing.worker.poll() is None:
                existing.worker.terminate()
            existing.push({'type': 'RUN_CANCELLED'})

        run_id = secrets.token_urlsafe(8)
        channel = RunChannel(run_id, session_id, channels)
        channels[run_id] = channel
        # R31: durable run record — survives a server bounce, unlike `channels`.
        db.record_run_start(run_id, session_id, pid=None)

        # The prompt rides on a file, not argv: Windows caps a process command
        # line at ~32k chars, and a long prompt (big editor selection) blew
        # CreateProcess up with WinError 206 → 500 on every long run.
        prompts = home / 'prompts'
        prompts.mkdir(parents=True, exist_ok=True)
        prompt_file = prompts / f'{run_id}.prompt'
        prompt_file.write_text(body.prompt, encoding='utf-8')
        cmd = [
            sys.executable, '-m', 'codingdude.worker',
            '--server', f'ws://{HOST}:{app.state.port}/runs/{run_id}/ws',
            '--session', session_id,
            '--workdir', workdir,
            '--prompt-file', str(prompt_file),
            '--run-id', run_id,
        ]
        if body.model:
            cmd += ['--model', body.model]
        if body.yolo:
            cmd.append('--yolo')
        if body.budget is not None:
            cmd += ['--budget', str(body.budget)]
        if body.fix_loop:
            cmd.append('--fix-loop')
        if body.image_b64:
            import base64
            import uuid as _uuid

            uploads = home / 'uploads'
            uploads.mkdir(parents=True, exist_ok=True)
            data = base64.b64decode(body.image_b64)
            image_file = uploads / f'{_uuid.uuid4().hex[:8]}{_image_extension(data)}'
            image_file.write_bytes(data)
            cmd += ['--image', str(image_file)]
        channel.worker = subprocess.Popen(
            cmd, env={**os.environ, 'CODEDUDE_WORKER_TOKEN': token}
        )
        # R31: backfill the live pid now that the process exists.
        db.record_run_start(run_id, session_id, pid=channel.worker.pid)
        logging.getLogger('codingdude.server').info(
            'RUN_START run=%s session=%s worker_pid=%s prompt=%r',
            run_id, session_id, channel.worker.pid, body.prompt[:120])

        return {'run_id': run_id}

    class ApprovalIn(BaseModel):
        decision: str  # 'approve' | 'pattern' | 'deny'

    @app.get('/runs/{run_id}/alive')
    def run_alive(run_id: str, _: None = Depends(authorize)) -> dict:
        """Watchdog probe (R2): is this run's worker process still running?

        Lets a reconnecting UI distinguish 'run alive, reattach the stream'
        from 'run already finished while detached'.
        """
        channel = channels.get(run_id)
        alive = channel is not None and channel.worker is not None and channel.worker.poll() is None
        return {'alive': alive}

    @app.post('/runs/{run_id}/approve')
    def approve(run_id: str, body: ApprovalIn, _: None = Depends(authorize)) -> dict:
        channel = channels.get(run_id)
        if channel is None:
            raise HTTPException(status_code=404, detail='no such run')
        if body.decision not in ('approve', 'pattern', 'deny'):
            raise HTTPException(status_code=422, detail='bad decision')
        channel.send_to_worker({'type': 'APPROVAL_RESPONSE', 'decision': body.decision})
        return {'sent': True}

    class AskIn(BaseModel):
        answers: dict

    @app.post('/runs/{run_id}/ask')
    def ask_user_response(run_id: str, body: AskIn, _: None = Depends(authorize)) -> dict:
        """Forward the user's answers to the worker's pending ask_user tool."""
        channel = channels.get(run_id)
        if channel is None:
            raise HTTPException(status_code=404, detail='no such run')
        channel.send_to_worker({'type': 'ASK_USER_RESPONSE', 'answers': body.answers})
        return {'sent': True}

    class ArtifactResponseIn(BaseModel):
        pick: str | None = None
        content: str | None = None

    @app.get('/sessions/{session_id}/processes')
    def session_processes(session_id: str, _: None = Depends(authorize)) -> list[dict]:
        """Shell processes this session spawned, newest first (R28 Phase 1)."""
        return db.list_processes(session_id)

    @app.get('/sessions/{session_id}/runs')
    def session_runs(
        session_id: str, limit: int = 20, _: None = Depends(authorize)
    ) -> list[dict]:
        """Recent runs, newest first (#77 run-output view); R31 runs table."""
        limit = max(1, min(limit, 100))
        return db.list_runs(session_id, limit=limit)

    @app.get('/sessions/{session_id}/artifacts')
    def session_artifacts(session_id: str, _: None = Depends(authorize)) -> list[dict]:
        """Living artifacts (choice cards, spec blocks), newest first (R6)."""
        from .artifacts import ArtifactStore

        return ArtifactStore(db, session_id).list()

    @app.get('/sessions/{session_id}/artifacts/events')
    def artifact_events(session_id: str, _: None = Depends(authorize)) -> StreamingResponse:
        """SSE push (R6): snapshot, then emitted/answered deltas, live."""
        from .artifacts import ArtifactStore

        def sse():
            for event in ArtifactStore(db, session_id).watch(poll_seconds=1.0):
                yield f'data: {json.dumps(event)}\n\n'

        return StreamingResponse(sse(), media_type='text/event-stream')

    @app.post('/artifacts/{artifact_id}/respond')
    def artifact_respond(artifact_id: str, body: ArtifactResponseIn, _: None = Depends(authorize)) -> dict:
        """Record the user's answer: a choice-card pick or an edited spec block."""
        from .artifacts import ArtifactStore

        response = (
            {'pick': body.pick} if body.pick is not None else {'content': body.content}
        )
        try:
            ArtifactStore(db, '').respond(artifact_id, response)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {'ok': True}

    @app.get('/sessions/{session_id}/plan')
    def session_plan(session_id: str, _: None = Depends(authorize)) -> dict:
        from .planning import PlanStore

        plan = PlanStore(db).latest(session_id)
        return plan or {}

    class NoteIn(BaseModel):
        content: str
        run_id: str | None = None
        offset_s: float | None = None

    class ProjectNoteIn(BaseModel):
        workdir: str
        content: str

    @app.post('/notes')
    def add_project_note(body: ProjectNoteIn, _: None = Depends(authorize)) -> dict:
        from .projectnotes import ProjectNoteStore

        note_id = ProjectNoteStore(db).add(
            str(Path(body.workdir).resolve()), body.content
        )
        return {'id': note_id}

    @app.get('/notes')
    def list_project_notes(
        workdir: str, include_resolved: bool = False,
        _: None = Depends(authorize),
    ) -> list[dict]:
        from .projectnotes import ProjectNoteStore

        return ProjectNoteStore(db).list(
            str(Path(workdir).resolve()), include_resolved=include_resolved
        )

    @app.post('/notes/{note_id}/resolve')
    def resolve_project_note(note_id: int, _: None = Depends(authorize)) -> dict:
        from .projectnotes import ProjectNoteStore

        if not ProjectNoteStore(db).resolve(note_id):
            raise HTTPException(status_code=404, detail='no such note')
        return {'resolved': True}

    @app.delete('/notes/{note_id}')
    def delete_project_note(note_id: int, _: None = Depends(authorize)) -> dict:
        from .projectnotes import ProjectNoteStore

        if not ProjectNoteStore(db).delete(note_id):
            raise HTTPException(status_code=404, detail='no such note')
        return {'deleted': True}

    class KeepIn(BaseModel):
        keep: bool

    @app.post('/sessions/{session_id}/keep')
    def keep_for_evals(session_id: str, body: KeepIn, _: None = Depends(authorize)) -> dict:
        db.set_keep_for_evals(session_id, body.keep)
        return {'ok': True}

    @app.post('/sessions/{session_id}/notes')
    def add_note(session_id: str, body: NoteIn, _: None = Depends(authorize)) -> dict:
        note_id = db.add_session_note(
            session_id, body.content, run_id=body.run_id, offset_s=body.offset_s,
        )
        return {'id': note_id}

    @app.get('/sessions/{session_id}/notes')
    def session_notes(session_id: str, _: None = Depends(authorize)) -> list[dict]:
        return db.list_session_notes(session_id)

    @app.get('/sessions/{session_id}/usage')
    def session_usage(session_id: str, _: None = Depends(authorize)) -> dict:
        return db.session_usage(session_id)

    @app.get('/sessions/{session_id}/diff')
    def session_diff(session_id: str, _: None = Depends(authorize)) -> dict:
        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        import subprocess

        result = subprocess.run(
            ['git', 'diff', 'HEAD'], cwd=workdir, capture_output=True, text=True, timeout=30
        )
        # #85: symbol-level "what changed" beside the raw diff.
        from .changesummary import changed_files, summarize
        from .impact import impact_graph

        try:
            summary = summarize(Path(workdir))
        except Exception:
            summary = []
        try:
            impact = impact_graph(Path(workdir), changed_files(Path(workdir)))
        except Exception:
            impact = {'edges': [], 'orphans': []}
        return {'diff': result.stdout, 'summary': summary, 'impact': impact}

    @app.get('/sessions/{session_id}/files')
    def session_files(session_id: str, _: None = Depends(authorize)) -> list[str]:
        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        root = Path(workdir)
        skip = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}
        out = []
        for p in sorted(root.rglob('*')):
            if any(part in skip for part in p.relative_to(root).parts):
                continue
            out.append(
                ('d ' if p.is_dir() else '  ') + str(p.relative_to(root)).replace('\\', '/')
            )
            if len(out) >= 500:
                break
        return out

    @app.get('/sessions/{session_id}/tree')
    def session_tree(session_id: str, _: None = Depends(authorize)) -> dict:
        """Nested file explorer tree (folders + files), Workdir-confined."""
        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        root = Path(workdir)
        skip = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache', 'dist', '.next'}

        def build(directory: Path, depth: int) -> list[dict]:
            if depth > 8:
                return []
            nodes = []
            try:
                entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return []
            for entry in entries:
                if entry.name in skip:
                    continue
                rel = entry.relative_to(root).as_posix()
                if entry.is_dir():
                    nodes.append({
                        'name': entry.name, 'path': rel, 'type': 'dir',
                        'children': build(entry, depth + 1),
                    })
                else:
                    nodes.append({'name': entry.name, 'path': rel, 'type': 'file'})
                if len(nodes) > 400:
                    break
            return nodes

        return {'name': root.name, 'type': 'dir', 'path': '', 'children': build(root, 0)}

    @app.get('/sessions/{session_id}/file')
    def get_file(session_id: str, path: str, _: None = Depends(authorize)) -> dict:
        from codingdude.tools import resolve_workdir_path

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target, error = resolve_workdir_path(workdir, path)
        if error or target is None:
            raise HTTPException(status_code=400, detail=error or 'bad path')
        if not target.is_file():
            raise HTTPException(status_code=404, detail='not found')
        try:
            text = target.read_text(encoding='utf-8', errors='replace')[:500_000]
        except OSError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            'path': path,
            'content': text,
            'is_markdown': path.lower().endswith(('.md', '.markdown')),
            'mtime': target.stat().st_mtime_ns,
        }

    @app.get('/sessions/{session_id}/callgraph')
    def session_callgraph(session_id: str, path: str, _: None = Depends(authorize)) -> dict:
        """Call graph of one workdir file — human code comprehension (#94, R42)."""
        from codingdude.tools import resolve_workdir_path

        from .callgraph import build_call_graph

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target, error = resolve_workdir_path(workdir, path)
        if error or target is None:
            raise HTTPException(status_code=400, detail=error or 'bad path')
        try:
            return build_call_graph(target)
        except (
            SyntaxError, ValueError, FileNotFoundError, UnicodeDecodeError
        ) as exc:
            raise HTTPException(
                status_code=422, detail=f'cannot analyze {path}: {exc}'
            ) from exc

    @app.get('/sessions/{session_id}/archmap')
    def session_archmap(session_id: str, _: None = Depends(authorize)) -> dict:
        """Module-level architecture map — files as nodes, imports as edges (#101)."""
        from .callgraph import build_module_graph

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        return build_module_graph(Path(workdir))

    @app.get('/sessions/{session_id}/trust')
    def session_trust(session_id: str, path: str, _: None = Depends(authorize)) -> dict:
        """Trust-my-tests: which tests reference this file (#103, R43)."""
        from .trustreport import build_trust_report

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target = Path(workdir) / path
        if not target.resolve().is_relative_to(Path(workdir).resolve()):
            raise HTTPException(status_code=400, detail='path escapes workdir')
        return build_trust_report(workdir, path)

    @app.get('/sessions/{session_id}/cfg')
    def session_cfg(
        session_id: str, path: str, function: str | None = None,
        _: None = Depends(authorize),
    ) -> dict:
        """Control-flow graph of one function — green reachable / red dead (#154, R46).

        With ``function`` omitted, returns the file's function list instead
        (the UI uses it to populate the picker).
        """
        import ast

        from codingdude.tools import resolve_workdir_path

        from .cfg import build_cfg

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target, error = resolve_workdir_path(workdir, path)
        if error or target is None:
            raise HTTPException(status_code=400, detail=error or 'bad path')
        try:
            source = target.read_text(encoding='utf-8', errors='replace')
            if function is None:
                names = [
                    node.name
                    for node in ast.walk(ast.parse(source))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                return {'path': path, 'functions': names}
            return build_cfg(source, function)
        except (
            SyntaxError, ValueError, FileNotFoundError, UnicodeDecodeError
        ) as exc:
            raise HTTPException(
                status_code=422, detail=f'cannot analyze {path}: {exc}'
            ) from exc

    @app.get('/sessions/{session_id}/structure')
    def session_structure(session_id: str, _: None = Depends(authorize)) -> dict:
        """Per-file symbol outlines — human project overview (#95, R42)."""
        from .structure import project_structure

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        return project_structure(Path(workdir))

    # ---- specialty-actions seam (#93, R41): checklists as invokable actions ----

    def _checklists_dir() -> Path:
        return Path(__file__).resolve().parents[2] / 'reference' / 'checklists'

    @app.get('/checklists')
    def list_checklists(_: None = Depends(authorize)) -> dict:
        """Distilled checklists (#92) with titles + use-when lines."""
        root = _checklists_dir()
        items = []
        if root.is_dir():
            for p in sorted(root.glob('*.md')):
                try:
                    md = p.read_text(encoding='utf-8')
                except OSError:
                    continue
                lines = md.split('\n')
                title = next((ln for ln in lines if ln.startswith('# ')), '').lstrip('# ').strip()
                title = title.removesuffix('Checklist').strip()
                use_when = next(
                    (ln.removeprefix('Use when:').strip() for ln in lines
                     if ln.startswith('Use when:')), '')
                items.append({'name': p.stem, 'title': title.strip(), 'use_when': use_when})
        return {'checklists': items}

    @app.get('/checklists/{name}')
    def get_checklist(name: str, _: None = Depends(authorize)) -> dict:
        path = (_checklists_dir() / f'{name}.md').resolve()
        if path.parent != _checklists_dir().resolve() or not path.is_file():
            raise HTTPException(status_code=404, detail=f'no such checklist: {name}')
        return {'name': name, 'markdown': path.read_text(encoding='utf-8')}

    @app.get('/sessions/{session_id}/file_diff')
    def file_diff(session_id: str, path: str, _: None = Depends(authorize)) -> dict:
        """HEAD baseline + on-disk content for the HITL diff view (#71).

        `base` is the git HEAD version of the file ('' for new/untracked
        files); `content` is what is on disk right now (the agent's edits).
        """
        import subprocess

        from codingdude.tools import resolve_workdir_path

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target, error = resolve_workdir_path(workdir, path)
        if error or target is None:
            raise HTTPException(status_code=400, detail=error or 'bad path')
        if not target.is_file():
            raise HTTPException(status_code=404, detail='not found')
        try:
            proc = subprocess.run(
                ['git', 'show', f'HEAD:{path}'],
                cwd=workdir, capture_output=True, timeout=10,
            )
            base = proc.stdout.decode('utf-8', errors='replace') if proc.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            base = ''
        try:
            content = target.read_text(encoding='utf-8', errors='replace')[:500_000]
        except OSError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {'path': path, 'base': base, 'content': content}

    @app.get('/sessions/{session_id}/renders')
    def session_renders(session_id: str, _: None = Depends(authorize)) -> dict:
        """Image files in the Workdir, newest first (screenshots, previews)."""
        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        session_start = 0
        for info in db.list_sessions(Path(workdir)):
            if info.session_id == session_id:
                try:
                    session_start = int(datetime.fromisoformat(info.created_at).timestamp())
                except ValueError:
                    session_start = 0
                break
        root = Path(workdir)
        exts = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'}
        skip = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}
        rendered: list[tuple[int, dict]] = []
        for p in sorted(root.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            if any(part in skip for part in p.relative_to(root).parts):
                continue
            st = p.stat()
            rendered.append((
                int(st.st_mtime),
                {
                    'path': p.relative_to(root).as_posix(),
                    'name': p.name,
                    'bytes': st.st_size,
                    'mtime': int(st.st_mtime),
                },
            ))
        rendered.sort(key=lambda entry: entry[0], reverse=True)
        # DB-persisted captures (R1) add provenance and survive workdir moves;
        # rows whose file is gone are dropped (nothing to serve).
        by_path = {entry['path']: dict(entry) for _mtime, entry in rendered}
        for rec in db.list_renders(session_id):
            if rec['path'] in by_path:
                by_path[rec['path']]['captured_at'] = rec['captured_at']
        return {
            'session_start': session_start,
            'renders': list(by_path.values())[:300],
        }

    @app.get('/sessions/{session_id}/render')
    def session_render(session_id: str, path: str, _: None = Depends(authorize)) -> Response:
        """Serve one rendered image (Workdir-confined)."""
        from codingdude.tools import resolve_workdir_path

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target, error = resolve_workdir_path(workdir, path)
        if error or target is None:
            raise HTTPException(status_code=400, detail=error or 'bad path')
        if not target.is_file():
            raise HTTPException(status_code=404, detail='not found')
        media = {
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.webp': 'image/webp', '.gif': 'image/gif', '.svg': 'image/svg+xml',
        }.get(target.suffix.lower(), 'application/octet-stream')
        return Response(content=target.read_bytes(), media_type=media)

    class FileSaveIn(BaseModel):
        path: str
        content: str
        expected_mtime: int | None = None  # staleness guard: st_mtime_ns at read time

    @app.put('/sessions/{session_id}/file')
    def save_file(session_id: str, body: FileSaveIn, _: None = Depends(authorize)) -> dict:
        from codingdude.tools import _atomic_write, resolve_workdir_path

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target, error = resolve_workdir_path(workdir, body.path)
        if error or target is None:
            raise HTTPException(status_code=400, detail=error or 'bad path')
        # Same staleness rail as the agent's edit tools: if the file changed
        # since the editor read it (agent wrote it mid-edit), refuse instead
        # of silently clobbering.
        if (
            body.expected_mtime is not None and target.exists()
            and target.stat().st_mtime_ns != body.expected_mtime
        ):
            raise HTTPException(
                status_code=409,
                detail=f'{body.path} changed on disk since it was read; '
                       'reload it and re-apply your edit.',
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, body.content)
        return {'saved': body.path, 'bytes': len(body.content),
                'mtime': target.stat().st_mtime_ns}

    class ProjectIn(BaseModel):
        name: str
        workdir: str

    @app.get('/projects')
    def get_projects(_: None = Depends(authorize)) -> list[dict]:
        return db.list_projects()

    @app.post('/projects')
    def add_project(body: ProjectIn, _: None = Depends(authorize)) -> dict:
        workdir = str(_validated_workdir(body.workdir))
        if not Path(workdir).is_dir():
            raise HTTPException(
                status_code=422,
                detail=f'no such directory: {workdir} — create it (or fix the path) first',
            )
        for p in db.list_projects():
            if p['workdir'] == workdir:
                raise HTTPException(status_code=409, detail='a project with this workdir already exists')
        pid = db.create_project(body.name, Path(workdir))
        # Project creation IS setup time: the base structure and the codegraph
        # index must exist before the first run, and failures must be visible
        # in the response (they used to be silent — live symptom: a fresh
        # project with no reference/ and no index).
        from .scaffold import ensure_project_scaffold

        wd = Path(workdir)
        scaffold = ensure_project_scaffold(wd)
        codegraph = _project_codegraph_boot(wd)
        return {
            'id': pid, 'name': body.name, 'workdir': workdir,
            'scaffold': scaffold, 'codegraph': codegraph,
        }

    @app.delete('/projects/{project_id}')
    def remove_project(project_id: int, _: None = Depends(authorize)) -> dict:
        return {'deleted': db.delete_project(project_id)}

    # ---- first-class planning data (R4): roadmap, tickets, decisions ----

    def _workdir_or_404(workdir: str) -> str:
        resolved = str(Path(workdir).resolve())
        if not Path(resolved).is_dir():
            raise HTTPException(status_code=404, detail='no such workdir')
        return resolved

    class RoadmapIn(BaseModel):
        title: str
        body: str = ''
        status: str | None = None  # update only

    @app.get('/planning')
    def get_planning(workdir: str, _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore, parse_roadmap_md

        store = RoadmapStore(db)
        resolved = _workdir_or_404(workdir)
        md = Path(resolved) / 'ROADMAP.md'
        # ROADMAP.md is canonical and always live - serve it directly when present.
        roadmap = parse_roadmap_md(md) if md.is_file() else store.list_roadmap(resolved)
        return {
            'roadmap': roadmap,
            'tickets': store.list_tickets(resolved),
            'decisions': store.list_decisions(resolved),
        }

    @app.post('/planning/roadmap')
    def add_roadmap_item(workdir: str, body: RoadmapIn, _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore, upsert_roadmap_md

        resolved = _workdir_or_404(workdir)
        md = Path(resolved) / 'ROADMAP.md'
        if md.is_file():
            upsert_roadmap_md(md, None, title=body.title, body=body.body,
                              status=body.status)
            return {'id': 'new'}
        item_id = RoadmapStore(db).create_roadmap_item(resolved, body.title, body.body)
        return {'id': item_id}

    class RoadmapUpdate(BaseModel):
        status: str
        body: str | None = None

    @app.put('/planning/roadmap/{item_id}')
    def change_roadmap_item(item_id: str, workdir: str, body: RoadmapUpdate,
                            _: None = Depends(authorize)) -> dict:
        from .roadmap import ROADMAP_STATUSES, RoadmapStore, upsert_roadmap_md

        if body.status not in ROADMAP_STATUSES:
            raise HTTPException(status_code=422, detail='bad status')
        resolved = _workdir_or_404(workdir)
        md = Path(resolved) / 'ROADMAP.md'
        if md.is_file() and item_id.startswith('R'):
            try:
                upsert_roadmap_md(md, item_id, status=body.status, body=body.body)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail='no such roadmap item') from exc
            return {'updated': item_id}
        fields: dict = {'status': body.status}
        if body.body is not None:
            fields['body'] = body.body
        try:
            numeric_id = int(item_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail='no such roadmap item') from exc
        changed = RoadmapStore(db).update_roadmap_item(resolved, numeric_id, **fields)
        if not changed:
            raise HTTPException(status_code=404, detail='no such roadmap item')
        return {'updated': item_id}

    @app.delete('/planning/roadmap/{item_id}')
    def remove_roadmap_item(item_id: str, workdir: str, _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore

        try:
            numeric_id = int(item_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail='no such roadmap item') from exc
        return {'deleted': RoadmapStore(db).delete_roadmap_item(
            _workdir_or_404(workdir), numeric_id)}

    class TicketIn(BaseModel):
        title: str
        body: str = ''
        blocked_by: str | None = None
        status: str | None = None  # update only

    @app.post('/planning/tickets')
    def add_ticket(workdir: str, body: TicketIn, _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore

        ticket_id = RoadmapStore(db).create_ticket(
            _workdir_or_404(workdir), body.title, body.body, body.blocked_by
        )
        return {'id': ticket_id}

    class TicketUpdate(BaseModel):
        status: str
        body: str | None = None

    @app.put('/planning/tickets/{ticket_id}')
    def change_ticket(ticket_id: int, workdir: str, body: TicketUpdate,
                      _: None = Depends(authorize)) -> dict:
        from .roadmap import TICKET_STATUSES, RoadmapStore

        if body.status not in TICKET_STATUSES:
            raise HTTPException(status_code=422, detail='bad status')
        fields: dict = {'status': body.status}
        if body.body is not None:
            fields['body'] = body.body
        changed = RoadmapStore(db).update_ticket(_workdir_or_404(workdir), ticket_id, **fields)
        if not changed:
            raise HTTPException(status_code=404, detail='no such ticket')
        return {'updated': ticket_id}

    @app.delete('/planning/tickets/{ticket_id}')
    def remove_ticket(ticket_id: int, workdir: str, _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore

        return {'deleted': RoadmapStore(db).delete_ticket(_workdir_or_404(workdir), ticket_id)}

    class DecisionIn(BaseModel):
        title: str
        body: str = ''

    @app.post('/planning/decisions')
    def add_decision(workdir: str, body: DecisionIn, _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore

        decision_id = RoadmapStore(db).create_decision(_workdir_or_404(workdir), body.title, body.body)
        return {'id': decision_id}

    class DecisionUpdate(BaseModel):
        body: str

    @app.put('/planning/decisions/{decision_id}')
    def change_decision(decision_id: int, workdir: str, body: DecisionUpdate,
                        _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore

        changed = RoadmapStore(db).update_decision(
            _workdir_or_404(workdir), decision_id, body=body.body
        )
        if not changed:
            raise HTTPException(status_code=404, detail='no such decision')
        return {'updated': decision_id}

    @app.delete('/planning/decisions/{decision_id}')
    def remove_decision(decision_id: int, workdir: str, _: None = Depends(authorize)) -> dict:
        from .roadmap import RoadmapStore

        return {'deleted': RoadmapStore(db).delete_decision(_workdir_or_404(workdir), decision_id)}


    @app.post('/sessions/{session_id}/review')
    async def run_review(session_id: str, _: None = Depends(authorize)) -> dict:
        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        # ADR-0002: agent runs never execute in the server process — the
        # review runs in a short-lived worker subprocess (--review mode)
        # and reports its findings on stdout.
        from .tools import run_captured

        cap = await run_captured(
            [sys.executable, '-m', 'codingdude.worker', '--review', session_id],
            cwd=Path('.'), timeout=600)
        if cap is None or cap.code != 0:
            raise HTTPException(
                status_code=502,
                detail=f'review worker failed: {(cap.stderr if cap else "timed out")[:400]}',
            )
        return json.loads(cap.stdout)

    @app.get('/sessions/{session_id}/checkpoints')
    def list_checkpoints(session_id: str, _: None = Depends(authorize)) -> list[dict]:
        from .checkpoints import CheckpointStore

        return CheckpointStore(home).list_checkpoints(session_id)

    class RestoreIn(BaseModel):
        path: str | None = None  # None → restore the whole checkpoint

    @app.post('/checkpoints/{session_id}/{cp_id}/restore')
    def restore_checkpoint(session_id: str, cp_id: str, body: RestoreIn,
                           _: None = Depends(authorize)) -> dict:
        from .checkpoints import CheckpointStore

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        store = CheckpointStore(home)
        try:
            if body.path:
                return store.restore_file(session_id, cp_id, body.path, Path(workdir))
            return store.restore_checkpoint(session_id, cp_id, Path(workdir))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post('/checkpoints/{session_id}/{cp_id}/rewind')
    def rewind_checkpoint(session_id: str, cp_id: str, _: None = Depends(authorize)) -> dict:
        from .checkpoints import CheckpointStore

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        return CheckpointStore(home).rewind_to(session_id, cp_id, Path(workdir))

    @app.get('/runs/active')
    def active_runs(_: None = Depends(authorize)) -> list[dict]:
        out = []
        for run_id, ch in channels.items():
            # Terminal already delivered: the worker may still be draining
            # its post-run tail (memory extraction), but the run is over —
            # listing it makes the UI show a stop button after 'finished'.
            if ch.saw_terminal():
                continue
            if ch.worker is None or ch.worker.poll() is None:
                out.append({'run_id': run_id, 'session_id': ch.session_id})
        return out

    @app.get('/sessions/{session_id}/trace')
    def session_trace(session_id: str, limit: int = 50, _: None = Depends(authorize)) -> list[dict]:
        """Replayable run trace: the last `limit` traced events (default 50)."""
        trace_file = home / 'traces' / f'{session_id}.jsonl'
        if not trace_file.exists():
            return []
        lines = trace_file.read_text(encoding='utf-8').splitlines()
        out = []
        for line in lines[-limit:]:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    @app.get('/sessions/{session_id}/standards')
    def session_standards(session_id: str, _: None = Depends(authorize)) -> dict:
        """The active engineering methodology: directive layers + review checklist."""
        from codingdude.directives import build_directive_layers
        from codingdude.prompts import load_prompt

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        return {
            'layers': build_directive_layers(home, Path(workdir)),
            'review_checklist': load_prompt('review'),
        }

    # ---- self-hosted configuration: directives + skills editable in the UI ----

    @app.get('/directives')
    def get_directives(_: None = Depends(authorize)) -> dict:
        path = home / 'DIRECTIVES.md'
        content = path.read_text(encoding='utf-8') if path.exists() else ''
        return {'content': content, 'path': str(path)}

    @app.put('/directives')
    def put_directives(body: dict, _: None = Depends(authorize)) -> dict:
        path = home / 'DIRECTIVES.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.get('content', ''), encoding='utf-8')
        return {'saved': str(path)}

    @app.get('/skills/detail')
    def get_skills_detail(_: None = Depends(authorize)) -> list[dict]:
        from codingdude.skills import SkillRegistry

        registry = SkillRegistry(home)
        return registry.detail()

    @app.put('/skills/detail/{name}')
    def put_skill(name: str, body: dict, _: None = Depends(authorize)) -> dict:
        from codingdude.skills import SkillRegistry

        registry = SkillRegistry(home)
        saved_to = registry.save(name, body.get('description', ''), body.get('body', ''))
        return {'saved': saved_to}

    @app.delete('/skills/detail/{name}')
    def delete_skill(name: str, _: None = Depends(authorize)) -> dict:
        from codingdude.skills import SkillRegistry

        registry = SkillRegistry(home)
        if not registry.delete(name):
            raise HTTPException(status_code=404, detail='no such skill')
        return {'deleted': name}


    class MemoryIn(BaseModel):
        content: str
        scope: str = 'workdir'

    @app.get('/memory')
    def get_memory(_: None = Depends(authorize)) -> list[dict]:
        from .memory import MemoryStore

        return MemoryStore(db).all_entries()

    @app.post('/memory')
    def add_memory(body: MemoryIn, _: None = Depends(authorize)) -> dict:
        from .memory import MemoryStore

        entry_id = MemoryStore(db).add(body.content, scope=body.scope)
        return {'id': entry_id}

    @app.delete('/memory/{entry_id}')
    def delete_memory(entry_id: int, _: None = Depends(authorize)) -> dict:
        from .memory import MemoryStore

        return {'deleted': MemoryStore(db).delete_id(entry_id)}

    @app.get('/mcp')
    def get_mcp(session_id: str, _: None = Depends(authorize)) -> list[dict]:
        from .mcp_config import list_mcp_servers

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        return list_mcp_servers(home, Path(workdir))

    class McpToggleIn(BaseModel):
        disabled: bool

    @app.post('/mcp/{name}/toggle')
    def toggle_mcp(name: str, body: McpToggleIn, session_id: str, _: None = Depends(authorize)) -> dict:
        from .mcp_config import set_mcp_disabled

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        if not set_mcp_disabled(home, Path(workdir), name, body.disabled):
            raise HTTPException(status_code=404, detail='no such server')
        return {'name': name, 'disabled': body.disabled}

    @app.delete('/runs/{run_id}')
    def cancel_run(run_id: str, _: None = Depends(authorize)) -> dict:
        channel = channels.get(run_id)
        if channel is None:
            raise HTTPException(status_code=404, detail='no such run')
        worker_pid = channel.worker.pid if channel.worker else None
        alive = channel.worker is not None and channel.worker.poll() is None
        logging.getLogger('codingdude.server').warning(
            'STOP_REQUESTED run=%s worker_pid=%s alive=%s', run_id, worker_pid, alive)
        if channel.worker and channel.worker.poll() is None:
            channel.worker.terminate()
        channel.push({'type': 'RUN_CANCELLED'})
        return {'cancelled': run_id}

    @app.get('/runs/{run_id}/events')
    async def run_events(
        run_id: str, request: Request, token_q: str = Query('', alias='token')
    ) -> StreamingResponse:
        # Cookie (browser login), bearer header, or query token all authenticate.
        cookie = request.cookies.get('cd_session', '')
        auth_header = request.headers.get('authorization', '')
        ok = (
            cookie == token
            or auth_header == f'Bearer {token}'
            or token_q == token
        )
        if not ok:
            raise HTTPException(status_code=401, detail='invalid token')
        host = request.client.host if request.client else ''
        local = ('127.0.0.1', '::1') + (('testclient',) if allow_testclient else ())
        if host not in local:
            raise HTTPException(status_code=403, detail='local only')
        channel = channels.get(run_id)
        if channel is None:
            raise HTTPException(status_code=404, detail='no such run')
        return StreamingResponse(
            channel.sse(), media_type='text/event-stream'
        )

    @app.websocket('/runs/{run_id}/ws')
    async def run_ws(
        ws: WebSocket, run_id: str, ws_token: str = Query('', alias='token')
    ):
        host = ws.client.host if ws.client else ''
        local = ('127.0.0.1', '::1') + (('testclient',) if allow_testclient else ())
        if ws_token != token or host not in local:
            await ws.close(code=4401)
            return
        await ws.accept()
        channel = channels.get(run_id)
        if channel is None:
            await ws.close(code=4404)
            return
        channel.boot_seen = True  # #148: worker reached the server
        channel.loop = asyncio.get_running_loop()

        async def forward_inbox():
            while True:
                msg = await channel.inbox.get()
                await ws.send_text(json.dumps(msg))

        inbox_task = asyncio.create_task(forward_inbox())
        try:
            while True:
                raw = await ws.receive_text()
                channel.push(json.loads(raw))
        except WebSocketDisconnect:
            pass
        finally:
            inbox_task.cancel()
            # R31: the worker closing its ws is the only worker-lifecycle
            # signal the server gets. Watch the process until it exits, log
            # it, and if it died without a terminal event, synthesize one so
            # no consumer waits on a dead run. Then reap the channel.
            # #148: pass db so the runs row gets its terminal status here;
            # the janitor covers workers that never connected.
            asyncio.create_task(_reap_worker(channel, db))

    @app.get('/models')
    def list_models(_: None = Depends(authorize)) -> dict:
        """The configured model lineup, for the UI's model selector."""
        from .config import KNOWN_PROVIDERS, load_config

        cfg = load_config(home)
        return {
            'default': 'main',
            # #212: configured custom providers are valid runtime choices too
            'provider_prefixes': sorted(set(KNOWN_PROVIDERS) | set(cfg.providers)),
            'models': {
                'main': cfg.models.main,
                'subagent': cfg.models.subagent,
                'fallback': cfg.models.fallback,
                'vision': cfg.models.vision,
            },
        }

    # ---- user-managed LLM configuration (R50, #208) ----

    @app.get('/config/models')
    def get_config_models(_: None = Depends(authorize)) -> dict:
        """Full lineup + provider key presence; secret values are never echoed."""
        from .config import load_config, models_payload

        return models_payload(load_config(home))

    class ConfigModelsIn(BaseModel):
        models: dict | None = None
        providers: dict | None = None

    @app.put('/config/models')
    def put_config_models(body: ConfigModelsIn, _: None = Depends(authorize)) -> dict:
        from .config import load_config, models_payload, save_models, save_provider_keys

        saved: dict = {}
        try:
            if body.providers is not None:
                saved['providers'] = save_provider_keys(home, body.providers)
            if body.models is not None:
                saved.update(save_models(home, body.models))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {'saved': saved, 'effective': models_payload(load_config(home))}

    @app.get('/config/verify')
    def get_config_verify(_: None = Depends(authorize)) -> dict:
        """Auth smoke for every configured provider (catches a clobbered
        key here instead of at the next run). Never returns key values."""
        from .config import load_config, verify_provider_keys

        return {'providers': verify_provider_keys(load_config(home))}

    class ExecIn(BaseModel):
        command: str

    @app.post('/sessions/{session_id}/exec')
    async def session_exec(session_id: str, body: ExecIn, _: None = Depends(authorize)) -> dict:
        """Run a shell command in the Workdir and return the output (Terminal panel)."""
        from .tools import run_captured, shell_argv

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        cap = await run_captured(
            shell_argv(body.command), cwd=Path(workdir), timeout=120)
        if cap is None:
            return {'exit': -1, 'output': 'timed out'}
        return {'exit': cap.code, 'output': cap.combined[:8000]}

    @app.get('/health')
    def health() -> dict:
        return {
            'ok': True,
            'version': __version__,
            'git_sha': _git_sha(),
            'started_at': _STARTED_AT,
        }

    @app.middleware('http')
    async def strip_api_prefix(request, call_next):
        """The built frontend calls /api/... (its dev-proxy convention);
        rewrite to the real routes when FastAPI serves it directly."""
        if request.url.path.startswith('/api/'):
            request.scope['path'] = request.url.path[len('/api'):]
        return await call_next(request)

    # Serve the built frontend when it exists (single-command deployment).
    dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if dist.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount('/', StaticFiles(directory=dist, html=True), name='ui')

    app.state.token = token
    app.state.db = db
    app.state.channels = channels
    app.state.port = 8000  # overwritten by serve() with the real bind port
    return app


def load_or_create_token(home: Path | None = None) -> str:
    """Stable token: generated once, stored next to the config, reused across
    restarts so workers and already-logged-in browsers never re-authenticate."""
    path = (home or config_home()) / 'server-token'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding='utf-8').strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(16)
    path.write_text(token, encoding='utf-8')
    return token


def serve(host: str = HOST, port: int = 8765) -> None:
    """Run the uvicorn server on the given host/port (foreground)."""
    import uvicorn

    token = load_or_create_token()
    app = create_app(token=token)
    app.state.port = port
    # Lifecycle diagnostics (R31) must land somewhere readable even when the
    # console that launched the server is gone.
    log_dir = config_home() / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / 'server.log', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger(__name__).info('codingdude server on http://%s:%s', host, port)
    print(f'codingdude server on http://{host}:{port} token={token}')
    uvicorn.run(app, host=host, port=port, log_level='warning')


if __name__ == '__main__':
    serve()
