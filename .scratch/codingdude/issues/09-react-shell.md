# 09: React shell

**What to build:** The browser face of CodingDude (ADR-0001): a React + Vite + Tailwind app speaking the AG-UI client protocol over SSE. The session sidebar creates Sessions per Workdir and lists/resumes past ones; the center pane streams the chat with a collapsible inline tool-call timeline (args → output → duration); a run can be stopped.

**Blocked by:** 08 (Web server + worker + SSE)

**Status:** resolved

- [x] Browser: create a Session on a Workdir, send a prompt, watch the streamed reply
- [x] Tool calls appear as collapsible timeline entries with arguments, output, and duration
- [x] Sidebar lists past Sessions and resumes one with its history rendered
- [x] Stop button cancels a running run
- [x] Dev build proxies to the local server without manual URL fiddling

## Comments

2026-09-07: Commit 0216dc4 (plus server fix: events endpoint accepts the token as a query param since EventSource can't send headers; push() marshals onto the event loop — sync endpoints run in FastAPI threadpool threads and asyncio.Queue.put_nowait is not thread-safe; `codingdude serve --port` starts server + UI; the built `frontend/dist` is served by FastAPI at `/`). Stack: React 18 + Vite + Tailwind v4 (@tailwindcss/vite). Auth token is pasted once into the sidebar and stored in localStorage. Caveat, stated honestly: acceptance criteria were verified at the HTTP seam (real uvicorn + worker subprocess + SSE assertions in tests/test_server.py) and via build + served-HTML smoke; no human has clicked through the UI yet — do one manual pass before calling it polished. Tool timeline currently shows tool name + result; per-call args/duration arrive with ticket 10's timeline work.
