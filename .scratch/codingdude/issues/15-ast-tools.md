# 15: AST tools

**What to build:** Navigation beyond text: tree-sitter-backed find-definition and find-references tools alongside grep, so the agent jumps to symbols instead of pattern-matching its way around.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** ready-for-agent

- [ ] Find-definition lands on the symbol's location in a sample multi-file repo
- [ ] Find-references returns call/usage sites across files
- [ ] A scripted navigation task uses AST tools where grep would struggle
- [ ] Unsupported languages degrade gracefully to a clear tool response, not an error
