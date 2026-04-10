# refactor: Unify handler type into single core Protocol

- Promote a canonical `Handler` protocol into `antkeeper.core.domain` so every handler source shares one type.
- Delete duplicate local protocols in `factories.py` and `ralph.py`; all handler-accepting APIs use the core type.
- Fix `App.handler` decorator to store the wrapper (not raw fn) in the registry for identity consistency.

## Solution Design

### Architectural Schema Changes

```yaml
types:
  Handler:
    kind: protocol
    module: antkeeper.core.domain
    attributes:
      - __name__: str
    methods:
      - __call__(self, runner: Runner, state: State) -> State  # positional-or-keyword, NO /

  # Changed signatures in App
  App.handler:
    was: "Callable[..., Any] -> Callable[..., Any]"
    now: "Handler -> Handler"

  App.add_handler:
    was: "fn: Callable"
    now: "fn: Handler"

  App.get_handler:
    was: "-> Callable[[Runner, State], State | NoReturn]"
    now: "-> Handler"

  run_workflow:
    steps:
      was: "list[Callable[[Runner, State], State]]"
      now: "list[Handler]"
```

## Relevant Files

- `src/antkeeper/core/domain.py` — Add the `Handler` protocol here alongside `State`, `Channel`, `StreamEvent`, `WorkflowFailedError`. Needs `Runner` import under `TYPE_CHECKING`.
- `src/antkeeper/core/app.py` — Tighten all handler type annotations to `Handler`. Change decorator to store wrapper in registry. Collapse `State | NoReturn` to `State`. Simplify `getattr(__name__)` fallbacks to `step.__name__`.
- `src/antkeeper/core/__init__.py` — Export `Handler` from the core package.
- `src/antkeeper/handlers/claude_code/factories.py` — Delete local `Handler` protocol (lines 134–147). Import `Handler` from `antkeeper.core.domain`.
- `src/antkeeper/handlers/ralph.py` — Delete `_NamedHandler` protocol (lines 21–26). Import `Handler` from `antkeeper.core.domain`. Update type annotations on `ralph()`.
- `src/antkeeper/__init__.py` — Add `Handler` to top-level re-exports if other core types are exported there.
- `tests/core/test_app.py` — Add tests for decorator registry identity.
- `tests/core/test_workflows.py` — Add handler composability tests.

## Workflow

### Step 1: Add `Handler` protocol to `core/domain.py`

- Add `from __future__ import annotations` at the top of `domain.py` (needed for forward-referencing `Runner`).
- Add `TYPE_CHECKING` import guard for `Runner` (same pattern used in `app.py` and `ralph.py`).
- Add `Protocol` to the existing `typing` import.
- Define the `Handler` protocol after the `Channel` protocol:
  ```python
  class Handler(Protocol):
      """A workflow handler callable with a __name__ attribute."""
      __name__: str
      def __call__(self, runner: Runner, state: State) -> State: ...
  ```
- No positional-only marker (`/`).

### Step 2: Export `Handler` from `core/__init__.py`

- Add `Handler` to the imports from `antkeeper.core.domain` in `core/__init__.py`.
- Check `src/antkeeper/__init__.py` and add `Handler` to top-level exports if other core types are re-exported there.

### Step 3: Tighten `core/app.py` type annotations

- Import `Handler` from `antkeeper.core.domain`.
- `App.handler` method:
  - Parameter annotation: `fn: Handler`.
  - Return annotation: `Handler`.
  - `wrapper` return annotation: `State` (remove `| NoReturn`).
  - Change `self.handlers[name] = fn` to `self.handlers[name] = wrapper`.
- `App.add_handler`: parameter type `fn: Handler`.
- `App.get_handler`: return type `Handler`.
- `run_workflow`: `steps` parameter type `list[Handler]`.
- Replace `getattr(step, '__name__', repr(step))` with `step.__name__` on lines 214 and 223 (and the span attributes on line 230).
- Remove `NoReturn` from the `typing` import if no longer used elsewhere in the file.

### Step 4: Delete local protocol in `factories.py`

- Delete the `Handler` class (lines 134–147) from `handlers/claude_code/factories.py`.
- Add `from antkeeper.core.domain import Handler` (or adjust the existing `domain` import line).
- Verify `cc_handler` return type annotation still references `Handler` — it should, now pointing at the core type.

### Step 5: Delete local protocol in `ralph.py`

- Delete the `_NamedHandler` class (lines 21–26) from `handlers/ralph.py`.
- Add `Handler` to the existing `from antkeeper.core.domain import State` import.
- Change `ralph()` signature: `handler: Handler` parameter, `-> Handler` return type (lines 111, 117).
- Remove `Protocol` from the `typing` import if no longer used.

### Step 6: Add tests

- See Testing Strategy below.

### Step 7: Validate

- Run all validation commands.

## Testing Strategy

### Unit Tests

**`tests/core/test_app.py`** — add:

- `test_handler_decorator_stores_wrapper_in_registry` — After `@app.handler`, `app.handlers[name]` is the wrapper, not the raw function. Verify `app.handlers[name] is not raw_fn`.
- `test_handler_decorator_registry_and_return_are_same_object` — `decorated = app.handler(fn)` and `app.handlers[fn.__name__]` are the same object (`is` check).

**`tests/core/test_workflows.py`** — add:

- `test_decorated_handler_usable_in_run_workflow` — `@app.handler` decorated function passed as a step to `run_workflow` executes correctly.
- `test_mixed_handler_sources_in_run_workflow` — A `steps` list containing a plain function and a decorated handler all execute in sequence.
- `test_decorated_handler_composable_with_ralph` — `ralph(decorated_fn, validator=v)` works and the resulting handler runs in `run_workflow`.
- `test_ralph_wrapping_cc_handler_pattern` — Define a handler mimicking `cc_handler` output (function with `__name__` set), wrap with `ralph`, pass to `run_workflow`. Verifies the full composition chain without requiring Claude Code CLI.

### Edge Cases

- A lambda assigned to a variable still has `__name__ == "<lambda>"` — verify `run_workflow` handles this without crashing.
- A handler defined with `**kwargs` in its signature still satisfies the protocol and works in `run_workflow`.
- Existing tests in `test_app.py` and `test_workflows.py` must continue to pass unchanged — the registry storage change should not break `test_app_constructor_with_handlers_dict` (constructor path is unaffected) or `test_multi_step_workflow` (uses `@app.handler` decorated functions as steps).

## Acceptance Criteria

- `just` (ruff + ty + tests) passes cleanly with no handler-related type errors.
- `cc_handler(...)` output can be passed directly to `ralph(...)` with no casts or type-checker complaints.
- `@app.handler`-decorated functions can be passed to `ralph(...)` and included in `run_workflow(...)` step lists without casts.
- A handler produced by `ralph(cc_handler(...))` can itself be included in a `run_workflow` step list and re-wrapped.
- `app.handlers[name]` (registry lookup) and the bound decorated name refer to the same callable object.
- No changes to the public call sites of `run_workflow`, `cc_handler`, or `ralph`. Downstream projects importing these symbols continue to work unmodified.
- All existing tests pass without modification.

### Validation Commands

```bash
# Full standard checks (ruff + ty + tests)
just

# Verify no remaining local Handler/NamedHandler protocols
rg "class Handler\(Protocol\)" src/antkeeper/handlers/
rg "class _NamedHandler" src/antkeeper/

# Verify Handler is exported from core
python -c "from antkeeper.core import Handler; print(Handler)"

# Verify no getattr __name__ fallbacks remain in app.py
rg "getattr.*__name__" src/antkeeper/core/app.py
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- `Runner.fail` is already annotated `-> NoReturn` (runner.py line 217). No change needed there.
- The `App.handler` wrapper is a plain forwarder via `functools.wraps`. Storing it in the registry instead of the raw fn means `get_handler` returns the wrapper. Since the wrapper just calls `fn(runner, state)`, runtime behavior is identical — but now `app.handlers[name]` and the decorated reference are the same object.
- The `add_handler` path stores whatever `Handler` is passed directly. This is intentional — `add_handler` is for pre-built handlers (factory outputs etc), while the decorator creates its own wrapper. Both paths store a `Handler`.
- The `test_app_constructor_with_handlers_dict` test uses the constructor `handlers={}` kwarg which bypasses the decorator entirely and is unaffected by the registry storage change.

## Report

Report the following on completion:

- Files changed (with line-count delta)
- Tests added (names and what they verify)
- Validation command results (pass/fail for each)
- Confirmation that `Handler` is importable from `antkeeper.core`
- Confirmation that no local handler protocols remain in `src/antkeeper/handlers/`
