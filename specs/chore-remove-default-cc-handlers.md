# chore: remove default handlers from claude_code package

- Remove all pre-registered handlers, steps, and workflows from `src/antkeeper/handlers/claude_code/__init__.py`.
- Package exports only `cc_handler` factory — users define their own handlers in `handlers.py`.
- BREAKING CHANGE: ignore backwards compatibility. The `app` instance and built-in handlers are deleted.

## Solution Design

### External Interface Change

The `antkeeper.handlers.claude_code` package becomes a thin re-export of the factory:

```python
from antkeeper.handlers.claude_code import cc_handler
```

Consumers no longer import `app` from this package. All handler definitions live in user-space `handlers.py` files (already the case for the root `handlers.py`).

### Architectural Schema Changes

```yaml
types:
  antkeeper.handlers.claude_code:
    kind: module
    exports:
      - cc_handler: Callable  # re-exported from factories
    removed:
      - app: App
      - derive_feature, specify, branch_if_on_main, implement, push, raise_a_pr: handlers
      - healthcheck, commit: handlers
      - specify_implement, sdlc, sdlc_iso: workflow handlers
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/__init__.py` — gut all handler/workflow code, keep only `cc_handler` re-export
- `tests/handlers/test_claude_code.py` — remove handler registration tests, replace with import test for `cc_handler`

## Workflow

### Step 1: Rewrite `__init__.py`

- Replace entire file contents with a module docstring and a single re-export:
  ```python
  """Claude Code handler utilities.

  Exports the ``cc_handler`` factory for building LLM-backed workflow handlers.
  """

  from antkeeper.handlers.claude_code.factories import cc_handler

  __all__ = ["cc_handler"]
  ```
- Remove all imports of `App`, `run_workflow`, `Runner`, `State`, `Worktree`, `git_worktree`, `latest_commit`, `run_prompt`, `datetime`

### Step 2: Rewrite tests

- Replace `tests/handlers/test_claude_code.py` with a single test that verifies `cc_handler` is importable from the package:
  ```python
  from antkeeper.handlers.claude_code import cc_handler
  assert callable(cc_handler)
  ```

### Step 3: Validate

- Run all validation commands

## Testing Strategy

### Unit Tests

- `test_cc_handler_importable_from_package` — verify `from antkeeper.handlers.claude_code import cc_handler` works and returns a callable

### Edge Cases

- No edge cases — this is a deletion chore

## Acceptance Criteria

- `src/antkeeper/handlers/claude_code/__init__.py` contains no handler definitions, no `App` instance, no workflow functions
- `from antkeeper.handlers.claude_code import cc_handler` works
- Zero test failures, zero ruff warnings, zero ty errors

### Validation Commands

```bash
uv run -m pytest tests/ -v
uv run ruff check .
uv run ty check src/
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The root `handlers.py` already defines its own independent set of handlers using `cc_handler` — it is unaffected by this change.
- The `factories.py` module is untouched; only the package `__init__.py` changes.

## Report

Report: files changed, tests modified, validation results. Max 200 words.
