# CodingDude - a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Check the mechanically verifiable claims in a doc or a commit message.

Why this exists: over six consecutive commits a reviewer found a written claim
the code did not support -- an invented second banner shape, a "hide the editor"
step that hid nothing, measured geometry the gate never recorded, a line count
1439 against a measured 1488, two paths named `store.py`/`analysis.py` that were
`db.py`/`ast_tools.py`. Every one was written from the diff, in the same pass as
the change, and no gate could contradict it: pytest, ruff and mypy test the code,
not the prose describing it. So the prose was unverified by construction, and the
only reader that ever disagreed arrived after publication.

This narrows that. It checks the subset of claims a machine can settle:

* paths in backticks exist (a doc naming `store.py` fails while `store.py` is `db.py`)
* `path:LINE` references point inside an existing file
* short hex refs name a real commit
* an identifier in backticks appears somewhere in the tracked source
* "N lines" next to a single named file matches that file

It cannot check what most of those six commits got wrong: whether a mechanism
works, whether a shape exists, or why an observation happened. Those need a probe
-- a command and its output pasted next to the claim -- and no tool can supply
that. `RESCUE.md` records the rule; this file catches the arithmetic.

Deliberately not checked, because a wrong check gets ignored and an ignored gate
is worse than none: test counts (pytest N passed, vitest N/N) -- settling those
means running the suites, which is `gates.bat`'s job, not a prose linter's;
directory line sums; and any claim phrased in prose rather than in backticks.

A path or identifier can be legitimately absent when the sentence is about its
removal. Mark it with `(removed)`, `(deleted)`, `(gone)` or `(historical)` in the
same sentence and the check skips that sentence. The marker is explicit on
purpose: naming a file that no longer exists is a decision, not an oversight.

Usage:
    python tools/claim_check.py code-design.md RESCUE.md
    python tools/claim_check.py --message-file .git/COMMIT_EDITMSG
    git log -1 --format=%B | python tools/claim_check.py --message -
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess  # nosec B404 - fixed git argv only, see _git
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Suffixes that make a backticked token a path claim rather than prose.
PATH_SUFFIXES = frozenset(
    {
        ".bat", ".cfg", ".css", ".db", ".html", ".ini", ".js", ".json", ".jsx",
        ".lock", ".md", ".mjs", ".ps1", ".py", ".sh", ".sql", ".toml", ".ts",
        ".tsx", ".txt", ".yaml", ".yml",
    }
)

#: Documents whose claims must hold *now*. Commit messages are excluded by
#: default: their narrative may legitimately name a file it replaced.
STRICT_DOCS = (
    "code-design.md",
    "RESCUE.md",
    "ROADMAP.md",
    "CONTRIBUTING.md",
    "README.md",
    "docs/USER-MANUAL.md",
    "docs/TECHNICAL-DESIGN-MANUAL.md",
)

#: Words that look like identifiers but name a tool, product or concept.
NOT_SYMBOLS = frozenset(
    {
        "AGPL", "AGENTS", "API", "AST", "CI", "CLI", "CRLF", "CSS", "DB", "DOM",
        "HTML", "HTTP", "JSON", "JWT", "LF", "MCP", "ORM", "PRD", "REST", "SHA",
        "SQL", "SSE", "TDD", "TTL", "UI", "URL", "UTF", "WAL", "XSS", "YAML",
        "chromium", "dockview", "eslint", "git", "github", "localhost", "mypy",
        "npm", "npx", "playwright", "pytest", "ruff", "sqlite", "uv", "vitest",
    }
)

REMOVAL_MARKERS = ("(removed)", "(deleted)", "(gone)", "(historical")

#: Files that live in the CodingDude home or a user's project, never in this
#: repo. The manuals name them bare because they are runtime state
#: (`~/.codingdude/config.toml`, a project's AGENT.md), so requiring them to
#: resolve here would flag correct prose. A closed list, not a pattern: adding
#: to it is a decision, and a repo file that goes missing is still caught.
RUNTIME_FILES = frozenset(
    {
        "AGENT.md",
        "DIRECTIVES.md",
        "config.toml",
        "mcp.json",
        "memory.db",
        "server-token",
    }
)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n\n+")
_BACKTICK = re.compile(r"`([^`\n]+)`")
_HEX_REF = re.compile(r"^[0-9a-f]{7,40}$")
_LINE_REF = re.compile(r"^(?P<path>[^\s:]+):(?P<line>\d+)(?:-(?P<end>\d+))?$")
_LINE_COUNT = re.compile(r"(?<![\d.])(\d[\d,]*)\s+lines?\b")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: `git ls-files` output per root, so one check run lists the tree once.
_TRACKED_CACHE: dict[str, list[str]] = {}


class GitUnavailable(RuntimeError):
    """Raised when git cannot be located; the checks that need it are skipped."""


def _git_binary() -> str:
    """Absolute path to git, resolved rather than assumed to be on PATH."""
    found = shutil.which("git")
    if not found:
        raise GitUnavailable("git not found on PATH")
    return found


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    # Fixed argv (no shell), binary resolved to an absolute path by _git_binary.
    return subprocess.run(  # nosec B603 - argv list, shell=False, resolved binary
        [_git_binary(), *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _is_marked_removed(sentence: str) -> bool:
    return any(marker in sentence.lower() for marker in REMOVAL_MARKERS)


def _looks_like_path(token: str) -> bool:
    """Whether a backticked token is a path claim rather than prose.

    A suffix on the final segment is required (or a trailing slash marking a
    directory). Prose in backticks that happens to contain a slash --
    `resolve_workdir_path/_file` -- is not a path claim, and treating it as one
    was the first version's mistake: 157 findings, nearly all basenames meaning
    `src/codingdude/x.py` rather than a repo-root file. A check that cries wolf
    is a check that gets ignored, which is worse than not having it.
    """
    if not token or " " in token:
        return False
    if token.startswith(("http://", "https://", "~", "/", "-", "<", ">")):
        return False
    if re.match(r"^[A-Za-z]:", token):  # Windows absolute path
        return False
    if any(ch in token for ch in "*?{}[]$=<>"):
        return False
    if token.endswith("/"):
        return True  # directory claim
    return Path(token.rsplit("/", 1)[-1]).suffix in PATH_SUFFIXES


def _tracked_files(root: Path) -> list[str]:
    """Every tracked path, posix-style, for resolving bare basenames.

    Documents name modules by basename (`tools.py`, `memory.py`) because the
    directory is implied. Resolving those against the repo root alone reports
    every one of them missing; resolving against the tracked tree is what a
    reader does.
    """
    cached = _TRACKED_CACHE.get(str(root))
    if cached is not None:
        return cached
    files: list[str] = []
    try:
        listed = _git(["ls-files"], root)
        if listed.returncode == 0:
            files = listed.stdout.splitlines()
    except (GitUnavailable, OSError):
        files = []
    if not files:
        files = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
    _TRACKED_CACHE[str(root)] = files
    return files


def _path_exists(token: str, root: Path) -> bool:
    """Whether a path claim names something in the tree.

    Three things a reader accepts and the first version did not: a token ending
    in "/" claims a *directory*, so it resolves by prefix, not by exact file; a
    root-level file (`SECURITY.md`) has no "/" before its name; and docs name a
    file by its distinctive tail (`workspace/catalogue.ts` for
    `frontend/src/workspace/catalogue.ts`). Each of those was a false positive
    here before, which is how a check earns being ignored.
    """
    clean = token.rstrip("/")
    if clean in RUNTIME_FILES:
        return True  # home/project runtime file, not a repo path
    tracked = _tracked_files(root)
    if (root / clean).exists():
        return True
    if token.endswith("/"):
        return any(name.startswith(clean + "/") or f"/{clean}/" in name for name in tracked)
    return any(name == clean or name.endswith("/" + clean) for name in tracked)


def _resolve(token: str, root: Path) -> Path | None:
    """The file a `path:LINE` reference names, or None if there is none."""
    direct = root / token
    if direct.is_file():
        return direct
    if "/" in token:
        return None
    matches = [name for name in _tracked_files(root) if name.endswith("/" + token)]
    if len(matches) == 1:
        return root / matches[0]
    # Zero matches: nothing to check. Several: the reference is ambiguous, so
    # picking one would be a guess -- treat it as unresolved rather than right.
    return None


def _looks_like_symbol(token: str) -> bool:
    """Whether a backticked token is a code identifier worth verifying.

    Underscores count as the tell: `poll_error`, `_no_readme_reason` and
    `check_paths` are identifiers, and the first version's `token.lower() == token`
    guard threw every one of them away — so the check silently skipped the exact
    misspellings it was written for. Plain lowercase English is still excluded;
    an underscore is not something prose does by accident.
    """
    if not _IDENTIFIER.match(token) or len(token) < 4:
        return False
    if token in NOT_SYMBOLS or token.upper() == token:
        return False
    if "_" in token:
        return True  # snake_case or _leading
    if token.lower() == token:
        return False  # a plain lowercase word
    return any(c.isupper() for c in token[1:])  # CamelCase


def _tracked_source_tokens(root: Path) -> set[str]:
    """Every identifier-shaped token in the tracked source, for symbol claims."""
    try:
        listed = _git(["ls-files"], root)
    except (GitUnavailable, OSError):
        return set()
    if listed.returncode != 0:
        return set()
    tokens: set[str] = set()
    for name in listed.stdout.splitlines():
        path = root / name
        if path.suffix not in PATH_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tokens.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    return tokens


def _commit_exists(ref: str, root: Path) -> bool:
    try:
        result = _git(["cat-file", "-e", f"{ref}^{{commit}}"], root)
    except (GitUnavailable, OSError):
        return True  # cannot tell; do not invent a failure
    return result.returncode == 0


def check_paths(text: str, root: Path = ROOT) -> list[str]:
    """Backticked paths that name nothing on disk."""
    problems = []
    for sentence in _sentences(text):
        if _is_marked_removed(sentence):
            continue
        for token in _BACKTICK.findall(sentence):
            token = token.strip()
            if not _looks_like_path(token) or _HEX_REF.match(token):
                continue
            if _LINE_REF.match(token):
                continue  # check_line_refs owns this shape
            if not _path_exists(token, root):
                problems.append(f"path does not exist: {token}")
    return problems


def check_line_refs(text: str, root: Path = ROOT) -> list[str]:
    """`path:LINE` references outside an existing file."""
    problems = []
    for sentence in _sentences(text):
        for token in _BACKTICK.findall(sentence):
            match = _LINE_REF.match(token.strip())
            if not match:
                continue
            target = _resolve(match.group("path"), root)
            if target is None:
                if not _is_marked_removed(sentence):
                    problems.append(f"line reference to a missing file: {token}")
                continue
            end = int(match.group("end") or match.group("line"))
            total = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
            if end > total:
                problems.append(
                    f"line reference past end of file: {token} ({target} has {total} lines)"
                )
    return problems


def check_hashes(text: str, root: Path = ROOT) -> list[str]:
    """Short hex refs that name no commit."""
    problems = []
    for token in _BACKTICK.findall(text):
        token = token.strip()
        if _HEX_REF.match(token) and not _commit_exists(token, root):
            problems.append(f"commit does not exist: {token}")
    return problems


def check_symbols(text: str, root: Path = ROOT, source: set[str] | None = None) -> list[str]:
    """Backticked identifiers that appear nowhere in the tracked source."""
    tokens = _tracked_source_tokens(root) if source is None else source
    problems = []
    for sentence in _sentences(text):
        if _is_marked_removed(sentence):
            continue
        for token in _BACKTICK.findall(sentence):
            token = token.strip()
            if not _looks_like_symbol(token):
                continue
            if token not in tokens:
                problems.append(f"identifier not in tracked source: {token}")
    return problems


def check_line_counts(text: str, root: Path = ROOT) -> list[str]:
    """`N lines` where the sentence names exactly one file.

    Only the unambiguous shape is checked: one backticked, resolvable file plus a
    line count in the same sentence. "485 lines across three files" is skipped --
    deciding which files were summed is not something this can settle.
    """
    problems = []
    for sentence in _sentences(text):
        if _is_marked_removed(sentence):
            continue
        match = _LINE_COUNT.search(sentence)
        if not match:
            continue
        targets = [
            resolved
            for resolved in (_resolve(token.strip(), root) for token in _BACKTICK.findall(sentence))
            if resolved is not None
        ]
        if len(targets) != 1:
            continue
        claimed = int(match.group(1).replace(",", ""))
        actual = len(targets[0].read_text(encoding="utf-8", errors="replace").splitlines())
        if claimed != actual:
            name = targets[0].relative_to(root).as_posix()
            problems.append(f"line count for {name}: claimed {claimed}, measured {actual}")
    return problems


def run(text: str, root: Path = ROOT, symbols: bool = True) -> list[str]:
    """Every finding, in a stable order."""
    problems = check_paths(text, root)
    problems += check_line_refs(text, root)
    problems += check_hashes(text, root)
    problems += check_line_counts(text, root)
    if symbols:
        problems += check_symbols(text, root)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claim_check",
        description="Check the mechanically verifiable claims in a doc or commit message.",
    )
    parser.add_argument("files", nargs="*", help="documents to check")
    parser.add_argument(
        "--message-file",
        metavar="PATH",
        help="check a commit message file ('-' for stdin)",
    )
    parser.add_argument(
        "--no-symbols",
        action="store_true",
        help="skip the identifier check (useful for historical narrative)",
    )
    args = parser.parse_args(argv)

    if not args.files and not args.message_file:
        parser.error("give at least one file or --message-file")

    sources: list[tuple[str, str]] = []
    for name in args.files:
        try:
            sources.append((name, Path(name).read_text(encoding="utf-8", errors="replace")))
        except OSError as exc:
            print(f"claim_check: cannot read {name}: {exc}", file=sys.stderr)
            return 2
    if args.message_file:
        if args.message_file == "-":
            sources.append(("<stdin>", sys.stdin.read()))
        else:
            try:
                text = Path(args.message_file).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"claim_check: cannot read {args.message_file}: {exc}", file=sys.stderr)
                return 2
            sources.append((args.message_file, text))

    # Built once, shared by every document: the source tree does not change
    # between files, and walking it per file would dominate the runtime.
    token_set = set() if args.no_symbols else _tracked_source_tokens(ROOT)

    failures = 0
    for name, text in sources:
        problems = check_paths(text, ROOT) + check_line_refs(text, ROOT)
        problems += check_hashes(text, ROOT) + check_line_counts(text, ROOT)
        if not args.no_symbols:
            problems += check_symbols(text, ROOT, source=token_set)
        for problem in problems:
            print(f"{name}: {problem}")
        failures += len(problems)

    if failures:
        print(f"claim_check: {failures} unsupported claim(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
