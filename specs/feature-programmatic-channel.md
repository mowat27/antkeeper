# feature: Programmatic channel for in-process workflow execution

- Add `ProgrammaticChannel` so external Python code (e.g. Overloop) can run antkeeper workflows via `run_handler()` and receive events through callbacks.
- Each `run_handler()` call is self-contained: load app, run workflow, return final state as a plain dict.
- Errors propagate as exceptions; no `sys.exit`, no swallowed failures.

## Solution Design

### External Interface Change

Construction and execution from external code:

```python
from antkeeper.channels.programmatic import ProgrammaticChannel

channel = ProgrammaticChannel(
    on_progress=lambda run_id, event: print(f"[{run_id}] {event.content}"),
    on_error=lambda run_id, message: print(f"[{run_id}] ERROR: {message}"),
)

result = channel.run_handler(
    "build_slice",
    {"brief": "Add auth", "n": 1},
    handlers_file="handlers.py",
)
print(result)  # final state dict
```

Callbacks are optional. When omitted, events are silently discarded (standard callback pattern). `on_progress` receives `(run_id: str, event: StreamEvent)` for all non-error, non-internal events with content. `on_error` receives `(run_id: str, message: str)` for error events.

If the workflow fails via `runner.fail()`, `WorkflowFailedError` propagates to the caller. If the handler raises any other exception, it also propagates. No exception is caught or converted — the caller controls error handling.

### Architectural Schema Changes

```yaml
types:
  ProgrammaticChannel:
    kind: class
    file: src/antkeeper/channels/programmatic.py
    fields:
      - on_progress: "Callable[[str, StreamEvent], None] | None"
      - on_error: "Callable[[str, str], None] | None"
    methods:
      - run_handler:
          params:
            - workflow_name: str
            - initial_state: "dict[str, Any] | None"  # defaults to None
            - handlers_file: str  # defaults to "handlers.py"
          returns: "dict[str, Any]"
          raises: [WorkflowFailedError, FileNotFoundError, AttributeError, ValueError]

  _InnerChannel:
    kind: class  # private, satisfies Channel protocol
    file: src/antkeeper/channels/programmatic.py
    fields:
      - type: str  # "programmatic"
      - workflow_name: str
      - initial_state: State
    methods:
      - report:
          params:
            - run_id: str
            - event: StreamEvent
```

### Design Notes

**Two-class architecture**: `ProgrammaticChannel` is constructed without knowing the workflow name. The Channel protocol requires `workflow_name` and `initial_state` as instance attributes. Solution: `run_handler()` creates a private `_InnerChannel` per call that satisfies the protocol, ensuring each call is fully self-contained.

**No verbose attribute**: `verbose` is not part of the Channel protocol. Programmatic callers receive all non-internal events and filter themselves.

**Per-call app loading**: `handlers_file` is a parameter of `run_handler()`, so `load_app()` runs each call. This matches the user's API where different calls could use different handler files.

## Relevant Files

- `src/antkeeper/core/domain.py` — defines `Channel` protocol, `StreamEvent`, `State`, `WorkflowFailedError`. The new channel must satisfy this protocol.
- `src/antkeeper/core/runner.py` — `Runner(app, channel)` constructor and `runner.run()` method. `run_handler()` creates a Runner internally.
- `src/antkeeper/loader.py` — `load_app(path)` loads an App from a Python file. Used by `run_handler()` to load the handlers file.
- `src/antkeeper/channels/__init__.py` — package docstring listing channels. Needs updating to mention ProgrammaticChannel.
- `src/antkeeper/channels/cli.py` — reference implementation for how a channel uses Runner and handles events.

### New Files

- `src/antkeeper/channels/programmatic.py` — the ProgrammaticChannel and _InnerChannel classes.
- `tests/channels/test_programmatic.py` — unit tests for the new channel.

## Workflow

### Step 1: Create ProgrammaticChannel module

- Create `src/antkeeper/channels/programmatic.py`
- Implement `ProgrammaticChannel` class:
  - `__init__(self, on_progress=None, on_error=None)` — stores callbacks
  - `run_handler(self, workflow_name, initial_state=None, handlers_file="handlers.py")` — loads app via `load_app(handlers_file)`, creates `_InnerChannel`, creates `Runner(app, inner)`, calls `runner.run()`, returns the result
- Implement `_InnerChannel` class:
  - `__init__(self, workflow_name, initial_state, on_progress, on_error)` — sets `self.type = "programmatic"`, stores `workflow_name`, copies `initial_state`, stores callbacks as private attrs
  - `report(self, run_id, event)` — skips internal events and empty content; routes error events to `on_error(run_id, event.content)`, all others to `on_progress(run_id, event)`; no-ops when callback is None

### Step 2: Update channels package docstring

- Add `ProgrammaticChannel` to the channel list in `src/antkeeper/channels/__init__.py`

### Step 3: Write tests

- Create `tests/channels/test_programmatic.py` with the tests described in the Testing Strategy below

### Step 4: Run validation commands

## Testing Strategy

### Unit Tests

**_InnerChannel.report() tests:**

1. `test_report_progress_calls_on_progress` — Create `_InnerChannel` with mock `on_progress`. Send `StreamEvent(type="progress", content="step done")`. Assert `on_progress` called with `(run_id, event)`.

2. `test_report_error_calls_on_error` — Create `_InnerChannel` with mock `on_error`. Send `StreamEvent(type="error", content="broke")`. Assert `on_error` called with `(run_id, "broke")` — string, not event.

3. `test_report_skips_internal_events` — Send event with `internal=True`. Assert neither callback called.

4. `test_report_skips_empty_content` — Send event with `content=""`. Assert neither callback called.

5. `test_report_non_error_types_go_to_on_progress` — Send events with types `"assistant"`, `"result"`, `"tool"`. Assert all routed to `on_progress`, not `on_error`.

6. `test_report_no_callbacks_does_not_raise` — Create `_InnerChannel` with both callbacks None. Send progress and error events. Assert no exception.

7. `test_inner_channel_attributes` — Assert `type == "programmatic"`, `workflow_name` and `initial_state` are stored correctly.

**ProgrammaticChannel.run_handler() tests:**

8. `test_run_handler_returns_final_state` — Create a temp handlers file with a simple handler that adds a key. Call `run_handler()`. Assert returned dict contains the handler's addition.

9. `test_run_handler_default_initial_state` — Call `run_handler()` without `initial_state`. Assert result contains only framework-injected keys.

10. `test_run_handler_propagates_workflow_failed_error` — Temp handlers file with handler that calls `runner.fail("boom")`. Assert `pytest.raises(WorkflowFailedError)`.

11. `test_run_handler_calls_on_progress` — Temp handlers file with handler that calls `runner.report_progress("step")`. Assert `on_progress` mock was called.

12. `test_run_handler_calls_on_error` — Temp handlers file with handler that calls `runner.report_error("warn")`. Assert `on_error` mock was called with the message string.

13. `test_run_handler_no_state_carries_between_calls` — Call `run_handler()` twice with same initial_state. Assert second result doesn't contain keys from first handler's additions.

14. `test_run_handler_initial_state_not_mutated` — Pass a dict as `initial_state`, keep a reference. After `run_handler()`, assert original dict is unchanged.

### Edge Cases

- Handler that returns state unchanged — `run_handler()` still returns a dict with framework keys
- `handlers_file` that doesn't exist — `FileNotFoundError` propagates
- `workflow_name` not registered — exception propagates from `app.get_handler()`

## Acceptance Criteria

- `ProgrammaticChannel` can be constructed with optional `on_progress` and `on_error` callbacks
- `run_handler()` loads an app from `handlers_file`, executes the named workflow, and returns final state as a dict
- `on_progress` receives `(run_id, StreamEvent)` for non-error, non-internal events with content
- `on_error` receives `(run_id, str)` for error events
- `WorkflowFailedError` and other exceptions propagate to the caller
- Each `run_handler()` call is self-contained — no shared state between calls
- All existing tests continue to pass

### Validation Commands

```bash
just ruff
just ty
just test
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- `_InnerChannel` is a private implementation detail. External callers should never import or instantiate it directly.
- The `handlers_file` parameter uses `load_app()` which resolves paths relative to process CWD, same as the CLI channel. Document this if it becomes a source of confusion.
- Future enhancement: accept a pre-loaded `App` instance to avoid per-call `load_app()`. Not in scope for this feature.

## Report

Files changed, tests added, validations added. Specifically:

- **New**: `src/antkeeper/channels/programmatic.py` — `ProgrammaticChannel` and `_InnerChannel` classes
- **New**: `tests/channels/test_programmatic.py` — 14 unit tests covering report routing, run_handler lifecycle, error propagation, and state isolation
- **Modified**: `src/antkeeper/channels/__init__.py` — docstring updated to list ProgrammaticChannel
- **Validations**: `just ruff`, `just ty`, `just test`
