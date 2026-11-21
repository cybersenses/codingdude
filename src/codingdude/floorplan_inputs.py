# CodingDude — a personal coding agent.
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
"""R103 #376: author floorplan's three inputs from facts this repo computes.

floorplan never calls a model. Its scripts do the analysis; what it cannot
know is *what a part of the codebase is for*. That arrives in three authored
files, and this module writes all three from facts already on disk:

- `architecture.json` — the chips on the board: nodes and their globs, the
  project's own name and entrypoints, and the declared external packages.
- `descriptions/repo.json` — one sentence per file and per route, quoted from
  that file's or that handler's own docstring.
- `recent-work.json` — the files the working tree has changed since `HEAD`, so
  the map highlights what this run just touched.

**Nothing here is invented.** Every name is the repository's own (a package
name, a directory, `pyproject.toml`); every sentence is the code's own
docstring; every glob is derived from the scan's file list rather than guessed.
Where a fact is absent the field is left out and floorplan falls back to its
own default — honest — instead of a plausible sentence, which is not. That is
floorplan's own rule (`references/writing-descriptions.md`, "Say what it does
today") and the reason the tree below is derived, never curated.

**The one failure mode worth designing against.** A glob that matches no file
is only a *warning* to floorplan (`build.mjs:236`), so a guessed path ships a
chip claiming files it does not have. The first probe of this feature did
exactly that: 5 warnings, 30.5% of files unassigned. `validate()` therefore
mirrors that check as an *error*, before the build is spent, and the author
refuses to write a file it knows is wrong. The globs it writes come from the
scan's own file list, so a mismatch here means the scan and the tree disagree —
which is also worth refusing.

**Where the files live.** In the map dir under the config home, beside
`scan.json`, never inside the project (decision #107): `build.mjs` reads all
four inputs from its out dir, so the map dir is self-contained.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess  # nosec B404 - one bounded `git status` read; the argv is a constant list, never user text
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .floorplan import ARCH_NAME, map_dir

#: The schema marker floorplan reads (`references/schema.md`).
ARCH_SCHEMA = 'floorplan/architecture@1'

#: Who the labels are written for. `developers` because this map describes a
#: source repository — the guide reserves `everyone` for an app's owner, and
#: that audience is a user decision, not an author's.
AUDIENCE = 'developers'

#: File categories the board shows. `code` is floorplan's own default; written
#: out because the authored file is the contract a reader checks.
INCLUDE = ('code',)

#: Trees left off the board entirely: vendored third-party code, which is what
#: `ignore` is for. Everything else is already skipped by the scan (`.venv`,
#: `node_modules`, `frontend/dist` — HARD_IGNORE_DIRS and gitignore).
IGNORE = ('vendor/**',)

#: How many files a directory must hold, by its depth, to earn a chip. Deeper
#: directories are folders on a parent chip rather than chips of their own:
#: floorplan already groups a node's folders once it holds more than ~24 files,
#: so a chip per leaf directory would say the same thing twice.
MIN_FILES_BY_DEPTH = {1: 1, 2: 4, 3: 8}

#: A directory whose role is legible from where it sits. Anything not named
#: here falls back to `library`, which is true of shared code and claims
#: nothing beyond that.
AREA_KINDS = {
    '.codingdude-seed': 'library',
    'docs': 'library',
    'frontend': 'ui',
    'src': 'service',
    'tests': 'test',
    'tools': 'script',
}

#: Segments whose plain word is not the segment itself. A label is a word for a
#: thing, and `src` is not a word — this table is where the directory name and
#: the word a reader needs differ, and nothing more is claimed by it.
AREA_LABELS = {
    'src': 'Source',
    'lib': 'Library',
    'tools': 'Tools',
    'tests': 'Tests',
    'assets': 'Assets',
    'scripts': 'Scripts',
}

#: Segments that are acronyms, spelled the way they are written.
ACRONYMS = {'cli': 'CLI', 'api': 'API', 'ui': 'UI', 'mcp': 'MCP', 'db': 'DB'}

#: The kinds floorplan accepts (`references/schema.md`).
KINDS = frozenset({
    'ui', 'service', 'worker', 'library', 'feature', 'data', 'config',
    'test', 'script', 'infra', 'external',
})

#: Authoring an `external` chip for every declared dependency would bury the
#: board in them, so the biggest by importing-file count win. A bound on
#: noise, not a judgement: the count comes from the scan.
MAX_EXTERNAL_NODES = 20

#: One sentence, ideally under 140 characters (`writing-descriptions.md`). The
#: cap stops a docstring's opening paragraph becoming a card's body text.
DESC_LIMIT = 200

#: `git status` is best effort and must never hold a build: bounded like every
#: other subprocess in this feature (#368's class).
GIT_TIMEOUT = 10

#: One descriptions file, not one per module: upstream splits them so parallel
#: agents can write without colliding, and this author writes them all in one
#: pass, so a second file would only add a way for two of them to disagree.
DESC_NAME = 'repo.json'

#: `recent-work.json` holds `tasks`, and a task's `title` is the only field the
#: builder requires. `request` stays absent on purpose: what the user asked for
#: is not a fact this module can read.
RECENT_NAME = 'recent-work.json'

#: floorplan's glob dialect compiled once per pattern: the author writes a
#: handful of shapes, but the validator is a gate, so it implements the
#: documented syntax rather than the subset it happens to emit.
_GLOB_CACHE: dict[str, re.Pattern[str]] = {}

_WILDCARD = ('*', '?', '{')


@dataclass(frozen=True)
class Authored:
    """What `author()` wrote, and anything a reader should still know."""

    ok: bool
    error: str = ''
    notes: tuple[str, ...] = ()
    paths: tuple[Path, ...] = ()

    def summary(self) -> str:
        """One line for the map receipt: what was written, or why not."""
        if not self.ok:
            return f'cannot author the map inputs: {self.error}'
        return 'wrote ' + ', '.join(path.name for path in self.paths)


# --- globs -------------------------------------------------------------------

def glob_match(pattern: str, path: str) -> bool:
    """Whether `pattern` claims `path`, per floorplan's glob rules.

    `**` crosses directories, `*` and `?` stay inside one segment, `{a,b}` is
    alternation, and a pattern with no wildcard also names a directory
    (`backend/app` means `backend/app/**`) — all of it from
    `references/schema.md`, because the same rule has to hold here and in the
    builder.
    """
    if not any(char in pattern for char in _WILDCARD):
        trimmed = pattern[:-1] if pattern.endswith('/') else pattern
        pattern = f'{trimmed}/**'
    compiled = _GLOB_CACHE.get(pattern)
    if compiled is None:
        compiled = re.compile(_translate(pattern))
        _GLOB_CACHE[pattern] = compiled
    return compiled.fullmatch(path) is not None


def _translate(pattern: str) -> str:
    """A glob pattern as a regular expression, anchored by the caller."""
    out: list[str] = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == '{':
            close = pattern.find('}', index)
            if close != -1:
                alts = pattern[index + 1:close].split(',')
                out.append('(?:' + '|'.join(re.escape(alt) for alt in alts) + ')')
                index = close + 1
                continue
        elif pattern.startswith('**', index):
            index += 2
            if index < length and pattern[index] == '/':
                # `**/x` also matches `x` at the root, as the schema's own
                # example (`**/*.test.tsx`) requires.
                index += 1
                out.append('(?:.*/)?')
            else:
                out.append('.*')
            continue
        elif char == '*':
            out.append('[^/]*')
        elif char == '?':
            out.append('[^/]')
        else:
            out.append(re.escape(char))
        index += 1
    return ''.join(out)


# --- the scan's file list ----------------------------------------------------

def included_files(scan: dict) -> list[dict]:
    """The files floorplan will show, from the scan it just wrote.

    The scan is the single source of file truth: it is what the builder
    assigns, so deriving globs from anything else (a fresh walk, a second skip
    list) would let the author and the builder disagree about which files exist
    — the drift #374 spent a ticket closing.
    """
    files: list[dict] = []
    for entry in scan.get('files') or ():
        if not isinstance(entry, dict):
            continue
        path = entry.get('path')
        if not isinstance(path, str) or entry.get('category') not in INCLUDE:
            continue
        if any(glob_match(pattern, path) for pattern in IGNORE):
            continue
        files.append(entry)
    return files


def _candidate_dirs(path: str) -> list[str]:
    """Every directory above `path` that could own it, shallowest first."""
    parts = path.split('/')[:-1]
    return ['/'.join(parts[:depth]) for depth in range(1, min(len(parts), 3) + 1)]


# --- nodes -------------------------------------------------------------------

def _label(segment: str) -> str:
    """A directory segment as a chip label: the repo's own word for it.

    `codingdude` -> `Codingdude`, `.codingdude-seed` -> `Codingdude Seed`,
    `src` -> `Source`, `cli` -> `CLI`. Mechanical, so a label never asserts a
    purpose the directory does not have.
    """
    cleaned = segment.lstrip('.').replace('-', ' ').replace('_', ' ')
    words = [word for word in cleaned.split() if word]
    if not words:
        return segment
    if len(words) == 1:
        plain = words[0].lower()
        if plain in AREA_LABELS:
            return AREA_LABELS[plain]
        if plain in ACRONYMS:
            return ACRONYMS[plain]
    return ' '.join(word[:1].upper() + word[1:] for word in words)


def _node_id(directory: str) -> str:
    """`a/b/c` -> `a.b.c`, the schema's "dotted by parent" convention."""
    return directory.replace('/', '.')


def _owner(path: str, eligible: set[str]) -> str:
    """The deepest eligible directory claiming `path` — the builder's rule 2."""
    best = ''
    for directory in _candidate_dirs(path):
        if directory in eligible:
            best = directory
    return best


def _parent_of(directory: str, kept: set[str]) -> str:
    """The nearest kept ancestor, or '' for a top-level chip."""
    parts = directory.split('/')
    for depth in range(len(parts) - 1, 0, -1):
        candidate = '/'.join(parts[:depth])
        if candidate in kept:
            return candidate
    return ''


def _kind(directory: str, entrypoints: set[str]) -> str:
    """The chip's kind: the area's role, or `service` if it owns an entrypoint."""
    if any(path.startswith(f'{directory}/') for path in entrypoints):
        return 'service'
    first = directory.split('/')[0]
    return AREA_KINDS.get(directory) or AREA_KINDS.get(first) or 'library'


def _area_summary(root: Path, directory: str) -> str:
    """A directory's own one-line purpose: its `__init__.py` docstring.

    Directories have no docstrings, and inventing one is the failure
    `writing-descriptions.md` warns about. So the summary comes from the module
    that *is* the package, and is absent when there is none: floorplan then
    reports the module as having no summary, which a reader can fix, rather
    than rendering a sentence nobody can check.
    """
    for candidate in ('__init__.py', 'index.ts', 'index.js'):
        path = root / directory / candidate
        if not path.is_file():
            continue
        return _module_docstring(path) if candidate == '__init__.py' else _header_comment(path)
    return ''


def _module_docstring(path: Path) -> str:
    """A Python module's docstring, first sentence, or ''."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except (OSError, SyntaxError, ValueError):
        # A file the interpreter cannot parse has no summary to quote. It is
        # still on the board — only the sentence is missing.
        return ''
    return _first_sentence(ast.get_docstring(tree, clean=True) or '')


def _header_comment(path: Path) -> str:
    """A JS/TS module's first non-licence block comment.

    Every file here opens with the AGPL header, so the naive "first comment" is
    the licence; the first one that is not is the file's own note.
    """
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    for block in re.findall(r'/\*(.*?)\*/', text, re.S):
        if 'GNU Affero' in block:
            continue
        sentence = _first_sentence(block)
        if sentence:
            return sentence
    return ''


def _first_sentence(text: str) -> str:
    """The opening sentence of a docstring, collapsed onto one line."""
    collapsed = ' '.join(text.split())
    if not collapsed:
        return ''
    match = re.match(r'(.+?[.!?])(?:\s|$)', collapsed)
    sentence = match.group(1) if match else collapsed
    if len(sentence) > DESC_LIMIT:
        sentence = sentence[:DESC_LIMIT - 1].rstrip() + '…'
    return sentence


def _root_node(owners: dict[str, str]) -> list[dict]:
    """Files no directory claims: `bench.py` and friends, if there are any.

    A chip of its own rather than leaving them on floorplan's `Unassigned`,
    because "files at the repository root" is a true statement about them and
    `Unassigned` reads as an authoring gap.
    """
    if not any(not owner for owner in owners.values()):
        return []
    return [{
        'id': 'root',
        'label': 'Root files',
        'kind': 'script',
        # `*` crosses no separator, so this claims root files only; a deeper
        # chip wins its own tree by depth.
        'paths': ['*'],
    }]


def nodes_for(root: Path, files: list[dict], entrypoints: set[str]) -> list[dict]:
    """One chip per directory that actually owns files, plus a root bucket.

    Two passes, because the two counts differ: a directory large enough to earn
    a chip may own nothing once deeper chips have claimed its files (`src` does
    exactly that on this repo), and a chip holding no files would be a lie the
    builder only warns about.
    """
    counts: dict[str, int] = {}
    for entry in files:
        for directory in _candidate_dirs(entry['path']):
            counts[directory] = counts.get(directory, 0) + 1
    # `_candidate_dirs` stops at depth 3 and `MIN_FILES_BY_DEPTH` covers 1-3, so
    # the fallback only fires if one of those two moves without the other.
    eligible = {
        directory for directory, count in counts.items()
        if count >= MIN_FILES_BY_DEPTH.get(directory.count('/') + 1, 10 ** 6)
    }
    owners = {entry['path']: _owner(entry['path'], eligible) for entry in files}
    owned: dict[str, int] = {}
    for owner in owners.values():
        if owner:
            owned[owner] = owned.get(owner, 0) + 1
    kept = {directory for directory in eligible if owned.get(directory)}
    nodes: list[dict] = []
    for directory in sorted(kept):
        node: dict = {
            'id': _node_id(directory),
            'label': _label(directory.split('/')[-1]),
            'kind': _kind(directory, entrypoints),
            'paths': [f'{directory}/**'],
        }
        parent = _parent_of(directory, kept)
        if parent:
            node['parent'] = _node_id(parent)
        summary = _area_summary(root, directory)
        if summary:
            node['summary'] = summary
        nodes.append(node)
    return [*nodes, *_root_node(owners)]


# --- declared dependencies ---------------------------------------------------

def _pyproject(root: Path) -> dict:
    """`pyproject.toml`, or {} when it is missing or unreadable."""
    try:
        return tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _package_json(root: Path) -> dict:
    """`frontend/package.json`, or {} — the npm half of the declared deps."""
    try:
        payload = json.loads((root / 'frontend' / 'package.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _requirement_name(spec: str) -> str:
    """`pydantic-ai>=2.68` -> `pydantic-ai`; extras and markers dropped."""
    return re.split(r'[\s<>=!~;\[(]', spec.strip(), maxsplit=1)[0]


def declared_dependencies(root: Path) -> list[tuple[str, str]]:
    """The (ecosystem, name) pairs this repo declares, in declaration order.

    Runtime dependencies plus the `dev` extra for Python, and both dependency
    blocks of the frontend manifest: a declared dependency is a fact, and the
    scan decides which of them are actually imported.
    """
    project = _pyproject(root).get('project') or {}
    extras = project.get('optional-dependencies') or {}
    raw: list[tuple[str, str]] = [
        ('pypi', _requirement_name(spec))
        for spec in list(project.get('dependencies') or []) + list(extras.get('dev') or [])
        if isinstance(spec, str)
    ]
    manifest = _package_json(root)
    for block in ('dependencies', 'devDependencies'):
        names = manifest.get(block)
        if isinstance(names, dict):
            raw += [('npm', name) for name in names]
    seen: set[str] = set()
    deps: list[tuple[str, str]] = []
    for ecosystem, name in raw:
        if not name:
            continue
        key = f'{ecosystem}:{_dep_key(name)}'
        if key in seen:
            continue
        seen.add(key)
        deps.append((ecosystem, name))
    return deps


def _dep_key(name: str) -> str:
    """`pydantic-ai` and `pydantic_ai` are one package."""
    return name.strip().lower().replace('-', '_')


def _slug(name: str) -> str:
    """A package name as an id segment: letters, digits, `_`."""
    return re.sub(r'[^0-9a-zA-Z]+', '_', name).strip('_').lower() or 'package'


def externals_for(deps: list[tuple[str, str]], scan: dict) -> list[dict]:
    """`external` chips for the declared dependencies the scan actually saw.

    Only declared ones: a transitive package the scan happens to notice is not
    something this repository chose. The count comes from the scan, so a chip
    is a measurement, and the cap keeps the board readable.
    """
    seen: dict[str, dict] = {}
    for entry in scan.get('externals') or ():
        if not isinstance(entry, dict):
            continue
        key = _dep_key(entry.get('name') or '')
        if key:
            seen[key] = entry
    matched: list[tuple[int, str, dict]] = []
    for _ecosystem, name in deps:
        entry = seen.get(_dep_key(name))
        if entry is not None:
            matched.append((int(entry.get('files') or 0), name, entry))
    matched.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            'id': f'dep.{_slug(name)}',
            'label': name,
            'kind': 'external',
            'packages': [str(entry.get('id') or name)],
        }
        for _files, name, entry in matched[:MAX_EXTERNAL_NODES]
    ]


# --- the payload -------------------------------------------------------------

def _entrypoint_files(root: Path, files: list[dict]) -> set[str]:
    """`[project.scripts]` targets, as the files that exist in the scan.

    A target is a `module:function` reference, so the file is the module's
    path — checked against the scan rather than assumed, because an entrypoint
    the map cannot show would be a chip claiming a file that is not on it.
    """
    scripts = (_pyproject(root).get('project') or {}).get('scripts') or {}
    present = {entry['path'] for entry in files}
    found: set[str] = set()
    for target in scripts.values():
        if not isinstance(target, str) or ':' not in target:
            continue
        module = target.split(':', 1)[0].replace('.', '/')
        for candidate in (f'src/{module}.py', f'{module}.py', f'src/{module}/__init__.py'):
            if candidate in present:
                found.add(candidate)
                break
    return found


def build_architecture(root: Path, scan: dict) -> dict:
    """The `architecture.json` payload for this repository.

    Pure in `(root, scan)` — no subprocess, no clock — so a test can assert the
    whole document against a fixture scan.
    """
    files = included_files(scan)
    entrypoints = _entrypoint_files(root, files)
    project = _pyproject(root).get('project') or {}
    name = project.get('name')
    payload: dict = {
        '$schema': ARCH_SCHEMA,
        'audience': AUDIENCE,
        'include': list(INCLUDE),
        'ignore': list(IGNORE),
        'project': {'name': name if isinstance(name, str) and name else root.name},
    }
    summary = project.get('description')
    if isinstance(summary, str) and summary.strip():
        payload['project']['summary'] = ' '.join(summary.split())
    if entrypoints:
        payload['project']['entrypoints'] = sorted(entrypoints)
    payload['nodes'] = [
        *nodes_for(root, files, entrypoints),
        *externals_for(declared_dependencies(root), scan),
    ]
    return payload


def validate(architecture: dict, files: list[dict]) -> list[str]:
    """Every reason the builder would refuse this file, or merely complain.

    The path rule is the point: `build.mjs:236` only *warns* when a node's glob
    matches no included file, and a warning scrolls past. A declared path that
    claims nothing is an authoring error — the chip says it owns files it does
    not have — so it is checked here, before the build, and returned verbatim.
    """
    paths = [entry['path'] for entry in files]
    errors: list[str] = []
    nodes = architecture.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        return ['architecture.json lists no nodes']
    ids: set[str] = set()
    for index, node in enumerate(nodes):
        where = f'nodes[{index}]'
        if not isinstance(node, dict):
            errors.append(f'{where} is not an object')
            continue
        node_id = node.get('id')
        if not isinstance(node_id, str) or not node_id:
            errors.append(f'{where} needs an id')
            continue
        where = f'node "{node_id}"'
        if node_id in ids:
            errors.append(f'{where} is declared twice')
        ids.add(node_id)
        label = node.get('label')
        if not isinstance(label, str) or not label:
            errors.append(f'{where} needs a label')
        if node.get('kind') not in KINDS:
            errors.append(f'{where} kind "{node.get("kind")}" is not one floorplan accepts')
        globs = node.get('paths') or []
        if node.get('kind') == 'external':
            if globs:
                errors.append(f'{where} is external and owns no files, but declares paths')
            if not node.get('packages'):
                errors.append(f'{where} is external and needs at least one package')
            continue
        if not globs:
            errors.append(f'{where} declares no paths')
        for glob in globs:
            if not any(glob_match(glob, path) for path in paths):
                errors.append(f'{where} path "{glob}" matches no included file')
    for node in nodes:
        parent = node.get('parent') if isinstance(node, dict) else None
        if parent and parent not in ids:
            errors.append(
                f'node "{node.get("id")}" names parent "{parent}", which is not a node')
    return errors


# --- descriptions ------------------------------------------------------------

def _function_docstrings(path: Path) -> dict[str, str]:
    """Every top-level function's first docstring sentence, by name.

    FastAPI handlers are top-level functions, so this covers the route table
    without walking nested scopes — and a handler defined some other way simply
    has no description, which is honest.
    """
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except (OSError, SyntaxError, ValueError):
        return {}
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        sentence = _first_sentence(ast.get_docstring(node, clean=True) or '')
        if sentence:
            found[node.name] = sentence
    return found


def descriptions(root: Path, files: list[dict], routes: list[dict]) -> dict:
    """One sentence per file and per route, quoted from the code's docstring.

    Python only, deliberately: every JS/TS file here opens with the licence
    header, so "first comment" is the licence, and a second heuristic on top of
    that would be this module paraphrasing code it has not read. A file
    floorplan has nothing for falls back to its own name, which is at least
    true.
    """
    payload: dict = {'files': {}, 'routes': {}}
    included = {entry['path'] for entry in files}
    for entry in files:
        if entry.get('lang') != 'python':
            continue
        sentence = _module_docstring(root / entry['path'])
        if sentence:
            payload['files'][entry['path']] = {'description': sentence}
    handler_docs: dict[str, dict[str, str]] = {}
    for route in routes:
        if not isinstance(route, dict):
            continue
        path = route.get('file')
        handler = route.get('handler')
        method = route.get('method')
        url = route.get('path')
        if not isinstance(path, str) or path not in included:
            continue
        if not isinstance(handler, str) or not isinstance(method, str) or not isinstance(url, str):
            continue
        if path not in handler_docs:
            handler_docs[path] = _function_docstrings(root / path)
        sentence = handler_docs[path].get(handler, '')
        if sentence:
            payload['routes'][f'{method} {url}'] = {'description': sentence}
    return payload


# --- recent work -------------------------------------------------------------

def git_changes(workdir: Path) -> tuple[dict[str, str], str]:
    """Changed paths since `HEAD` -> `new` | `changed`, and why it failed.

    The run's own delta: a run's work is the working tree until it is
    committed, so `git status` is the honest source and needs no run plumbing.
    Bounded, and a failure returns the reason rather than an empty map that
    would read as "nothing changed".
    """
    git = shutil.which('git')
    if git is None:
        return {}, 'recent work unavailable: git is not on PATH'
    try:
        cap = subprocess.run(  # nosec B603 - resolved executable, constant argv, no shell
            [git, 'status', '--porcelain'],
            cwd=str(workdir), capture_output=True, text=True,
            timeout=GIT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, f'recent work unavailable: {type(exc).__name__} running git status'
    if cap.returncode != 0:
        detail = (cap.stderr or '').strip().splitlines()
        reason = f'recent work unavailable: git status exited {cap.returncode}'
        return {}, reason + (f' ({detail[0]})' if detail else '')
    changes: dict[str, str] = {}
    for line in cap.stdout.splitlines():
        status, rest = line[:2], line[3:]
        path = rest.split(' -> ')[-1].strip().strip('"')
        if not path or 'D' in status:
            continue
        changes[path.replace('\\', '/')] = 'new' if '?' in status or 'A' in status else 'changed'
    return changes, ''


def _owner_label(architecture: dict, path: str) -> str:
    """The label of the deepest chip claiming `path`, or ''.

    Reuses the board's own labels instead of inventing a second naming: the
    "Recent work" card then names the same part the reader is looking at.
    """
    best = ''
    label = ''
    for node in architecture.get('nodes') or ():
        if not isinstance(node, dict):
            continue
        for pattern in node.get('paths') or ():
            if glob_match(pattern, path) and len(pattern) > len(best):
                best, label = pattern, str(node.get('label') or '')
    return label


def recent_work(root: Path, files: list[dict], architecture: dict) -> tuple[dict, str]:
    """`recent-work.json`: the included files the working tree has changed.

    Refs that are not on the map are filtered out here rather than left for the
    builder to drop with a warning: a docs edit is real work but it is not on
    the board, and one warning per such file would bury the rest.
    """
    changes, error = git_changes(root)
    included = {entry['path'] for entry in files}
    items = [
        {'ref': path, 'change': change}
        for path, change in sorted(changes.items()) if path in included
    ]
    payload: dict = {'updatedAt': datetime.now(UTC).isoformat(), 'tasks': []}
    if not items:
        return payload, error
    areas: dict[str, int] = {}
    for item in items:
        label = _owner_label(architecture, item['ref'])
        areas[label] = areas.get(label, 0) + 1
    dominant = max(areas.items(), key=lambda pair: (pair[1], pair[0]))[0]
    skipped = len(changes) - len(items)
    summary = (
        f'{len(items)} changed file(s) on this map'
        + (f'; {skipped} changed path(s) are not code on it' if skipped else '')
    )
    payload['tasks'] = [{
        'title': f'Changes in {dominant}' if dominant else 'Changes at the root',
        'summary': summary,
        'items': items,
    }]
    return payload, error


# --- the author --------------------------------------------------------------

def author(workdir: str | Path, home: str | Path | None = None) -> Authored:
    """Write floorplan's three inputs into this project's map dir.

    Reads `scan.json` — the scan always runs first — because the globs are
    derived from it. Refuses rather than writing a file whose globs claim no
    files: the build would only warn, and a warning is how the first probe
    shipped 5 wrong paths.
    """
    root = Path(workdir)
    target = map_dir(root, home)
    scan_path = target / 'scan.json'
    try:
        scan = json.loads(scan_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return Authored(ok=False, error=f'cannot read the scan at {scan_path}: {exc}')
    if not isinstance(scan, dict):
        return Authored(ok=False, error=f'the scan at {scan_path} is not an object')
    files = included_files(scan)
    if not files:
        return Authored(ok=False, error=(
            'the scan found no code files to map: every category it reported '
            "falls outside the map's include list"))
    architecture = build_architecture(root, scan)
    errors = validate(architecture, files)
    if errors:
        more = f' (and {len(errors) - 5} more)' if len(errors) > 5 else ''
        return Authored(ok=False, error='; '.join(errors[:5]) + more)
    recent, note = recent_work(root, files, architecture)
    described = descriptions(root, files, scan.get('routes') or [])
    written: list[Path] = []
    for path, payload in (
        (target / ARCH_NAME, architecture),
        (target / 'descriptions' / DESC_NAME, described),
        (target / RECENT_NAME, recent),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
        written.append(path)
    return Authored(ok=True, paths=tuple(written), notes=(note,) if note else ())
