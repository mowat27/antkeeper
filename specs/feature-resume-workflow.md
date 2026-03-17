# feature: Resume a workflow from where it left off

- `antkeeper resume <run_id>` loads persisted state, skips completed steps, and continues from the next one.
- Fails with clear stderr messages when run_id not found, workflow already completed, or no progress to resume.
- Handlers require zero changes; resume is transparent via a `_resume_skip` state key consumed by `run_workflow`.

## Solution Design

### External Interface Change

**CLI** gains a new `resume` subcommand:

```
antkeeper resume [--agents-file PATH] <run_id>
```

- `run_id` (positional, required): the 8-char hex identifier from a previous run.
- `--agents-file` (optional, default `handlers.py`): same as `run` subcommand.

The command loads the persisted state file for the given `run_id`, validates it is resumable, injects `_resume_skip` into the state, and executes the workflow. The resumed execution gets a **new** `run_id` (it is a new Runner instance). Handlers call `run_workflow` as usual — no handler changes needed.

**API / Slack**: No changes in this iteration. Future channels can adopt the same pattern (load state, set `_resume_skip`, run).

### Architectural Schema Changes

```yaml
functions:
  run_workflow:
    module: antkeeper.core.app
    params:
      runner: Runner
      state: State
      steps: "list[Callable[[Runner, State], State]]"
      skip: "int = 0"  # NEW — number of steps to skip
    returns: State
    notes: >
      When skip > 0, skips the first `skip` steps and initialises
      _progress.completed to `skip`. Also checks for _resume_skip
      in state (set by CLI resume) and uses it as the skip value
      if skip param is 0. The _resume_skip key is stripped from
      state before execution.

  _load_state_by_run_id:
    module: antkeeper.cli
    params:
      state_dir: str
      run_id: str
    returns: "tuple[dict, str]"  # (state dict, file path)
    raises:
      - FileNotFoundError
    notes: >
      Private helper in cli.py. Uses glob to match
      *-{run_id}.json in state_dir.

types:
  State:
    reserved_keys:
      _resume_skip: "int | absent"  # NEW — consumed by run_workflow, never persisted
```

### REST Changes

None.

### Database Changes

None.

## Relevant Files

- `src/antkeeper/core/app.py` — `run_workflow` gets `skip` param and `_resume_skip` consumption logic.
- `src/antkeeper/cli.py` — new `resume` subcommand, `_load_state_by_run_id` helper, CLI validation.
- `src/antkeeper/core/domain.py` — update `State` docstring to document `_resume_skip` as a reserved key.
- `tests/core/test_workflows.py` — tests for `run_workflow` skip behaviour.
- `tests/test_cli.py` — tests for resume arg parsing and integration.

### New Files

- `tests/core/test_resume.py` — dedicated tests for resume-specific behaviour (state loading, skip consumption, error paths).

## Workflow

### Step 1: Add `skip` parameter to `run_workflow`

- In `src/antkeeper/core/app.py`, add `skip: int = 0` parameter to `run_workflow`.
- When `skip == 0`, check `state.get("_resume_skip")`. If present and > 0, use it as the skip value.
- Strip `_resume_skip` from state before proceeding (construct new dict without it).
- Change `_progress` initialisation from `"completed": 0` to `"completed": skip`.
- Change the step iteration from `for step in steps:` to `for step in steps[skip:]`.
- Log the skip count when > 0: `runner.logger.info(f"Resuming: skipping {skip} completed steps")`.

### Step 2: Add `_load_state_by_run_id` helper to CLI

- In `src/antkeeper/cli.py`, add a module-level helper function `_load_state_by_run_id(state_dir: str, run_id: str) -> tuple[dict, str]`.
- Use `glob.glob(os.path.join(state_dir, f"*-{run_id}.json"))` to find the state file by filename pattern.
- If no match, raise `FileNotFoundError(f"No state file found for run_id: {run_id}")`.
- If match found, read and parse JSON, return `(state_dict, file_path)`.

### Step 3: Add `resume` subcommand to CLI

- In `src/antkeeper/cli.py`, in `main()`:
  - Add a `resume` subparser with `--agents-file` (default `handlers.py`) and positional `run_id`.
  - In the `resume` command handler:
    1. Load the app from `args.agents_file` (reuse existing error handling pattern from `_run_workflow_cli`).
    2. Call `_load_state_by_run_id(app.state_dir, args.run_id)`. Catch `FileNotFoundError` → print `f"Error: no state found for run_id: {args.run_id}"` to stderr, exit 1.
    3. Validate `workflow_name` exists in loaded state. If missing → print to stderr, exit 1.
    4. Validate `_progress` exists in loaded state. If missing → print `"Error: cannot resume: workflow has no progress to resume from"` to stderr, exit 1.
    5. Validate `_progress["completed"] < _progress["total"]`. If not → print `f"Error: cannot resume: workflow already completed ({completed}/{total} steps)"` to stderr, exit 1.
    6. Set `state["_resume_skip"] = state["_progress"]["completed"]`.
    7. Create `CliChannel(workflow_name=state["workflow_name"], initial_state=state)`.
    8. Create `Runner(app, channel)` — new run_id, new state file, new log file.
    9. Call `runner.run()`. Catch `WorkflowFailedError` → print to stderr, exit 1.
    10. Print result to stdout.

### Step 4: Update `State` docstring

- In `src/antkeeper/core/domain.py`, add `_resume_skip` to the framework-reserved keys documentation for `State`.

### Step 5: Write tests

- See Testing Strategy below.

### Step 6: Validate

- Run all validation commands below.

## Testing Strategy

### Unit Tests

**`tests/core/test_workflows.py`** — new `TestWorkflowSkip` class:

- `test_run_workflow_skip_skips_first_n_steps`: 3 steps that each append their name to a list in state. `run_workflow(..., skip=2)` → only third step name in list. `_progress == {"total": 3, "completed": 3}`.
- `test_run_workflow_skip_zero_runs_all`: `skip=0` runs all steps. Same as default.
- `test_run_workflow_skip_preserves_progress_start`: Capturing step verifies `_progress["completed"]` starts at `skip` value, not 0.
- `test_run_workflow_resume_skip_in_state_auto_skips`: State has `_resume_skip: 1`. Call `run_workflow(runner, state, [step_a, step_b])` with no explicit `skip`. Only `step_b` executes. `_resume_skip` is NOT in final state.
- `test_run_workflow_resume_skip_consumed_after_first_call`: State has `_resume_skip: 1`. Call `run_workflow` twice sequentially. First call skips 1. Second call starts from 0 (because `_resume_skip` was consumed).
- `test_run_workflow_explicit_skip_overrides_resume_skip`: `skip=2` takes precedence even if `_resume_skip` is in state.

**`tests/core/test_resume.py`** — new file:

- `test_load_state_by_run_id_finds_matching_file`: Write a state file `20260316-abcd1234.json` to a temp dir. Call `_load_state_by_run_id(dir, "abcd1234")`. Returns correct state and path.
- `test_load_state_by_run_id_not_found`: Empty dir → `FileNotFoundError`.
- `test_load_state_by_run_id_multiple_files`: Multiple state files, finds correct one.

**`tests/test_cli.py`** — new `TestResumeArgParsing` class:

- `test_parse_resume_with_run_id`: Parse `["resume", "abcd1234"]` → `args.run_id == "abcd1234"`, `args.command == "resume"`.
- `test_parse_resume_missing_run_id_exits`: Parse `["resume"]` → `SystemExit`.
- `test_parse_resume_with_agents_file`: Parse `["resume", "--agents-file", "custom.py", "abcd1234"]` → `args.agents_file == "custom.py"`.

### Integration

**`tests/test_cli.py`** — new `TestResumeIntegration` class:

- `test_resume_loads_state_and_runs`: Write a temp agents file with a 2-step workflow handler. Write a state file with `_progress: {"total": 2, "completed": 1}`. Invoke `main()` with `["antkeeper", "resume", "--agents-file", path, run_id]`. Assert only second step executed.
- `test_resume_run_id_not_found_exits`: No matching state file. Assert `SystemExit(1)`, stderr has error.
- `test_resume_already_completed_exits`: State with `completed == total`. Assert `SystemExit(1)`, stderr has "already completed".
- `test_resume_no_progress_exits`: State without `_progress`. Assert `SystemExit(1)`, stderr has error.
- `test_resume_no_workflow_name_exits`: State without `workflow_name`. Assert `SystemExit(1)`, stderr has error.

### Edge Cases

- `run_id` not found in state dir → `FileNotFoundError` → stderr + exit 1.
- Workflow already completed (`completed >= total`) → stderr + exit 1.
- No `_progress` in state (single handler, not composite) → stderr + exit 1.
- No `workflow_name` in state file → stderr + exit 1.
- 0 completed steps → `_resume_skip=0` → `run_workflow` runs all steps (effectively a restart).
- `_resume_skip` is stripped from state and never persisted — does not leak into handler logic.

## Acceptance Criteria

- `antkeeper resume <run_id>` successfully resumes a partially-completed workflow, executing only the remaining steps.
- All failure cases (run_id not found, no progress, already completed, no workflow_name) print clear messages to stderr and exit 1.
- Existing `antkeeper run` behaviour is unchanged — `skip=0` default, no `_resume_skip` in state.
- Existing tests pass with zero regressions.
- `_resume_skip` key never appears in persisted state files.
- Handlers do not need modification to support resume.

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run pytest tests/ -v
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The resumed execution creates a **new run_id** and new state/log files. The original state file is not modified. This means resuming the same `run_id` multiple times is possible (each creates a new execution).
- `_resume_skip` is a framework-reserved key (prefixed with `_`) that acts as a one-shot signal from the CLI to `run_workflow`. It is consumed on first use and stripped from state, so sequential `run_workflow` calls in the same handler are unaffected.
- API and Slack resume can be added later by following the same pattern: load state → validate → set `_resume_skip` → run.
- The `_load_state_by_run_id` helper is private to `cli.py`. If API resume is added later, extract it to a shared module at that point.

## Report

Files changed: `src/antkeeper/core/app.py`, `src/antkeeper/cli.py`, `src/antkeeper/core/domain.py`. Tests added: `tests/core/test_resume.py` (new), `tests/core/test_workflows.py` (new class), `tests/test_cli.py` (new classes). Validations: ruff, ty, pytest.
