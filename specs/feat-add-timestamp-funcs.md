# feat: Add timestamp and log-dir helper functions

- Extract `make_timestamp()` and `make_log_dir(base_dir)` into `antkeeper.helpers` for client handler code reuse.
- `make_log_dir` returns a closure compatible with `App(log_dir=...)` producing `"{base_dir}/{timestamp}-{runner.id}/"`.
- Both functions importable from `antkeeper` top-level package.

## Solution Design

### External Interface Change

Clients can now import two utility functions directly:

```python
from antkeeper import make_timestamp, make_log_dir

# Use make_timestamp() in handlers
@app.handler
def my_handler(runner, state):
    ts = make_timestamp()  # "20260314120000"
    return {**state, "timestamp": ts}

# Use make_log_dir() with App
app = App(log_dir=make_log_dir("agents/logs"))
```

All channels (CLI, API, Slack) benefit equally since these are pure utilities consumed by handler code.

### Architectural Schema Changes

```yaml
types:
  helpers.timestamps:
    kind: module
    functions:
      - make_timestamp() -> str
      - make_log_dir(base_dir: str) -> Callable[[Runner], str]
```

## Relevant Files

- `src/antkeeper/helpers/__init__.py` — add imports and `__all__` entries for new functions; update module docstring.
- `src/antkeeper/__init__.py` — add imports and `__all__` entries for top-level export.

### New Files

- `src/antkeeper/helpers/timestamps.py` — new module containing `make_timestamp` and `make_log_dir`.
- `tests/helpers/test_timestamps.py` — unit tests for the new functions.

## Workflow

### Step 1: Create `src/antkeeper/helpers/timestamps.py`

- Add module docstring following the pattern in `helpers/json.py`.
- Implement `make_timestamp() -> str` — returns `datetime.now().strftime("%Y%m%d%H%M%S")`.
- Implement `make_log_dir(base_dir: str) -> Callable[["Runner"], str]` — returns a closure that, given a runner, produces `f"{base_dir}/{make_timestamp()}-{runner.id}/"`.
- Use `from __future__ import annotations` and `TYPE_CHECKING` guard to import `Runner` for type annotation without circular dependency, matching the pattern in `src/antkeeper/core/app.py`.
- The inner `_log_dir` function should type its `runner` parameter as `Runner`.

### Step 2: Update exports

- In `src/antkeeper/helpers/__init__.py`: import `make_timestamp` and `make_log_dir` from `antkeeper.helpers.timestamps`, add to `__all__`, update module docstring to mention timestamp utilities.
- In `src/antkeeper/__init__.py`: import `make_timestamp` and `make_log_dir` from `antkeeper.helpers.timestamps`, add to `__all__`.

### Step 3: Write tests in `tests/helpers/test_timestamps.py`

- Implement the test cases described in the Testing Strategy section below.
- Follow patterns from `tests/helpers/test_extract_json.py`.

### Step 4: Run validation commands

- Run all validation commands below and fix any issues until zero errors and zero warnings.

## Testing Strategy

### Unit Tests

**`test_make_timestamp_format`**
- Patch `antkeeper.helpers.timestamps.datetime` so `datetime.now()` returns `datetime(2026, 3, 14, 9, 5, 7)`.
- Assert result equals `"20260314090507"`.

**`test_make_log_dir_returns_callable`**
- Call `make_log_dir("logs")` and assert the result is callable.

**`test_make_log_dir_produces_correct_path`**
- Patch `antkeeper.helpers.timestamps.datetime` so `datetime.now()` returns a fixed datetime.
- Create a mock runner with `id = "abc123"`.
- Call `make_log_dir("/var/logs")` to get the callable, invoke it with the mock runner.
- Assert result is `"/var/logs/20260314090507-abc123/"` (using the patched timestamp).

**`test_make_log_dir_uses_timestamp_at_call_time`**
- Call `make_log_dir("out")` without mocking to get the callable.
- Then patch `datetime.now()` to return `datetime(2099, 12, 31, 23, 59, 59)` and invoke the callable with a mock runner (`id = "run1"`).
- Assert result is `"out/20991231235959-run1/"`, proving the timestamp is captured at invocation time, not factory time.

### Integration

No integration tests needed — these are pure utility functions.

### Edge Cases

- Verify trailing slash is present on `make_log_dir` output.
- Verify timestamp is 14 characters and all numeric (covered by `test_make_timestamp_format` with a known datetime).

## Acceptance Criteria

- `make_timestamp()` returns a 14-character string in `YYYYMMDDHHmmss` format.
- `make_log_dir(base_dir)` returns a callable that produces `"{base_dir}/{timestamp}-{runner.id}/"`.
- Both are importable via `from antkeeper import make_timestamp, make_log_dir`.
- Both are importable via `from antkeeper.helpers import make_timestamp, make_log_dir`.
- All existing tests continue to pass.
- All new tests pass.
- `ruff`, `ty`, and `pytest` report zero errors.

### Validation Commands

```bash
just ruff
just ty
just test
```

```bash
uv run python -c "from antkeeper import make_timestamp, make_log_dir; print(make_timestamp()); print(make_log_dir('logs'))"
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- Do NOT refactor `runner.py` to use `make_timestamp()` — these helpers are for client handler code only.
- The `Runner.__init__` generates its own timestamp independently (line 71 of `runner.py`). When `make_log_dir` is used as `App(log_dir=...)`, its closure will call `make_timestamp()` at resolution time inside `Runner.__init__`. This means two `datetime.now()` calls occur within the same `__init__`, which could theoretically produce different seconds. This is acceptable — the directory timestamp and log filename timestamp serving different purposes is fine.
- Use `TYPE_CHECKING` guard for `Runner` import to avoid circular dependency, matching the pattern established in `app.py`.

## Report

Report the following on completion:
- Files changed (with line counts)
- Files created (with line counts)
- Tests added (names and status)
- Validation command results (ruff, ty, pytest)
