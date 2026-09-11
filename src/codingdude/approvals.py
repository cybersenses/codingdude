"""Approval tiers (per the spec's static table): auto / gated+pattern / always-gated.

- APPROVED: reads, searches, in-Workdir edits, local git reads, and benign shell
  utilities — runs without asking.
- NEEDS_GATE: ordinary shell commands. One approval can cover the rest of the
  Session via a Pattern Approval (leading-token, or a multi-token family such
  as `npm test`).
- DENIED: remote mutations and destructive operations. Never unlocked by a
  pattern — only by `--yolo` (the explicit full-off switch, ADR-0003).
"""

import re
from dataclasses import dataclass, field

APPROVED = 'approved'
NEEDS_GATE = 'needs_gate'
DENIED = 'denied'

# Commands that run without a gate: read-only / dev-loop conveniences.
# NOTE: `find` is deliberately NOT here — `find -delete` / `-exec` are
# destructive (self-review C1). `git branch` creation is gated (story 19).
AUTO_SHELL = re.compile(
    r'^(ls|dir|cat|head|tail|pwd|echo|which|where|tree|wc|file|stat|'
    r'git (status|log|diff|show)|node --version|python --version)\b'
)

# The always-gated tier: remote mutations and destructive operations.
ALWAYS_GATED = re.compile(
    r'^(git (push|remote|clean|reset --hard)|gh (pr|repo|release|api|run)'
    r'|npm (publish|unpublish|access|deprecate)|pip (upload|publish)'
    r'|docker (push|rm|rmi)|rm |rmdir|del |rd |remove-item|mv |move '
    r'|format |shutdown|taskkill|find .*(-delete|-exec|-ok)|chmod |chown )'
    r'|(^|[;&|]\s*)sudo\b'
    r'|curl .+(-T|--upload|-d|--data|-X ?(POST|PUT|DELETE))'
    r'|wget .+(--post-file|--method)',
    re.IGNORECASE,
)

# Binaries that execute arbitrary code from their own arguments: a Pattern
# Approval for these covers the EXACT command only, never the bare binary.
# (self-review C1: approving `python -m pytest` must not unlock `python -c ...`.)
INTERPRETERS = frozenset({
    'python', 'python3', 'py', 'node', 'nodejs', 'deno', 'bun', 'npx', 'pnpx',
    'bash', 'sh', 'zsh', 'fish', 'pwsh', 'powershell', 'cmd', 'ruby', 'perl',
    'php', 'osascript', 'env', 'uv', 'uvx', 'pipx', 'pythonw',
})

# Binaries whose leading token alone is too broad; the pattern is the first two
# tokens (`npm test`, not `npm`). (self-review C2.)
MULTI_TOKEN_BINARIES = frozenset({
    'npm', 'pnpm', 'yarn', 'pip', 'pip3', 'docker', 'docker-compose', 'kubectl',
    'git', 'poetry', 'cargo', 'go', 'dotnet', 'az', 'aws', 'gcloud', 'make',
})

# Heuristic for commands reaching outside the Workdir (home dirs, parent dirs,
# absolute paths). Best-effort by nature — the file tools are the hard boundary.
OUTSIDE_WORKDIR = re.compile(
    r'(\.\.[\\/]|~[\\/]|(?:[A-Za-z]:)[\\/]|/(?:home|Users|etc|var|tmp)/)',
)

DEFAULT_ALLOWED_BINARIES = {
    'ls', 'dir', 'cat', 'head', 'tail', 'pwd', 'echo', 'which', 'where',
    'tree', 'wc', 'file', 'stat', 'grep', 'rg', 'diff', 'sort', 'uniq',
    'pytest', 'python', 'python3', 'node', 'git', 'gh', 'ruff', 'mypy',
}


@dataclass
class ApprovalPolicy:
    """Session-scoped approval state. Thread-safe enough for one run at a time.

    `ask`, when set, is an async callable(command) -> 'approve' | 'pattern' |
    'deny'. Interactive frontends set it: a gate waits for the user's answer.
    Without it (headless), gates abort the run per ADR-0003.

    `allowed_binaries`: deny-by-default gate for unknown leading tokens — a
    command whose binary is not on this list (nor pattern-approved) is gated
    even if it would otherwise look read-only.
    """

    yolo: bool = False
    patterns: set[str] = field(default_factory=set)
    ask: object | None = None
    on_pattern: object | None = None  # callable(pattern) — engine persists it
    allowed_binaries: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_BINARIES))

    def approve_pattern(self, pattern: str) -> None:
        self.patterns.add(pattern)

    def decide(self, command: str) -> str:
        if self.yolo:
            return APPROVED
        stripped = command.strip()
        if not stripped:
            return NEEDS_GATE
        if ALWAYS_GATED.match(stripped) or OUTSIDE_WORKDIR.search(stripped):
            return DENIED
        base = stripped.split()[0]
        # Multi-token pattern families: `npm test` approves `npm test ...`
        # but never `npm publish` (self-review C2).
        if any(stripped == p or stripped.startswith(p + ' ') for p in self.patterns):
            return APPROVED
        if AUTO_SHELL.match(stripped) and base in self.allowed_binaries:
            return APPROVED
        return NEEDS_GATE

    def pattern_for(self, command: str) -> str:
        """The Pattern Approval a user implicitly grants by approving this command.

        Tiered by breadth, narrowest first:
        - Interpreter/host binaries (python/node/bash/...) → the EXACT command,
          so approving `python -m pytest` never unlocks `python -c "<code>"`
          (self-review C1).
        - Multi-token command families (npm/pip/git/...) → the first two tokens,
          so approving `npm test` never unlocks `npm publish` (self-review C2).
        - Otherwise → the leading token (e.g. `pytest`).
        """
        tokens = command.strip().split()
        if not tokens:
            return ''
        base = tokens[0]
        if base in INTERPRETERS:
            return command.strip()
        if base in MULTI_TOKEN_BINARIES and len(tokens) > 1:
            return ' '.join(tokens[:2])
        return base


# Default binaries considered safe to gate-approve as reads. Anything outside
# this set NEEDS_GATE the first time; the user can then approve the pattern.
