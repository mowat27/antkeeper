# bugfix: switch ClaudeCodeAgent to --output-format json

- `claude -p` hangs indefinitely when the process completes but fails to exit; JSON output mode forces a clean exit.
- Session ID is unavailable for log correlation; JSON envelope exposes it.
- Parse the JSON envelope, log `session_id` at INFO, return only `envelope["result"]`.

## Solution Design

### External Interface Change

`ClaudeCodeAgent.prompt()` continues to return `str` — callers see no change. The returned value is now `envelope["result"]` (the LLM's text response) instead of raw stdout. The `--output-format json` flag is appended automatically and can be suppressed by passing it in `opts`.

### Architectural Schema Changes

```yaml
types:
  ClaudeCodeAgent:
    kind: class
    methods:
      prompt:
        returns: str  # unchanged — now envelope["result"] instead of raw stdout
        raises:
          - AgentExecutionError: claude binary not found or non-zero exit code (unchanged)
          - ValueError: JSON parse failure or missing "result" key in envelope (new)
```

### No REST or Database Changes

## Relevant Files

- `src/antkeeper/llm/claude_code.py` — the file being changed; add `import json`, add `--output-format json` flag, parse envelope, log session_id, raise `ValueError` on bad envelope, move command debug log before subprocess call
- `tests/llm/test_claude_code_agent.py` — update existing tests (stdout mocks must now be valid JSON envelopes, command assertions must include `--output-format json`); add new tests

## Workflow

### Step 1: Update `claude_code.py`

- Add `import json` at the top (alongside existing `import logging` and `import subprocess`)
- Before `cmd.extend(opts_list)`, add the output-format flag with override guard:
  ```python
  if not any(o.startswith("--output-format") for o in opts_list):
      cmd.extend(["--output-format", "json"])
  ```
- Move `logger.debug(f"LLM subprocess command: {cmd}")` to **before** the `subprocess.run()` call (currently it is after, so it never fires on `FileNotFoundError`)
- After the non-zero returncode check, replace `return result.stdout` with:
  ```python
  try:
      envelope = json.loads(result.stdout)
      result_text = envelope["result"]
  except (json.JSONDecodeError, KeyError) as exc:
      raise ValueError(f"Failed to parse claude JSON output: {result.stdout!r}") from exc
  session_id = envelope.get("session_id")
  logger.info(f"LLM session_id: {session_id}")
  logger.info(f"LLM response received (length={len(result_text)} chars)")
  logger.debug(f"LLM response content: {result_text}")
  return result_text
  ```
- Remove the existing `logger.info(f"LLM response received ...")` and `logger.debug(f"LLM response content ...")` lines that reference `result.stdout` directly (they are replaced above)

### Step 2: Update existing tests in `TestClaudeCodeAgent`

All tests that set `stdout="..."` on the `CompletedProcess` mock must change to a valid JSON envelope. Use this minimal envelope constant at the top of the test module:

```python
ENVELOPE = '{"session_id": "test-session", "result": "ok", "duration_ms": 100, "usage": {}, "total_cost_usd": 0.0}'
```

For `test_successful_prompt_returns_stdout`: change `stdout="answer"` to a JSON envelope with `"result": "answer"`. The assertion `== "answer"` stays the same.

For `test_empty_prompt_passed_through`: change `stdout=""` to a JSON envelope with `"result": ""`. Update the expected command list to `["claude", "--output-format", "json", "-p", ""]`.

For `test_opts_passed_to_command`: update `stdout` to valid envelope; update expected command to `["claude", "--output-format", "json", "--verbose", "-p", "hello"]`.

For `test_opts_override_convenience_params`: update `stdout` to valid envelope; update expected command to `["claude", "--output-format", "json", "--model", "opus", "--dangerously-skip-permissions", "-p", "hello"]`.

For all other tests that only assert on command args (model, yolo): update `stdout` to valid envelope; no assertion changes needed.

### Step 3: Add new tests in `TestClaudeCodeAgent`

- **`test_output_format_json_added_to_command`** — normal call with no opts; assert `"--output-format"` and `"json"` appear consecutively in `call_args`
- **`test_output_format_not_duplicated_when_in_opts`** — pass `opts=["--output-format", "json"]`; assert `"--output-format"` appears exactly once in `call_args`
- **`test_output_format_startswith_guard`** — pass `opts=["--output-format=stream"]`; assert `"--output-format"` appears exactly once in `call_args` (the `=`-joined form is recognized by the guard)
- **`test_result_extracted_from_envelope`** — set `stdout` to a full envelope with `"result": "the answer"`; assert `agent.prompt(...)` returns `"the answer"` (not the full JSON string)
- **`test_invalid_json_raises_value_error`** — set `stdout` to `"not valid json"` with `returncode=0`; assert `ValueError` is raised
- **`test_missing_result_key_raises_value_error`** — set `stdout` to `'{"session_id": "s1"}'` (no `"result"` key) with `returncode=0`; assert `ValueError` is raised
- **`test_session_id_logged_at_info`** — use `caplog` at `logging.INFO` on `antkeeper.llm.claude_code`; assert a log record containing the session_id value from the envelope appears after a successful prompt

### Step 4: Run validation commands

```bash
just check
```

## Testing Strategy

### Unit Tests

All in `tests/llm/test_claude_code_agent.py`. Patch `antkeeper.llm.claude_code.subprocess.run`. All `stdout` values must be valid JSON envelopes after this change.

### Integration

None required — `TestIntegration` uses `FakeAgent` and is unaffected.

### Edge Cases

- `opts` containing `--output-format=json` (equals form) must not produce a duplicate flag
- `opts` containing `--output-format json` (space form) must not produce a duplicate flag
- Missing `session_id` in envelope must not raise — `envelope.get("session_id")` returns `None` and logs `None`
- Empty `result` field (`""`) must return empty string without raising

## Acceptance Criteria

- `claude -p` subprocess receives `--output-format json` in all invocations
- `agent.prompt()` returns the `result` field from the JSON envelope, not raw stdout
- `session_id` appears in an INFO-level log record after every successful prompt
- `ValueError` is raised (not `AgentExecutionError`) when the envelope cannot be parsed or lacks `"result"`
- Callers passing `--output-format` in `opts` (either form) suppress the automatic flag without duplication
- All existing tests pass with only the targeted modifications described above

### Validation Commands

```bash
just check
```

This runs linting (`ruff`), typechecking (`ty`), and the full test suite. Zero errors and zero warnings required.

## Notes

- `ValueError` for parse errors is intentional: the `cc_handler` factory (`factories.py:101`) already catches `ValueError` for unparseable LLM responses. Raising `AgentExecutionError` for a parse failure would conflate subprocess failures with response-format failures and violate the documented error taxonomy in `app_docs/instrumentation.md`.
- `run_prompt()` does not need changes — it delegates to `ClaudeCodeAgent` and its callers already receive a `str`. `test_run_prompt.py` does not need changes.
- `duration_ms`, `usage`, and `total_cost_usd` are available in the envelope but are not logged — no current operational use case justifies the noise.
- No timeout parameter is added — `--output-format json` resolves the hang by forcing a clean process exit.

## Report

Spec covers changes to two files:
- `src/antkeeper/llm/claude_code.py` — 4 changes: add `import json`; add `--output-format json` with `startswith` guard; move command debug log before subprocess call; replace raw stdout return with envelope parse, session_id logging, and `ValueError` on bad envelope
- `tests/llm/test_claude_code_agent.py` — update 7 existing tests (stdout mocks → valid JSON envelopes, command assertions include `--output-format json`); add 7 new tests covering flag injection, guard behaviour, result extraction, parse errors, and session_id logging

Validation: `just check` (lint + typecheck + full test suite, zero warnings).
