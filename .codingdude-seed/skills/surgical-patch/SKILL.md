---
name: surgical-patch
description: Fix bugs and small behavior changes at the narrowest responsible layer. Use when regression proof, preserved surrounding behavior, and task-relevant tests matter.
---

# Surgical patch

The request's verbs define the scope. "Fix X" authorizes exactly X — not hardening, not validation the spec didn't name, not style work in the same file. If the ask is vague, fix the named behavior and report what you deliberately left alone; never treat vagueness as a license to improve.

- Reproduce failure first when economical; otherwise capture strongest available evidence.
- Trace symptom to responsible mechanism.
- Change narrowest layer that owns incorrect behavior.
- Preserve unrelated behavior, user changes, and EXISTING tests — never delete or replace a passing test to make room for new ones; add alongside it.
- Avoid cleanup, renaming, abstraction, type hints, docstrings, and extra validation outside the fix.
- Add only regression proof relevant to task.

## Scope-creep traps (each one has burned real patches)

| Trap | Tell |
| --- | --- |
| "Make it production-ready" | You are inventing requirements. Ship the named behavior. |
| Input hardening the bug report never mentioned | Only add if the fix itself is incorrect without it |
| Rewriting a file instead of editing lines | Almost always smuggling in style changes |
| Deleting/replacing existing tests | A regression: old tests must still pass unchanged |
| "While I'm in here" improvements | Note them in "Not done on purpose" instead |

## Required report section: "Not done on purpose"

Every patch report lists what you noticed, judged out of scope, and left — with one line on why. This is how the requester sees the boundaries you drew and decides follow-ups. Missing section = the boundary is invisible = scope creep is unverifiable.

Run focused proof plus nearest affected gate, AND the pre-existing tests for touched files. Stop when failure is fixed and regression proof passes.

## Success Signal

The diff contains only the fix + its regression test; every pre-existing test still exists and passes unmodified; the report's "Not done on purpose" section names at least the tempting adjacent changes that were skipped.
