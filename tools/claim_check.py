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
* a sentence claiming what a failure path does (raises/silently/always/...)
  carries `[probe: ...]` or "not yet verified" -- on by default for commit
  messages, opt-in (`--failure-modes`) for documents

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

Paths inside a gitignored tree (`frontend/dist/`, `node_modules/`, `reference/`,
`.scratch/`) are skipped rather than reported. They are build products and a local
library: absent from a fresh checkout by definition, so a finding there describes
the machine that ran the check, not the document.

Usage:
    python tools/claim_check.py code-design.md RESCUE.md
    python tools/claim_check.py --message-file .git/COMMIT_EDITMSG
    git log -1 --format=%B | python tools/claim_check.py --message -

The identifier check is on by default only for `--message-file`; `--symbols` and
`--no-symbols` override that either way.
"""

from __future__ import annotations

import argparse
import os
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

#: Suffixes that must not vouch for an identifier. A symbol written in a doc or a
#: data file would otherwise find itself in the corpus below and pass the check
#: that exists to catch invented symbols -- prose proving prose.
NON_SOURCE_SUFFIXES = frozenset({".md", ".json", ".txt", ".lock", ".yaml", ".yml"})

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
    "docs/manual/quickstart.md",
    "docs/manual/tour.md",
    "docs/manual/panels.md",
    "docs/manual/workflows.md",
    "docs/manual/configuration.md",
    "docs/manual/extending.md",
    "docs/manual/reference.md",
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
        ".codingdude.toml",
        "traces",
        "uploads",
        "logs",
    }
)


#: Words that assert what happens when something goes wrong. A sentence
#: carrying one is a claim about a failure path, which is exactly the class
#: six consecutive commits got wrong -- the happy paths were executed, the
#: failure paths were described from imagination. Such a sentence must name the
#: command that demonstrated it (`[probe: ...]`) or admit it was not run
#: (`not yet verified`); anything else is rejected.
_FAILURE_MODE_PATTERNS = (
    r"\braises\b",
    r"\bsilently\b",
    r"\bcan never\b",
    r"\bcannot miss\b",
    r"\bcan't miss\b",
    r"\balways\b",
    r"\bunreachable\b",
    r"\bhides\b",
    r"\bprevents\b",
    r"\bguarantees\b",
)
_FAILURE_MODE_RE = re.compile("|".join(_FAILURE_MODE_PATTERNS), re.IGNORECASE)
#: The annotation must name a command, so at least one non-space character
#: after the colon -- `[probe: ]` is an empty vouch.
_PROBE_RE = re.compile(r"\[probe:\s*[^\]\s]")

#: A bullet is a separate claim: a probe on the next line proves nothing about
#: this one, so single newlines split sentences too, not just blank lines.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
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
    # Repo-only ignore evaluation: claims are measured against THIS repo's
    # .gitignore, never ambient machine config. Probe (#267): a CI runner's
    # `~/.config/git/ignore` — the XDG fallback git reads whenever
    # core.excludesFile is unset — exempted every missing path, so four
    # path-claim tests passed with zero findings on CI while failing locally.
    # Setting the key with `-c` takes highest precedence AND switches the XDG
    # fallback off; GIT_CONFIG_GLOBAL/NOSYSTEM strip the remaining machine
    # config for good measure.
    argv = [_git_binary(), "-c", f"core.excludesFile={os.devnull}", *args]
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    return subprocess.run(  # nosec B603 - argv list, shell=False, resolved binary
        argv,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
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


def _is_ignored(token: str, root: Path) -> bool:
    """Whether a path claim points into a gitignored tree.

    The check this feeds cannot be made honestly about such a path. `frontend/dist/`,
    `node_modules/`, `reference/` and `.scratch/` are build products and a local
    library: absent from a fresh checkout *by definition*, present here because a
    build or a scan ran. Asserting on them made the whole check machine-dependent --
    green on the author's tree, twelve findings in a clean one (probe: a
    `git worktree` of HEAD, `pytest tests/test_claim_check.py` -> 4 failed).

    Fails closed: if git cannot answer, the path is still checked.

    Two shapes, neither of them the raw trailing-slash path:

    * a FILE claim (`src/codingdude/store.py`) is probed as itself — git 2.56
      (the CI runner) phantom-matches nonexistent trailing-slash paths, and a
      `store.py/` probe fabricated a directory claim the document never made,
      silently exempting every missing file path on CI (#267);
    * a DIRECTORY claim (`frontend/dist/`) is probed as a file inside the tree
      (`frontend/dist/x`) — directory-only ignore patterns (`reference/`) match
      their contents, so the answer is the same, and the 2.56 trailing-slash
      phantom is sidestepped (`no-such-dir/x` is an ordinary file path).
    """
    if token.endswith("/"):
        forms = [token.rstrip("/") + "/x"]
    else:
        forms = [token]
    for form in dict.fromkeys(forms):
        try:
            result = _git(["check-ignore", "-q", "--", form], root)
        except (GitUnavailable, OSError):
            return False
        if result.returncode == 0:
            return True
    return False


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
    if any(c.isdigit() for c in token):
        return False  # a run id, hash or versioned name: `G0SUN1seqSI` is not a symbol
    if "_" in token:
        return True  # snake_case or _leading
    if token.lower() == token:
        return False  # a plain lowercase word
    return any(c.isupper() for c in token[1:])  # CamelCase


def _source_files(root: Path) -> list[str]:
    """Tracked files whose text may vouch for an identifier.

    Excludes prose and data (`NON_SOURCE_SUFFIXES`): a symbol named only in a
    document must fail the check, not cite itself.
    """
    return [
        name
        for name in _tracked_files(root)
        if Path(name).suffix in PATH_SUFFIXES and Path(name).suffix not in NON_SOURCE_SUFFIXES
    ]


def _tracked_source_tokens(root: Path) -> set[str]:
    """Every identifier-shaped token in the tracked source, for symbol claims.

    Built from `_tracked_files` rather than a second `git ls-files`: one run
    should list the tree once, and its rglob fallback keeps this working outside
    a repository instead of returning an empty set that flags every symbol.
    """
    tokens: set[str] = set()
    for name in _source_files(root):
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")
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
            if _path_exists(token, root) or _is_ignored(token, root):
                continue
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
                if not _is_ignored(match.group("path"), root) and not _is_marked_removed(sentence):
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
    for sentence in _sentences(text):
        if _is_marked_removed(sentence):
            continue
        for token in _BACKTICK.findall(sentence):
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


def check_failure_modes(text: str) -> list[str]:
    """Failure-mode claims with no probe annotation and no honesty marker.

    Every finding in the six-commit pattern shared one shape: a sentence about
    what happens when something goes wrong, written from the diff, never
    executed. A gate cannot force the execution, but it can force the choice
    this check offers: name the command that demonstrated the behaviour
    (`[probe: ...]`) or write `not yet verified` and let the reader weigh it.
    Sentence-scoped by design -- an annotation a paragraph away proves nothing.
    """
    problems = []
    for sentence in _sentences(text):
        if not _FAILURE_MODE_RE.search(sentence):
            continue
        if _PROBE_RE.search(sentence) or "not yet verified" in sentence.lower():
            continue
        problems.append(f"failure-mode claim without a probe: {sentence.strip()}")
    return problems


def run(
    text: str,
    root: Path = ROOT,
    symbols: bool = True,
    source: set[str] | None = None,
    failure_modes: bool = False,
) -> list[str]:
    """Every finding, in a stable order.

    The single definition of "the check set and its order" — `main` calls this
    rather than repeating the list, so a check added here reaches the CLI.
    `source` is passed through so a caller checking several documents builds the
    identifier corpus once. `failure_modes` is opt-in here: the living documents
    describe historical behaviour in prose, so it defaults off and `main` turns
    it on for commit messages, where the claim is about this change.
    """
    problems = check_paths(text, root)
    problems += check_line_refs(text, root)
    problems += check_hashes(text, root)
    problems += check_line_counts(text, root)
    if failure_modes:
        problems += check_failure_modes(text)
    if symbols:
        problems += check_symbols(text, root, source=source)
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
        help="skip the identifier check (the default for documents)",
    )
    parser.add_argument(
        "--symbols",
        action="store_true",
        help="force the identifier check on (the default for --message-file)",
    )
    parser.add_argument(
        "--failure-modes",
        action="store_true",
        help=(
            "check failure-mode prose (raises/silently/always/...); a sentence "
            "with such a verb must carry '[probe: ...]' or 'not yet verified' "
            "(the default for --message-file)"
        ),
    )
    parser.add_argument(
        "--no-failure-modes",
        action="store_true",
        help="skip the failure-mode check (documents describe history in prose)",
    )
    args = parser.parse_args(argv)

    # Documents name other people's APIs and planned ones by design, so the
    # identifier check fires on correct prose there; a commit message claims "this
    # symbol is mine and I just wrote it", which is the shape it can settle. Hence
    # the default follows the input, and both flags exist to override it.
    if args.symbols:
        with_symbols = True
    elif args.no_symbols:
        with_symbols = False
    else:
        with_symbols = bool(args.message_file)

    # Same reasoning for failure-mode prose: a living document narrates what a
    # past change did, which is history rather than a live claim, while a commit
    # message asserts behaviour this change introduces. The verbs list is small
    # on purpose -- a wrong check gets ignored, and an ignored gate is worse
    # than none.
    if args.failure_modes:
        with_failure_modes = True
    elif args.no_failure_modes:
        with_failure_modes = False
    else:
        with_failure_modes = bool(args.message_file)

    if not args.files and not args.message_file:
        parser.error("give at least one file or --message-file")

    sources: list[tuple[str, str, bool]] = []  # (name, text, is_commit_message)
    for name in args.files:
        try:
            sources.append((name, Path(name).read_text(encoding="utf-8", errors="replace"), False))
        except OSError as exc:
            print(f"claim_check: cannot read {name}: {exc}", file=sys.stderr)
            return 2
    if args.message_file:
        if args.message_file == "-":
            sources.append(("<stdin>", sys.stdin.read(), True))
        else:
            try:
                text = Path(args.message_file).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"claim_check: cannot read {args.message_file}: {exc}", file=sys.stderr)
                return 2
            sources.append((args.message_file, text, True))

    # Built once, shared by every document: the source tree does not change
    # between files, and walking it per file would dominate the runtime.
    token_set = _tracked_source_tokens(ROOT) if with_symbols else set()

    # Documents are failure-mode-checked only on explicit `--failure-modes`,
    # even when a --message-file is present in the same run: the default that
    # follows the input applies per source, not to the whole invocation.
    failures = 0
    for name, text, is_commit_message in sources:
        problems = run(
            text, ROOT, symbols=with_symbols, source=token_set,
            failure_modes=with_failure_modes if is_commit_message else args.failure_modes,
        )
        for problem in problems:
            print(f"{name}: {problem}")
        failures += len(problems)

    if failures:
        print(f"claim_check: {failures} unsupported claim(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
