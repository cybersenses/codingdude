# R6 tracer — living-artifact collaboration channel

Thin vertical slice: the agent can emit structured artifacts the user interacts
with in the session UI, and the answers flow back into the conversation.

## Scope (tracer)

- **Store** — `src/codingdude/artifacts.py`: `ArtifactStore(db, session_id)`
  over a new `artifacts` table in the existing session DB (same `_SCHEMA`
  pattern as `reference_sections`). Columns: `id` (url-safe token),
  `session_id`, `kind` (`choice` | `spec`), `title`, `payload_json`,
  `status` (`pending` | `answered`), `response_json`, `created_at`.
  - `emit_choice_card(question, options, description='') -> artifact_id`
  - `emit_spec_block(name, markdown) -> artifact_id`
  - `respond(artifact_id, response: dict)` — validates per kind
    (choice: `pick` must be one of the options; spec: `content` is the
    edited markdown); answering is idempotent-last-write.
  - `list()` — newest first; `feedback(artifact_id)` — response dict or
    `None` while pending. Unknown id → readable error.
- **Agent tools** — `build_artifacts_toolset(db, session_id)`:
  `emit_choice_card`, `emit_spec_block`, `get_artifact_feedback`
  (returns the response JSON, or `pending — user has not answered yet`).
  Wired into `plugins.build_all`.
- **Server** — `GET /sessions/{id}/artifacts`,
  `POST /artifacts/{artifact_id}/respond` (`{pick}` or `{content}`),
  both behind `authorize`.
- **Frontend** — new `Artifacts` tab in RightPanel (4 s poll, like the
  other tabs): choice cards render the options as pick buttons;
  spec blocks render an editable textarea with a save button;
  mermaid fences render as code blocks (render-only, per Round-1 decision).
- **Flow back into conversation** — the agent's `get_artifact_feedback`
  poll is the return path for the tracer; no worker push/interruption yet.

## Non-goals (this slice)

- SSE push of new artifacts to the UI (polling suffices for a tracer)
- Worker-interrupt on response; annotations; multi-artifact threads;
  ticket/decision auto-creation from picks.

## Tests (seams)

1. `ArtifactStore` against real SQLite (`Database.connect(tmp_path)`):
   emit → pending → respond → feedback round-trip for both kinds;
   bad pick / unknown id → readable errors.
2. Server endpoints via TestClient: list + respond + authorize.
3. Toolset via FunctionToolset: emit tools create pending artifacts;
   `get_artifact_feedback` reports pending, then the answer.
