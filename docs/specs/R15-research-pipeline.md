# R15 — Research pipeline

## Problem
The agent can search the web ad-hoc, but findings evaporate after the session and
are never curated into durable, citable guidance. R11 gave us a reference
knowledgebase (`reference/` → index → `search_references`/`read_reference`) with
no pipeline feeding it from the web.

## Decisions (user, this session)
- **Budget**: up to 5 sources per subtopic; escalate +5 only when sources wildly
  disagree. Never spiral.
- **Scope**: decompose subject into subtopics/variants unless the user bounded
  the query.
- **Driver**: the agent drives the process.
- **Autonomy**: mid-task autonomous research is allowed by default; the user may
  forbid it per request.
- **Trust gate**: soft only — present findings via `ask_user` for validation.
  If the user then asks the agent to act on the findings, that is implicit
  approval. No blocking approval gate.
- **Freshness**: no automatic re-research. Updates happen on explicit human
  request ("research X again"). The `As of <date>` stamp makes staleness
  visible, not enforced.

## Design
- New module `codingdude/research.py`: `build_research_toolset(workdir)` with
  one tool, **`save_research(topic, markdown, replace=False)`**.
  - Search/fetch/analysis stay with the existing `web_search`/`web_fetch`
    tools — the LLM does the judging; no duplicated web plumbing.
  - The research *process* (budget, escalation, decomposition, soft gate) is
    prescribed in the tool docstrings — one source of truth for the discipline.
  - `save_research` validates structure: must cite at least one source URL and
    carry an `As of:` date stamp. Writes atomically to
    `reference/research/<slug>.md`.
  - `replace=False` refuses to clobber an existing non-empty doc (freshness
    updates are human-triggered; a deliberate `replace=True` (or edit_file)
    covers them).
  - Files land under `reference/`, so the existing `ReferenceStore.reindex()`
    picks them up on the next `search_references` — no new retrieval path.
- Wired in `plugins/__init__.py` next to `build_references_toolset`.

## Stories
1. `save_research` writes `reference/research/<slug>.md` and the content is
   found by `search_references`.
2. Missing source citation or `As of:` stamp → rejected with a readable error.
3. Existing doc + `replace=False` → refused; `replace=True` → overwritten.
4. Topic slugs are filesystem-safe (spaces/punctuation → dashes).

## Verification
pytest (new tests in tests/test_research.py), ruff, mypy, npm build untouched.
