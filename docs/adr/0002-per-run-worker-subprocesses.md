# One worker subprocess per run, not in-server execution or a daemon

The web server never executes agent runs in its own process, nor through a persistent worker daemon. Each accepted run gets a freshly spawned worker subprocess that connects back over a local WebSocket and streams events, which the server bridges to browser SSE and persists to SQLite. For a single-user tool this looks heavier than it needs to be — that's deliberate: a run that hangs or burns budget dies with its process (kill = cancel), the server stays responsive, and no daemon supervision/queue-polling machinery exists to babysit. Crash recovery comes from Session history in SQLite, not from process liveness. Headless Runs bypass the server entirely and execute the engine in-process.

## Considered Options

- **In-server asyncio tasks** — rejected: a wedged run or runaway loop takes down the UI with it; cancellation via kill is cleaner.
- **Persistent worker daemon + SQLite job queue** — rejected until proven necessary: queue polling and supervision are cost without benefit at 1–3 concurrent runs.
- **Redis + Celery** — rejected: industrial machinery for a single-user tool.
