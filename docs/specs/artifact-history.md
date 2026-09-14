# Artifact history: Q&A + decision capture

## Goal
The Artifacts tab becomes a per-session decision history: every `ask_user`
question the user answered and every recorded design decision is auto-captured
as an artifact. The agent does nothing extra; capture is automatic and
best-effort (a capture failure never breaks the run).

## Contract
- `ArtifactStore.record_qa(questions: list, answers) -> str` — kind `qa`,
  status `answered`, payload `{"questions": [...], "answers": {...}}`.
- `ArtifactStore.record_decision(title: str, body: str) -> str` — kind
  `decision`, status `answered`, payload `{"title", "body"}`.
- `build_roadmap_toolset(store, workdir, session_id=None)` — when `session_id`
  is given, `record_decision` also mirrors the decision as a `decision`
  artifact in that session.
- `worker.ask_user_fn` records a `qa` artifact after answers arrive
  (including timeout answers — they are part of history).
- Frontend renders `qa` and `decision` read-only in the Artifacts feed.
- No new endpoints; existing `GET /sessions/{id}/artifacts` + SSE cover it.

## Tests
- `tests/test_artifacts.py`: record_qa / record_decision round-trips via
  `list()`; roadmap toolset mirrors decision when session_id passed, and does
  not when omitted (back-compat).
- `tests/test_ask_user.py`: ask_user_fn path records qa artifact (fake asker).
- `npm run build` for the frontend rendering.
