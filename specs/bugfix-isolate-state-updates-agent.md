# bugfix: isolate state_updates commands in delegated agent

- When `cc_handler` has `state_updates`, the JSON extraction instruction competes with the command's own output instructions in the same context, causing unreliable output.
- Fix: all `state_updates` commands delegate to a sub-agent, giving clean context separation. One path, no branching on command type.
- Fire-and-forget handlers (no `state_updates`) are unaffected.

## Solution Design

### Architectural Schema Changes

```yaml
functions:
    _delegation_prompt:
      module: antkeeper.handlers.claude_code.factories
      visibility: private
      signature: "_delegation_prompt(command: str, *, required_fields: list[str]) -> str"
      purpose: "Build a prompt that delegates the command to a sub-agent and asks the outer agent to return JSON"

removed:
    json_prompt:
      module: antkeeper.helpers.json
      reason: "No longer consumed. Replaced by _delegation_prompt in the CC handler layer. Can be reintroduced if a generic consumer emerges."
```

### External Interface Change

No external interface changes. The `cc_handler` factory signature is unchanged. Callers see the same `(Runner, State) -> State` handler. The delegation is an internal implementation detail of how the prompt is structured when `state_updates` is set.

## Relevant Files

Use these files to fix the bug:

- `src/antkeeper/handlers/claude_code/factories.py` — Add private `_delegation_prompt` function. Replace `json_prompt` call in the `state_updates` branch with `_delegation_prompt`. Remove `json_prompt` import entirely.
- `src/antkeeper/helpers/json.py` — Delete `json_prompt` function. Keep `extract_json`.
- `src/antkeeper/helpers/__init__.py` — Remove `json_prompt` from imports and `__all__`. Update module docstring.
- `tests/handlers/test_factories.py` — Update and add tests for the delegation prompt path.
- `tests/helpers/test_json_prompt.py` — Delete this entire file (all tests are for `json_prompt`).

## Workflow

### Step 1: Add `_delegation_prompt` to factories.py

- Add `import json as _json` at the top of the module.
- Add a private module-level function `_delegation_prompt(command: str, *, required_fields: list[str]) -> str`.
- The function builds this exact prompt text:

```
Use an agent to run the following command:

{command}

Wait for the agent to finish. Then, using the agent's output, return ONLY a JSON object with these fields — no other text, no markdown fences, no explanation:

{json.dumps(example)}

Replace each placeholder with the actual value from the agent's output.
```

Where `example = {field: f"<{field}>" for field in required_fields}`.

### Step 2: Update the `state_updates` branch in `cc_handler`

- In the `handler` inner function, change the `state_updates` branch from:
  ```python
  if state_updates:
      prompt = json_prompt(prompt, required_fields=state_updates)
  ```
  to:
  ```python
  if state_updates:
      prompt = _delegation_prompt(prompt, required_fields=state_updates)
  ```
- Change the import line from `from antkeeper.helpers.json import json_prompt, extract_json` to `from antkeeper.helpers.json import extract_json`.

### Step 3: Remove `json_prompt`

- In `src/antkeeper/helpers/json.py`, delete the `json_prompt` function entirely. Keep `extract_json`.
- In `src/antkeeper/helpers/__init__.py`:
  - Remove `json_prompt` from the import line.
  - Remove `json_prompt` from `__all__`.
  - Remove the `json_prompt` line from the module docstring.
- Delete `tests/helpers/test_json_prompt.py` entirely.

### Step 4: Update factory tests

- **`tests/handlers/test_factories.py`**:
  - Rename `test_state_updates_wraps_prompt_with_json_prompt` to `test_state_updates_uses_delegation_prompt`. Update to verify the prompt passed to `run_prompt` contains `"Use an agent to run the following command"` and the interpolated command text.
  - Add `test_delegation_prompt_includes_required_fields` — verify all `state_updates` field names appear in the delegation prompt sent to `run_prompt`.
  - Add `test_delegation_prompt_non_slash_command` — verify a plain-text command (e.g. `"analyze $spec_file"`) with `state_updates` also uses the delegation prompt (same path, no branching).
  - Add `test_fire_and_forget_slash_command_no_delegation` — verify a slash command with no `state_updates` passes through unchanged (no delegation wrapper, no JSON instruction).

### Step 5: Run validation commands

- Run all checks to verify zero errors, zero warnings.

## Testing Strategy

### Unit Tests

**`_delegation_prompt` (tested indirectly via `cc_handler` factory tests)**:
- Any command with `state_updates` produces a delegation prompt containing `"Use an agent"`, the interpolated command, and all required field names.
- Fire-and-forget commands (no `state_updates`) pass the command through unchanged.

### Edge Cases

- Empty `state_updates` list (`[]`) — fire-and-forget, no delegation. Covered by existing `test_empty_list_state_updates_is_fire_and_forget`.
- Single field in `state_updates` — delegation prompt with one field in the JSON example.
- Command with `$var` placeholders — interpolation happens before delegation wrapping.
- Non-slash command with `state_updates` — same delegation path as slash commands.
- Command containing special characters (quotes, newlines) — command text appears verbatim in the delegation prompt.

## Acceptance Criteria

- All `cc_handler` handlers with `state_updates` use the delegation prompt — one code path, no command-type branching.
- Fire-and-forget handlers (no `state_updates`) are completely unaffected.
- `json_prompt` is fully removed from the codebase (function, imports, exports, tests).
- `extract_json` is unaffected and remains in `helpers/json.py`.
- All existing tests pass (updated where necessary).
- New tests cover the delegation path for both slash and non-slash commands.

### Validation Commands

```bash
# Run all tests
uv run -m pytest tests/ -v

# Lint
uv run ruff check .

# Type check
uv run ty check
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The delegation pattern adds a sub-agent spawn, which may increase latency and token usage slightly. This is acceptable given the reliability improvement — eliminates an entire class of competing-instruction failures.
- The `_delegation_prompt` function is private to `factories.py` because it is specific to Claude Code's agent spawning capability, per the owner's comment on issue #24: "this solution is specific to Claude Code."
- `json_prompt` is removed entirely rather than kept for hypothetical future consumers. If a generic JSON prompt helper is needed later, it can be built with better information about the actual use case.

## Report

Report: files changed, tests added/removed/updated, validations passed. Max 200 words.
