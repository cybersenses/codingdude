# HANDOFF.md

Continuity notes between CodingDude development sessions. Replace with the
current state at each handoff; keep it concise and free of personal data
(no user paths, keys, or private hostnames).

## Current state

See ROADMAP.md (roadmap + tickets), docs/adr/ (design decisions), and
git log for recent work. This file intentionally holds no session data -
per-session handoff content lives in the conversation, not in the repo.

### Post-Mortem: Artifacts SSE delta crash (TypeError reading 'html')

- **Timeline** - 2026-11-12 ~14:25 UTC: user's UI crashed on Artifacts render
  right after the R87 v3 hard refresh. 14:33 diagnosis: `ArtifactStore.watch()`
  shipped `emitted`/`answered` SSE deltas as raw DB rows (`payload_json`, no
  `payload`); snapshot frames were fine, so only in-place card replacement
  crashed, and only `kind='html'` produced the reported TypeError. 14:34 RED
  tests both seams; fix + guards; 14:52 gates green, commit `6d6e6e0`.
- **Impact** - whole React tree unmounted (white screen) whenever an artifact
  changed while the panel was open; no data loss (DB rows were all intact).
- **Contributing factors** - the SSE delta path had no payload assertions; the
  frontend trusted `payload.*` on every kind branch with no error boundary in
  the dock; the widget-vocabulary pin (Python side) silently broke in the #330
  v3 swap because its gates were frontend-only (vitest), so full-suite runs
  had lapsed; per-boot token blocks quick live-API probes (diagnosis went via
  read-only SQLite instead).
- **5 Whys** - crash reading `.html` -> `payload` undefined -> delta was a raw
  row -> `watch()` used `_get()` (raw) where `list()` maps -> the two item
  shapes were never pinned to a shared contract, and no test rendered a
  payload-less card.
- **Action items** -
  | action | owner | priority | status |
  |---|---|---|---|
  | map deltas via `_get_mapped` (watch) | codingdude | P0 | done `6d6e6e0` |
  | payload-less render guard in Artifacts.jsx | codingdude | P0 | done `6d6e6e0` |
  | re-point widget pin at wireloom-adapter.ts | codingdude | P1 | done `6d6e6e0` |
  | full pytest suite after frontend-shape changes (gate discipline) | codingdude | P1 | process rule, adopted |

