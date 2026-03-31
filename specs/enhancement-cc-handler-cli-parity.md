# enhancement: cc_handler factory CLI parity with prompt()

- Expose `opts` and `yolo` params in `cc_handler` factory, forwarding them to `ClaudeCodeAgent`
- Update antkeeper architect coding standards to document all Claude control options for both factory and hand-written handlers

## Solution Design

### External Interface Change

After this change, `cc_handler` supports two new keyword arguments:

```python
# Pass arbitrary CLI flags
specify = cc_handler("/specify $prompt", opts=["--max-turns", "1"])

# Disable permission skipping (default is True for backward compat)
careful = cc_handler("/review $pr_url", yolo=False)

# Combine both
custom = cc_handler("/deploy", opts=["--allowedTools", "Bash"], yolo=False)
```

Hand-written handlers already have full control via `run_prompt(prompt, logger, model=..., opts=...)` and direct `ClaudeCodeAgent(model=..., yolo=..., opts=...)` construction. No changes needed there — only documentation improvements.

### Architectural Schema Changes

```yaml
types:
  cc_handler:
    kind: factory_function
    params:
      - command: str                              # Required
      - state_updates: list[str] | None = None
      - label: str | None = None
      - model: str | None = None
      - env: dict[str, str] | None = None
      - opts: list[str] | None = None             # New
      - yolo: bool = True                          # New
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/factories.py` — contains `cc_handler` factory; add `opts` and `yolo` params, forward to `ClaudeCodeAgent` constructor
- `src/antkeeper/llm/claude_code.py` — contains `ClaudeCodeAgent` and `run_prompt`; read-only reference for how `opts` and `yolo` are handled (no changes needed)
- `tests/handlers/test_factories.py` — existing factory tests; update broken assertions and add new test cases
- `.claude/skills/antkeeper-architect/references/coding-standards.md` — architect skill reference; update signature, options table, and add `run_prompt` opts documentation

## Workflow

### Step 1: Update cc_handler factory signature

- Add `opts: list[str] | None = None` and `yolo: bool = True` keyword arguments to `cc_handler` in `src/antkeeper/handlers/claude_code/factories.py`
- Change the `ClaudeCodeAgent` construction inside the handler closure from `ClaudeCodeAgent(model=effective_model, yolo=True)` to `ClaudeCodeAgent(model=effective_model, yolo=yolo, opts=opts)`
- Update the `Args:` docstring block to document `opts` and `yolo`

### Step 2: Fix existing tests and add new test cases

- Update existing `assert_called_once_with` assertions in `tests/handlers/test_factories.py` that assert the old two-argument form — add `opts=None` to match the new call signature. Affected tests:
  - `test_extraction_always_uses_haiku`
  - `test_model_override_passed_to_agent`
  - `test_model_override_beats_state_model`
  - `test_no_model_override_falls_back_to_state`
- Add new test cases (see Testing Strategy below)

### Step 3: Update antkeeper architect coding standards

- In `.claude/skills/antkeeper-architect/references/coding-standards.md`:
  - Update the `cc_handler` full signature block (lines 92-101) to include `opts` and `yolo`
  - Add `opts` and `yolo` rows to the options table (lines 105-111)
  - In the "Stream events through the channel" section (line 188+), add a note that `run_prompt()` accepts `opts` for arbitrary CLI flags and that `ClaudeCodeAgent` accepts both `opts` and `yolo` for full control in hand-written handlers

### Step 4: Run validation commands

- Run all validation commands below and fix any failures

## Testing Strategy

### Unit Tests

All tests in `tests/handlers/test_factories.py`. Follow existing patterns: patch `antkeeper.handlers.claude_code.factories.ClaudeCodeAgent`, use `runner_factory()`, assert on `mock_agent_cls.assert_called_once_with(...)`.

**New test cases:**

1. `test_opts_forwarded_to_agent` — `cc_handler("/cmd", opts=["--max-turns", "5"])` results in `ClaudeCodeAgent(model=..., yolo=True, opts=["--max-turns", "5"])`
2. `test_opts_default_is_none` — `cc_handler("/cmd")` results in `opts=None` passed to agent
3. `test_yolo_default_is_true` — `cc_handler("/cmd")` results in `yolo=True` passed to agent
4. `test_yolo_false_forwarded_to_agent` — `cc_handler("/cmd", yolo=False)` results in `yolo=False` passed to agent
5. `test_opts_and_yolo_combined` — `cc_handler("/cmd", yolo=False, opts=["--verbose"])` results in both being forwarded
6. `test_opts_with_state_updates_mode` — in extraction mode, `opts` is forwarded to the primary `ClaudeCodeAgent` while extraction still uses its own hardcoded `["--max-turns", "1"]`

### Edge Cases

- `opts=[]` vs `opts=None` — empty list should be forwarded as-is, not converted to `None`
- Extraction middleware isolation — handler-level `opts` must not leak into the extraction `run_prompt` call

## Acceptance Criteria

- `cc_handler` accepts `opts` and `yolo` keyword arguments
- `opts` is forwarded verbatim to `ClaudeCodeAgent` constructor
- `yolo` defaults to `True` (backward compatible) and is forwarded to `ClaudeCodeAgent`
- Existing `cc_handler` calls work without modification
- Extraction middleware continues to use its own hardcoded opts for the extraction call
- Coding standards document reflects the new parameters for both `cc_handler` and hand-written handler patterns
- All tests pass, including updated existing tests and new test cases

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run pytest tests/ -x -q
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The `ClaudeCodeAgent` already handles flag deduplication internally — if `opts` contains `--model`, `--dangerously-skip-permissions`, `--output-format`, or `--verbose`, the agent skips adding those from its convenience params. This means `opts` can safely override any built-in flag without conflict.
- `run_prompt()` hardcodes `yolo=True` and does not expose it as a parameter. This is intentional — `run_prompt` is a convenience wrapper for the common case. Hand-written handlers that need `yolo=False` should construct `ClaudeCodeAgent` directly.

## Report

Report: files changed, tests added, validation results. Include the updated `cc_handler` signature and confirm backward compatibility is preserved. Max 200 words.
