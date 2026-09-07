# Web UI as the primary frontend, not a terminal UI

CodingDude's user-facing frontend is a browser app (React + Vite + Tailwind, AG-UI protocol over SSE) rather than the terminal UI (Textual/REPL) that most personal coding agents use. The product's core interactions — live diffs of every edit, inline Approval cards with Approve/Approve-all-matching/Deny, a tool-call timeline, file tree, terminal panel, and cost meter — are graphical by nature, and owning those components outright beats borrowing a generic chat kit. The trade: a second codebase (frontend) to maintain and an HTTP layer around the engine. A thin Headless Run mode keeps a terminal entry point for scripting, and the REPL prototype was dropped deliberately.

## Considered Options

- **Rich terminal UI (Textual)** — rejected: diff rendering, approval modals, and file trees are cramped in a terminal; we'd rebuild GUI concepts in a harder medium.
- **pydantic-ai's built-in web chat sample** — rejected: generic chat shape; outgrown immediately.
- **CopilotKit prebuilt components** — rejected: the coding-specific panels *are* the product; the dependency would shape the UI.
