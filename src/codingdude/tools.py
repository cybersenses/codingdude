"""Coding tools: list, read, grep, glob, plus surgical edits — all confined to the Workdir."""

import ast
import asyncio
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from codingdude.editmatch import find_similar_lines, replace_most_similar_chunk
from codingdude.langs import LanguageSpec, spec_for
from codingdude.processes import ProcessRegistry
from codingdude.pyparse import parse_python

from .approvals import DENIED, NEEDS_GATE
from .astdiff import describe_ast_change
from .config import ThinkingSetting
from .directives import project_directives_guard
from .errors import GateRequired
from .security import format_findings, scan_source

MAX_READ_BYTES = 256 * 1024
MAX_GREP_RESULTS = 50
MAX_FILE_BYTES = 2 * 1024 * 1024  # grep: skip files larger than this
SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}
SECRET_MARKERS = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')


def _git_bash_exe() -> str | None:
    """Windows: locate Git Bash. Bare `bash` may resolve to the WSL stub
    (which fails with 'no installed distributions' when WSL has no distro),
    so prefer the bash shipped next to git itself."""
    git_exe = shutil.which('git')
    if git_exe:
        for base in (Path(git_exe).parent, Path(git_exe).parent.parent):
            cand = base / 'bin' / 'bash.exe'
            if cand.exists():
                return str(cand)
    for cand in (Path(r'C:\Program Files\Git\bin\bash.exe'),):
        if cand.exists():
            return str(cand)
    found = shutil.which('bash')
    if found and 'system32' not in found.lower():  # skip the WSL stub
        return found
    return None


def shell_argv(command: str, shell_bin: str = 'bash') -> list[str]:
    """Argv to run `command` under the configured shell (bash or powershell).

    One place, so the shell tool / coverage / fix-loop can't drift onto a
    hardcoded `bash` on Windows (self-review M10). On Windows `bash` means
    Git Bash, resolved explicitly so the WSL stub never wins.
    """
    if shell_bin == 'powershell':
        return ['powershell', '-NoProfile', '-Command', command]
    if os.name == 'nt':
        bash = _git_bash_exe()
        if bash is not None:
            return [bash, '-c', command]
    return ['bash', '-c', command]


# Names that contain a marker but are known-safe; extend if a benign
# variable is ever scrubbed (self-review L3). Empty today — SYSTEMROOT and
# the other Windows system vars don't contain a marker.
ENV_ALLOWLIST: frozenset[str] = frozenset()


def scrubbed_env() -> dict:
    """Child-process environment with secret-looking variables removed.

    The shell tool must not hand provider keys to arbitrary commands.
    Scrubbing stays deliberately conservative — any name *containing* a
    marker is dropped — so a real secret is never leaked; `ENV_ALLOWLIST`
    is the escape hatch for a benign name that happens to contain one.
    """
    import os

    return {
        k: v
        for k, v in os.environ.items()
        if k in ENV_ALLOWLIST
        or not any(marker in k.upper() for marker in SECRET_MARKERS)
    }

def _kill_tree_sync(pid: int) -> None:
    """Kill `pid` and its descendants (blocking; run via to_thread).

    proc.kill() only terminates the direct child — on Windows grandchildren
    (uv/python under bash) survive holding the pipes. taskkill /T walks the
    tree; on POSIX the process group covers it.
    """
    import logging
    import signal
    import subprocess

    try:
        if os.name == 'nt':
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True, timeout=10, check=False,
            )
        else:  # pragma: win32 no cover — POSIX branch
            getpgid = getattr(os, 'getpgid', None)
            killpg = getattr(os, 'killpg', None)
            if getpgid is not None and killpg is not None:
                killpg(getpgid(pid), getattr(signal, 'SIGKILL', signal.SIGTERM))
    except (OSError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning('tree-kill of pid %s failed: %s', pid, exc)


def _close_pipes(proc: asyncio.subprocess.Process) -> None:
    """Best-effort close of a killed process's pipe transports.

    On the Proactor loop an abandoned pipe read never completes, so the
    transport lingers and can wedge loop shutdown (R30 #61)."""
    for reader in (proc.stdout, proc.stderr):
        if reader is None:
            continue
        transport = getattr(reader, '_transport', None)
        if transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001 - cleanup must never raise
                pass


async def _kill_tree(pid: int) -> None:
    await asyncio.to_thread(_kill_tree_sync, pid)


class Captured(NamedTuple):
    """Result of a captured subprocess run (run_captured)."""
    code: int
    stdout: str
    stderr: str

    @property
    def combined(self) -> str:
        return (self.stdout + self.stderr).strip()


async def run_captured(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict | None = None,
    shell: bool = False,
    registry: 'ProcessRegistry | None' = None,
) -> Captured | None:
    """Run a command, capture output, kill on timeout.

    Returns None when the process was killed after  seconds —
    callers format their own timeout message. One place so timeout
    handling (kill, not orphan) and decode can't drift across call sites.

    `registry` (R28 Phase 1) records the command's lifecycle: spawn, exit,
    and whether it left background writers on the pipes.
    """
    if env is None:
        env = scrubbed_env()
    if shell:
        try:
            proc = await asyncio.create_subprocess_shell(
                ' '.join(argv), cwd=cwd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env)
        except OSError as exc:  # #146: WinError 206, bad shell, ...
            return Captured(code=-1, stdout='',
                            stderr=f'spawn failed: {type(exc).__name__}: {exc}')
    else:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env)
        except OSError as exc:  # FileNotFoundError (missing binary) is an OSError
            return Captured(code=-1, stdout='',
                            stderr=f'spawn failed: {type(exc).__name__}: {exc}')
    if registry is not None:
        registry.register(proc.pid, ' '.join(argv))
    try:
        # R21: wait on the *process*, not communicate()/proc.wait(). Both wait
        # for pipe EOF on Windows — a grandchild that inherited stdout/stderr
        # keeps the pipes open after the parent exits, so a finished command
        # would block to the full timeout, get killed, and lose its output.
        # Poll returncode instead: it is set the moment the process exits.
        deadline = time.monotonic() + timeout
        while proc.returncode is None and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if proc.returncode is None:
            await _kill_tree(proc.pid)
            while proc.returncode is None:
                await asyncio.sleep(0.05)
            _close_pipes(proc)
            if registry is not None:
                registry.finish(proc.pid, status='killed', exit_code=proc.returncode)
            return None

        # Drain the pipes with a per-read grace window: stop as soon as the
        # parent has exited and a read times out (leftover pipe writers like
        # grandchildren would otherwise hold EOF forever). A stall means the
        # command spawned something that outlives it — registered as a
        # background orphan (R28 Phase 1), never killed here.
        assert proc.stdout is not None and proc.stderr is not None  # PIPEs above
        stdout, stdout_stalled = await _drain(proc.stdout)
        stderr, stderr_stalled = await _drain(proc.stderr)
        background = stdout_stalled or stderr_stalled
        if registry is not None:
            registry.finish(
                proc.pid, status='exited', exit_code=proc.returncode,
                background=background,
            )

        return Captured(
            code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout.decode(errors='replace'),
            stderr=stderr.decode(errors='replace'),
        )
    except BaseException:
        # R30 #61: cancellation (e.g. a caller's wait_for) must not orphan
        # the process tree — surviving children hold the pipes and wedge
        # the Windows Proactor loop close, hanging worker shutdown.
        if proc.returncode is None:
            await asyncio.shield(_kill_tree(proc.pid))
            _close_pipes(proc)
        raise


async def _drain(reader: asyncio.StreamReader) -> tuple[bytes, bool]:
    """Collect output until EOF, or until a read stalls after the process
    ended (grandchild-held pipe). Callers must have awaited proc.wait().

    Returns (output, stalled): stalled=True means writers other than the
    finished process still held the pipe — a background spawner.
    """
    chunks: list[bytes] = []
    stalled = False
    while True:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=1.0)
        except TimeoutError:
            stalled = True
            break
        if not line:  # EOF
            break
        chunks.append(line)
    return b''.join(chunks), stalled


EditEmitter = Callable[[dict], None]


def _read_verbatim(target: Path) -> str:
    """UTF-8 strict read that preserves the file's line endings verbatim (R12 #2)."""
    with open(target, encoding='utf-8', errors='strict', newline='') as f:
        return f.read()


def _atomic_write(target: Path, text: str) -> None:
    """Atomic text write: temp file in the same directory + os.replace (R12 #3).

R24 (#38): the temp name carries a uuid so concurrent writers to the same
target never collide on it (WinError 32 on Windows), and os.replace is
retried briefly to absorb transient locks on the target (AV, open editors).
Raises PermissionError naming the locked path if it stays locked.
"""
    import os

    tmp = target.with_name(f'{target.name}.{uuid.uuid4().hex}.codingdude-tmp')
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        last_exc: PermissionError | None = None
        for attempt in range(3):
            try:
                os.replace(tmp, target)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.05 * (attempt + 1))
        if last_exc is not None:
            raise PermissionError(
                f'{target} is locked by another process; write not applied.'
            ) from last_exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _ts_symbol_replacement(
    before: str, path: str, symbol: str, new_body: str, spec: LanguageSpec
) -> tuple[str, str]:
    """Resolve and rewrite a symbol via tree-sitter; return (new_text, summary)."""
    import textwrap

    from codingdude.tsedit import describe_ts_change, ts_symbol_spans

    src = before.encode('utf-8')
    spans = ts_symbol_spans(src, spec)
    candidates = {
        name: span
        for name, span in spans.items()
        if name.rsplit('.', 1)[-1] == symbol
    }
    if len(candidates) > 1:
        raise ModelRetry(
            f'symbol {symbol!r} is ambiguous in {path} — matches: '
            f'{", ".join(sorted(candidates))}. Use the qualified name.'
        )
    if symbol in spans:
        start, end = spans[symbol]
    elif candidates:
        start, end = next(iter(candidates.values()))
    else:
        known = ', '.join(sorted(spans)) or '(none)'
        raise ModelRetry(
            f'symbol {symbol!r} not found in {path}. Top-level definable '
            f'symbols: {known}.'
        )

    body = textwrap.dedent(new_body).rstrip('\n')
    lines = before.splitlines(keepends=True)
    eol = '\r\n' if lines and lines[0].endswith('\r\n') else '\n'
    # Re-indent to the replaced symbol's original indentation; text before
    # the span on its first line (e.g. 'export ') is preserved verbatim.
    line_start = src.rfind(b'\n', 0, start) + 1
    indent_match = re.match(rb'[ \t]*', src[line_start:start])
    indent = indent_match.group(0).decode('utf-8') if indent_match else ''
    if indent:
        body = '\n'.join(
            indent + ln if ln.strip() else ln for ln in body.split('\n')
        )
    replacement = body.encode('utf-8').replace(b'\n', eol.encode())
    after_bytes = src[:start] + replacement + src[end:]
    summary = describe_ts_change(src, after_bytes, spec)
    return after_bytes.decode('utf-8'), summary


def changed_line_numbers(before: str, after: str) -> set[int]:
    """1-based line numbers in `after` touched by the before→after edit.

    difflib opcodes → every line an insert/replace touched. Empty `before`
    (new file) marks all lines changed, so the whole file stays gated.
    """
    import difflib

    changed: set[int] = set()
    sm = difflib.SequenceMatcher(None, before.splitlines(), after.splitlines())
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ('insert', 'replace'):
            changed.update(range(j1 + 1, j2 + 1))
    return changed


def partition_findings(
    findings: list[dict], changed: set[int]
) -> tuple[list[dict], list[dict]]:
    """Split gate findings into (blocking, pre-existing).

    Findings on lines the edit touched (or line 0 / unattributed) block;
    findings elsewhere existed before the edit and are reported as warnings —
    they can never be fixed by retrying, and blocking on them exhausted the
    retry budget on files that were already flagged (gate diff-scope fix).
    """
    blocking = [f for f in findings if f['line'] == 0 or f['line'] in changed]
    preexisting = [f for f in findings if f['line'] != 0 and f['line'] not in changed]
    return blocking, preexisting


def build_toolset(
    workdir: Path,
    on_edit: EditEmitter | None = None,
    read_only: bool = False,
    approvals=None,
    capture: Callable[[Path], None] | None = None,
) -> FunctionToolset:  # noqa: C901
    """Build the toolset bound to a Workdir (via closure). read_only strips edits.
    `capture(abs_path)` snapshots a file before the agent modifies it (checkpoints).

    `approvals` (an ApprovalPolicy) gates AGENT.md edits — the Project Context
    changes only with explicit consent (spec story 26).
    """

    def resolve(path: str) -> Path:
        target = (workdir / path).resolve()
        try:
            target.relative_to(workdir.resolve())
        except ValueError:
            raise ModelRetry(
                f'Path {path!r} is outside the Workdir. '
                'Only paths inside the Workdir are accessible.'
            ) from None
        return target

    # R12 staleness registry: last-observed (mtime_ns, size) per relative path.
    observed: dict[str, tuple[int, int]] = {}

    def observe(rel: str, target: Path) -> None:
        st = target.stat()
        observed[rel] = (st.st_mtime_ns, st.st_size)

    def check_stale(rel: str, target: Path) -> None:
        rec = observed.get(rel)
        if rec is None:
            return
        st = target.stat()
        if (st.st_mtime_ns, st.st_size) != rec:
            # Gate diff-scope: hand the model the fresh bytes in the same
            # retry, so the re-read round-trip is not paid (a live concurrent
            # writer used to burn the whole retry budget on this race).
            fresh = _read_verbatim(target)[:6000]
            raise ModelRetry(
                f'{rel} changed since it was last read — re-edit using THIS '
                'current content (concurrent change; refusing to overwrite '
                f'blind):\n\n{fresh}'
            )

    def list_dir(path: str = '.') -> str:
        target = resolve(path)
        if not target.exists():
            return f'(directory not found: {path} — list_dir "." to see what exists)'
        entries = sorted(
            target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
        return '\n'.join(
            f"{'d' if e.is_dir() else '-'} {e.name}" for e in entries
        ) or '(empty)'

    def read_file(path: str) -> str:
        target = resolve(path)
        if not target.is_file():
            raise ModelRetry(f'{path!r} is not a file (list_dir first to explore).')
        try:
            with open(target, encoding='utf-8', errors='strict', newline='') as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(target, encoding='utf-8', errors='replace', newline='') as f:
                text = f.read()
        observe(path, target)
        return text[:MAX_READ_BYTES]

    def grep(pattern: str, path: str = '.') -> str:
        target = resolve(path)
        if not target.exists():
            return f'(path not found: {path} — list_dir "." to see what exists)'
        rx = re.compile(pattern)
        results: list[str] = []
        files = [target] if target.is_file() else sorted(target.rglob('*'))
        for f in files:
            if not f.is_file() or any(
                part in SKIP_DIRS for part in f.relative_to(workdir).parts
            ):
                continue
            try:
                data = f.read_text(encoding='utf-8', errors='replace')[:MAX_FILE_BYTES]
                for i, line in enumerate(data.splitlines(), 1):
                    if rx.search(line):
                        results.append(f'{f.relative_to(workdir)}:{i}: {line.strip()}')
                        if len(results) >= MAX_GREP_RESULTS:
                            return '\n'.join(results) + '\n(truncated)'
            except OSError:
                continue
        return '\n'.join(results) or '(no matches)'

    def glob(pattern: str) -> str:
        root = workdir.resolve()
        # Refuse patterns that climb out of the Workdir (mirrors resolve()).
        if Path(pattern).is_absolute() or '..' in Path(pattern).parts:
            raise ModelRetry(
                f'Glob pattern {pattern!r} escapes the Workdir. '
                'Use a relative pattern inside the project.'
            )
        matches = sorted(
            str(m.relative_to(root)) for m in root.glob(pattern) if m.is_file()
        )
        return '\n'.join(matches) or '(no matches)'

    def emit_edit(path: str, before: str, after: str) -> None:
        if on_edit:
            on_edit({'type': 'EDIT_APPLIED', 'kind': 'edit', 'path': path, 'before': before, 'after': after})

    def _guard_project_context(path: str) -> None:
        """Directives files (AGENT.md, DIRECTIVES.md) always need a gate."""
        if not project_directives_guard(path):
            return
        if approvals is None:
            raise ModelRetry(
                f'{path} is a directives file; editing it requires the approval '
                'system, which is not active in this run.'
            )
        if not approvals.yolo:
            raise GateRequired(f'edit {path}')

    def _security_gate(
        path: str, content: str, suffix: str, before: str = ''
    ) -> str:
        """R47 #155: scan content before it hits disk; findings block the write.

        Gate diff-scope: only findings on lines this edit touched block the
        write. Pre-existing findings elsewhere come back as a warning string
        for the tool result — retrying cannot fix them.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            findings = scan_source(path, content, suffix, Path(td))
        if not findings:
            return ''
        blocking, preexisting = partition_findings(
            findings, changed_line_numbers(before, content)
        )
        if blocking:
            raise ModelRetry(format_findings(path, blocking))
        if not preexisting:
            return ''
        lines = [f'security gate: pre-existing findings in {path} '
                 '(not introduced by this edit, not blocking):']
        lines.extend(
            f'  - :{f["line"]} [{f["severity"]}] {f["id"]}: {f["message"]}'
            for f in preexisting
        )
        return '\n'.join(lines)

    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Replace `old_text` with `new_text` — the match must be unique."""
        _guard_project_context(path)
        if capture:
            capture(resolve(path))
        target = resolve(path)
        check_stale(path, target)
        try:
            before = _read_verbatim(target)
        except UnicodeDecodeError:
            raise ModelRetry(
                f'{path} is not valid UTF-8; refusing to edit it to avoid '
                'silent corruption. Convert or repair the encoding first.'
            ) from None
        # Byte-faithful fast path: old_text as given (the model copied it
        # verbatim). Anything else goes through the layered matcher, which
        # handles CRLF mismatch, indent drift, and '...' elision.
        if old_text in before:
            if before.count(old_text) > 1:
                raise ModelRetry(
                    f'old_text appears more than once in {path} '
                    f'({before.count(old_text)} times). Include more '
                    'surrounding context so the match is unique.'
                )
            after = before.replace(old_text, new_text, 1)
        else:
            replaced = replace_most_similar_chunk(before, old_text, new_text)
            if replaced is None:
                hint = find_similar_lines(old_text, before)
                msg = (
                    f'old_text not found in {path}. Re-read the file and copy '
                    'the exact text to replace, including whitespace.'
                )
                if hint:
                    msg += f'\nDid you mean to match these lines?\n\n{hint}\n'
                raise ModelRetry(msg)
            after = replaced
        warn = _security_gate(path, after, target.suffix, before)
        _atomic_write(target, after)
        # Verify + rollback (R12 #3): the file on disk must equal what we
        # meant to write, or the original bytes go back.
        written = _read_verbatim(target)
        if written != after:
            # Restore original bytes directly — not via _atomic_write, so a
            # broken write primitive can't take the rollback down with it.
            target.write_bytes(before.encode('utf-8'))
            raise ModelRetry(
                f'write verification failed for {path}; original content '
                'restored. Do not retry unchanged — inspect the file first.'
            )
        observe(path, target)
        summary = (
            describe_ast_change(before, after) if target.suffix == '.py' else ''
        )
        emit_edit(path, before, after)
        return f'edited {path}' + (f'\n{summary}' if summary else '') + (
            f'\n{warn}' if warn else ''
        )

    def _parse_module(target: Path, text: str):
        try:
            return parse_python(text)
        except SyntaxError:
            raise ModelRetry(
                f'{target.name} does not parse as Python; edit_symbol needs a '
                'valid-syntax file (use edit_file instead).'
            ) from None

    def edit_symbol(path: str, symbol: str, new_body: str) -> str:
        """Replace a top-level function/class or method body by symbol name.

        `symbol` is a qualified name: 'my_func', 'MyClass', or 'MyClass.method'.
        `new_body` is the complete replacement definition (dedented if needed).
        Preferred over edit_file for whole-symbol rewrites — it cannot miss or
        duplicate matches.
        """
        import textwrap

        _guard_project_context(path)
        if capture:
            capture(resolve(path))
        target = resolve(path)
        check_stale(path, target)
        try:
            before = _read_verbatim(target)
        except UnicodeDecodeError:
            raise ModelRetry(
                f'{path} is not valid UTF-8; refusing to edit it to avoid '
                'silent corruption.'
            ) from None
        if target.suffix == '.py':
            tree = _parse_module(target, before)
        else:
            spec = spec_for(target.suffix)
            if spec is None:
                raise ModelRetry(
                    f'edit_symbol does not support {target.suffix} files '
                    '(no grammar registered); use edit_file instead.'
                )
            if spec.navigation_only:
                raise ModelRetry(
                    f'{target.suffix} files are navigation-only; use '
                    'edit_file for edits.'
                )
            after, summary = _ts_symbol_replacement(
                before, path, symbol, new_body, spec
            )
            warn = _security_gate(path, after, target.suffix, before)
            _atomic_write(target, after)
            written = _read_verbatim(target)
            if written != after:
                target.write_bytes(before.encode('utf-8'))
                raise ModelRetry(
                    f'write verification failed for {path}; original content '
                    'restored. Do not retry unchanged — inspect the file first.'
                )
            observe(path, target)
            emit_edit(path, before, after)
            result = f'edited {path}: replaced {symbol}' + (
                f'\n{warn}' if warn else ''
            )
            if summary:
                result += f'\n{summary}'
            return result
        # Collect qualified names: top-level defs/classes and their direct
        # methods, with byte-accurate line spans (decorators included).
        spans: dict[str, list[int]] = {}  # qualified name -> [start_line, end_line]
        for node in tree.body:
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            start = min(
                [d.lineno or node.lineno for d in node.decorator_list]
                + [node.lineno]
            )
            spans[node.name] = [start, node.end_lineno or node.lineno]
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(
                        child, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        spans[f'{node.name}.{child.name}'] = [
                            min(
                                [
                                    d.lineno
                                    for d in child.decorator_list
                                ]
                                + [child.lineno]
                            ),
                            child.end_lineno or child.lineno,
                        ]

        candidates = {
            name: span
            for name, span in spans.items()
            if name.rsplit('.', 1)[-1] == symbol
        }
        if len(candidates) > 1:
            # A bare name colliding with a method (or several) is ambiguous;
            # only an exact qualified match is unambiguous.
            raise ModelRetry(
                f'symbol {symbol!r} is ambiguous in {path} — matches: '
                f'{", ".join(sorted(candidates))}. Use the qualified name.'
            )
        if symbol in spans:
            start, end = spans[symbol]
        elif candidates:
            start, end = next(iter(candidates.values()))
        else:
            known = ', '.join(sorted(spans)) or '(none)'
            raise ModelRetry(
                f'symbol {symbol!r} not found in {path}. Top-level '
                f'definable symbols: {known}.'
            )

        body = textwrap.dedent(new_body).rstrip('\n')
        lines = before.splitlines(keepends=True)
        eol = '\r\n' if lines and lines[0].endswith('\r\n') else '\n'
        # Re-indent to the replaced symbol's original indentation, so a
        # dedented method body stays inside its class.
        indent_match = re.match(r'[ \t]*', lines[start - 1])
        indent = indent_match.group(0) if indent_match else ''
        if indent:
            body = '\n'.join(
                indent + ln if ln.strip() else ln
                for ln in body.split('\n')
            )
        replacement = body + eol
        after = ''.join(lines[: start - 1]) + replacement + ''.join(lines[end:])
        warn = _security_gate(path, after, target.suffix, before)
        _atomic_write(target, after)
        written = _read_verbatim(target)
        if written != after:
            target.write_bytes(before.encode('utf-8'))
            raise ModelRetry(
                f'write verification failed for {path}; original content '
                'restored. Do not retry unchanged — inspect the file first.'
            )
        observe(path, target)
        summary = describe_ast_change(before, after)
        emit_edit(path, before, after)
        result = f'edited {path}: replaced {symbol}' + (
            f'\n{warn}' if warn else ''
        )
        if summary:
            result += f'\n{summary}'
        return result

    def write_file(path: str, content: str) -> str:
        """Create a new file (with parent dirs). Existing non-empty files must use edit_file.

        CRITICAL for heredocs and multi-line strings: never retype large
        static chunks (SQL, HTML templates, scripts) from memory — mangling
        their whitespace breaks them. Compose files with generated code and
        text content; when replacing heredoc-heavy code in an existing file,
        include the entire heredoc (delimiters included) in the match.
        """
        _guard_project_context(path)
        if capture:
            capture(resolve(path))
        target = resolve(path)
        try:
            existed = _read_verbatim(target) if target.exists() else ''
        except UnicodeDecodeError:
            raise ModelRetry(
                f'{path} is not valid UTF-8; refusing to overwrite it.'
            ) from None
        if existed.strip():
            raise ModelRetry(
                f'{path} already exists and is not empty — use edit_file to change it.'
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        warn = _security_gate(path, content, target.suffix)
        _atomic_write(target, content)
        observe(path, target)
        emit_edit(path, existed, content)
        return f'wrote {path}' + (f'\n{warn}' if warn else '')

    tools: list[Callable] = [list_dir, read_file, grep, glob]
    if not read_only:
        tools += [edit_file, write_file, edit_symbol]
    return FunctionToolset(tools)


async def _resolve_gate(policy, command: str, always: bool = False) -> None:
    """Resolve a gated action: ask the user (interactive) or abort (headless).

    - no ask callback → GateRequired (headless abort, ADR-0003)
    - 'approve' → run once
    - 'pattern' → approve for the session; on always-gated actions the pattern
      is never persisted (only this one run goes through)
    - 'deny' → ModelRetry so the model knows the user said no
    """
    if policy is None or policy.ask is None:
        raise GateRequired(command)
    answer = await policy.ask(command)
    if answer == 'deny':
        raise ModelRetry(
            f'User DENIED this action: {command}. Do not retry it unchanged; '
            'continue the task another way or ask the user what to do instead.'
        )
    if answer == 'pattern' and not always:
        # One source of truth for what a pattern covers — never the bare
        # leading token, or an interpreter approval unlocks the interpreter
        # (self-review C1).
        pattern = policy.pattern_for(command)
        policy.approve_pattern(pattern)
        if policy.on_pattern:
            policy.on_pattern(pattern)


def build_shell_toolset(
    workdir: Path, policy, shell_bin: str = 'bash',
    on_render: Callable[[str], None] | None = None,
    registry: ProcessRegistry | None = None,
) -> FunctionToolset:
    """The shell tool, gated by the ApprovalPolicy.

    `on_render(relative_path)` is called for image files a command creates
    (capture hook, R1): screenshots auto-register as renders instead of
    staying orphan scratch files.

    `registry` (R28 Phase 1) records every spawned command so HITL can see
    the agent's processes; visibility only — no behavior change.
    """

    def _mask_workdir(command: str) -> str:
        """Blank out references to the Workdir itself before the approval
        decision: `cd G:/proj && ...` targets the project the agent is
        already confined to and must not read as an outside path."""
        resolved = workdir.resolve()
        backslash = chr(92)
        variants = {
            str(workdir),
            str(resolved),
            str(resolved).replace(backslash, '/'),
            str(resolved).lower().replace(backslash, '/'),
            '/' + workdir.drive.lower() + str(resolved)[2:].replace(backslash, '/'),
        }
        masked = command
        for variant in variants:
            if variant:
                masked = masked.replace(variant, '.')
        return masked

    async def shell(command: str, timeout: int = 120) -> str:
        decision = policy.decide(_mask_workdir(command))
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
        argv = shell_argv(command, shell_bin)
        started = time.time()
        cap = await run_captured(argv, cwd=workdir, timeout=timeout,
                                 registry=registry)
        if cap is None:
            return 'exit code: -1 (timed out)'
        if on_render is not None:
            _register_new_renders(workdir, started, on_render)
        output = cap.combined
        if len(output) > 8000:
            output = output[:4000] + '\n...\n' + output[-4000:]
        return f'exit code: {cap.code}\n{output}'

    def process_list() -> str:
        """Processes this session spawned, newest first."""
        rows = registry.snapshot() if registry is not None else []
        if not rows:
            return 'no processes registered'
        lines = [
            f"pid {r['pid']}  {r['status']}"
            + (' (background)' if r.get('background') else '')
            + f"  {r['command']}"
            for r in rows
        ]
        return '\n'.join(lines)

    def process_poll(pid: str) -> str:
        """Check whether a registered process is still running."""
        if registry is None:
            return 'process registry unavailable'
        record = registry.poll(_pid(pid))
        if record is None:
            return (
                f'pid {pid} was not registered by this session; '
                'use process_list to see known processes.'
            )
        return (
            f"pid {record['pid']}  {record['status']}"
            + (' (background)' if record.get('background') else '')
            + f"  {record['command']}"
        )

    def process_kill(pid: str) -> str:
        """Kill a process this session spawned (registered pids only)."""
        if registry is None:
            return 'process registry unavailable'
        return registry.kill(_pid(pid))

    def process_write(pid: str, text: str) -> str:
        """Write text to the stdin of an interactive shell session."""
        if registry is None:
            return 'process registry unavailable'
        return registry.write(_pid(pid), text)

    def process_read(pid: str) -> str:
        """Read output produced by an interactive session since last read."""
        if registry is None:
            return 'process registry unavailable'
        session = registry.sessions.get(_pid(pid))
        if session is None:
            return (
                f'pid {pid} is not an interactive session of this agent; '
                'use process_list to see known processes.'
            )
        out = session.read_new()
        record = registry.poll(_pid(pid))
        status = record['status'] if record else 'unknown'
        return f'[{status}]\n{out}' if out or status != 'running' else (
            out or '[no new output]')

    return FunctionToolset([
        shell, process_list, process_poll, process_kill,
        process_write, process_read,
    ])


def _pid(raw: str) -> int:
    """Parse a pid tool argument; 0 marks invalid (never a live pid)."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
_RENDER_SCAN_SKIP = {'.git', '.venv', 'node_modules', '__pycache__'}


def _register_new_renders(workdir: Path, started: float, on_render: Callable[[str], None]) -> None:
    """Report image files created/modified since `started` (best-effort).

    A render-producing command (screenshot, pixel gate) must surface its
    output; scanning for fresh images after the command is the cheapest
    reliable hook. Failures here never fail the command itself.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        for p in workdir.rglob('*'):
            if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if any(part in _RENDER_SCAN_SKIP for part in p.parts):
                continue
            if p.stat().st_mtime >= started:
                on_render(p.relative_to(workdir).as_posix())
    except OSError as exc:
        logger.warning('render capture scan failed: %s', exc)


def build_delegation_toolset(
    workdir: Path,
    subagent_model,
    thinking: ThinkingSetting | None = None,
    *,
    delegation_config=None,
    emitter=None,
    db=None,
    session_id: str = '',
    approvals=None,
) -> FunctionToolset:
    """The `delegate` tool: spawn a read-only Subagent on the cheap model.

    Subagents never see edit/write/shell/delegation tools, so Delegation
    can't route around Approval tiers. R13: the subagent's tools are rooted
    at a fresh git worktree (torn down afterwards), the run is bracketed by
    DELEGATION_STARTED/COMPLETED trace events, bounded by the configured
    request budget, and billed to the parent session.
    """
    from .config import DelegationConfig

    cfg = delegation_config or DelegationConfig()

    def _emit(event: dict) -> None:
        if emitter is not None:
            emitter(event)

    def _bill(usage) -> None:
        # Delegations are real spend: attribute to the parent Session (H6).
        if db is None or not session_id:
            return
        try:
            cost = getattr(usage, 'cost', None)
            db.record_usage(
                session_id,
                model=str(getattr(subagent_model, 'model_name', subagent_model)),
                requests=getattr(usage, 'requests', 0) or 0,
                input_tokens=getattr(usage, 'input_tokens', 0) or 0,
                output_tokens=getattr(usage, 'output_tokens', 0) or 0,
                cost_usd=float(cost) if cost is not None else None,
            )
        except Exception:  # noqa: BLE001 - accounting must never fail a run
            pass

    async def delegate(task: str, write: bool = False) -> str:
        import uuid as _uuid

        from pydantic_ai import Agent
        from pydantic_ai.exceptions import UsageLimitExceeded
        from pydantic_ai.settings import ModelSettings
        from pydantic_ai.usage import UsageLimits

        from .delegation import brief_prompt, build_brief
        from .prompts import load_prompt
        from .sandbox import _make_venv, exec_in_sandbox_dir
        from .worktrees import (
            WORKTREE_DIRNAME,
            WorktreeError,
            create_worktree,
            remove_worktree,
        )

        if write and approvals is None:
            return ('error: write delegations require an approval policy '
                    '(none configured for this session)')
        delegation_id = 'dlg-' + _uuid.uuid4().hex[:8]
        sandbox_name = 'delegation-' + uuid.uuid4().hex[:8]
        agent_workdir = workdir
        isolated = False
        try:
            create_worktree(workdir, sandbox_name)
            agent_workdir = workdir / WORKTREE_DIRNAME / sandbox_name
            isolated = True
            if write:
                _make_venv(agent_workdir)  # best-effort: exec falls back to PATH
        except WorktreeError:
            isolated = False  # no git history / name clash: unisolated, said so
        brief = build_brief(task, agent_workdir, cfg.max_requests)
        _emit({'type': 'DELEGATION_STARTED', 'task': task[:200],
               'isolated': isolated, 'delegation_id': delegation_id,
               'write': write,
               'brief_symbols': len(brief.symbols),
               'has_contract': brief.contract is not None})
        settings: ModelSettings = ModelSettings(timeout=300)
        if thinking is not None:
            settings['thinking'] = thinking

        async def exec_in_sandbox(command: str) -> str:
            '''Run one shell command inside this delegation's isolated
            sandbox worktree (its own branch; the main tree is untouched).
            Changes you make here come back to the parent as a diff.'''
            return await exec_in_sandbox_dir(
                workdir, sandbox_name, command, approvals)

        toolsets: list = [build_toolset(agent_workdir, read_only=True)]
        if write:
            from pydantic_ai.toolsets import FunctionToolset as _FTS

            toolsets.append(_FTS([exec_in_sandbox]))
        # R25: sub-agents get the same error-feedback seam as the main agent.
        from codingdude.tool_errors import error_feedback_toolset

        toolsets = [error_feedback_toolset(toolsets)]
        sub_agent: Agent = Agent(
            model=subagent_model,
            instructions=load_prompt('delegation'),
            toolsets=toolsets,
            model_settings=settings,
        )
        sandbox_diff: str | None = None
        try:
            try:
                result = await sub_agent.run(
                    brief_prompt(brief),
                    usage_limits=UsageLimits(request_limit=cfg.max_requests),
                )
            except UsageLimitExceeded:
                return (
                    'delegation aborted: exceeded the delegation budget of '
                    f'{cfg.max_requests} model requests. Narrow the task and '
                    'delegate again with a tighter question.'
                )
            if write and isolated:
                # intent-to-add so newly created files appear in the diff
                await run_captured(['git', 'add', '-N', '-A'],
                                   cwd=agent_workdir, timeout=60)
                cap = await run_captured(['git', 'diff'], cwd=agent_workdir,
                                         timeout=60)
                sandbox_diff = cap.combined.strip() if cap else ''
        finally:
            if isolated:
                remove_worktree(workdir, sandbox_name)
        usage = result.usage
        _bill(usage)
        cost = getattr(usage, 'cost', None)
        _emit({
            'type': 'DELEGATION_COMPLETED',
            'isolated': isolated,
            'delegation_id': delegation_id,
            'write': write,
            'requests': usage.requests or 0,
            'input_tokens': usage.input_tokens or 0,
            'output_tokens': usage.output_tokens or 0,
            'cost_usd': float(cost) if cost is not None else None,
        })
        output = str(result.output)
        if write and isolated:
            diff = sandbox_diff or ''
            output += (
                '\n\nSandbox diff (proposed, not applied):\n' + diff
                if diff else
                '\n\n(sandbox tree clean - no changes to integrate)')
        if cfg.max_cost_usd is not None and cost is not None \
                and float(cost) > cfg.max_cost_usd:
            output += (
                '\n(note: delegation cost ' + format(float(cost), '.4f')
                + ' USD exceeded the configured cap of '
                + str(cfg.max_cost_usd) + ' USD - consider raising '
                '[delegation].max_cost_usd or splitting the task)'
            )
        return output

    return FunctionToolset([delegate])


def build_web_toolset() -> 'AbstractToolset':
    """Web search (DuckDuckGo, no key) and page fetch, from pydantic-ai's built-ins.

    Local URLs are allowed — tests and self-hosted docs are legitimate targets.
    """
    from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
    from pydantic_ai.common_tools.web_fetch import web_fetch_tool
    from pydantic_ai.toolsets import RenamedToolset

    inner = FunctionToolset(
        [duckduckgo_search_tool(), web_fetch_tool(allow_local_urls=True)]
    )
    return RenamedToolset(inner, {'web_search': 'duckduckgo_search'})


def build_git_toolset(workdir: Path, policy) -> FunctionToolset:
    """Git/GitHub tools under the tier table: reads auto, commit/branch gated,
    push/PR always-gated (never pattern-unlockable)."""

    async def _run(argv: list[str], timeout: int = 60, use_shell: bool = False) -> str:
        cap = await run_captured(argv, cwd=workdir, timeout=timeout, shell=use_shell)
        if cap is None:
            return f'exit -1\n timed out after {timeout}s'
        return f'exit {cap.code}\n{cap.combined}' if cap.combined else f'exit {cap.code}'

    async def git_status() -> str:
        return await _run(['git', 'status', '--porcelain', '-b'])

    async def git_log(limit: int = 20) -> str:
        return await _run(['git', 'log', '--oneline', f'-n{limit}'])

    async def git_diff(path: str = '') -> str:
        argv = ['git', 'diff']
        if path:
            argv += ['--', path]
        return await _run(argv)

    async def _gate(command: str, always: bool = False) -> None:
        from .approvals import DENIED, NEEDS_GATE

        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=always or decision == DENIED)

    async def git_commit(message: str) -> str:
        await _gate('git commit')
        await _run(['git', 'add', '-A'])
        out = await _run(['git', 'commit', '-m', message])
        if 'commit failed' in out or 'exit 1' in out:
            return f'commit failed: {out}'
        return f'committed: {out.split(chr(10))[0]}'

    async def git_branch(name: str) -> str:
        await _gate('git branch')
        return await _run(['git', 'checkout', '-b', name])

    async def git_push(remote: str = 'origin', branch: str = 'main') -> str:
        await _gate('git push', always=True)  # always-gated: only explicit consent
        old = await _run(['git', 'rev-parse', f'{remote}/{branch}'])
        out = await _run(['git', 'push', remote, branch])
        if 'exit 0' not in out.split('\n')[0]:
            return out
        # R33 #67: post-push auto review directive. The pushed range feeds
        # the review loop; the loop never auto-pushes again.
        base = old.split('\n')[-1].strip() if 'exit 0' in old else ''
        range_note = (
            f'pushed range {base}..HEAD'
            if base else
            f'first push of {branch} — review the full branch diff'
        )
        return (
            f'{out}\n\nPOST-PUSH REVIEW REQUIRED ({range_note}).\n'
            'Before any further work: run the code-review flow over the pushed '
            'range — delegate review sub-agents on the Standards and Spec axes, '
            'include codegraph impact analysis on touched symbols, verify each '
            'finding against the code, then apply only verified fixes '
            '(surgical-patch / edit_symbol), re-run the project gates, and '
            'commit. Do NOT push the fixes without fresh explicit user consent.'
        )

    async def gh_pr_create(title: str, body: str) -> str:
        await _gate('gh pr create', always=True)
        # shell=True so Windows resolves gh (and test stubs) via PATH
        return await _run(
            ['gh', 'pr', 'create', '--title', title, '--body', body, '--fill'],
            use_shell=True,
        )

    async def gh_pr_view(number: int) -> str:
        await _gate('gh pr view', always=True)
        return await _run(['gh', 'pr', 'view', str(number)], use_shell=True)

    async def pr_summary(base: str = 'origin/main') -> str:
        """Compose a PR body from commits, diff stat, and AST summaries."""
        from .prsum import pr_summary_async

        return await pr_summary_async(workdir, base)

    return FunctionToolset(
        [
            git_status, git_log, git_diff, git_commit, git_branch, git_push,
            gh_pr_create, gh_pr_view, pr_summary,
        ]
    )


def resolve_workdir_path(workdir: str | Path, path: str) -> tuple[Path | None, str | None]:
    """Containment-checked path resolution for server-side file access.

    Returns (path, None) or (None, error). Symlink-safe: both sides are
    resolved before the containment check.
    """
    root = Path(workdir).resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, f'path {path!r} escapes the Workdir'
    return target, None

def resolve_workdir_file(root: Path, rel_path: str) -> Path | None:
    """Containment-checked resolution of an existing *file* under ``root``.

    Returns the resolved path, or None when it escapes the root or is not
    a regular file. Used by the subprocess-based analysis tools (bench,
    fuzzing, profile).
    """
    target = (root / rel_path).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target


def build_coverage_toolset(workdir: Path, policy) -> FunctionToolset:
    """The `run_coverage` tool: execute the project's test suite with coverage
    analysis and return per-file results with missing lines. Gated like shell
    (it runs your tests), pattern-approvable under 'coverage'."""

    async def run_coverage(source: str = '.') -> str:
        from .approvals import NEEDS_GATE

        # `source` is model-supplied: keep it a relative in-Workdir path and
        # pass argv (never a shell), so `.; rm -rf /` cannot execute (H3).
        if not source or Path(source).is_absolute() or '..' in Path(source).parts:
            raise ModelRetry(f'{source!r} is not a relative in-Workdir coverage source.')
        argv = ['python', '-m', 'pytest', f'--cov={source}',
                '--cov-report=term-missing', '-q']
        command = ' '.join(argv)
        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
        cap = await run_captured(argv, cwd=workdir, timeout=600)
        if cap is None:
            return 'exit code: -1 (coverage run timed out after 600s)'
        out = cap.combined
        if len(out) > 6000:
            out = out[:3000] + '\n...\n' + out[-3000:]
        return f'exit code: {cap.code}\n{out}'

    return FunctionToolset([run_coverage])


def build_knip_toolset(workdir: Path) -> FunctionToolset:
    """The `find_unused_exports` tool for JS/TS projects: runs knip from the
    project's own devDependencies (never auto-installing). Graceful when
    knip isn't set up."""

    async def find_unused_exports() -> str:
        if not (workdir / 'package.json').exists():
            return 'no package.json — knip only applies to JS/TS projects'
        cap = await run_captured(
            ['npx --no-install knip --reporter compact'],
            cwd=workdir, timeout=300, shell=True)
        if cap is None:
            return 'knip timed out after 300s'
        out = cap.combined
        code = cap.code
        if code != 0 and 'knip' not in out and len(out) < 200:
            return (
                'knip is not installed in this project. Add it as a devDependency '
                '(npm i -D knip) to enable unused-export and unused-dependency detection.'
            )
        return f'exit {code}\n{out[:6000]}'

    return FunctionToolset([find_unused_exports])


def build_ci_toolset(workdir: Path) -> FunctionToolset:
    """CI tools via the gh CLI. Read-only (run list, failed logs) — auto tier.

    `gh run rerun`/watch and anything mutating stay in the shell's
    always-gated tier; never auto-approved here."""

    async def _gh(argv: list[str], timeout: int = 120) -> str:
        cap = await run_captured(['gh', *argv], cwd=workdir, timeout=timeout)
        if cap is not None and cap.code == -1 and 'spawn failed' in cap.stderr:
            return (
                'gh is not installed - these CI tools need the GitHub CLI '
                '(https://cli.github.com).'
            )
        if cap is None:
            return 'gh timed out'
        return f'exit {cap.code}\n{cap.combined}' if cap.combined else f'exit {cap.code}'

    async def ci_status(branch: str = '') -> str:
        """Latest CI run statuses for the current repo (via gh)."""
        argv = ['run', 'list', '--limit', '5']
        if branch:
            argv += ['--branch', branch]
        return await _gh(argv)

    async def ci_failures(run_id: str = '') -> str:
        """Failed step names and log excerpts for a CI run (via gh)."""
        argv = ['run', 'view']
        if run_id:
            argv.append(run_id)
        argv += ['--log-failed']
        return await _gh(argv)

    return FunctionToolset([ci_status, ci_failures])


def build_audit_toolset(workdir: Path) -> FunctionToolset:
    """`dependency_audit`: vulnerability scan via pip-audit (Python) and
    npm audit (JS/TS). Read-only; auto tier. Reports what it finds; missing
    tools are surfaced so the agent can suggest installation."""

    async def _run(cmd: list[str], timeout: int = 300) -> str:
        cap = await run_captured(cmd, cwd=workdir, timeout=timeout)
        if cap is not None and cap.code == -1 and 'spawn failed' in cap.stderr:
            return f'{cmd[0]} is not installed'
        if cap is None:
            return 'audit timed out'
        return cap.combined

    async def dependency_audit() -> str:
        sections = []

        if (workdir / 'requirements.txt').exists() or (workdir / 'pyproject.toml').exists():
            pip_result = await _run(['pip-audit', '--progress-spinner', 'off'])
            if 'No known vulnerabilities found' in pip_result or 'no known vulnerabilities' in pip_result.lower():
                sections.append('pip-audit: no known vulnerabilities')
            elif 'is not recognized' in pip_result or 'No module named pip_audit' in pip_result:
                sections.append('pip-audit: not installed (pip install pip-audit)')
            else:
                sections.append(f'pip-audit:\n{pip_result[:3000]}')

        if (workdir / 'package.json').exists():
            npm_result = await _run(['npm', 'audit', '--json'])
            import json as _json

            try:
                report = _json.loads(npm_result)
                vulns = report.get('metadata', {}).get('vulnerabilities', {})
                total = vulns.get('total', 0)
                sections.append(
                    f'npm audit: {total} vulnerabilit{"y" if total == 1 else "ies"} '
                    f'(critical: {vulns.get("critical", 0)}, high: {vulns.get("high", 0)}, '
                    f'moderate: {vulns.get("moderate", 0)}, low: {vulns.get("low", 0)})'
                )
            except _json.JSONDecodeError:
                sections.append(f'npm audit: {npm_result[:500]}')

        return '\n\n'.join(sections) or '(no supported project manifests found)'

    return FunctionToolset([dependency_audit])


def build_ask_user_toolset(policy, recorder=None):
    """The `ask_user` tool: interactive questions (radios / checkboxes / text).

    `recorder(questions, answers)`, when given, is called after each answer so
    the exchange lands in the session's artifact history. Recorder failures are
    swallowed -- capture must never break the run.
    """
    import json as _json

    async def ask_user(questions: str) -> str:
        """Ask the user one or more questions and wait for their answers.

        `questions` is a JSON array, for example:
          [{"question": "Which database?", "options": ["postgres", "sqlite"],
            "multi": false}]
        Set `"multi": true` when several options may apply — the user sees
        checkboxes instead of radios. Leave `options` empty for a free-text
        question. Even with options, the user always gets an "Other…" field,
        so they can type an answer you did not list. Returns the answers as JSON.
        """
        from pydantic_ai import ModelRetry

        asker = getattr(policy, 'ask_user', None) if policy is not None else None
        if asker is None:
            raise ModelRetry(
                'ask_user needs the interactive UI (it is unavailable in headless runs).'
            )
        try:
            payload = _json.loads(questions) if isinstance(questions, str) else questions
        except _json.JSONDecodeError as exc:
            raise ModelRetry(f'questions must be valid JSON: {exc}') from None
        answers = await asker(payload)
        if recorder is not None:
            try:
                recorder(payload, answers)
            except Exception:  # noqa: BLE001 -- history capture is best-effort
                pass
        return 'User answers (JSON):\n' + _json.dumps(answers, ensure_ascii=False, indent=2)

    return FunctionToolset([ask_user])
