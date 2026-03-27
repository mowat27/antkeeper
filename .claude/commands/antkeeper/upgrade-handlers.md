---
description: Check handler files for pre-streaming API usage and upgrade them to use collect_result(run_prompt(...)).
argument-hint: [path/to/handlers.py ...]
allowed-tools: Bash(ruff *), Edit, Read, Glob, Grep
---

# Purpose

Upgrade handler files from the old `run_prompt() -> str` API to the streaming `collect_result(run_prompt(...))` pattern.

## Variables

* ARGUMENTS: $ARGUMENTS

Parse from ARGUMENTS:

* **HANDLER_FILES** — One or more file paths to check. If empty, default to `handlers.py` in the project root.

## Instructions

* Only upgrade hand-written handlers that call `run_prompt(...)` and assign the result to a variable as a string (the old API).
* The upgrade strategy is mechanical: wrap `run_prompt(...)` with `collect_result(...)` and destructure the return value as `(text, _events)`.
* Do NOT convert any handler to stream events directly (no `for event in ...` loops). Maintain exact parity with the previous blocking behaviour.
* Do NOT touch `cc_handler(...)` factory calls — they already handle streaming internally.
* Do NOT modify `runner.report_progress()` or `runner.report_error()` calls — these still work unchanged.
* After editing, run `ruff check --fix` on each modified file.

## Workflow

1. Resolve HANDLER_FILES. If none provided, glob for `handlers.py` in the project root.
2. For each file, read it and identify call sites that match the old pattern:
   - Direct assignment: `result = run_prompt(...)` where `result` is used as a `str`
   - Any bare `run_prompt(...)` call whose return value is consumed as a string
3. For each identified call site, apply the upgrade:
   - Change `response = run_prompt(...)` to `response, _events = collect_result(run_prompt(...))`
   - If the variable name differs, preserve it: `text, _events = collect_result(run_prompt(...))`
   - If the result is unused (fire-and-forget), wrap as `_result, _events = collect_result(run_prompt(...))`
4. Fix imports in each modified file:
   - Ensure `collect_result` is imported from `antkeeper.llm.claude_code` alongside `run_prompt`
   - If the file already imports `collect_result`, do not duplicate
5. Run `ruff check --fix` on each modified file.
6. Report results.

## Report

For each file checked, report:

* **File path**
* **Status**: `upgraded` (with count of call sites changed), `already current` (no changes needed), or `skipped` (no `run_prompt` usage found)
* **Changes made**: list each call site upgraded (line number and before/after)
