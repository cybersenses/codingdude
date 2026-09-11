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
    """Bridges worker WebSocket events to SSE subscribers."""

    def __init__(self, run_id: str, session_id: str, registry: dict):
        self.run_id = run_id
        self.session_id = session_id
        self.registry = registry
        self.queue: asyncio.Queue = asyncio.Queue()
        self.inbox: asyncio.Queue = asyncio.Queue()  # server → worker (approvals)
        self.worker: subprocess.Popen | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    def push(self, event: dict) -> None:
        # Sync endpoints run in threadpool threads: marshal onto the loop once
        # a consumer is attached, before that rely on single-producer safety.
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, event)
        else:
            self.queue.put_nowait(event)

    def send_to_worker(self, message: dict) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.inbox.put_nowait, message)
        else:
            self.inbox.put_nowait(message)

    async def sse(self):
        self.loop = asyncio.get_running_loop()
        try:
            while True:
                event = await self.queue.get()
                yield f'data: {json.dumps(event)}\n\n'
                if event.get('type') in TERMINAL_EVENTS:
                    return
        finally:
            # Reap only dead runs: a live worker must stay cancellable even if
            # the browser's EventSource dropped (reconnect, refresh, sleep).
            if self.worker is None or self.worker.poll() is not None:
                self.registry.pop(self.run_id, None)


def create_app(
    home: Path | None = None, token: str | None = None, allow_testclient: bool = False
) -> FastAPI:
    home = home or config_home()
    token = token or secrets.token_urlsafe(16)
    from .mcp_config import ensure_default_mcp

    ensure_default_mcp(home)
    app = FastAPI()
    db = Database.connect(home)
    channels: dict[str, RunChannel] = {}

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

    class RunIn(BaseModel):
        prompt: str
        model: str | None = None
        yolo: bool = False
        budget: float | None = None
        fix_loop: bool = False
        image_b64: str | None = None  # base64 data-URL payload (no prefix)

    @app.post('/sessions')
    def create_session(body: SessionIn, _: None = Depends(authorize)) -> dict:
        session_id = db.create_session(Path(body.workdir).resolve(), title=body.title)
        return {'session_id': session_id}

    @app.get('/sessions')
    def list_sessions(workdir: str, _: None = Depends(authorize)) -> list[dict]:
        import dataclasses

        rows = db.list_sessions(Path(workdir).resolve())
        return [dataclasses.asdict(r) for r in rows]

    @app.get('/sessions/{session_id}/messages')
    def session_messages(session_id: str, _: None = Depends(authorize)) -> list[dict]:
        import time as _time

        from pydantic_ai.messages import ModelMessagesTypeAdapter
        from pydantic_core import ValidationError

        from .messages import decode_messages

        for attempt in range(5):
            try:
                payloads = db.load_messages(session_id)
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

        cmd = [
            sys.executable, '-m', 'codingdude.worker',
            '--server', f'ws://{HOST}:{app.state.port}/runs/{run_id}/ws',
            '--session', session_id,
            '--workdir', workdir,
            '--prompt', body.prompt,
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

        return {'run_id': run_id}

    class ApprovalIn(BaseModel):
        decision: str  # 'approve' | 'pattern' | 'deny'

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

    @app.get('/sessions/{session_id}/plan')
    def session_plan(session_id: str, _: None = Depends(authorize)) -> dict:
        from .planning import PlanStore

        plan = PlanStore(db).latest(session_id)
        return plan or {}

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
        return {'diff': result.stdout}

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
        try:
            text = target.read_text(encoding='utf-8', errors='replace')[:500_000]
        except OSError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            'path': path,
            'content': text,
            'is_markdown': path.lower().endswith(('.md', '.markdown')),
        }

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
        return {
            'session_start': session_start,
            'renders': [entry for _mtime, entry in rendered][:300],
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

    @app.put('/sessions/{session_id}/file')
    def save_file(session_id: str, body: FileSaveIn, _: None = Depends(authorize)) -> dict:
        from codingdude.tools import resolve_workdir_path

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        target, error = resolve_workdir_path(workdir, body.path)
        if error or target is None:
            raise HTTPException(status_code=400, detail=error or 'bad path')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding='utf-8')
        return {'saved': body.path, 'bytes': len(body.content)}

    class ProjectIn(BaseModel):
        name: str
        workdir: str

    @app.get('/projects')
    def get_projects(_: None = Depends(authorize)) -> list[dict]:
        return db.list_projects()

    @app.post('/projects')
    def add_project(body: ProjectIn, _: None = Depends(authorize)) -> dict:
        workdir = str(Path(body.workdir).resolve())
        for p in db.list_projects():
            if p['workdir'] == workdir:
                raise HTTPException(status_code=409, detail='a project with this workdir already exists')
        pid = db.create_project(body.name, Path(workdir))
        return {'id': pid, 'name': body.name, 'workdir': workdir}

    @app.delete('/projects/{project_id}')
    def remove_project(project_id: int, _: None = Depends(authorize)) -> dict:
        return {'deleted': db.delete_project(project_id)}

    @app.post('/sessions/{session_id}/review')
    async def run_review(session_id: str, _: None = Depends(authorize)) -> dict:
        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        from .config import load_config
        from .engine import Engine

        eng = Engine(config=load_config(), db=db)
        eng._extraction_model = eng._build_subagent_model()
        findings = await eng.review_diff(session_id)
        return {'findings': findings or 'CLEAN — no findings'}

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

    @app.get('/models')
    def list_models(_: None = Depends(authorize)) -> dict:
        """The configured model lineup, for the UI's model selector."""
        from .config import load_config

        cfg = load_config()
        return {
            'default': 'main',
            'models': {
                'main': cfg.models.main,
                'subagent': cfg.models.subagent,
                'fallback': cfg.models.fallback,
                'vision': cfg.models.vision,
            },
        }

    class ExecIn(BaseModel):
        command: str

    @app.post('/sessions/{session_id}/exec')
    async def session_exec(session_id: str, body: ExecIn, _: None = Depends(authorize)) -> dict:
        """Run a shell command in the Workdir and return the output (Terminal panel)."""
        import asyncio

        from .tools import scrubbed_env

        workdir = db.session_workdir(session_id)
        if not workdir:
            raise HTTPException(status_code=404, detail='no such session')
        proc = await asyncio.create_subprocess_exec(
            'bash', '-c', body.command, cwd=workdir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=scrubbed_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            return {'exit': -1, 'output': 'timed out'}
        output = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
        return {'exit': proc.returncode, 'output': output[:8000]}

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
    import uvicorn

    token = load_or_create_token()
    app = create_app(token=token)
    app.state.port = port
    logging.getLogger(__name__).info('codingdude server on http://%s:%s', host, port)
    print(f'codingdude server on http://{host}:{port} token={token}')
    uvicorn.run(app, host=host, port=port, log_level='warning')


if __name__ == '__main__':
    serve()
