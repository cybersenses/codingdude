# 08: Web server + worker + SSE

**What to build:** ADR-0002 made real. A FastAPI server (localhost bind + token auth) exposes session create/list/resume and run-start endpoints; each accepted run spawns a worker subprocess that executes the engine, connects back over a local WebSocket, and streams native agent events, which the server bridges to browser-facing SSE in the AG-UI protocol shape. Killing the worker cancels the run; a crashed worker leaves the Session resumable from history.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** ready-for-agent

- [ ] Server rejects unauthenticated/non-local requests; token auth passes
- [ ] Starting a run spawns a worker subprocess and the SSE endpoint emits the run's events in AG-UI shape
- [ ] Session create/list/resume endpoints work against the SQLite store
- [ ] Killing the worker process cancels the run cleanly (server stays up)
- [ ] A worker crash mid-run leaves the Session resumable with prior turns intact
- [ ] HTTP-seam tests (test client + scripted engine) cover the above
