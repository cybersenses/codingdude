"""CodingDude web server: sessions + runs, bridging worker events to SSE.

Per ADR-0002 the server never runs the agent itself: each accepted run spawns a
worker subprocess that connects back over a local WebSocket; the server bridges
those events to browser-facing SSE in AG-UI shape and persists state to SQLite
(the worker shares the same DB).
"""

import asyncio
import json
import secrets
import subprocess
import sys
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import config_home
from .db import Database

HOST = '127.0.0.1'  # localhost only, by design


class RunChannel:
    """Bridges worker WebSocket events to SSE subscribers."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.worker: subprocess.Popen | None = None

    def push(self, event: dict) -> None:
        self.queue.put_nowait(event)

    async def sse(self):
        while True:
            event = await self.queue.get()
            yield f'data: {json.dumps(event)}\n\n'
            if event.get('type') in ('RUN_FINISHED', 'RUN_ERROR', 'RUN_CANCELLED'):
                return


def create_app(
    home: Path | None = None, token: str | None = None, allow_testclient: bool = False
) -> FastAPI:
    home = home or config_home()
    token = token or secrets.token_urlsafe(16)
    app = FastAPI()
    db = Database.connect(home)
    channels: dict[str, RunChannel] = {}

    def authorize(request: Request) -> None:
        auth = request.headers.get('authorization', '')
        if not auth.startswith('Bearer ') or auth.removeprefix('Bearer ') != token:
            raise HTTPException(status_code=401, detail='invalid token')
        host = request.client.host if request.client else ''
        local = ('127.0.0.1', '::1') + (('testclient',) if allow_testclient else ())
        if host not in local:
            raise HTTPException(status_code=403, detail='local only')

    class SessionIn(BaseModel):
        workdir: str
        title: str | None = None

    class RunIn(BaseModel):
        prompt: str
        model: str | None = None
        yolo: bool = False

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

        from pydantic_core import ValidationError
        from pydantic_ai.messages import ModelMessagesTypeAdapter

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
        row = db._conn.execute(
            'SELECT workdir FROM sessions WHERE session_id = ?', (session_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='no such session')
        workdir = row['workdir']

        run_id = secrets.token_urlsafe(8)
        channel = RunChannel()
        channels[run_id] = channel

        cmd = [
            sys.executable, '-m', 'codingdude.worker',
            '--server', f'ws://{HOST}:{app.state.port}/runs/{run_id}/ws?token={token}',
            '--session', session_id,
            '--workdir', workdir,
            '--prompt', body.prompt,
        ]
        if body.model:
            cmd += ['--model', body.model]
        if body.yolo:
            cmd.append('--yolo')
        channel.worker = subprocess.Popen(cmd)

        return {'run_id': run_id}

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
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        authorize(request)
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
        if ws_token != token or host not in ('127.0.0.1', '::1', 'testclient'):
            await ws.close(code=4401)
            return
        await ws.accept()
        channel = channels.get(run_id)
        if channel is None:
            await ws.close(code=4404)
            return
        try:
            while True:
                raw = await ws.receive_text()
                channel.push(json.loads(raw))
        except WebSocketDisconnect:
            pass

    @app.get('/health')
    def health() -> dict:
        return {'ok': True}

    app.state.token = token
    app.state.db = db
    app.state.channels = channels
    app.state.port = 8000  # overwritten by serve() with the real bind port
    return app


def serve(host: str = HOST, port: int = 8765) -> None:
    import uvicorn

    app = create_app()
    app.state.port = port
    print(f'codingdude server on http://{host}:{port} token={app.state.token}')
    uvicorn.run(app, host=host, port=port, log_level='warning')


if __name__ == '__main__':
    serve()
