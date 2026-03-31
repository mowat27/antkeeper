# feature: Agent data streaming via JSONL with middleware pipeline

- Switch `ClaudeCodeAgent` from buffered JSON (`subprocess.run`) to streamed JSONL (`subprocess.Popen`) yielding `StreamEvent`s
- Unify channel reporting into single `report(run_id, event)` method; Runner convenience methods unchanged for handlers
- Route events through composable middleware pipeline; extraction step becomes middleware not special-cased logic

## Solution Design

### External Interface Change

**Channels** gain a single `report(run_id, event)` method replacing `report_progress` and `report_error`. Each channel decides rendering based on `event.type` and `event.internal`:

- **CLI**: progress/error print as today (error to stderr). `assistant` and `tool` suppressed unless verbose mode added later. `result` logs usage from metadata.
- **Slack**: progress posts to thread. Error posts with `[ERROR]` prefix. Internal events suppressed.
- **API**: progress/error print as today (error to stderr). Internal events suppressed.

**Runner** keeps `report_progress(message)` and `report_error(message)` unchanged. Hand-written handlers calling `runner.report_progress("msg")` continue to work without changes. Internally, these construct a `StreamEvent` and call `channel.report()`.

**Hand-written handlers** that call `run_prompt()` directly (e.g. `healthcheck`) must update: `run_prompt` now returns `Iterator[StreamEvent]`. Use `collect_result()` to get `(result_text, all_events)`.

### Architectural Schema Changes

```yaml
types:
  StreamEvent:
    kind: dataclass
    module: antkeeper.core.domain
    fields:
      - type: str           # "progress", "assistant", "tool", "result", "rate_limit", "error"
      - content: str         # human-readable payload
      - metadata: "dict[str, Any] | None"  # structured data (usage, cost, rate limit fields)
      - internal: bool       # True for housekeeping calls (e.g. extraction step)
    defaults:
      metadata: None
      internal: False

  Channel:
    kind: protocol
    module: antkeeper.core.domain
    attributes:
      - type: str
      - workflow_name: str
      - initial_state: State
    methods:
      - report(run_id: str, event: StreamEvent) -> None  # replaces report_progress + report_error

  Agent:
    kind: protocol
    module: antkeeper.llm.__init__
    methods:
      - prompt(prompt: str) -> "Iterator[StreamEvent]"  # was -> str

  Middleware:
    kind: type_alias
    module: antkeeper.handlers.claude_code.factories
    definition: "Callable[[Iterator[StreamEvent]], Iterator[StreamEvent]]"
```

## Relevant Files

- `src/antkeeper/core/domain.py` — add `StreamEvent` dataclass; replace `report_progress`/`report_error` on `Channel` protocol with `report()`
- `src/antkeeper/llm/__init__.py` — update `Agent` protocol: `prompt()` returns `Iterator[StreamEvent]`
- `src/antkeeper/llm/claude_code.py` — rewrite `ClaudeCodeAgent.prompt()` to use `Popen` + JSONL yielding `StreamEvent`s; change `run_prompt()` to return `Iterator[StreamEvent]`; add `collect_result()` utility
- `src/antkeeper/llm/errors.py` — no changes needed (AgentExecutionError unchanged)
- `src/antkeeper/core/runner.py` — update `report_progress`/`report_error` to construct `StreamEvent` and call `channel.report()`
- `src/antkeeper/channels/cli.py` — replace `report_progress`/`report_error` with `report()`
- `src/antkeeper/channels/api.py` — replace `report_progress`/`report_error` with `report()`
- `src/antkeeper/channels/slack.py` — replace `report_progress`/`report_error` with `report()`
- `src/antkeeper/handlers/claude_code/factories.py` — rewrite `cc_handler` to use streaming pipeline with middleware; add `Middleware` type alias, `build_pipeline()`, and extraction middleware
- `handlers.py` — update `healthcheck` handler to use `collect_result()` with `run_prompt()`
- `tests/conftest.py` — update `TestChannel`: replace `report_progress`/`report_error` with `report()`, add `events` list, maintain `progress_messages`/`error_messages` for backward compat

### New Files

- `tests/llm/test_middleware.py` — tests for `build_pipeline()` and extraction middleware

## Workflow

### Step 1: Add StreamEvent to domain and update Channel protocol

- Add `StreamEvent` dataclass to `src/antkeeper/core/domain.py` with fields: `type: str`, `content: str`, `metadata: dict[str, Any] | None = None`, `internal: bool = False`
- Add `from dataclasses import dataclass` and update `typing` imports
- Replace `report_progress` and `report_error` methods on `Channel` protocol with single `report(self, run_id: str, event: StreamEvent) -> None`
- Update `Agent` protocol in `src/antkeeper/llm/__init__.py`: change return type of `prompt()` from `str` to `Iterator[StreamEvent]`

### Step 2: Update Runner convenience methods

- In `src/antkeeper/core/runner.py`, update `report_progress()` to construct `StreamEvent(type="progress", content=message)` and call `self.channel.report(self.id, event)`
- Update `report_error()` to construct `StreamEvent(type="error", content=message)` and call `self.channel.report(self.id, event)`
- Method signatures on Runner remain unchanged: `report_progress(self, message: str)` and `report_error(self, message: str)`
- Add import of `StreamEvent` from `antkeeper.core.domain`

### Step 3: Update all channel implementations

- **CliChannel** (`src/antkeeper/channels/cli.py`): Remove `report_progress` and `report_error`. Add `report(self, run_id: str, event: StreamEvent) -> None` that:
  - Suppresses internal events (return early if `event.internal`)
  - Formats message as `[{workflow_name}, {run_id}] {event.content}`
  - Prints to `sys.stderr` if `event.type == "error"`, otherwise to stdout
- **ApiChannel** (`src/antkeeper/channels/api.py`): Same pattern as CliChannel
- **SlackChannel** (`src/antkeeper/channels/slack.py`): Remove `report_progress` and `report_error`. Add `report()` that:
  - Suppresses internal events
  - Adds `[ERROR] ` prefix for error events
  - Posts via `_post_to_thread()`
- **TestChannel** (`tests/conftest.py`): Remove `report_progress` and `report_error`. Add `report()` that:
  - Appends to `self.progress_messages` for non-error events (backward compat)
  - Appends to `self.error_messages` for error events (backward compat)
  - Appends all events to a new `self.events: list[StreamEvent]` attribute
  - Add `events` list initialisation in `__init__`

### Step 4: Rewrite ClaudeCodeAgent for streaming

- In `src/antkeeper/llm/claude_code.py`, change `prompt()` to return `Iterator[StreamEvent]`:
  - Replace `--output-format json` with `--output-format stream-json` in command construction
  - Replace `subprocess.run` with `subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, env=env)`
  - **OTel span management**: Use manual span management, NOT `with start_as_current_span` across yields. Start span before Popen, use `try/finally` in the generator to ensure `span.end()` is called and `proc.kill(); proc.wait()` on incomplete consumption:
    ```
    span = tracer.start_span("antkeeper.llm.call", attributes={...})
    ctx = trace.set_span_in_context(span)
    token = context.attach(ctx)
    try:
        proc = Popen(...)
        for line in proc.stdout:
            event = _parse_jsonl_line(line)
            if event.type == "result":
                # set span attributes from metadata before yielding
                _set_span_telemetry(span, event.metadata)
            yield event
        proc.wait()
        if proc.returncode != 0:
            raise AgentExecutionError(...)
    except Exception as exc:
        span.set_status(StatusCode.ERROR)
        span.record_exception(exc)
        raise
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        span.end()
        context.detach(token)
    ```
  - **JSONL line parsing**: Add `_parse_jsonl_line(line: str) -> StreamEvent` helper that:
    - Parses JSON from the line
    - Maps Claude event types to StreamEvent types: `assistant` text deltas -> `type="assistant"`, `system` events -> `type="tool"`, `result` -> `type="result"` with usage/cost/session_id in metadata, rate limit events -> `type="rate_limit"` with capacity in metadata
    - Raises `ValueError` on malformed JSON (fail immediately, consistent with current behaviour)
    - Logs and skips unknown event types (yield nothing for unrecognised types)
  - **Error semantics**: `FileNotFoundError` from `Popen()` constructor -> `AgentExecutionError` (same as today). Non-zero exit after stream consumed -> `AgentExecutionError` raised from generator `finally`/post-loop. Malformed JSONL -> `ValueError` raised immediately.

- Change `run_prompt()` to return `Iterator[StreamEvent]` instead of `str`. It remains a thin wrapper creating `ClaudeCodeAgent(model=model, yolo=True, opts=opts)` and returning `agent.prompt(prompt)`.

- Add `collect_result()` function:
  ```python
  def collect_result(events: Iterator[StreamEvent]) -> tuple[str, list[StreamEvent]]:
      """Consume an event stream, returning (result_text, all_events)."""
      all_events: list[StreamEvent] = []
      result_text = ""
      for event in events:
          all_events.append(event)
          if event.type == "result" and not event.internal:
              result_text = event.content
      return result_text, all_events
  ```

### Step 5: Rewrite cc_handler with middleware pipeline

- In `src/antkeeper/handlers/claude_code/factories.py`:
  - Add `Middleware` type alias: `Middleware = Callable[[Iterator[StreamEvent]], Iterator[StreamEvent]]`
  - Add `build_pipeline()`:
    ```python
    def build_pipeline(stream: Iterator[StreamEvent], middlewares: list[Middleware]) -> Iterator[StreamEvent]:
        for mw in middlewares:
            stream = mw(stream)
        return stream
    ```
  - Add extraction middleware factory function:
    ```python
    def _extraction_middleware(required_fields: list[str], logger: logging.Logger, model_opts: tuple[str, list[str] | None]) -> Middleware:
        def middleware(stream: Iterator[StreamEvent]) -> Iterator[StreamEvent]:
            for event in stream:
                yield event
                if event.type == "result":
                    extraction_stream = run_prompt(
                        _extraction_prompt(event.content, required_fields=required_fields),
                        logger,
                        model=_EXTRACTION_MODEL,
                        opts=["--max-turns", "1"],
                    )
                    for ext_event in extraction_stream:
                        yield StreamEvent(
                            type=ext_event.type,
                            content=ext_event.content,
                            metadata=ext_event.metadata,
                            internal=True,
                        )
        return middleware
    ```
  - Rewrite `handler()` inner function in `cc_handler`:
    - Import `ClaudeCodeAgent` and `StreamEvent`
    - Create agent directly: `agent = ClaudeCodeAgent(model=effective_model, yolo=True)`
    - Get stream: `stream = agent.prompt(prompt)`
    - Build middleware: if `state_updates`, add extraction middleware
    - Build pipeline: `pipeline = build_pipeline(stream, middlewares)`
    - Iterate pipeline in `try/finally` (calling `pipeline.close()` on error to ensure generator cleanup):
      - Forward each event to `runner.channel.report(runner.id, event)`
      - Collect primary result: if `event.type == "result" and not event.internal` -> save `event.content`
      - Collect extraction result: if `event.type == "result" and event.internal` -> parse with `extract_json(event.content)`
    - After iteration: if `state_updates` and no extraction result, treat as error (consistent with current KeyError handling)
    - Return `{**state, **result}`

### Step 6: Update hand-written handlers

- In `handlers.py`, update `healthcheck`:
  - Import `collect_result` from `antkeeper.llm.claude_code`
  - Change `response = run_prompt(...)` to:
    ```python
    response, _events = collect_result(run_prompt(...))
    ```

### Step 7: Update tests

- **`tests/conftest.py`**: Already updated in Step 3
- **`tests/llm/test_claude_code_agent.py`**: Replace `subprocess.run` mocking with `subprocess.Popen` mocking. Use a helper that returns a mock with iterable `stdout` and `wait()` returning 0. Update all assertions from `agent.prompt() -> str` to consuming `Iterator[StreamEvent]`. Update OTel span tests for manual span management.
- **`tests/llm/test_run_prompt.py`**: Update to expect `Iterator[StreamEvent]` return type. Add tests for `collect_result()`.
- **`tests/handlers/test_factories.py`**: Update mocking from `run_prompt -> str` to streaming. Test middleware pipeline integration. Test that events are forwarded to channel. Test extraction middleware produces internal events. Test error propagation.
- **`tests/channels/test_cli_channel.py`**: Replace `report_progress`/`report_error` tests with `report()` tests using `StreamEvent` instances.
- **`tests/channels/test_api_channel.py`**: Same pattern.
- **`tests/channels/test_slack_channel.py`**: Same pattern. Add test for internal event suppression.
- **`tests/test_tracing.py`**: Update subprocess mock and return type expectations.
- **`tests/llm/test_middleware.py`** (new): Tests for `build_pipeline` and extraction middleware (see Testing Strategy).

### Step 8: Validate

- Run all validation commands below

## Testing Strategy

### Unit Tests

**StreamEvent** (in existing domain tests or `test_claude_code_agent.py`):
- Construction with all fields
- Default values (`metadata=None`, `internal=False`)

**ClaudeCodeAgent streaming** (`tests/llm/test_claude_code_agent.py`):
- Mock `subprocess.Popen` with iterable stdout yielding JSONL lines
- `test_prompt_returns_iterator_of_stream_events` — consuming the iterator yields `StreamEvent` instances
- `test_prompt_parses_assistant_events` — assistant JSONL lines become `type="assistant"` events
- `test_prompt_parses_result_event` — result envelope becomes `type="result"` with metadata
- `test_prompt_non_zero_exit_raises` — non-zero exit code raises `AgentExecutionError`
- `test_prompt_binary_not_found` — `FileNotFoundError` from Popen raises `AgentExecutionError`
- `test_prompt_malformed_jsonl_raises` — bad JSON raises `ValueError`
- `test_output_format_stream_json_flag` — verify `--output-format stream-json` in Popen args
- `test_otel_span_attributes_from_result` — span has session_id, cost, token counts from result metadata
- `test_otel_span_closed_on_incomplete_consumption` — generator close triggers span.end()

**collect_result** (`tests/llm/test_run_prompt.py`):
- `test_collect_result_returns_text_and_events` — consumes stream, returns (text, events)
- `test_collect_result_empty_stream` — returns ("", [])
- `test_collect_result_ignores_internal_result` — only non-internal result used as text

**Middleware** (`tests/llm/test_middleware.py` — new file):
- `test_build_pipeline_no_middlewares` — identity pass-through
- `test_build_pipeline_single_middleware` — transforms stream
- `test_build_pipeline_sequential_order` — middlewares applied left-to-right
- `test_extraction_middleware_intercepts_result` — triggers extraction on result event
- `test_extraction_middleware_splices_internal_events` — extraction events have `internal=True`
- `test_extraction_middleware_passes_non_result_events` — progress events unchanged
- `test_extraction_middleware_error_propagates` — extraction failure propagates as exception

**Channels** (update existing test files):
- Each channel: `test_report_progress_event`, `test_report_error_event`, `test_report_internal_event_suppressed`
- SlackChannel: `test_report_survives_http_failure`

**Runner** (update existing tests):
- `test_report_progress_constructs_stream_event` — calls `channel.report()` with progress StreamEvent
- `test_report_error_constructs_stream_event` — calls `channel.report()` with error StreamEvent

**cc_handler** (`tests/handlers/test_factories.py`):
- `test_fire_and_forget_consumes_stream` — stream consumed, state returned unchanged
- `test_extraction_mode_uses_pipeline` — two agent calls, extraction result merged into state
- `test_events_forwarded_to_channel` — channel receives events during handler execution
- `test_agent_error_raises_workflow_failed` — `AgentExecutionError` from stream -> `WorkflowFailedError`
- `test_generator_cleanup_on_error` — pipeline.close() called on failure

### Integration

- `test_handler_with_streaming_agent_in_runner` — full flow: handler uses streaming agent, events reach TestChannel, state correct
- `test_multi_step_workflow_streaming` — two streaming steps via `run_workflow`, both complete, channel captures all events

### Edge Cases

- Empty JSONL stream (process exits 0 with no output) -> empty iterator, no result
- Process killed mid-stream -> generator finally cleans up Popen, span closed
- Extraction middleware receives no result event -> no extraction triggered, fire-and-forget behaviour
- Multiple result events in stream -> last non-internal result used (defensive)
- Very large JSONL line -> parsed normally (no line length limit)

## Acceptance Criteria

- `ClaudeCodeAgent.prompt()` returns `Iterator[StreamEvent]` and reads `--output-format stream-json` JSONL from `subprocess.Popen`
- All JSONL event types (assistant, tool, result, rate_limit) are mapped to `StreamEvent` with correct type, content, and metadata
- OTel spans are correctly opened before streaming and closed in `finally` with telemetry attributes from the result event
- Subprocess is killed and waited on if the iterator is not fully consumed (no process leaks)
- Channel protocol has single `report(run_id, event)` method; all four channel implementations updated
- Runner `report_progress` and `report_error` signatures unchanged; internally delegate to `channel.report()` via StreamEvent
- `cc_handler` uses middleware pipeline; extraction is implemented as middleware yielding internal events
- `collect_result()` utility consumes an event stream and returns `(result_text, all_events)`
- `handlers.py` healthcheck uses `collect_result()` with `run_prompt()`
- All existing tests updated; new middleware tests added
- Zero test failures, zero lint errors, zero type errors

### Validation Commands

```bash
# Run all tests
uv run pytest

# Lint
uv run ruff check src tests handlers.py

# Type check
uv run ty check

# Shorthand: run all checks via just
just
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The `--output-format stream-json` flag is the Claude CLI's JSONL streaming mode. Each line is a self-contained JSON object with a `type` field. Verify exact event schema against Claude CLI docs during implementation.
- The `Agent` protocol in `src/antkeeper/llm/__init__.py` changes from `-> str` to `-> Iterator[StreamEvent]`. Any future agent implementation (PI, etc.) must yield `StreamEvent`s. Non-streaming agents can yield a single `type="result"` event.
- Natural backpressure exists: if channel.report() is slow (e.g. Slack HTTP), Popen stdout pipe buffer fills and the subprocess blocks on write. This is acceptable behaviour, not a bug.
- The `Middleware` type alias and `build_pipeline` live in `factories.py` alongside the extraction middleware — no new module for pipeline infrastructure. If more middleware is added later, extraction to a separate module is trivial.

## Report

**Files changed**: `domain.py`, `runner.py`, `cli.py`, `api.py`, `slack.py`, `claude_code.py`, `llm/__init__.py`, `factories.py`, `handlers.py`, `conftest.py`
**New files**: `tests/llm/test_middleware.py`
**Tests added**: ~30 new/updated test cases covering StreamEvent, streaming agent, collect_result, middleware pipeline, extraction middleware, channel.report(), runner delegation, cc_handler pipeline integration
**Validations**: `uv run pytest`, `uv run ruff check`, `uv run ty check`, `just`
