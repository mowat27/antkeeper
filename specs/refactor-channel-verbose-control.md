# refactor: Move verbose control from handlers to channels

- Channels alone decide what to show and how to render based on their own verbose setting
- Handlers always forward all events unconditionally; remove `_should_report` and `collect_result`
- Non-verbose mode shows progress/error as plain text; verbose mode shows all events as JSON

## Solution Design

### External Interface Change

Channels gain a `verbose` constructor parameter (default `False`). This controls both **which event types** are displayed and **how they are rendered**.

**CliChannel** (`verbose=False`): only progress/error events, rendered as `event.content` plain text.
**CliChannel** (`verbose=True`): all events with content, rendered as `event.to_json()` JSON.

**ApiChannel** (`verbose=False`): only progress/error events, rendered as `event.content`.
**ApiChannel** (`verbose=True`): all events with content, rendered as `event.to_json()`.

**SlackChannel** (`verbose=False`): only progress/error events, rendered as `event.content`.
**SlackChannel** (`verbose=True`): all events with content, rendered as `event.content` (Slack always uses plain text due to thread readability constraints).

`cc_handler` factory loses its `verbose` parameter. All events are unconditionally forwarded to `runner.channel.report()`.

### Architectural Schema Changes

```yaml
types:
  CliChannel:
    kind: class
    fields:
      - type: str
      - workflow_name: str
      - initial_state: State
      - verbose: bool  # New field, default False

  ApiChannel:
    kind: class
    fields:
      - type: str
      - workflow_name: str
      - initial_state: State
      - verbose: bool  # New field, default False

  SlackChannel:
    kind: class
    fields:
      - type: str
      - workflow_name: str
      - initial_state: State
      - verbose: bool  # New field, default False

  cc_handler:
    kind: factory_function
    parameters:
      - command: str
      - state_updates: list[str] | None
      - label: str | None
      - model: str | None
      - env: dict[str, str] | None
      # verbose: REMOVED
      - opts: list[str] | None
      - yolo: bool
```

Note: The `Channel` protocol in `domain.py` is **unchanged**. `verbose` is a constructor concern for each implementation, not part of the `report()` protocol signature.

## Relevant Files

- `src/antkeeper/channels/cli.py` — add `verbose` param, change report to filter by event type and render as `event.content` (non-verbose) or `event.to_json()` (verbose)
- `src/antkeeper/channels/api.py` — add `verbose` param, same filtering/rendering logic as CLI
- `src/antkeeper/channels/slack.py` — add `verbose` param, same type filtering; always render as `event.content`
- `src/antkeeper/handlers/claude_code/factories.py` — remove `verbose` param, `_should_report` function; always forward events unconditionally
- `src/antkeeper/llm/claude_code.py` — remove `collect_result` function
- `.claude/commands/antkeeper/upgrade-handlers.md` — delete entire file
- `tests/handlers/test_factories.py` — remove `_should_report` tests and import; update integration tests
- `tests/llm/test_run_prompt.py` — remove `TestCollectResult` class and `collect_result` import
- `tests/channels/test_cli_channel.py` — update assertions for plain text rendering; add verbose mode tests
- `tests/channels/test_api_channel.py` — add verbose mode filtering/rendering tests
- `tests/channels/test_slack_channel.py` — add verbose mode filtering tests
- `app_docs/instrumentation.md` — update to reflect channel-level filtering instead of handler-level
- `app_docs/testing_policy.md` — remove references to `_should_report` and `collect_result` test patterns
- `app_docs/releasing.md` — remove `collect_result` from public API exports
- `app_docs/slack.md` — update references to event filtering
- `app_docs/README.md` — update references to `cc_handler` verbose and `collect_result`
- `.claude/skills/design-expert/self-improve.md` — update references
- `.claude/skills/antkeeper-architect/references/coding-standards.md` — update references

## Workflow

### Step 1: Update channel report methods

For each channel (`cli.py`, `api.py`, `slack.py`):

- Add `verbose: bool = False` parameter to `__init__`
- Store as `self.verbose`
- Update `report()` method with this logic:
  1. If `event.internal`, return (unchanged)
  2. If `not event.content`, return (guard moved here from `_should_report`)
  3. If `not self.verbose` and `event.type not in ("progress", "error")`, return
  4. Render: if `self.verbose`, use `event.to_json()`; else use `event.content`
  5. For **SlackChannel only**: always use `event.content` regardless of verbose (skip step 4 rendering switch)
- Keep existing output targets (stdout/stderr for CLI/API, Slack thread for Slack)
- Keep existing message prefix format (e.g. `[workflow, run_id]`)

### Step 2: Simplify cc_handler factory

In `src/antkeeper/handlers/claude_code/factories.py`:

- Remove the `_should_report` function entirely (lines 140-155)
- Remove the `verbose` parameter from `cc_handler` signature and its docstring
- Replace the conditional `if _should_report(event, verbose):` (line 264) with unconditional `runner.channel.report(runner.id, event)` — forward every event
- Update the module docstring to remove the paragraph about `verbose`

### Step 3: Remove collect_result

In `src/antkeeper/llm/claude_code.py`:

- Delete the `collect_result` function (lines 260-277)

### Step 4: Delete upgrade-handlers command

- Delete `.claude/commands/antkeeper/upgrade-handlers.md`

### Step 5: Update tests

**`tests/handlers/test_factories.py`:**
- Remove the `_should_report` import from line 27 (keep `cc_handler` import)
- Delete all `_should_report` unit tests (the `test_should_report_*` tests)
- Delete the verbose-mode integration tests (`test_default_mode_forwards_result_events`, `test_default_mode_forwards_error_events`, `test_default_mode_suppresses_assistant_events`, `test_default_mode_suppresses_tool_events`, `test_verbose_mode_forwards_all_event_types`, `test_empty_content_never_forwarded`, `test_verbose_does_not_affect_state_return`)
- Remove `verbose=True` from any remaining tests that used it (e.g. `test_fire_and_forget_consumes_stream`, `test_events_forwarded_to_channel`). These tests should still pass since events are now always forwarded.

**`tests/llm/test_run_prompt.py`:**
- Remove the `collect_result` import
- Delete the `TestCollectResult` class and all its test methods

**`tests/channels/test_cli_channel.py`:**
- Update existing `test_report_progress_event` to assert plain text output (`event.content`) instead of JSON (`event.to_json()`)
- Update existing `test_report_error_event` similarly
- Add: `test_verbose_false_suppresses_non_progress_non_error` — assistant/tool/result events produce no output
- Add: `test_verbose_true_shows_all_events_as_json` — all event types with content produce JSON output
- Add: `test_empty_content_suppressed` — events with empty content produce no output regardless of verbose
- Add: `test_verbose_defaults_to_false` — constructor default check

**`tests/channels/test_api_channel.py`:**
- Add same tests as CLI channel (verbose filtering and rendering)

**`tests/channels/test_slack_channel.py`:**
- Add: `test_verbose_false_suppresses_non_progress_non_error` — non-progress/error events produce no Slack API call
- Add: `test_verbose_true_shows_all_events_as_plain_text` — all event types posted, always as `event.content`
- Add: `test_empty_content_suppressed` — no Slack API call for empty content
- Add: `test_verbose_defaults_to_false`

### Step 6: Update documentation

Update these files to remove references to `_should_report`, `collect_result`, and handler-side verbose control. Replace with channel-side verbose descriptions where appropriate:

- `app_docs/instrumentation.md`
- `app_docs/testing_policy.md`
- `app_docs/releasing.md`
- `app_docs/slack.md`
- `app_docs/README.md`
- `.claude/skills/design-expert/self-improve.md`
- `.claude/skills/antkeeper-architect/references/coding-standards.md`

### Step 7: Validate

Run the validation commands below.

## Testing Strategy

### Unit Tests

**Channel filtering/rendering (per channel):**
- Verbose defaults to False
- Non-verbose mode: only progress and error events displayed, rendered as plain text (`event.content`)
- Verbose mode: all event types displayed; CLI/API render as JSON (`event.to_json()`), Slack renders as `event.content`
- Internal events suppressed in both modes
- Empty content suppressed in both modes

**Factory (cc_handler):**
- Events are unconditionally forwarded to `runner.channel.report()` — no filtering
- Existing fire-and-forget and extraction tests pass without `verbose` parameter

### Edge Cases

- Internal event with verbose=True: must still be suppressed
- Error event with empty content: suppressed (empty content guard takes precedence)
- rate_limit event (has empty content by default): suppressed by empty content guard
- Progress event from `runner.report_progress()`: passes through in both modes (type is "progress")

## Acceptance Criteria

- `_should_report` function no longer exists in `factories.py`
- `verbose` parameter no longer exists on `cc_handler`
- `collect_result` function no longer exists in `claude_code.py`
- `.claude/commands/antkeeper/upgrade-handlers.md` no longer exists
- Each channel constructor accepts `verbose: bool = False`
- Non-verbose channels show only progress/error events as plain text
- Verbose channels show all events; CLI/API use JSON format, Slack uses plain text
- All existing tests pass (with modifications) plus new channel verbose tests
- No references to `_should_report` or `collect_result` remain in docs

### Validation Commands

IMPORTANT: If any of the checks above fail you must investigate and fix the error.  It is not acceptable to simply explain away the problem.  You must reach zero errors, zero warnings before you move on.  This includes pre-existing issues and other issues that you don't think are related to this bugfix.

```bash
# Run all tests
uv run pytest

# Type checking
uv run ty check

# Linting
uv run ruff check src/ tests/

# Verify removals
grep -r "_should_report" src/ tests/ && echo "FAIL: _should_report still referenced" || echo "PASS: _should_report removed"
grep -r "collect_result" src/ tests/ && echo "FAIL: collect_result still referenced" || echo "PASS: collect_result removed"
test ! -f .claude/commands/antkeeper/upgrade-handlers.md && echo "PASS: upgrade-handlers command removed" || echo "FAIL: upgrade-handlers command still exists"

# Verify verbose not on cc_handler
grep -n "verbose" src/antkeeper/handlers/claude_code/factories.py && echo "FAIL: verbose still in factories" || echo "PASS: verbose removed from factories"

# Verify channels have verbose
grep -n "verbose" src/antkeeper/channels/cli.py src/antkeeper/channels/api.py src/antkeeper/channels/slack.py || echo "FAIL: verbose not added to channels"
```

## Notes

- The `Channel` protocol in `domain.py` is intentionally unchanged. `verbose` is a constructor-time configuration concern, not a protocol method concern. Test doubles (like `TestChannel`) should continue capturing all events unconditionally.
- State updates (extraction pipeline, field merging) in `cc_handler` are completely untouched. Only the event reporting path changes.
- Channel construction sites (`cli.py`, `webhook.py`, `slack_events.py`) default to `verbose=False` automatically. Adding a CLI `--verbose` flag or API parameter to enable verbose mode is out of scope.
- The `healthcheck` handler in `handlers.py` already forwards all events to the channel. No changes needed there — the channel now handles filtering.

## Report

Report after implementation:

- Files changed (list each with one-line summary of change)
- Files deleted
- Tests removed (count and reason)
- Tests added (count and what they cover)
- All validation commands pass with zero errors/warnings
