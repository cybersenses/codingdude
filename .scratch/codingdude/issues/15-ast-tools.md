# 15: AST tools

**What to build:** Navigation beyond text: tree-sitter-backed find-definition and find-references tools alongside grep, so the agent jumps to symbols instead of pattern-matching its way around.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** resolved

- [x] Find-definition lands on the symbol's location in a sample multi-file repo
- [x] Find-references returns call/usage sites across files
- [x] A scripted navigation task uses AST tools where grep would struggle
- [x] Unsupported languages degrade gracefully to a clear tool response, not an error

## Comments

2026-09-07: Commit 42179c3 + e7e0117. `ast_tools.py` builds a find_definition/find_references toolset on tree-sitter (Python grammar); definitions found via function/class definition nodes, references via identifier nodes excluding the def site — docstring mentions correctly excluded (a grep-based approach can't do that). Non-Python paths get a ModelRetry pointing at grep instead of an error.
