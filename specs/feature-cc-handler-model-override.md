# feature: Add optional model override to cc_handler

- Allow `cc_handler` callers to pin a specific model at factory time, overriding the model from state.
- Default to `state.get("model")` when no override is provided, preserving current behaviour.
- Zero impact on existing call sites; purely additive keyword-only parameter.

## Solution Design

### External Interface Change

Channels and handler authors can now pin a model when constructing a handler:

```python
# Before: model always comes from state
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])

# After: optionally override model at factory time
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"], model="claude-sonnet-4")

# Omitting model preserves current behaviour (falls back to state)
implement = cc_handler("/sdlc:implement $spec_file")
```

### Architectural Schema Changes

```yaml
types:
  cc_handler:
    kind: function
    parameters:
      - command: str
      - state_updates: list[str] | None  # keyword-only, default None
      - label: str | None                # keyword-only, default None
      - model: str | None                # NEW - keyword-only, default None
    returns: Handler
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/factories.py` — the factory function to modify; add `model` parameter and override logic.
- `tests/handlers/test_factories.py` — existing test suite; add 3 new tests for model override behaviour.
- `app_docs/instrumentation.md` — documents `cc_handler`; add a line about the `model` parameter.

## Workflow

### Step 1: Add `model` parameter to `cc_handler`

- Add `model: str | None = None` as a keyword-only argument after `label` in the `cc_handler` signature.
- Change the `run_prompt` call from:
  ```python
  response = run_prompt(prompt, runner.logger, model=state.get("model"))
  ```
  to:
  ```python
  response = run_prompt(prompt, runner.logger, model=model if model is not None else state.get("model"))
  ```
- Update the docstring Args section to document `model`:
  ```
  model: LLM model identifier. When provided, overrides the model from
      state. Defaults to ``state.get("model")``.
  ```

### Step 2: Add tests

- Add a new section `# model override` in `tests/handlers/test_factories.py` after the `$var interpolation` section.
- Add 3 tests following the existing fire-and-forget pattern (mock `run_prompt`, use `runner_factory()`):
  1. `test_model_override_passed_to_run_prompt` — factory `model="claude-opus-4"`, state has no `model` key, assert `run_prompt` called with `model="claude-opus-4"`.
  2. `test_model_override_beats_state_model` — factory `model="claude-opus-4"`, state has `model="claude-sonnet-4"`, assert `run_prompt` called with `model="claude-opus-4"`.
  3. `test_no_model_override_falls_back_to_state` — factory with no `model` arg, state has `model="claude-sonnet-4"`, assert `run_prompt` called with `model="claude-sonnet-4"`.

### Step 3: Update instrumentation docs

- In `app_docs/instrumentation.md`, in the `cc_handler` factory section, add a brief mention that `model` can be passed to override the state model.

### Step 4: Validate

- Run the validation commands below.

## Testing Strategy

### Unit Tests

- 3 new tests covering all branches of `model if model is not None else state.get("model")`:
  - Factory override provided, no state model → override used
  - Factory override provided, state model also present → factory override wins
  - No factory override, state model present → state model used
- The fourth path (neither provided → `None`) is already covered by 5+ existing tests that assert `model=None`.

### Edge Cases

- `model=None` (default) must fall back to state — covered by test 3 and existing tests.
- State has no `"model"` key and no factory override — already covered by existing tests asserting `model=None`.

## Acceptance Criteria

- `cc_handler` accepts an optional `model` keyword argument.
- When `model` is provided, it is passed to `run_prompt` regardless of state contents.
- When `model` is `None` (default), `state.get("model")` is used as before.
- All existing tests pass unchanged.
- 3 new tests pass.
- Type checker (`ty`) reports no new errors.
- Linter (`ruff`) reports no new errors.

### Validation Commands

```bash
uv run pytest
uv run ruff check src/ tests/
uv run ty check src/
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- Use `model if model is not None else state.get("model")` (ternary) rather than `model or state.get("model")`. The `or` pattern would silently discard an empty-string model, whereas the ternary correctly uses `None` as the sentinel — matching the `None`-check semantics used throughout the LLM layer (`ClaudeCodeAgent`, `run_prompt`).
- The `Handler` Protocol does not need updating — it constrains the returned callable's signature, not the factory's parameters.
- No existing call sites need modification; all omit `model` and get the current behaviour.

## Report

- **Files changed**: `src/antkeeper/handlers/claude_code/factories.py`, `tests/handlers/test_factories.py`, `app_docs/instrumentation.md`
- **Tests added**: 3 (model override, override beats state, fallback to state)
- **Validations**: `pytest`, `ruff check`, `ty check`
