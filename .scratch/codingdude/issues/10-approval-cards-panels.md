# 10: Approval cards + panels

**What to build:** The interactive safety and visibility layer. Gated actions surface as inline cards in the chat showing the exact command (and diff where applicable) with Approve / Approve-all-matching / Deny; denial feeds a refusal back to the model as observable behavior. The right panel gains its tabs: live working-tree Diff, Files tree, Terminal (streaming command output), and Cost meter.

**Blocked by:** 03 (Surgical edits), 04 (Shell tool + Approval tiers), 09 (React shell)

**Status:** resolved (one manual UI pass still recommended)

- [x] A gated shell action in the browser shows an approval card with the exact command
- [x] Approve proceeds; Approve-all-matching skips subsequent matching commands for the Session; Deny returns a refusal the model responds to
- [x] Edits appear in the Diff panel as they land, live
- [x] Files panel browses the Workdir tree; Terminal panel delegates to the tool timeline; Cost panel shows per-Session tokens and dollars

## Comments

2026-09-07: Commit 1c618cd. Engine: `ApprovalPolicy.ask` (async) makes gates interactive — approve proceeds, deny raises ModelRetry with an explicit user-refusal message, pattern persists via `on_pattern` (always-gated actions never persist patterns even when approve-all is clicked). Headless (no ask) keeps ADR-0003 aborts. Worker wires ask over the WebSocket (GATE_REQUEST out, APPROVAL_RESPONSE in); server adds POST /runs/{id}/approve with a worker-bound inbox (thread-safe marshalling like the event queue). Roundtrip proven end-to-end through a real subprocess at the HTTP seam. Panels poll new endpoints: /sessions/{id}/usage, /diff, /files; /memory (list/add/delete). Budget setter rides RunIn.budget. Terminal tab delegates to the tool timeline rather than duplicating output. Same caveat as ticket 09: verified at the seams; one human click-through recommended.

2026-09-08 (live-UI bug fix): first human click-through reproduced the reported "freeze" — the approval card was erased the instant it appeared. Root cause: pydantic-ai emits FunctionToolCallEvent (TOOL_CALL_START) *before* awaiting tool execution, so it raced the GATE_REQUEST and the frontend cleared the gate on TOOL_CALL_START. Fix: the card clears only on TOOL_CALL_END (or when the user clicks a decision button). Verified in a real browser: gate → card stays → Approve → command runs → RUN_FINISHED with verified output.
