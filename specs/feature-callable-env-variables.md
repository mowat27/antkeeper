# feature: Callable values for App log_dir and env

- Allow `App(log_dir=...)` and `App(env={...})` values to be callables that receive the `runner` and return the resolved value.
- Callables are evaluated per handler invocation, enabling dynamic configuration based on runtime context (run_id, workflow_name, etc.).
- Static values continue to work unchanged — fully backward compatible.

## Solution Design

### External Interface Change

After this change, handler files can pass functions wherever they currently pass static values for `log_dir` and `env` dict values:

```python
from antkeeper.core.app import App

# Dynamic log directory based on run ID
app = App(log_dir=lambda runner: f"logs/{runner.workflow_name}/{runner.id}")

# Mixed static and dynamic env vars
app = App(env={
    "STATIC_KEY": "always-this",
    "RUN_ID": lambda runner: runner.id,
    "LOG_PATH": lambda runner: f"logs/{runner.id}.log",
})
```

All channels (CLI, API, Slack) benefit automatically — the resolution happens in the `Runner`, which is shared across all channels.

### Architectural Schema Changes

```yaml
types:
    App:
      kind: class
      fields:
        - log_dir: str | Callable[[Runner], str]  # Now accepts callable
        - worktree_dir: str
        - state_dir: str
        - env: dict[str, Any | Callable[[Runner], Any]] | None  # Values now accept callable
        - handlers: dict[str, Callable]
```

## Relevant Files

- `src/antkeeper/core/runner.py` — Where `log_dir` is consumed in `__init__` (line 70) and `env` is passed to `_app_env()` in `run()` (line 110). Both resolution changes happen here.
- `src/antkeeper/core/app.py` — `App.__init__` type hints and docstrings need updating to document callable support. No functional changes. `_app_env()` is unchanged.
- `tests/core/test_workflows.py` — Contains `TestAppEnvironment` class and helper functions (`_make_env_app`, `_run_handler`, `_SimpleChannel`). New callable tests go here following the same patterns.

## Workflow

### Step 1: Add callable resolution to Runner

- In `Runner.__init__` (runner.py, around line 70): Before using `app.log_dir` for `os.makedirs` and path construction, resolve it:
  ```python
  log_dir = app.log_dir(self) if callable(app.log_dir) else app.log_dir
  ```
  Use the resolved `log_dir` local variable for `os.makedirs` and `os.path.join` calls (lines 70-72).

- In `Runner.run()` (runner.py, line 110): Before passing `app.env` to `_app_env()`, build a resolved copy:
  ```python
  resolved_env = (
      {k: (v(self) if callable(v) else v) for k, v in self.app.env.items()}
      if self.app.env
      else self.app.env
  )
  with _app_env(resolved_env):
  ```

### Step 2: Update App type hints and docstrings

- In `App.__init__` (app.py, line 84): Update the `log_dir` parameter type hint from `str` to `str | Callable[[Runner], str]`.
- Update the `env` parameter docstring to note that values can be callables accepting `(runner)` and returning the value.
- No functional changes to `App` or `_app_env`.

### Step 3: Add tests for callable env values

- Add new test cases to the `TestAppEnvironment` class in `tests/core/test_workflows.py` using the existing `_make_env_app`, `_run_handler`, and `_SimpleChannel` helpers.

### Step 4: Add tests for callable log_dir

- Add a new `TestCallableLogDir` class in `tests/core/test_workflows.py` using the same helpers.

### Step 5: Run validation commands

- Run all validation commands and fix any issues until zero errors, zero warnings.

## Testing Strategy

### Unit Tests

**Callable log_dir:**

1. `test_callable_log_dir_resolves_with_runner` — `App(log_dir=lambda runner: f"/tmp/{runner.id}")`. Verify log files are written to the path returned by the callable.
2. `test_static_log_dir_still_works` — `App(log_dir="/tmp/static")`. Confirm no regression from adding callable support. (Covered by existing tests but worth an explicit assertion in the new test class.)

**Callable env values:**

3. `test_callable_env_value_resolved_before_handler` — `App(env={KEY: lambda runner: "computed"})`. Handler reads `os.environ[KEY]` and asserts `"computed"`.
4. `test_mixed_callable_and_static_env` — `App(env={A: "static", B: lambda runner: "dynamic"})`. Handler verifies both values.
5. `test_callable_env_receives_runner_properties` — `App(env={KEY: lambda runner: runner.id})`. Handler verifies value equals `runner.id`.
6. `test_callable_env_restored_after_run` — Verify callable-resolved env var is absent from `os.environ` after handler completes.

### Edge Cases

- `test_callable_env_that_raises_propagates` — Callable raises `ValueError`. Assert it propagates and env is cleaned up.
- `test_callable_log_dir_that_raises_propagates` — Callable raises `RuntimeError`. Assert `Runner.__init__` raises.
- `test_env_with_no_callables_unchanged` — Plain dict with no callables works identically to current behavior.

## Acceptance Criteria

- `App(log_dir=<callable>)` evaluates the callable with `runner` and uses the returned string for log directory and file paths.
- `App(env={key: <callable>})` evaluates callable values with `runner` before setting env vars for handler execution.
- Static values for both `log_dir` and `env` continue to work identically to current behavior.
- Callables receive only the `runner` argument (not state).
- Errors from callables propagate naturally without special handling.
- Env var save/restore lifecycle applies equally to resolved callable values.
- All existing tests continue to pass without modification.

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run -m pytest tests/ -v
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The timing asymmetry between `log_dir` (resolved in `__init__`) and `env` (resolved in `run()`) is intentional: `log_dir` is infrastructure needed before the handler runs, while `env` is execution context that only matters inside the handler.
- At `log_dir` resolution time, `self.id` and `self.channel` (including `workflow_name`) are available on the runner, but state is not yet built. This is by design — `log_dir` is needed before the workflow starts.
- `callable("foo")` returns `False` in Python, so static strings pass through the check safely.
- No changes to `_app_env()` — it continues to receive a plain resolved dict.
- No new classes, protocols, or abstractions are introduced.

## Report

Report: files changed, tests added, validations passed. Include the resolved paths used during testing to confirm dynamic resolution worked correctly.
