# feature: App environment variables for handlers

- Add optional `env` dict to `App` that sets `os.environ` vars before each handler runs
- Convert values to `str()` at set time; propagate conversion failures as exceptions
- Restore original environment after handler completes or fails

## Solution Design

### External Interface Change

All channels benefit automatically — `App(env=...)` is set once at construction, applies to every handler invocation regardless of channel.

```python
# CLI usage
app = App(env={"API_KEY": "sk-123", "TIMEOUT": 30})

@app.handler
def call_api(runner, state):
    # os.environ["API_KEY"] == "sk-123"
    # os.environ["TIMEOUT"] == "30"  (converted from int)
    result = subprocess.run(["curl", ...], capture_output=True)
    return {**state, "result": result.stdout}
```

```python
# Server/Slack — same App, env vars active for every workflow run
app = App(env={"SERVICE_URL": "https://api.example.com"})
```

### Architectural Schema Changes

```yaml
types:
  App:
    kind: class
    fields:
      - handlers: dict[str, Callable]
      - log_dir: str
      - worktree_dir: str
      - state_dir: str
      - env: dict[str, Any] | None  # New field

functions:
  _app_env:
    kind: contextmanager
    location: antkeeper.core.app  # Module-level, consistent with git_worktree pattern
    args:
      - env: dict[str, Any] | None
    behavior: |
      No-op if env is None or empty dict.
      Otherwise: save originals, convert values to str(), set on os.environ, yield, restore in finally.
      Keys absent from os.environ before are deleted on restore (via pop).
```

## Relevant Files

- `src/antkeeper/core/app.py` — `App.__init__` gets `env` param; new `_app_env` context manager added at module level
- `src/antkeeper/core/runner.py` — `Runner.run()` wraps the handler call with `_app_env(self.app.env)`
- `tests/core/test_app.py` — Constructor tests for `env` parameter
- `tests/core/test_workflows.py` — Execution tests for env var setting, restoration, conversion, and error handling

## Workflow

### Step 1: Add `_app_env` context manager to `app.py`

- Add `import os` and `from contextlib import contextmanager` to `src/antkeeper/core/app.py`
- Add module-level `_app_env` function after imports, before the `App` class:
  - If `env` is `None` or empty dict: `yield` immediately (no-op)
  - Otherwise: save `{k: os.environ.get(k) for k in env}`, then `str(value)` each value and set on `os.environ`
  - If `str()` raises, let it propagate (no try/except around conversion)
  - In `finally`: for each key, if saved value was `None`, `os.environ.pop(k, None)`; otherwise restore original value

### Step 2: Add `env` parameter to `App.__init__`

- Add `env: dict[str, Any] | None = None` parameter to `App.__init__` — placed after `state_dir` and before `handlers` to match the existing config-before-overrides ordering
- Store as `self.env = env`
- Update the docstring Args block to document the new parameter

### Step 3: Wrap handler call in `Runner.run()`

- In `src/antkeeper/core/runner.py`, import `_app_env` from `antkeeper.core.app`
- In `Runner.run()`, wrap the handler invocation (currently `state = self.workflow(self, state)` at line 107) with `with _app_env(self.app.env):`
- Do NOT wrap calls in `run_workflow()` — the env is set for the entire handler execution via `Runner.run()`, and `run_workflow()` is always called from within a handler

### Step 4: Add tests

- Add constructor tests to `tests/core/test_app.py`
- Add execution tests to `tests/core/test_workflows.py` in a new `TestAppEnvironment` class

### Step 5: Run validation commands

## Testing Strategy

### Unit Tests

In `tests/core/test_app.py`:
- `test_app_constructor_stores_env` — `App(env={"FOO": "bar"})` stores the dict on `app.env`
- `test_app_constructor_default_env_is_none` — `App()` has `app.env is None`

In `tests/core/test_workflows.py` (new `TestAppEnvironment` class):
- `test_handler_sees_env_vars` — Handler reads `os.environ["TEST_VAR"]` and puts it in state; verify value is correct
- `test_env_values_converted_to_string` — Pass `env={"NUM": 42}`, handler reads `os.environ["NUM"]` and verifies it equals `"42"`
- `test_env_restored_after_successful_handler` — After `runner.run()`, env var is no longer in `os.environ`
- `test_env_restored_after_failed_handler` — Handler raises; after catching, env var is no longer in `os.environ`
- `test_existing_env_var_preserved` — Pre-set an env var, override via `App(env=...)`, verify handler sees new value, verify original restored after run
- `test_none_env_is_noop` — `App(env=None)`, handler runs normally, no env side effects
- `test_empty_env_dict_is_noop` — `App(env={})`, handler runs normally
- `test_invalid_env_value_propagates` — Object with `__str__` that raises; verify exception propagates and env is cleaned up
- `test_run_workflow_steps_see_env_vars` — Steps within `run_workflow()` can access env vars set at `Runner.run()` level
- `test_env_restored_after_run_workflow_step_failure` — Step in `run_workflow()` raises; env vars still cleaned up

### Edge Cases

- Value is `None` (converted to string `"None"` — valid, `str(None)` succeeds)
- Value is `0`, `False`, empty string (all valid `str()` conversions)
- Key already exists in `os.environ` with different value (save and restore)
- Key does not exist in `os.environ` before (delete on restore, not set to `None`)
- Handler raises exception (env must still be restored via `finally`)
- `str()` raises on conversion (partial env set must be cleaned up in `finally`)

## Acceptance Criteria

- `App(env={"KEY": value})` stores the dict and makes env vars available to handlers via `os.environ`
- Non-string values are converted via `str()` before setting
- Env vars are restored to their original state after handler completes (success or failure)
- Keys not present in `os.environ` before are removed after handler completes
- `App()` and `App(env=None)` and `App(env={})` behave identically — no env manipulation
- If `str(value)` raises, the exception propagates and any partially-set env vars are cleaned up
- All existing tests continue to pass
- `run_workflow()` is NOT modified — env vars flow through from `Runner.run()`

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run -m pytest tests/ -v
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- Thread-safety: `os.environ` is process-global. Concurrent `Runner` instances in the same process would conflict. This is acceptable for the current single-threaded execution model and is not addressed in this feature.
- The `_app_env` context manager is private (prefixed with `_`). It is not exported from `__init__.py` and is an implementation detail.
- The context manager pattern follows the existing codebase precedent set by `git_worktree` in `src/antkeeper/git/worktrees.py`.

## Report

Report files changed, tests added, and validation results. Include:
- Number of files modified
- Number of new tests added
- Results of ruff, ty, and pytest runs
- Confirmation that env vars are correctly set during handler execution and restored afterward
