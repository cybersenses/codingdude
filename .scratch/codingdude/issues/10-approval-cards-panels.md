# 10: Approval cards + panels

**What to build:** The interactive safety and visibility layer. Gated actions surface as inline cards in the chat showing the exact command (and diff where applicable) with Approve / Approve-all-matching / Deny; denial feeds a refusal back to the model as observable behavior. The right panel gains its tabs: live working-tree Diff, Files tree, Terminal (streaming command output), and Cost meter.

**Blocked by:** 03 (Surgical edits), 04 (Shell tool + Approval tiers), 09 (React shell)

**Status:** ready-for-agent

- [ ] A gated shell action in the browser shows an approval card with the exact command
- [ ] Approve proceeds; Approve-all-matching skips subsequent matching commands for the Session; Deny returns a refusal the model responds to
- [ ] Edits appear in the Diff panel as they land, live
- [ ] Files panel browses the Workdir tree; Terminal panel streams command output; Cost panel shows per-Session tokens and dollars
