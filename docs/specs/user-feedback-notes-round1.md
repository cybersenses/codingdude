# Spec: User feedback round 1 (WifiMon session notes → CodingDude improvements)

All 12 user notes concern CodingDude itself. Decisions confirmed by user 2026-07-28.

## T11 — Project notes (N10, N11, N12)
- New `project_notes` table: `id, workdir, content, status ('open'|'resolved'), created_at, resolved_at`. Workdir-scoped → no cross-project bleed (N11).
- Agent tools (workdir toolset): `read_project_notes` (open notes first, resolved on request), `resolve_note(id)`, `add_project_note` (agent may record guidance too).
- Server: `GET/POST /projects/{workdir}/notes` … actually workdir as query param on `/notes` endpoints (consistent with `/sessions?workdir=`): `GET /notes?workdir=`, `POST /notes` (create), `POST /notes/{id}/resolve`, `DELETE /notes/{id}` (clear, N12).
- Frontend: Notes panel gains a project-level list with resolve/clear buttons; session notes stay as-is.
- Lifecycle: user (UI) and agent (`resolve_note`) may resolve/clear freely (user decision).

## T12 — Platform facts + instruction contract (N1, N2, N3, N5, N7, N9)
`Engine._build_instructions` gains:
1. A **platform block**: OS (`sys.platform` + `platform.system/release`), shell, Python version, workdir path form — the agent never claims a wrong platform (N1).
2. A **contract block** (instructions only, no mechanical gate — user decision):
   - If the prompt asks to evaluate/assess/review, report findings only; do not start fixing (N3).
   - If you ask the user a question (ask_user / choice card), stop and wait for the answer before acting (N2).
   - Plan before non-trivial work; state the plan first (N9).
   - On missing dependencies (runtimes, packages, CLIs), check availability and offer to install rather than just reporting (N7).
   - Be terse; no information overload (N5, already observed working — keep).

## T13 — Codegraph auto-bootstrap (N8)
- At run start (engine, before first model call): if the workdir lacks a `.codegraph` index, run the codegraph init+index automatically (subprocess, best-effort with logged failure — never blocks the run on error).
- Enforcement of usage stays in global directives.

## T14 — HTML artifacts (N6)
- `ArtifactStore.emit_html(name, html)` → kind `'html'`; agent tool `emit_html`.
- Frontend Artifacts tab: `html` artifacts render inline in a sandboxed `<iframe srcdoc>`; a one-line explainer header on the tab says what artifacts are.
- Server: existing `GET /sessions/{id}/artifacts` already returns payloads — no contract change.

## Out of scope
- Mechanical write-tool locking for assessment runs (rejected: keep it simple).
- N4 (HTML file write failure): root cause was WSL/Windows path confusion — covered by the platform facts block; no separate fix.
