# 08: Web server + worker + SSE

**What to build:** ADR-0002 made real. A FastAPI server (localhost bind + token auth) exposes session create/list/resume and run-start endpoints; each accepted run spawns a worker subprocess that executes the engine, connects back over a local WebSocket, and streams native agent events, which the server bridges to browser-facing SSE in the AG-UI protocol shape. Killing the worker cancels the run; a crashed worker leaves the Session resumable from history.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** resolved

- [x] Server rejects unauthenticated/non-local requests; token auth passes
- [x] Starting a run spawns a worker subprocess and the SSE endpoint emits the run's events in AG-UI shape
- [x] Session create/list/resume endpoints work against the SQLite store
- [x] Killing the worker process cancels the run cleanly (server stays up)
- [x] A worker crash mid-run leaves the Session resumable with prior turns intact
- [x] HTTP-seam tests (test client + scripted engine) cover the above

## Comments

2026-09-07: Commit d89cf24. Engine gained `emit` — a streaming branch (`agent.iter` + `node.stream`) emitting AG-UI wire events (RUN_STARTED, TEXT_MESSAGE_START/CONTENT/END, TOOL_CALL_ARGS/END; terminal RUN_FINISHED/RUN_ERROR/RUN_CANCELLED sent by the worker). Worker subprocess (`python -m codingdude.worker`) connects back via `websockets` and shares the SQLite DB. Server: FastAPI on 127.0.0.1 with Bearer-token auth; SSE bridge; DELETE /runs/{id} terminates the worker. HTTP-seam tests run a real uvicorn server on a thread so the subprocess genuinely connects over TCP; scripted models injected via the `codingdude-test:echo` / `codingdude-test:sleep` test hooks (no API keys needed). Hardening added along the way: WAL + busy_timeout for multi-process SQLite; terminal events are sent only after persistence so message reads can't race the run. Note: AG-UI *wire shape* is emitted directly; full protocol fidelity via pydantic-ai's `ag_ui` adapter (thinking parts etc.) is a later upgrade and needs the `ag-ui-protocol` package.
