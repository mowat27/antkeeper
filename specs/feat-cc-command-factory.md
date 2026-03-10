# feat: cc_handler factory for Claude Code handlers

- Eliminate boilerplate in 6 Claude Code handlers via a single `cc_handler` factory function
- Factory produces `(Runner, State) -> State` handlers in two modes: static updates or JSON field extraction
- Refactor `derive_feature`, `specify`, `branch_if_on_main`, `implement`, `push`, `raise_a_pr` to one-liners

## Solution Design

### External Interface Change

Channels gain no new capabilities. The factory is internal to `handlers/claude_code/` — it changes how handlers are built, not what they do. All 11 handler names remain registered identically. Existing workflows are unaffected.

Usage from handler files (e.g. `pw-finances/handlers.py`):

```python
from antkeeper.handlers.claude_code import cc_handler

# Simple mode — static state merge after LLM call
implement = cc_handler("/implement {spec_file}", updates={"implement_status": "complete"})

# JSON mode — extract fields from LLM response into state
specify = cc_handler("/specify {prompt}", json_fields=["spec_file", "slug"])
```

### Architectural Schema Changes

```yaml
types:
  cc_handler:
    kind: function
    module: antkeeper.handlers.claude_code.factories
    parameters:
      - command: str  # Format string with {key} placeholders interpolated from state
      - updates: dict[str, Any] | None  # keyword-only, default None
      - json_fields: list[str] | None  # keyword-only, default None
      - label: str | None  # keyword-only, default None
    returns: Callable[[Runner, State], State]
    validation: ValueError if both or neither of updates/json_fields provided (at factory call time)
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/__init__.py` — contains the 11 handlers; 6 will be replaced with `cc_handler` calls
- `src/antkeeper/llm/claude_code.py` — `run_prompt(prompt, logger, model=...)` called by the factory
- `src/antkeeper/llm/errors.py` — `AgentExecutionError` caught by the factory
- `src/antkeeper/helpers/json.py` — `json_prompt(prompt, *, required_fields=)` and `extract_json(response)` used in JSON mode
- `src/antkeeper/core/runner.py` — `Runner` class with `report_progress()`, `fail()`, `logger`
- `src/antkeeper/core/domain.py` — `State` type alias
- `tests/handlers/test_claude_code.py` — existing handler tests; must remain green with same 11 handler names
- `tests/conftest.py` — `runner_factory` fixture providing `(Runner, TestChannel)` pairs

### New Files

- `src/antkeeper/handlers/claude_code/factories.py` — the `cc_handler` factory function
- `tests/handlers/test_factories.py` — unit tests for the factory

## Workflow

### Step 1: Create `factories.py` with `cc_handler`

- Create `src/antkeeper/handlers/claude_code/factories.py`
- Implement `cc_handler(command, *, updates=None, json_fields=None, label=None)` returning `Callable[[Runner, State], State]`
- **Validation** (at factory call time): raise `ValueError` if both `updates` and `json_fields` are provided, or if neither is provided
- **Label defaulting**: if `label` is None, take the first whitespace-delimited token of `command` and strip any leading `/`
- **`__name__`**: set `handler.__name__ = label` directly on the returned function (no sanitization — all current labels are valid identifiers)
- **Generated handler behaviour**:
  1. `runner.report_progress(f"Running {label}")`
  2. Interpolate: `prompt = command.format_map(state)`
  3. If JSON mode: `prompt = json_prompt(prompt, required_fields=json_fields)`
  4. `response = run_prompt(prompt, runner.logger, model=state.get("model"))`
  5. If JSON mode: `parsed = extract_json(response)` then `result = {k: parsed[k] for k in json_fields}`
  6. If simple mode: `result = updates`
  7. `runner.report_progress(f"{label} complete")`
  8. Return `{**state, **result}`
- **Error handling**: wrap steps 2–6 in a single `try/except` catching `(KeyError, AgentExecutionError, ValueError)` and calling `runner.fail(f"{label} failed: {error}")` which raises `WorkflowFailedError`
- **No prompt/response logging** — the LLM layer already logs at appropriate levels
- Imports:
  ```python
  from typing import Any, Callable
  from antkeeper.core.runner import Runner
  from antkeeper.core.domain import State
  from antkeeper.helpers.json import json_prompt, extract_json
  from antkeeper.llm.claude_code import run_prompt
  from antkeeper.llm.errors import AgentExecutionError
  ```

### Step 2: Update `__init__.py` — re-export and refactor handlers

- Import and re-export `cc_handler` from `factories.py` in `src/antkeeper/handlers/claude_code/__init__.py`
- Replace 6 handler definitions with `cc_handler` calls:

  | Handler | Mode | Factory call |
  |---|---|---|
  | `derive_feature` | JSON | `cc_handler("/derive_feature {prompt}", json_fields=["feature_type", "slug"])` |
  | `specify` | JSON | `cc_handler("/specify {prompt}", json_fields=["spec_file", "slug"])` |
  | `branch_if_on_main` | JSON | `cc_handler("/branch {spec_file}", json_fields=["branch_name"])` |
  | `implement` | simple | `cc_handler("/implement {spec_file}", updates={"implement_status": "complete"})` |
  | `push` | simple | `cc_handler("Push the current branch to the remote origin.", updates={"push_status": "complete"})` |
  | `raise_a_pr` | simple | `cc_handler("Create a pull request for the current branch using gh pr create.", updates={"pr_status": "complete"})` |

- Register each with `app.add_handler(handler_name)` as they are no longer decorated with `@app.handler`
- **Keep as-is**: `healthcheck` (logs raw response), `commit` (calls `latest_commit()` post-LLM), and all composite workflows (`specify_implement`, `sdlc`, `sdlc_iso`)

### Step 3: Write tests for `cc_handler`

- Create `tests/handlers/test_factories.py`
- Mock `run_prompt` at `antkeeper.handlers.claude_code.factories.run_prompt` throughout
- Use `runner_factory` fixture from `conftest.py` for `(Runner, TestChannel)` pairs

### Step 4: Run validation commands

- Run all validation commands listed below
- Fix any failures before considering the task complete

## Testing Strategy

### Unit Tests

**Validation tests** (no Runner needed):
- `test_raises_when_both_updates_and_json_fields_provided` — assert `ValueError`
- `test_raises_when_neither_updates_nor_json_fields_provided` — assert `ValueError`

**Simple mode tests** (mock `run_prompt`):
- `test_simple_mode_merges_updates_into_state` — state = `{"x": 1}`, updates = `{"status": "done"}`, assert returned state has both
- `test_simple_mode_interpolates_command_with_state` — command = `"/implement {spec_file}"`, state has `spec_file`, assert `run_prompt` called with interpolated string
- `test_simple_mode_reports_progress` — assert TestChannel progress messages contain "Running {label}" and "{label} complete"

**JSON mode tests** (mock `run_prompt`, `extract_json`):
- `test_json_mode_wraps_prompt_with_json_prompt` — assert `json_prompt` called with interpolated command and `required_fields=json_fields`
- `test_json_mode_extracts_only_named_fields` — mock `extract_json` returning extra keys, assert only `json_fields` keys merged
- `test_json_mode_reports_progress` — assert progress messages

**Label and `__name__` tests**:
- `test_default_label_strips_leading_slash` — command `/commit arg`, assert `__name__` is `"commit"`
- `test_default_label_first_token` — command `"do_stuff arg1"`, assert `__name__` is `"do_stuff"`
- `test_custom_label_overrides_default` — explicit `label="my_label"`, assert `__name__` is `"my_label"`

**Error handling tests**:
- `test_agent_execution_error_calls_runner_fail` — mock `run_prompt` raising `AgentExecutionError`, assert `WorkflowFailedError` raised
- `test_bad_json_calls_runner_fail` — mock `extract_json` raising `ValueError`, assert `WorkflowFailedError` raised
- `test_missing_state_key_calls_runner_fail` — command has `{missing}`, state lacks key, assert `WorkflowFailedError` raised

### Edge Cases

- Command with no interpolation placeholders (e.g. `"/commit"`) succeeds
- Command with multiple placeholders interpolates all
- Empty `updates={}` merges nothing (state unchanged)
- Single `json_fields=["result"]` extracts one field
- Missing field in parsed JSON response (key in `json_fields` not in LLM output) routes to `runner.fail()` via `KeyError`

## Acceptance Criteria

- `cc_handler` factory function exists in `src/antkeeper/handlers/claude_code/factories.py`
- `cc_handler` is importable from `antkeeper.handlers.claude_code`
- 6 handlers replaced with one-liner `cc_handler` calls
- All 11 handler names still registered (same names, same count)
- All new unit tests pass
- All existing tests pass with zero regressions
- `ruff`, `ty`, and full test suite pass cleanly

### Validation Commands

```bash
# Linting
uv run ruff check src/ tests/

# Type checking
uv run ty check src/

# New factory tests
uv run -m pytest tests/handlers/test_factories.py -v

# Existing handler tests unchanged
uv run -m pytest tests/handlers/test_claude_code.py -v

# Full test suite
uv run -m pytest tests/ -v

# All-in-one
just
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- **No prompt/response logging in factory-generated handlers** — this is intentional. The LLM layer (`run_prompt` / `ClaudeCodeAgent`) already logs at appropriate levels. Dropping the `runner.logger.info(f"... prompt/response ...")` lines from the 6 refactored handlers is a deliberate break from their current pattern.
- **`commit` excluded** — it calls `latest_commit()` after `run_prompt` and uses the result in state. This post-run logic doesn't fit either factory mode. Keep it hand-written.
- **`healthcheck` excluded** — it logs and posts the raw response. Neither mode covers this.
- **Error handling is new** — existing handlers let exceptions propagate uncaught. The factory routes `AgentExecutionError`, `ValueError`, and `KeyError` through `runner.fail()`, which reports via the channel before raising `WorkflowFailedError`. This is strictly better behaviour.
- **Progress message format standardised** — existing handlers use inconsistent formats ("Running /specify", "Deriving feature metadata", "Running git push"). Factory standardises to "Running {label}" / "{label} complete".

## Report

**Files changed**: `src/antkeeper/handlers/claude_code/factories.py` (new), `src/antkeeper/handlers/claude_code/__init__.py` (refactor 6 handlers)
**Tests added**: `tests/handlers/test_factories.py` (new) — ~14 test cases covering validation, simple mode, JSON mode, labels, error handling, edge cases
**Validations**: ruff, ty, pytest (full suite), just
