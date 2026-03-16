# fix: fix-gh-issues delegates to run instead of duplicating it

- Eliminate duplicated argparse flags by using a shared parent parser for `run` and `fix-gh-issues`.
- Extract `_build_common_state` helper so both branches share state-building logic before calling `_run_workflow_cli`.
- Pure refactor — no behavioral changes to CLI invocations.

## Solution Design

### External Interface Change

No external interface changes. All existing CLI invocations produce identical results:

```bash
# These continue to work exactly as before
antkeeper fix-gh-issues sdlc 26 30
antkeeper fix-gh-issues --model opus --agents-file handlers.py specify 42 99
antkeeper run --model sonnet specify prompts/describe.md
```

## Relevant Files

Use these files to fix the bug:

- `src/antkeeper/cli.py` — contains the duplicated subparser flags (lines 258-270), the parallel execution branches (lines 289-327), and the shared `_run_workflow_cli` helper. All changes happen here.
- `tests/test_cli.py` — contains `TestArgParsing._build_parser()` and `TestFixGhIssuesArgParsing._build_parser()` which mirror the production parser structure and need updating to use the parent parser pattern.

## Workflow

### Step 1: Extract `_build_common_state` helper in `cli.py`

- Add a new private function `_build_common_state(args) -> dict` near `_run_workflow_cli`:
  - Calls `parse_state_pairs(args.initial_state)`
  - Conditionally sets `state["model"]` only when `args.model is not None` (preserve the existing guard)
  - Returns the state dict
- Refactor the `run` branch (lines 289-305) to call `_build_common_state(args)` instead of inline `parse_state_pairs` + model merge
- Refactor the `fix-gh-issues` branch (lines 307-327) to call `_build_common_state(args)` instead of inline `parse_state_pairs` + model merge

### Step 2: Share argparse flags via parent parser in `cli.py`

- Create `common_run_parent = argparse.ArgumentParser(add_help=False)` inside `main()` with the shared flags:
  - `--agents-file` (default `handlers.py`)
  - `--initial-state` (action `append`, default `[]`)
  - `--model` (default `None`)
  - `workflow_name` (positional)
- Change `run_parser` to `subparsers.add_parser("run", parents=[common_run_parent])` and only add `prompt_files` (nargs `*`)
- Change `fix_gh_issues_parser` to `subparsers.add_parser("fix-gh-issues", parents=[common_run_parent])` and only add `issue_numbers` (nargs `+`, type `int`)
- Remove the 5 duplicated `add_argument` calls from the `fix-gh-issues` subparser

### Step 3: Update test parser builders in `test_cli.py`

- Update `TestArgParsing._build_parser()` to use the parent parser pattern mirroring the new production code
- Update `TestFixGhIssuesArgParsing._build_parser()` to use the parent parser pattern mirroring the new production code
- All existing test assertions remain unchanged — only the parser construction changes

### Step 4: Validate

- Run validation commands below

## Testing Strategy

### Unit Tests

No new unit tests needed. The `_build_common_state` helper is a 4-line private function wrapping `parse_state_pairs` (already tested in `TestParseStatePairs`) plus a conditional model merge. Existing integration tests in `TestCliIntegration` and `TestFixGhIssuesIntegration` exercise both code paths end-to-end.

### Integration

No new integration tests needed. All 6 tests in `TestFixGhIssuesIntegration` and 7 tests in `TestCliIntegration` call `main()` end-to-end and verify identical behavior.

### Edge Cases

- `action="append"` with `default=[]` on the parent parser: safe because each `parse_args()` call creates a fresh default list. The parent is only used as a `parents=` source (signalled by `add_help=False`), never parsed directly.
- Argument ordering in `--help` output may change cosmetically (inherited args appear before subparser-specific ones). This is acceptable.
- `args.model is not None` guard in `_build_common_state` must be preserved to avoid injecting `"model": None` into state when `--model` is not passed.

## Acceptance Criteria

- `antkeeper fix-gh-issues <workflow> <issue_number>` continues to fetch the issue via `gh` and run the workflow with a prompt containing the issue JSON
- `fix-gh-issues` subparser no longer duplicates `run`'s flag definitions — both inherit from a shared parent
- State-building logic (`parse_state_pairs` + model merge) appears once in `_build_common_state`, not twice
- `--model`, `--agents-file`, `--initial-state` flags work identically for both `run` and `fix-gh-issues`
- All existing tests pass without behavioral changes
- No changes to core framework modules

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run -m pytest tests/ -v
uv run antkeeper fix-gh-issues --help
uv run antkeeper run --help
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The `common_run_parent` is constructed inside `main()`, not at module level. This is consistent with the existing pattern where all parser setup lives in `main()`. Tests mirror this by building their own parsers in `_build_parser()` methods.
- `_build_common_state` is deliberately minimal — it only extracts the exact duplicated lines. No additional logic is added.
- The `fix-gh-issues` branch retains its own error handling for `gh` CLI failures (`FileNotFoundError`, `CalledProcessError`, `JSONDecodeError`). This is correct — these are CLI-layer concerns that belong in the command branch, not in a shared helper.

## Report

Files changed: `src/antkeeper/cli.py`, `tests/test_cli.py`. Tests modified: `TestArgParsing._build_parser()` and `TestFixGhIssuesArgParsing._build_parser()` updated to use parent parser pattern. No new tests added. Validations: ruff lint, ty typecheck, pytest, CLI help output for both `run` and `fix-gh-issues`.
