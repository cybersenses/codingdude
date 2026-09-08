"""Directives: the always-on rule layers injected into every run.

Two sources, later layers win on conflict:
1. Global: `~/.codingdude/DIRECTIVES.md` — user-level taste (languages,
   test policy, style rules).
2. Project: `<workdir>/AGENT.md` — already the Project Context; included here
   as the project directive layer.

Budget-capped: the global layer truncates first so project rules always
survive. Truncation is always marked, never silent.
"""

from pathlib import Path

DIRECTIVES_FILENAME = 'DIRECTIVES.md'
DIRECTIVES_BUDGET = 4000
_GLOBAL_BUDGET = 3000


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace').strip() if path.exists() else ''


def build_directive_layers(home: Path, workdir: Path) -> str:
    """Compose the directive text for a run (empty string when none exist)."""
    parts: list[str] = []

    global_text = _read(home / DIRECTIVES_FILENAME)
    if global_text:
        if len(global_text) > _GLOBAL_BUDGET:
            global_text = global_text[:_GLOBAL_BUDGET]
        parts.append(f'## Global directives (user-level rules)\n\n{global_text}')

    project_text = _read(workdir / 'AGENT.md')
    if project_text:
        parts.append(f'## Project directives\n\n{project_text}')

    if not parts:
        return ''
    text = '\n\n'.join(parts)
    if len(text) > DIRECTIVES_BUDGET:
        text = text[:DIRECTIVES_BUDGET] + '\n[directives truncated]'
    return text


def project_directives_guard(path: str) -> bool:
    """True when the path is a directives file (gated like AGENT.md)."""
    return Path(path).name.upper() in ('AGENT.MD', DIRECTIVES_FILENAME.upper())
