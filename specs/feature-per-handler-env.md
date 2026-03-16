# feature: Per-handler env support for cc_handler

- Allow `cc_handler` to accept an optional `env` dict that sets environment variables for that handler's execution only.
- Handler-level env merges with App-level env using `{**app_env, **handler_env}` — handler values win.
- Reuses existing `_app_env` context manager via nested context blocks.

## Solution Design

### External Interface Change

`cc_handler` gains an optional `env` keyword argument:

```python
# Per-handler env override — sets CLAUDE_CODE_EFFORT_LEVEL=high for this handler only
implement_team = cc_handler(
    "/implement-team $spec_file",
    label="Implement spec_file using a team",
    env={"CLAUDE_CODE_EFFORT_LEVEL": "high"},
)

# Combined with model override
specify_slice = cc_handler(
    "/design-importer specify-slice $prompt",
    label="Specify design slice",
    model='sonnet',
    env={"CLAUDE_CODE_EFFORT_LEVEL": "medium"},
    state_updates=["spec_file"],
)

# No env override — behaves exactly as today
review = cc_handler("/review $spec_file", label="Review spec_file")
```

The `env` dict contains static `str` values only (no callables — matching the `model` parameter pattern). Values are active for the entire handler execution, including both `run_prompt` calls in extraction mode.

### Architectural Schema Changes

```yaml
types:
    cc_handler:
      kind: function
      parameters:
        - command: str
        - state_updates: list[str] | None  # unchanged
        - label: str | None                # unchanged
        - model: str | None                # unchanged
        - env: dict[str, str] | None       # New parameter
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/factories.py` — the `cc_handler` factory function; receives the new `env` parameter and wraps handler body in `with _app_env(env):`
- `src/antkeeper/core/app.py` — defines `_app_env` context manager (read-only, no changes needed)
- `tests/handlers/test_factories.py` — add tests for `env` parameter

## Workflow

### Step 1: Add `env` parameter to `cc_handler`

In `src/antkeeper/handlers/claude_code/factories.py`:

- Add import: `from antkeeper.core.app import _app_env`
- Add `env: dict[str, str] | None = None` parameter to `cc_handler()` signature, after `model`
- Update the module docstring to mention the `env` parameter
- Update the `cc_handler` docstring to document the `env` parameter and its merge semantics with App-level env
- Inside the inner `handler` function, wrap the existing `try/except` block (lines 119–141) in `with _app_env(env):`. The `report_progress` calls can remain outside the `with` block. The structure becomes:

```python
def handler(runner: Runner, state: State) -> State:
    runner.report_progress(f"Running {label}")
    with _app_env(env):
        try:
            # ... existing interpolation, run_prompt, extraction logic unchanged ...
        except (KeyError, AgentExecutionError, ValueError) as error:
            runner.fail(f"{label} failed: {error}")
    runner.report_progress(f"{label} complete")
    return {**state, **result}
```

Note: `result` is assigned inside the `with` block. The variable must remain accessible after the block exits. Since the `except` clause calls `runner.fail()` which raises `WorkflowFailedError`, `result` is always assigned when execution reaches the return statement. No structural changes to error handling are needed.

### Step 2: Add tests

In `tests/handlers/test_factories.py`, add a new section `# Handler-level env` with the tests described in the Testing Strategy below.

### Step 3: Validate

Run the validation commands to confirm zero errors, zero warnings.

## Testing Strategy

### Unit Tests

All tests go in `tests/handlers/test_factories.py` under a new `# Handler-level env` section. Follow existing patterns: mock `run_prompt` at `antkeeper.handlers.claude_code.factories.run_prompt`, use `runner_factory()`.

1. **`test_env_sets_vars_during_handler_execution`** — Create handler with `env={"_ANTKEEPER_TEST_HF_KEY": "secret"}`. Mock `run_prompt` with a `side_effect` that captures `os.environ["_ANTKEEPER_TEST_HF_KEY"]`. Assert captured value is `"secret"`.

2. **`test_env_restored_after_handler`** — Ensure `_ANTKEEPER_TEST_HF_RESTORE` is absent from `os.environ`. Call handler with `env={"_ANTKEEPER_TEST_HF_RESTORE": "val"}`. After handler returns, assert the key is absent from `os.environ`.

3. **`test_env_restored_after_handler_failure`** — Handler with `env={"_ANTKEEPER_TEST_HF_FAIL": "val"}`, mock `run_prompt` raises `AgentExecutionError`. Inside `pytest.raises(WorkflowFailedError)`, after the exception, assert the key is absent from `os.environ`.

4. **`test_env_preserves_existing_var`** — Set `os.environ["_ANTKEEPER_TEST_HF_ORIG"] = "original"` in a `try/finally`. Create handler with `env={"_ANTKEEPER_TEST_HF_ORIG": "override"}`. Assert value is `"override"` during execution (via `side_effect`) and `"original"` after handler returns.

5. **`test_env_none_is_noop`** — `cc_handler("/cmd", env=None)` works identically to `cc_handler("/cmd")`. Handler returns state unchanged, no crash.

6. **`test_env_active_during_extraction_step`** — Handler with `state_updates=["x"]` and `env={"_ANTKEEPER_TEST_HF_EXT": "val"}`. Mock `run_prompt` with `side_effect` list (two calls); both capture and assert the env var is present. Mock `extract_json` returns `{"x": "v"}`.

7. **`test_env_with_multiple_vars`** — `env={"_ANTKEEPER_TEST_HF_A": "1", "_ANTKEEPER_TEST_HF_B": "2"}`. Mock `run_prompt` side_effect asserts both are present during execution. Both absent after handler returns.

### Integration

No integration tests needed — this is a pure unit-level change to the factory function.

### Edge Cases

- `env=None` (default) — no-op, covered by test 5
- `env={}` — no-op via `_app_env`'s existing guard (`if not env: yield; return`), implicitly covered
- Env restored on handler failure — covered by test 3
- Pre-existing env var preserved — covered by test 4

## Acceptance Criteria

- `cc_handler` accepts an optional `env` keyword argument of type `dict[str, str] | None`
- Environment variables from `env` are set in `os.environ` during handler execution
- Environment variables are restored after handler completes (success or failure)
- Handler-level env overrides App-level env for overlapping keys (nesting semantics)
- Both `run_prompt` calls (primary + extraction) see the handler env
- `env=None` (default) is a no-op — fully backward compatible
- All existing tests continue to pass unchanged

### Validation Commands

```bash
uv run pytest tests/ -x -q
uv run ruff check src/ tests/
uv run ty check src/
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error.  It is not acceptable to simply explain away the problem.  You must reach zero errors, zero warnings before you move on.  This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- `_app_env` is imported cross-module (from `antkeeper.core.app` into `antkeeper.handlers.claude_code.factories`). This follows the existing precedent set by `antkeeper.core.runner` which already imports `_app_env` from `antkeeper.core.app`. Relocating or making `_app_env` public is out of scope for this change.
- Handler-level `env` is static `dict[str, str]` only — no callable support. This matches the `model` parameter pattern (static override at factory definition time). App-level `env` supports callables because it has `Runner` context at resolution time; handler-level env doesn't need that flexibility.
- The `_app_env` context manager handles `None` and empty dicts as no-ops, converts values via `str()`, and guarantees cleanup in a `finally` block — all pre-existing, battle-tested behaviour.

## Report

Report the following on completion:
- Files changed and lines modified
- Tests added (count and names)
- Validation command results (pass/fail counts)
- Confirmation that all existing tests still pass
