# feature: simplify cc_handler and add workflow progress

- Unify `cc_handler` to one mode: optional `state_updates` list replaces both `updates` and `json_fields`.
- Switch command interpolation from `{var}` to `$var` to avoid clashing with Python format strings.
- Track workflow progress (`_progress`) in state via `run_workflow`, replacing per-handler static status dicts.

## Solution Design

### External Interface Change

Handler definitions become simpler and consistent:

```python
# JSON extraction — parse response, merge named fields into state
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])

# Fire-and-forget — run command, no state merge
implement = cc_handler("/sdlc:implement $spec_file")
```

Workflow progress is automatically available in state after `run_workflow`:

```python
state["_progress"]  # {"total": 3, "completed": 3}
```

All channels (CLI, API, Slack) benefit because progress is in state — channels can inspect `_progress` if they choose to, or ignore it.

### Architectural Schema Changes

```yaml
types:
  cc_handler:
    kind: function
    params:
      - command: str           # $var placeholders interpolated from state
      - state_updates: list[str] | None  # JSON fields to extract (replaces updates + json_fields)
      - label: str | None      # progress label, defaults to first token
    returns: Callable[[Runner, State], State]

  run_workflow:
    kind: function
    params:
      - runner: Runner
      - state: State
      - steps: list[Callable]
    returns: State  # includes _progress: {"total": int, "completed": int}
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/factories.py` — cc_handler factory, main change target
- `src/antkeeper/core/app.py` — `run_workflow` function, add `_progress` tracking
- `handlers.py` — consumer of cc_handler, migrate syntax
- `src/antkeeper/handlers/claude_code/__init__.py` — consumer of cc_handler, migrate syntax
- `tests/handlers/test_factories.py` — factory unit tests, full rewrite
- `tests/core/test_workflows.py` — add `_progress` tests

## Workflow

### Step 1: Update cc_handler factory

- Change signature: remove `updates` and `json_fields`, add `state_updates: list[str] | None = None`
- Remove the mutual-exclusion `ValueError`
- Replace `command.format_map(state)` with `re.sub(r'\$([a-zA-Z_]\w*)', lambda m: str(state[m.group(1)]), command)`
- When `state_updates` is non-empty: wrap prompt with `json_prompt(prompt, required_fields=state_updates)`, parse response with `extract_json`, merge only named fields
- When `state_updates` is `None` or empty: call `run_prompt`, discard response, return state unchanged
- Ensure `result = {}` for the discard branch to avoid `UnboundLocalError`
- Error handling unchanged: `KeyError`, `AgentExecutionError`, `ValueError` caught and routed to `runner.fail()`

### Step 2: Add _progress to run_workflow

- Before the step loop: `state = {**state, "_progress": {"total": len(steps), "completed": 0}}`
- After each step completes: `progress = {**state["_progress"], "completed": state["_progress"]["completed"] + 1}` then `state = {**state, "_progress": progress}`
- No changes to `Runner.run()` — single handler runs have no `_progress` key

### Step 3: Migrate handlers.py

- Change all `{var}` to `$var` in command strings
- Replace `updates={"implement_status": "complete"}` with no argument (fire-and-forget)
- Replace `json_fields=[...]` with `state_updates=[...]`
- Remove unused imports (`extract_json`, `ClaudeCodeAgent`)

### Step 4: Migrate handlers/claude_code/__init__.py

- Same changes as Step 3: `{var}` → `$var`, `updates=` → remove, `json_fields=` → `state_updates=`

### Step 5: Rewrite factory tests

- Remove validation tests for old mutual-exclusion rule
- Add tests for:
  - `state_updates` mode: wraps with `json_prompt`, parses, merges named fields only
  - Fire-and-forget mode (no `state_updates`): runs command, returns state unchanged
  - Empty list `state_updates=[]` behaves same as `None`
  - `$var` interpolation from state
  - Multiple `$var` placeholders
  - No `$` tokens — command passes through unchanged
  - Missing state key for `$var` → `WorkflowFailedError`
  - `${var}` is NOT interpolated (left as literal text)
  - Label derivation (unchanged behaviour)
  - Error handling (AgentExecutionError, bad JSON, missing JSON field)

### Step 6: Add _progress tests

- `test_run_workflow_final_state_has_progress` — returned state has `_progress == {"total": N, "completed": N}`
- `test_run_workflow_progress_increments_per_step` — a capturing handler verifies `_progress["completed"]` increments
- `test_run_workflow_single_step_progress` — single step produces `{"total": 1, "completed": 1}`
- `test_single_handler_run_has_no_progress` — `Runner.run()` directly produces no `_progress` key

### Step 7: Validate

- Run all validation commands

## Testing Strategy

### Unit Tests

**Factory tests** (`tests/handlers/test_factories.py`):
- Mock `run_prompt` and `extract_json` at the factory module as per existing pattern
- Use `runner_factory()` with no arguments
- Test both modes: `state_updates` (JSON extraction) and fire-and-forget (no `state_updates`)
- Test `$var` interpolation: single, multiple, missing key, no vars, `${var}` not matched

**Workflow tests** (`tests/core/test_workflows.py`):
- Use existing `runner_factory` and `app` fixtures
- Define inline handlers that capture `state["_progress"]` to verify mid-workflow values

### Edge Cases

- `state_updates=[]` (empty list) behaves as fire-and-forget, same as `None`
- Command with no `$` placeholders passes through unchanged
- `$var` at end of string (no trailing space)
- `$var` where value is non-string (converted via `str()`)
- `${var}` left as literal text (not interpolated)
- Handler that returns state with `_progress` key — framework overwrites it on next step (acceptable; `_progress` is framework-managed)

## Acceptance Criteria

- `cc_handler` accepts `state_updates` parameter instead of `updates`/`json_fields`
- `cc_handler("/cmd $key")` interpolates `$key` from state
- `cc_handler("/cmd $key", state_updates=["f1"])` wraps with `json_prompt`, extracts `f1`
- `cc_handler("/cmd")` with no `state_updates` runs command and returns state unchanged
- `run_workflow` injects and increments `_progress` in state
- `Runner.run()` does not inject `_progress`
- All existing handler definitions migrated to new syntax
- Zero test failures, zero ruff warnings, zero ty errors

### Validation Commands

```bash
uv run -m pytest tests/ -v
uv run ruff check .
uv run ty check src/
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The `_progress` key uses underscore prefix to signal framework-managed data, consistent with `_persist_state` convention.
- No escape mechanism for literal `$` in commands. This is acceptable — current commands are slash commands and plain English, not shell scripts. Can be added later if needed.
- The `document` command in `handlers.py` has no `$var` placeholders — it's a static string and works unchanged.
- `_progress` will appear in persisted state JSON files. This is useful for debugging workflow execution.

## Report

Report: files changed, tests added/modified, validation results. Max 200 words.
