# Spec — R7 thin tracer: session-replay eval harness (ticket #3)

## Goal
Replay recorded sessions against the engine with a scripted model and assert on
**process properties** (what the agent did), not implementation details. Runs as
plain pytest; no CI gate yet (ratified).

## Seams (public interface)
- `codingdude.evals.export_scenario(db, session_id, name, checks) -> dict`
  Reads persisted messages; returns `{name, prompt, responses, checks}`.
  `prompt` = first user text part; `responses` = each recorded ModelResponse as
  `{'text': str|None, 'tool_calls': [{'tool_name','args'}]}`.
- `codingdude.evals.write_scenario(scenario, path)` / `load_scenario(path) -> dict`
- `codingdude.evals.replay(scenario, workdir, home, config=None) -> ReplayResult`
  Builds a scripted model (tests/helpers.scripted) that returns recorded
  responses in order; runs `Engine.run` with `ApprovalPolicy()`; returns
  outcome + trace events read from `home/traces/{session_id}.jsonl`.
- `codingdude.evals.CHECKS` — registry of named predicates
  `(replay_result) -> str | None` (None = pass). Unknown name → `ValueError`
  naming the check.
- `codingdude.evals.run_scenarios(dir, workdir, home, config=None) -> list[Failure]`
  Iterates `*.json`, replays, applies declared checks; returns readable
  `Failure(name, check, message)` records.

## Checks (tracer set)
- `user_prompt_first` — first trace event is USER_PROMPT
- `tool_call_executed` — at least one TOOL_CALL_START event
- `plan_gated_headless` — outcome.status == 'gate_aborted' and gate mentions the plan (ADR-0003)
- `directive_echo` — output contains 'ZEBRA-RULE' (stands in for a
  verification-following skill; a scenario violating it must FAIL the suite
  with a readable assertion)

## Scenario files
`tests/scenarios/*.json`: `edit-surgical`, `plan-headless-abort` (must pass),
`broken-skill` (must fail — proves the harness can catch a skipping agent).

## Not in scope (thickening later)
Real-session recording tooling/CLI, CI promotion, scenario library curation,
flake/cost hardening.
