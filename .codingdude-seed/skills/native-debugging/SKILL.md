---
name: native-debugging
description: >
  Debug native-language programs (Odin, C/C++, Rust, Zig) with symbol-bearing
  builds and batch debugger commands. Use when a native binary crashes, hangs,
  or misbehaves and a stack trace / variable inspection is needed — companion
  to diagnosing-bugs.
---

# Native debugging

Standard debugger: **LLDB** (`lldb.cmd` in `~/.local/bin`; LLVM 23, PDB + DWARF).
Fallbacks: gdb, cdb (Windows SDK, if installed). Never assume a debugger exists
— probe with `lldb --version` first.

## 1. Two builds (always)

Debug build: symbols, no optimization — the ONLY build you debug.
Release build: `-o:speed` / `-O2` / `--release` — never debug it, never infer
behavior from it.

| Language | Debug build | Release build |
|---|---|---|
| Odin  | `odin build . -debug -o:none` | `odin build . -o:speed` |
| MSVC  | `cl /Zi /Od` | `cl /O2` |
| clang/gcc | `-g -O0` | `-O2` |
| Rust  | `cargo build` (dev profile) | `cargo build --release` |

Odin libraries have no `main`: check builds use `-no-entry-point`; linking a
library needs `-build-mode:static` (which ignores /DEBUG flags — LNK4044 is
harmless). "Debug a library" = build a debug exe that links it.

## 2. Batch debugging (unattended — no UI)

Run to crash, capture backtrace, quit:

```
lldb -b -o run -o bt -o quit -- ./app.exe
```

- Stop reason line names the exception (e.g. `0xc0000005 Access violation`)
  and the faulting address.
- With symbols, `bt`/frame output includes `file.odin:LINE` and prints the
  surrounding source — cite that line in the diagnosis.
- Useful batch commands: `bt all` (all threads), `frame variable` (locals),
  `p expr`, `break set -f file -l N` + `-o run -o c`, `thread backtrace`,
  `register read`.

gdb equivalent: `gdb -batch -ex run -ex bt --args ./app`.
Windows cdb equivalent: `cdb -c "g; kb; q" app.exe`.

## 3. Crash-postmortem (no live debugger)

Windows: enable local dumps (HKLM\SOFTWARE\Microsoft\Windows\Windows Error
Reporting\LocalDumps) or run under LLDB once to get the trace directly —
prefer the latter.

## 4. Rules

- Reproduce first with the smallest binary; then attach the debugger.
- Batch output is evidence — paste the stop reason + frame #0 into the diagnosis.
- Never claim "fixed" without re-running the debug build under the debugger.
- LLDB on Windows needs a `python3.dll` on PATH; the shipped `lldb.cmd` shim
  handles it. If moved machines lack it, point PATH at any CPython 3.x dir.
