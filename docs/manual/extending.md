# Extending CodingDude

Up: [User Manual](../USER-MANUAL.md) · Next: [Reference](reference.md)

## MCP servers

Model Context Protocol servers add tools to the agent (search, code
navigation, GitHub, …). Config is JSON, merged **global + project**:

- `~/.codingdude/mcp.json` — global (seeded on first boot)
- `<project>/.codingdude/mcp.json` — project-specific

Toggle servers per session in the **MCP** panel (enable/disable). A server
that fails to start is reported; it never silently disappears from a run.

## Skills

A skill is a directory with a `SKILL.md` — a procedure the agent loads by
name when relevant, instead of holding every procedure in context. Drop
skills in `~/.codingdude/skills/` (global) or the project's skills dir, or
create/edit/delete them in the **Standards** panel.

## Directives

Directives are rules injected into every run:

- `~/.codingdude/DIRECTIVES.md` — global, always injected
- `<project>/AGENT.md` — project rules, layered on top

Edit either in the **Standards** panel. Good directives are short, absolute,
and about process or safety ("never push without explicit consent") rather
than task-specific facts (those belong in project notes or memory).

## Checklists

`reference/checklists/*.md` in the CodingDude repo (also seeded into
projects) are distilled review procedures. They surface in the composer's
**checklist…** picker (sends a checklist run) and in the **Standards**
panel.

Next: [Reference](reference.md)
