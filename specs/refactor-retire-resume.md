# refactor: Remove resume capability from antkeeper

- Remove `skip` param, `_progress` and `_resume_skip` state keys — simplify `run_workflow` to a clean state-threading fold
- Delete `antkeeper resume` CLI command and all supporting code — users restart workflows from scratch
- BREAKING CHANGE: ignore backwards compatibility; delete all resume-related tests, docs, and references

## Solution Design

### Architectural Schema Changes

```yaml
functions:
  run_workflow:
    removed_params:
      - skip: int  # deleted entirely
    removed_state_keys:
      - _progress: dict  # no longer injected into state
      - _resume_skip: int  # no longer consumed from state
    behaviour: "Simple fold — iterate steps, call each with state, persist after each, return final state"

cli_commands:
  resume:
    status: deleted  # entire command removed

helpers:
  _load_state_by_run_id:
    status: deleted  # only used by resume command
```

## Relevant Files

- `src/antkeeper/core/app.py` — contains `run_workflow` with skip/progress logic to simplify
- `src/antkeeper/cli.py` — contains `resume` command, `_load_state_by_run_id`, and imports to remove
- `src/antkeeper/core/domain.py` — `State` docstring documents `_progress` and `_resume_skip`
- `src/antkeeper/__init__.py` — top-level docstring references "and resume support"
- `src/antkeeper/core/__init__.py` — docstring documents `_progress` key
- `src/antkeeper/core/runner.py` — docstrings reference `_progress` written during step sequencing
- `tests/core/test_resume.py` — entire file to delete
- `tests/core/test_workflows.py` — `TestWorkflowSkip` and `TestWorkflowProgress` classes to delete
- `tests/test_cli.py` — `TestResumeCommand` class and `test_resume_verbose_flag_accepted` to delete
- `README.md` — resume references in feature description and quickstart
- `app_docs/reference.md` — `antkeeper resume` CLI section and `run_workflow` skip/resume description
- `app_docs/instrumentation.md` — "Workflow Resume" section and `_progress` persistence description
- `app_docs/testing_policy.md` — resume testing patterns and class references
- `app_docs/README.md` — instrumentation summary references resume mechanics

## Workflow

### Step 1: Simplify `run_workflow` in `src/antkeeper/core/app.py`

- Replace the entire `run_workflow` function body with a simple fold:
  ```python
  def run_workflow(runner: Runner, state: State, steps: list[Handler]) -> State:
      """Execute a sequence of workflow steps with state threading."""
      tracer = trace.get_tracer("antkeeper")
      runner.logger.info(f"run_workflow started with {len(steps)} steps: {[s.__name__ for s in steps]}")
      for i, step in enumerate(steps):
          step_name = step.__name__
          runner.logger.info(f"Executing step: {step_name}")
          with tracer.start_as_current_span(
              "antkeeper.workflow.step",
              attributes={
                  "run_id": state.get("run_id", ""),
                  "workflow_name": state.get("workflow_name", ""),
                  "step_name": step_name,
                  "step_index": i,
                  "step_total": len(steps),
              },
          ):
              state = step(runner, state)
          runner._persist_state(state)
          runner.logger.debug(f"Step completed: {step_name}, state keys: {list(state.keys())}")
      runner.logger.info("run_workflow completed")
      return state
  ```
- Remove `skip` parameter from signature
- Remove `_resume_skip` consumption logic
- Remove `_progress` dict injection and update
- Remove the initial `_persist_state` call that existed only for progress tracking (the `Runner.run()` method already persists initial state before calling the handler)

### Step 2: Remove resume from CLI in `src/antkeeper/cli.py`

- Delete `import glob as globmod` (only used by `_load_state_by_run_id`)
- Delete `import json` (only used by `_load_state_by_run_id`)
- Delete the `_load_state_by_run_id` helper function
- Delete the `resume` CLI command (entire `@cli.command()` block)

### Step 3: Clean up domain and docstrings

- `src/antkeeper/core/domain.py` — remove `_progress` and `_resume_skip` entries from `State` docstring
- `src/antkeeper/__init__.py` — remove "and resume support" from top-level docstring
- `src/antkeeper/core/__init__.py` — remove `_progress` documentation from docstring
- `src/antkeeper/core/runner.py` — remove docstring references to `_progress` (references at the `_persist_state` call documentation and `run_workflow` integration docs)
- NOTE: `report_progress` on `Runner` is a separate concept (channel reporting) and must NOT be touched

### Step 4: Delete resume tests

- Delete `tests/core/test_resume.py` entirely
- Delete `TestWorkflowSkip` class from `tests/core/test_workflows.py`
- Delete `TestWorkflowProgress` class from `tests/core/test_workflows.py`
- Clean up module docstring in `tests/core/test_workflows.py` if it references progress/skip/resume
- Delete `TestResumeCommand` class from `tests/test_cli.py`
- Delete `test_resume_verbose_flag_accepted` method from `TestVerboseFlag` in `tests/test_cli.py`

### Step 5: Add replacement tests in `tests/core/test_workflows.py`

- Add `test_state_persisted_after_each_step` — two-step workflow verifies `_persist_state` called after each step (replaces coverage lost from `TestWorkflowProgress`)
- Add `test_final_state_has_no_progress_or_resume_keys` — run a multi-step workflow, assert `_progress` and `_resume_skip` absent from returned state (guards against reintroduction)
- Add `test_nested_run_workflow` — outer handler calls `run_workflow` with an inner step that itself calls `run_workflow`; verify state threads correctly through both levels (this is the motivating bug — confirms it cannot recur)

### Step 6: Update documentation

- `README.md` — remove resume feature description and `antkeeper resume` quickstart example
- `app_docs/reference.md` — remove the `antkeeper resume` CLI section; update `run_workflow` description to remove skip/resume references
- `app_docs/instrumentation.md` — remove "Workflow Resume" section; update the persistence description to reflect the simplified per-step persist (remove the "before first step" progress-persist description but keep the per-step persistence description)
- `app_docs/testing_policy.md` — remove resume testing patterns, `TestResumeCommand`, `TestWorkflowSkip`, `TestWorkflowProgress` requirements
- `app_docs/README.md` — update instrumentation summary to remove resume mechanics references

### Step 7: Run validation commands

## Testing Strategy

### Unit Tests

**Delete:**
- `tests/core/test_resume.py` — 3 tests for `_load_state_by_run_id`
- `TestWorkflowSkip` — 6 tests for `skip` parameter and `_resume_skip`
- `TestWorkflowProgress` — 5 tests for `_progress` injection/tracking
- `TestResumeCommand` — 5 tests for resume CLI command
- `test_resume_verbose_flag_accepted` — 1 test for verbose on resume

**Add:**
- `test_state_persisted_after_each_step` — verify `runner._persist_state` called after each step in a multi-step workflow
- `test_final_state_has_no_progress_or_resume_keys` — assert removed keys never appear in output state
- `test_nested_run_workflow` — verify nested `run_workflow` calls thread state correctly without key conflicts

### Edge Cases

- Nested workflows: inner `run_workflow` must not corrupt outer state (the motivating bug)
- Single-step workflow: still persists after the one step
- Zero-step workflow: returns state unchanged (existing `run_workflow` behaviour — verify existing tests cover this)

## Acceptance Criteria

- `antkeeper resume` command no longer exists
- `_progress` never appears in source code outside of test files
- `_resume_skip` never appears anywhere in source
- `run_workflow` signature has no `skip` parameter
- Nested workflows execute without state key conflicts
- All existing non-resume tests continue to pass
- Three new tests cover: per-step persistence, no stale keys, nested workflows

### Validation Commands

```bash
# All tests pass
just check

# resume command is gone
uv run antkeeper resume abc123 2>&1 | grep -q "No such command"

# _progress never appears in framework source
test "$(grep -r '_progress' src/antkeeper/ | wc -l)" -eq 0

# _resume_skip never appears in source
test "$(grep -r '_resume_skip' src/ | wc -l)" -eq 0

# skip parameter is gone from run_workflow signature
grep 'def run_workflow' src/antkeeper/core/app.py | grep -v skip

# test_resume.py is deleted
test ! -f tests/core/test_resume.py

# import glob as globmod is gone from cli.py
! grep -q 'import glob' src/antkeeper/cli.py
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- `report_progress` on `Runner` is a channel-facing progress reporting method — completely separate from the `_progress` state key being removed. Do not confuse or conflate them.
- `app_docs/instrumentation.md` will need the persistence section rewritten, not just deleted — the per-step persistence behaviour is preserved, only the pre-step progress-persist is removed.
- The `Runner.run()` method already persists initial state before calling handlers, so removing the initial `_persist_state` in `run_workflow` loses no data.

## Report

Report the following on completion:

- Files changed (modified and deleted)
- Tests deleted (count and names)
- Tests added (count and names)
- Validation command results (all must pass)
- Any pre-existing issues encountered and how they were resolved
