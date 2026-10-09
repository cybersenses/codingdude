"""Native debugging helper for CodingDude.

Captures a symbolicated backtrace from a crashing binary in batch mode.
Builds (with debug symbols) and runs the program under the best available
debugger (LLDB, then GDB). Companion to the `native-debugging` skill.

Usage:
    python native_debug.py build  --lang odin  <src-dir>   # debug build only
    python native_debug.py run    --exe ./app.exe [--args ...]
    python native_debug.py full   --lang odin  <src-dir>   # build + run
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404 - local dev tooling, fixed argv tables below
import sys

# Per-language debug build commands (two-build doctrine: debug vs release).
BUILD_COMMANDS: dict[str, list[str]] = {
    'odin': ['odin', 'build', '{src}', '-debug', '-o:none', '{out}'],
    'c': ['clang', '-g', '-O0', '{src}', '-o', '{out}'],
    'cpp': ['clang++', '-g', '-O0', '{src}', '-o', '{out}'],
    'rust': ['rustc', '-g', '-C', 'debuginfo=2', '{src}', '-o', '{out}'],
}

DEBUGGER_BATCH: dict[str, list[str]] = {
    # -b batch, run, backtrace, quit -- arguments after `--` are the target.
    'lldb': ['-b', '-o', 'run', '-o', 'bt', '-o', 'quit'],
    'gdb': ['-batch', '-ex', 'run', '-ex', 'bt', '-ex', 'quit'],
}


def find_debugger() -> str:
    for name in DEBUGGER_BATCH:
        if shutil.which(name):
            return name
    raise SystemExit(
        'no debugger found: install LLVM (lldb) or gdb; '
        'on Windows: winget install LLVM.LLVM'
    )


def build(lang: str, src: str, out: str) -> None:
    template = BUILD_COMMANDS.get(lang)
    if template is None:
        raise SystemExit(f'no build recipe for {lang!r}; known: {sorted(BUILD_COMMANDS)}')
    cmd = [part.format(src=src, out=out) for part in template]
    print('+', ' '.join(cmd))
    subprocess.run(cmd, check=True)  # nosec B603 - fixed local toolchain argv


def run(exe: str, args: list[str]) -> int:
    dbg = find_debugger()
    cmd = [dbg, *DEBUGGER_BATCH[dbg], '--', exe, *args]
    print('+', ' '.join(cmd))
    return subprocess.run(cmd, check=False).returncode  # nosec B603


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('build', 'full'):
        p = sub.add_parser(name)
        p.add_argument('--lang', required=True, choices=sorted(BUILD_COMMANDS))
        p.add_argument('src')
        p.add_argument('--out', default='app_debug.exe')
    p = sub.add_parser('run')
    p.add_argument('--exe', required=True)
    p.add_argument('args', nargs='*')
    ns = ap.parse_args()

    if ns.cmd == 'run':
        return run(ns.exe, ns.args)
    build(ns.lang, ns.src, ns.out)
    if ns.cmd == 'full':
        return run(ns.out, [])
    return 0


if __name__ == '__main__':
    sys.exit(main())
