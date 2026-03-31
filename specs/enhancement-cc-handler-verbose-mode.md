# enhancement: cc_handler verbose mode for event filtering

- Add `verbose: bool = False` optarg to `cc_handler()` controlling which events reach the channel.
- Default mode forwards only `result` and `error` events (high-level progress), suppressing blank lines from empty stream events.
- Verbose mode forwards all events with non-empty content, matching current behavior minus empty content.

## Solution Design

### External Interface Change

The `cc_handler` factory gains a `verbose` keyword argument. Channels see fewer events by default (only results and errors), or all non-empty events when verbose is enabled.

**CLI channel example:**
```python
# Default — clean output, no blank lines from assistant/tool chatter
specify = cc_handler("/specify $prompt", state_updates=["spec_file"])

# Verbose — see all LLM stream events (debugging, transparency)
specify = cc_handler("/specify $prompt", state_updates=["spec_file"], verbose=True)
```

**Slack channel example:**
```python
# Default — thread only shows result/error messages
implement = cc_handler("/implement $spec_file")

# Verbose — thread shows every assistant thought and tool use
implement = cc_handler("/implement $spec_file", verbose=True)
```

### Architectural Schema Changes

```yaml
types:
  # No changes to StreamEvent, Channel, Runner, or core types

functions:
  cc_handler:
    kind: factory
    module: antkeeper.handlers.claude_code.factories
    params:
      - command: str
      - state_updates: list[str] | None  # unchanged
      - label: str | None                # unchanged
      - model: str | None                # unchanged
      - env: dict[str, str] | None       # unchanged
      - verbose: bool  # NEW — default False
    returns: Handler

  _should_report:
    kind: private function
    module: antkeeper.handlers.claude_code.factories
    params:
      - event: StreamEvent
      - verbose: bool
    returns: bool
```

## Relevant Files

Use these files to implement the change:

- `src/antkeeper/handlers/claude_code/factories.py` — contains `cc_handler` factory and the event forwarding loop (line 225-226) that needs the filter. Add `verbose` param and `_should_report` helper here.
- `tests/handlers/test_factories.py` — all cc_handler tests. Two existing tests need updating; new tests needed for verbose/default filtering.

## Workflow

### Step 1: Add `_should_report` helper to factories.py

- Add a private module-level function `_should_report(event: StreamEvent, verbose: bool) -> bool` before `cc_handler`.
- Logic:
  ```python
  def _should_report(event: StreamEvent, verbose: bool) -> bool:
      if not event.content:
          return False
      if verbose:
          return True
      return event.type in ("result", "error")
  ```
- Empty content is always suppressed regardless of mode or event type.
- Default mode: only `result` and `error` with content pass through.
- Verbose mode: all events with content pass through.

### Step 2: Add `verbose` parameter to `cc_handler`

- Add `verbose: bool = False` to `cc_handler`'s keyword arguments (after `env`).
- Update the docstring to document the new parameter.

### Step 3: Apply filter in the event forwarding loop

- Change the event loop (currently line 225-226) from:
  ```python
  for event in pipeline:
      runner.channel.report(runner.id, event)
  ```
  to:
  ```python
  for event in pipeline:
      if _should_report(event, verbose):
          runner.channel.report(runner.id, event)
  ```
- The extraction logic at line 227-228 (`if event.type == "result" and event.internal`) must remain OUTSIDE the filter — extraction always processes internal results regardless of verbose mode. Move it to be a sibling condition in the loop, not nested inside the report condition.

### Step 4: Update existing tests

- `test_fire_and_forget_consumes_stream` (line 207): Change to pass `verbose=True` to `cc_handler` since its purpose is verifying stream consumption, not filtering behavior.
- `test_events_forwarded_to_channel` (line 253): Change to pass `verbose=True` to `cc_handler` since its purpose is verifying events reach the channel.

### Step 5: Add new tests

Add the following tests in a new section `# Verbose mode / event filtering`:

- `test_default_mode_forwards_result_events` — stream emits `assistant` + `result` with content; only `result` appears in `channel.events`.
- `test_default_mode_forwards_error_events` — stream emits `assistant` + `error` event with content; only `error` appears in `channel.events`.
- `test_default_mode_suppresses_assistant_events` — stream emits `assistant` + `result`; no `assistant` in `channel.events`.
- `test_default_mode_suppresses_tool_events` — stream emits `tool` + `result`; no `tool` in `channel.events`.
- `test_verbose_mode_forwards_all_event_types` — stream emits `assistant`, `tool`, `result` with content; all appear in `channel.events` when `verbose=True`.
- `test_empty_content_never_forwarded` — stream emits events with `content=""`; none appear in `channel.events` regardless of mode.
- `test_verbose_does_not_affect_state_return` — with `verbose=True`, fire-and-forget still returns state unchanged.

### Step 6: Run validation commands

- Run all validation commands listed below.

## Testing Strategy

### Unit Tests

Test `_should_report` as a pure function (no mocks needed):
- `result` event with content + `verbose=False` → True
- `error` event with content + `verbose=False` → True
- `assistant` event with content + `verbose=False` → False
- `tool` event with content + `verbose=False` → False
- `rate_limit` event with content + `verbose=False` → False
- Any event with content + `verbose=True` → True
- Any event with empty content + either mode → False

Test handler integration using existing mock patterns:
- Default mode: only result/error events in `channel.events`
- Verbose mode: all non-empty events in `channel.events`
- Extraction still works correctly in both modes

### Edge Cases

- Empty string content (`""`) — always filtered
- Verbose mode with extraction (state_updates): extraction still works, internal result events still processed
- `verbose=False` explicit matches default behavior
- Stream with only empty-content events: `channel.events` is empty

## Acceptance Criteria

- `cc_handler("/cmd")` forwards only `result` and `error` events with non-empty content to the channel.
- `cc_handler("/cmd", verbose=True)` forwards all events with non-empty content to the channel.
- Events with empty content are never forwarded regardless of verbose mode.
- Extraction mode continues to work correctly — internal result events are still processed for JSON extraction regardless of verbose setting.
- All existing tests pass (with the two noted updates).
- New tests cover both modes and edge cases.

### Validation Commands

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

```bash
# Run all tests
uv run pytest tests/ -v

# Run only handler tests
uv run pytest tests/handlers/test_factories.py -v

# Typecheck
uv run ty check src/ tests/

# Lint
uv run ruff check src/ tests/
```

## Notes

- The `_should_report` helper is intentionally a module-level private function (not a method) to match the existing pattern of `_extraction_prompt` and `_extraction_middleware` in the same file.
- Internal events (`event.internal=True`) are a pre-existing concern — they currently reach `channel.report()` in the existing code. This is out of scope for this change but noted for future consideration.
- The `--verbose` flag on `ClaudeCodeAgent` is unchanged — the agent still streams all events. Filtering is purely a cc_handler-level concern about what to report to the channel.

## Report

Report the following on completion:

- Files changed (with line-level summary of changes)
- Tests added (names and what they cover)
- Tests updated (names and what changed)
- Validation command results (all must pass with zero errors/warnings)
