"""Approval tiers (per the spec's static table): auto / gated+pattern / always-gated.

- APPROVED: reads, searches, in-Workdir edits, local git reads, and benign shell
  utilities — runs without asking.
- NEEDS_GATE: ordinary shell commands. One approval can cover the rest of the
  Session via a Pattern Approval (the command's leading token).
- DENIED: remote mutations and destructive operations. Never unlocked by a
  pattern — only by `--yolo` (the explicit full-off switch, ADR-0003).
"""

from dataclasses import dataclass, field
import re

APPROVED = 'approved'
NEEDS_GATE = 'needs_gate'
DENIED = 'denied'

# Commands that run without a gate: read-only / dev-loop conveniences.
# NOTE: git branch *creation* is deliberately not auto (spec story 19).
AUTO_SHELL = re.compile(
    r'^(ls|dir|cat|head|tail|pwd|echo|which|where|find|tree|wc|file|stat|'
    r'git (status|log|diff|show)|node --version|python --version)\b'
)

# The always-gated tier: remote mutations and destructive operations.
ALWAYS_GATED = re.compile(
    r'^(git (push|remote|clean|reset --hard)|gh (pr|repo|release|api)|'
    r'rm |rmdir|del |rd |remove-item|mv |move |format |shutdown|taskkill)'
    r'|(^|[;&|]\s*)sudo\b',
    re.IGNORECASE,
)

# Heuristic for commands reaching outside the Workdir (home dirs, parent dirs,
# absolute paths). Best-effort by nature — the file tools are the hard boundary.
OUTSIDE_WORKDIR = re.compile(
    r'(\.\./|~/|~\\\\|(?:[A-Za-z]:\\\\)|/(?:home|Users|etc|var|tmp)/)',
)


@dataclass
class ApprovalPolicy:
    """Session-scoped approval state. Thread-safe enough for one run at a time.

    `ask`, when set, is an async callable(command) -> 'approve' | 'pattern' |
    'deny'. Interactive frontends set it: a gate waits for the user's answer.
    Without it (headless), gates abort the run per ADR-0003.
    """

    yolo: bool = False
    patterns: set[str] = field(default_factory=set)
    ask: object | None = None
    on_pattern: object | None = None  # callable(pattern) — engine persists it

    def approve_pattern(self, pattern: str) -> None:
        self.patterns.add(pattern)

    def decide(self, command: str) -> str:
        if self.yolo:
            return APPROVED
        stripped = command.strip()
        if ALWAYS_GATED.match(stripped) or OUTSIDE_WORKDIR.search(stripped):
            return DENIED
        if stripped.split()[0] in self.patterns:
            return APPROVED
        if AUTO_SHELL.match(stripped):
            return APPROVED
        return NEEDS_GATE

    def pattern_for(self, command: str) -> str:
        """The Pattern Approval a user implicitly grants by approving this command."""
        return command.strip().split()[0]
