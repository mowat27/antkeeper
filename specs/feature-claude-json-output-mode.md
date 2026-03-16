# feature: Claude Code JSON output mode with session logging

- Add `--output-format json` to `claude -p` to fix process hang and parse structured envelope.
- Log `session_id` and telemetry (`duration_ms`, `usage`, `total_cost_usd`) at DEBUG level.
- Return `data["result"]` string; raise `ValueError` for unparseable or missing-field responses.

## Solution Design

### External Interface Change

No change to the `Agent` protocol or any public API. `ClaudeCodeAgent.prompt(str) -> str` remains identical from callers' perspective. The returned string is now sourced from `data["result"]` inside the JSON envelope rather than raw stdout.

### Architectural Schema Changes

No type or interface changes. The `Agent` protocol and `AgentContext` dataclass are unchanged.

### Internal Change to `ClaudeCodeAgent.prompt()`

1. Add `["--output-format", "json"]` to the command, guarded by `if "--output-format" not in opts_list` (matching the existing `--model` and `--dangerously-skip-permissions` guard pattern).
2. Parse `result.stdout` with `json.loads`.
3. Log `session_id`, `duration_ms`, `usage`, `total_cost_usd` at DEBUG (all via `.get()` since fields may be absent).
4. Return `data["result"]` (raises `KeyError` if absent — caught and re-raised as `ValueError`).
5. On `json.JSONDecodeError` or `KeyError` on `"result"`: raise `ValueError` with a message that includes a truncated excerpt of `result.stdout` for diagnostics. Do **not** use `AgentExecutionError` — that class is scoped to subprocess execution failures (non-zero exit, binary not found) and callers rely on that distinction.

## Relevant Files

- `src/antkeeper/llm/claude_code.py` — the only production file changing; `prompt()` method is modified.
- `tests/llm/test_claude_code_agent.py` — existing tests need mock stdout updated to valid JSON envelopes; new tests to be added.

## Workflow

### Step 1: Update `ClaudeCodeAgent.prompt()` in `claude_code.py`

- Add the output-format guard immediately before the `"-p"` flag (consistent position with other flag guards).
- After `subprocess.run(...)`, wrap the following in a try/except:
  - `data = json.loads(result.stdout)` — on `json.JSONDecodeError` raise `ValueError(f"Claude returned non-JSON output: {result.stdout[:200]!r}")`
  - `return data["result"]` — on `KeyError` raise `ValueError(f"Claude JSON envelope missing 'result' field: {result.stdout[:200]!r}")`
- Before the return, log at DEBUG:
  ```python
  self.logger.debug("LLM session_id=%s duration_ms=%s usage=%s cost=%s",
                    data.get("session_id"), data.get("duration_ms"),
                    data.get("usage"), data.get("total_cost_usd"))
  ```
- Update the `prompt()` docstring: Returns section → "The `result` field from the Claude JSON envelope." Raises section → add `ValueError` for parse/missing-field errors.
- Update the existing `self.logger.debug("LLM response received ...")` line to use `len(data["result"])` instead of `len(result.stdout)`.

### Step 2: Update existing tests in `test_claude_code_agent.py`

Update all tests that mock `subprocess.run` with `stdout="..."` — replace plain strings with a valid JSON envelope. Use a module-level helper:

```python
def _envelope(result="ok", session_id="s1", duration_ms=100, usage=None, total_cost_usd=0.0):
    return json.dumps({
        "type": "result", "subtype": "success",
        "result": result, "session_id": session_id,
        "duration_ms": duration_ms, "usage": usage or {},
        "total_cost_usd": total_cost_usd,
    })
```

Tests to update:
- `test_successful_prompt_returns_stdout` — update mock stdout and assertion.
- `test_model_passed_to_subprocess` — update mock stdout.
- `test_no_model_omits_flag` — update mock stdout.
- `test_empty_prompt_passed_through` — update mock stdout and update command assertion to include `--output-format json`.
- `test_yolo_adds_permissions_flag` — update mock stdout.
- `test_opts_passed_to_command` — update mock stdout and update expected command list.
- `test_opts_override_convenience_params` — update mock stdout and expected command list.

### Step 3: Add new tests in `test_claude_code_agent.py`

- `test_output_format_json_flag_always_present` — assert `["--output-format", "json"]` appear consecutively in subprocess call args.
- `test_output_format_not_duplicated_when_in_opts` — pass `opts=["--output-format", "json"]`; assert flag appears only once in call args.
- `test_successful_prompt_returns_result_field` — mock full envelope, assert return value is `data["result"]`.
- `test_invalid_json_raises_value_error` — mock `stdout="not json"`, assert `pytest.raises(ValueError)`.
- `test_missing_result_key_raises_value_error` — mock stdout with envelope missing `"result"`, assert `pytest.raises(ValueError)`.
- `test_telemetry_logged_at_debug` — use `caplog.set_level(logging.DEBUG, logger="antkeeper.llm.claude_code")`; assert debug records contain `session_id` value and `duration_ms` value.
- `test_empty_result_string_returned` — mock envelope with `"result": ""`; assert `agent.prompt("x") == ""`.
- `test_missing_session_id_does_not_raise` — mock envelope without `"session_id"`; assert call succeeds without error.
- `test_none_total_cost_does_not_raise` — mock envelope with `"total_cost_usd": null`; assert no error.

### Step 4: Run validation commands

```bash
cd /Users/adrian/code/mowat27/precision-weave/antkeeper
uv run pytest tests/llm/test_claude_code_agent.py -v
uv run pytest --tb=short
uv run ruff check src/
uv run ty check src/
```

All must pass with zero errors and zero warnings.

## Testing Strategy

### Unit Tests

All tests patch `subprocess.run` at the boundary — no real subprocess invocations.

- One test per code path: JSON parse success, `JSONDecodeError`, missing `"result"` key.
- Existing tests updated to use `_envelope()` helper for mock stdout.
- Logging tests use `caplog` (pytest built-in); no manual logger patching needed.

### Integration

None required — the change is entirely internal to `ClaudeCodeAgent.prompt()`.

### Edge Cases

- `"result": ""` — empty string is a valid result; must not be treated as falsy and rejected.
- `session_id` absent from envelope — logging must use `.get()` and not raise `KeyError`.
- `total_cost_usd: null` — `.get()` handles this; no crash.
- Non-JSON prefix/suffix in stdout — `JSONDecodeError` is caught; error message includes truncated raw stdout.
- User passes `--output-format` in `opts` — guard prevents duplication; wrong format value is user's responsibility.

## Acceptance Criteria

- `ClaudeCodeAgent.prompt()` adds `--output-format json` to every command unless already present in `opts`.
- Returns the `"result"` string from the parsed JSON envelope (not raw stdout).
- Logs `session_id`, `duration_ms`, `usage`, `total_cost_usd` at DEBUG level.
- Raises `ValueError` (not `AgentExecutionError`) for JSON parse failures or missing `"result"` key.
- All existing tests pass with mock stdout updated to valid JSON envelopes.
- All new tests pass.
- Zero ruff lint errors. Zero ty type errors.

### Validation Commands

```bash
# All tests must pass
uv run pytest --tb=short

# Targeted tests for this change
uv run pytest tests/llm/test_claude_code_agent.py -v

# Lint
uv run ruff check src/

# Type check
uv run ty check src/
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on.

## Notes

- The process hang (issue 27) is eliminated by JSON output mode's cleaner exit behaviour — no timeout is required.
- `AgentExecutionError` must remain scoped to subprocess execution failures; `ValueError` is the established convention for unparseable/missing-field JSON responses (consistent with the `cc_handler` factory's error taxonomy).
- `session_id` is logged at DEBUG (not INFO) — consistent with other telemetry fields and avoids writing linkable identifiers to INFO-level log aggregators.
- The `run_prompt` convenience wrapper and `cc_handler` factory are unaffected — they consume the `str` return value of `prompt()` which is unchanged.

## Report

**Spec file**: `specs/feature-claude-json-output-mode.md`

**Design**: Single-method change to `ClaudeCodeAgent.prompt()` in `claude_code.py`. Adds `--output-format json` flag, parses JSON envelope, logs telemetry at DEBUG, returns `data["result"]`.

**Agent observations**:
- Designer identified that issues 22 and 27 are solved by the same one-line command change.
- Craig confirmed the solution is appropriately minimal with no unnecessary abstractions.
- Eduard flagged two standards violations in the initial design: (1) `AgentExecutionError` should be `ValueError` for parse failures — `AgentExecutionError` is scoped to subprocess failures and the factory layer distinguishes them; (2) `session_id` should log at DEBUG not INFO to match the telemetry convention and avoid logging linkable identifiers at INFO level. Both corrections applied.
- Tester identified 7 existing tests needing mock stdout updates and 9 new tests (including edge cases for empty result, missing session_id, and null cost).

**Trade-offs**: No timeout added — JSON mode's clean exit eliminates the hang per issue 27. Error message includes truncated raw stdout for diagnostics when JSON parsing fails.

**Files changed**: 1 production file (`claude_code.py`). **Tests added**: 9 new unit tests. **Tests updated**: 7 existing tests.
