# bugfix: Persist _progress before first workflow step

- `run_workflow()` initializes `_progress` but never persists it until after the first step completes.
- External consumers reading state between workflow start and first step completion see no `_progress`.
- Add a single `_persist_state` call after `_progress` initialization, before the step loop.

## Solution Design

### Architectural Schema Changes

No interface changes. The fix adds one internal call to an existing private method.

## Relevant Files

- `src/antkeeper/core/app.py` — contains `run_workflow()` where `_progress` is initialized (line 181) but not persisted until inside the loop (line 188). The fix goes here.
- `tests/core/test_workflows.py` — contains `TestWorkflowProgress` class. The new test goes here.

## Workflow

### Step 1: Fix `run_workflow` persistence gap

- In `src/antkeeper/core/app.py`, add `runner._persist_state(state)` immediately after line 181 (the `_progress` initialization) and before the `for step in steps:` loop.
- The change is:
  ```python
  state = {**state, "_progress": {"total": len(steps), "completed": 0}}
  runner._persist_state(state)
  for step in steps:
  ```

### Step 2: Add regression test

- In `tests/core/test_workflows.py`, add `test_initial_progress_persisted_before_first_step` to the `TestWorkflowProgress` class.
- The test registers a handler that calls `run_workflow` with one step. That step reads `runner._state_path` from disk and asserts `_progress == {"total": 1, "completed": 0}`.
- Add `import json` at the top of the file if not already present.

### Step 3: Run validation commands

- Run all validation commands to confirm zero errors and zero regressions.

## Testing Strategy

### Unit Tests

- **`test_initial_progress_persisted_before_first_step`**: Register a handler calling `run_workflow` with a single step. The step reads the state file from disk via `runner._state_path` and captures the persisted `_progress`. Assert `_progress == {"total": 1, "completed": 0}`. This test fails without the fix and passes with it.

### Edge Cases

- **Empty steps list**: `run_workflow(runner, state, [])` — the initial `_progress` with `total: 0, completed: 0` is persisted. No loop runs. Existing `Runner.run()` post-handler persist (line 129) writes the final state. This works correctly with the fix.
- **Single step**: Covered by the new test above.
- **Multi-step**: Already covered by existing `test_run_workflow_progress_increments_per_step`.

## Acceptance Criteria

- `_progress` with `completed: 0` is on disk before the first step executes.
- All existing tests continue to pass with no regressions.
- No new public API surface introduced.

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run -m pytest tests/ -v
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The fix follows the existing persist-after-mutate pattern used at `runner.py:114`, `runner.py:129`, and `app.py:188`.
- No new dependencies or abstractions introduced.

## Report

Files changed: `src/antkeeper/core/app.py` (1 line added). Tests added: 1 (`test_initial_progress_persisted_before_first_step`). Validation: ruff, ty, pytest.
