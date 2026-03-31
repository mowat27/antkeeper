# Testing Policy

## Philosophy

Test the framework, not the app. The core machinery (`antkeeper.core.*`) is the unit under test. User-defined handlers exist only as test data to exercise the framework.

## Test Structure

### Each Test Owns Its Setup

Build the `App`, register handlers, and wire the `Runner` inside each test. No shared global state. This makes test scope explicit and prevents coupling between test cases.

```python
def test_single_handler(runner_factory):
    app = App()

    @app.handler
    def my_handler(runner, state: State) -> State:
        return {**state, "result": state["result"] + 1}

    runner, source = runner_factory(app, "my_handler", {"result": 10})
    result = runner.run()
    assert result["result"] == 11
```

### Replace I/O at the Boundary

Swap channels that do I/O (stdout, stderr) with capturing doubles that collect into lists. Match the interface via duck typing (no inheritance required).

**TestChannel** is the primary test double, defined in `tests/conftest.py`:
- Implements `report(run_id, event: StreamEvent) -> None`
- Captures all events to `events: list[StreamEvent]`
- Provides backward-compatible lists: `progress_messages: list[str]` (non-error events) and `error_messages: list[str]` (error events)
- Provides initial state without external dependencies

**runner_factory** is a pytest fixture that creates `(Runner, TestChannel)` pairs for tests:

```python
runner, source = runner_factory(app, "workflow_name", {"initial": "state"})
```

## Test Coverage Rules

### One Test Per Code Path

If two tests traverse the same core path with different data, they're the same test. A single-handler workflow is one path regardless of what the handler computes.

Focus on:
- Single handler execution
- Multi-step workflow composition via `run_workflow()`
- Error propagation (WorkflowFailedError)
- Handler resolution (unknown workflow names)
- Environment variable lifecycle (`App(env=...)`: setting, str conversion, restoration, error propagation)

Avoid testing:
- Handler business logic (that's app code, not framework code)
- Different data values through the same path
- I/O formatting details (those belong in channel-specific tests)

## Running Tests

```bash
uv run -m pytest tests/ -v
```

Run via justfile:
```bash
just test
```

## Test Organization

Tests mirror source layout:
```
tests/
├── core/              # Tests for src/antkeeper/core/
│   ├── test_loader.py # load_app() unit tests
│   └── test_resume.py # _load_state_by_run_id state loading tests
├── channels/          # Tests for src/antkeeper/channels/
│   └── test_slack_channel.py  # SlackChannel unit tests
├── handlers/          # Tests for src/antkeeper/handlers/
│   ├── test_claude_code.py    # Claude Code handler registration tests
│   └── test_factories.py      # cc_handler factory unit tests
├── helpers/           # Tests for src/antkeeper/helpers/
│   ├── test_github.py         # fetch_gh_issue() and build_issues_prompt() unit tests
│   └── test_timestamps.py     # make_timestamp() and make_log_dir() unit tests
├── llm/               # Tests for src/antkeeper/llm/
│   ├── test_claude_code_agent.py  # ClaudeCodeAgent streaming tests
│   ├── test_run_prompt.py         # run_prompt() and collect_result() tests
│   └── test_middleware.py         # build_pipeline() and extraction middleware tests
├── git/               # Tests for src/antkeeper/git/
│   ├── conftest.py    # git_repo fixture
│   ├── test_core.py          # execute() function tests
│   ├── test_branch.py        # current() function tests
│   ├── test_worktree.py      # Worktree class tests
│   └── test_context.py       # git_worktree context manager tests
├── test_cli.py        # Tests for src/antkeeper/cli.py
├── test_slack_server.py  # Tests for Slack event endpoint
└── test_tracing.py    # Tests for OpenTelemetry tracing integration
```

### CLI Testing Patterns

CLI tests use click's `CliRunner` for end-to-end invocation without spawning a subprocess:

```python
from click.testing import CliRunner
from antkeeper.cli import cli

def test_run_invokes_workflow(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "healthcheck"])
    assert result.exit_code == 0
```

**Test classes** in `tests/test_cli.py`:
- `TestParseStatePairs` — unit tests for the `parse_state_pairs()` helper (no Runner or CLI invocation)
- `TestRunCommand` — CliRunner tests for the `run` subcommand
- `TestInitCommand` — CliRunner tests for the `init` subcommand
- `TestResumeCommand` — CliRunner tests for the `resume` subcommand

**Key patterns:**
- Use `CliRunner(mix_stderr=False)` when asserting on stderr separately from stdout
- Use `runner.invoke(cli, args, input="text")` to simulate piped stdin
- `result.exit_code` for exit status; `result.output` for stdout; `result.stderr` for stderr (when `mix_stderr=False`)
- Create temp handler files with `tmp_path` or `tempfile`; pass via `--agents-file`
- For error paths, assert `result.exit_code == 1` and check `result.stderr` or `result.output` for the message

For file-based inputs (e.g., positional prompt file arguments), write known content to a temp file and verify it flows through to the handler state.

### API Channel Testing Patterns

API channel tests follow the same test double pattern as CLI channel:

**ApiChannel unit tests** (`tests/channels/test_api_channel.py`):
- Test channel type identifier
- Test initial state handling (parametrized for None default)
- Test progress output goes to stdout with correct format
- Test error output goes to stderr using delegation pattern

**Server endpoint tests** (`tests/test_server.py`):
- Use FastAPI's `TestClient` from `httpx` package
- Create fixture with temp agents file containing test handlers
- Test successful workflow triggering returns run_id
- Test unknown workflow names return 404
- Test invalid request bodies return 422 validation errors
- Each test cleans up temp files in fixture teardown

### SlackChannel Testing Patterns

SlackChannel tests (`tests/channels/test_slack_channel.py`) mock the HTTP transport layer:

**Mock httpx.Client.post** - Patch `antkeeper.channels.slack.httpx.Client` to intercept Slack API calls without network I/O:

```python
@patch("antkeeper.channels.slack.httpx.Client")
def test_report_progress_posts_to_slack_thread(self, mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    channel = SlackChannel("wf", slack_token="xoxb-test", channel_id="C123", thread_ts="1234.5678")
    event = StreamEvent(type="progress", content="step done")
    channel.report("run1", event)

    mock_client.post.assert_called_once_with(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": "Bearer xoxb-test"},
        json={"channel": "C123", "thread_ts": "1234.5678", "text": "[wf, run1] step done"},
    )
```

**HTTP failure resilience** - Verify that `httpx.HTTPError` is caught and logged, not raised:

```python
@patch("antkeeper.channels.slack.httpx.Client")
def test_report_survives_http_failure(self, mock_client_cls):
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.HTTPError("connection failed")
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    channel = SlackChannel("wf", slack_token="xoxb-test", channel_id="C123", thread_ts="1234.5678")
    event = StreamEvent(type="progress", content="step done")
    channel.report("run1", event)  # should not raise
```

Tests cover: channel type identifier, initial state handling (parametrized for None default), progress event format, error event `[ERROR]` prefix, internal event suppression, and HTTP failure resilience.

### Slack Server Testing Patterns

Slack event endpoint tests (`tests/test_slack_server.py`) exercise the `/slack_event` POST route:

**Mock slack_api** - Patch `antkeeper.http.slack_events.slack_api` with `AsyncMock` to intercept all Slack API calls (reactions, chat.postMessage) without network I/O:

```python
api_mock = AsyncMock(return_value={"ok": True})
slack_api_patch = patch("antkeeper.http.slack_events.slack_api", api_mock)
```

**Environment variable patching** - Use `patch.dict(os.environ, {...})` to inject required Slack env vars (`SLACK_BOT_TOKEN`, `SLACK_BOT_USER_ID`, `SLACK_COOLDOWN_SECONDS`):

```python
env_patch = patch.dict(os.environ, {
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_BOT_USER_ID": "U_BOT",
    "SLACK_COOLDOWN_SECONDS": "0",
})
```

**Testing without environment variables** - Use a separate `slack_client_no_env` fixture to test behavior when environment variables are missing. This fixture creates a test client with only `SLACK_COOLDOWN_SECONDS` set, then explicitly pops `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` from `os.environ` after calling `create_app()`. This approach handles the case where `dotenv.load_dotenv()` might have loaded these variables from a `.env` file:

```python
@pytest.fixture
def slack_client_no_env(self):
    with patch.dict(os.environ, {"SLACK_COOLDOWN_SECONDS": "0"}):
        app = create_app("tests/fixtures/handlers.py")
        # Remove vars after create_app() in case dotenv loaded them
        os.environ.pop("SLACK_BOT_TOKEN", None)
        os.environ.pop("SLACK_BOT_USER_ID", None)
        yield TestClient(app)
```

This pattern ensures clean isolation even when a `.env` file exists in the project directory.

**Deterministic timers** - Set `SLACK_COOLDOWN_SECONDS=0` to eliminate debounce delays. For tests that verify debounce behavior (deduplication, edits, replies), override to a large value (`9999`) so the timer never fires during the test:

```python
@patch.dict(os.environ, {"SLACK_COOLDOWN_SECONDS": "9999"})
def test_duplicate_event_deduplication(self, slack_client):
    ...
```

**Timer task completion** - For tests that verify timer-fired workflow dispatch, use `time.sleep(0.2)` after sending the event to allow the background asyncio timer task to complete before asserting on mock calls.

Tests cover: URL verification challenge response (with and without env vars), environment variable validation (missing both, missing token only, missing user ID only), bot self-message filtering, mention acknowledgement (reaction), event deduplication, message edit updates, thread reply appending (with and without files), message deletion, timer-fired workflow dispatch, unknown workflow error posting, unknown event type handling, and orphan thread reply filtering.

## Fixture Management

All shared fixtures live in `tests/conftest.py`:
- `app` - Returns `App(log_dir=tempfile.mkdtemp(), worktree_dir=tempfile.mkdtemp(), state_dir=tempfile.mkdtemp())` per test for log, worktree, and state isolation
- `runner_factory` - Creates Runner + TestChannel pairs, accepts optional `app` parameter
- `TestChannel` - In-memory channel double for capturing I/O

Git-specific fixtures live in `tests/git/conftest.py`:
- `git_repo` - Creates a temp git repository with an initial commit, sets up git config (user.name, user.email), changes cwd into the repo, and restores original cwd on teardown. Use this for tests that exercise git worktree operations, git branch operations, or any git command execution.

Keep fixture scope minimal. Prefer function-scoped fixtures to session-scoped unless there's a compelling performance reason.

### Log, Worktree, and State Isolation in Tests

The `app` fixture directs logs, worktrees, and state files to temp directories per test, preventing files from accumulating in the working directory. Tests that create Runners should use the `app` fixture:

```python
def test_something(app, runner_factory):
    runner, source = runner_factory(app, "workflow", {})
    # Log files go to app.log_dir (temp directory)
    # Worktrees go to app.worktree_dir (temp directory)
    # State files go to app.state_dir (temp directory)
```

### App Environment Variable Testing Patterns

Tests for the `App(env=...)` feature live in `tests/core/test_workflows.py` in the `TestAppEnvironment` class, alongside the workflow execution tests. Constructor-level tests (`test_app_constructor_stores_env`, `test_app_constructor_default_env_is_none`) live in `tests/core/test_app.py`.

Because these tests manipulate `os.environ` directly, they use a prefixed key convention (`_ANTKEEPER_TEST_ENV_*`) to avoid colliding with real environment variables. Each test cleans up after itself.

The `TestAppEnvironment` class uses its own helpers (`_make_env_app`, `_run_handler`, `_SimpleChannel`) rather than the shared `runner_factory` fixture, because the env tests need precise control over the `App` constructor arguments and don't benefit from the shared fixture's defaults.

Tests cover:

- `test_handler_sees_env_vars` — Handler reads an env var set via `App(env=...)` and finds the expected value
- `test_env_values_converted_to_string` — Integer values (e.g., `42`) are converted to `"42"` before being set on `os.environ`
- `test_env_restored_after_successful_handler` — Key is absent from `os.environ` after handler completes successfully
- `test_env_restored_after_failed_handler` — Key is absent from `os.environ` even when the handler raises
- `test_existing_env_var_preserved` — A key already in `os.environ` is overridden during handler execution and its original value is restored afterward
- `test_none_env_is_noop` — `App(env=None)` runs handlers without touching `os.environ`
- `test_empty_env_dict_is_noop` — `App(env={})` runs handlers without touching `os.environ`
- `test_invalid_env_value_propagates` — An object whose `__str__` raises causes the exception to propagate; any partially-set vars are cleaned up
- `test_run_workflow_steps_see_env_vars` — Steps inside `run_workflow()` can access env vars set at `Runner.run()` level
- `test_env_restored_after_run_workflow_step_failure` — Env vars are cleaned up even when a step inside `run_workflow()` raises

### Resume Testing Patterns

Tests for workflow resume cover three distinct concerns, each in its own class or file.

**`tests/core/test_resume.py`** — dedicated file for `_load_state_by_run_id` behaviour:

- `TestLoadStateByRunId` — unit tests for the state-file lookup helper using `tempfile.TemporaryDirectory`. Tests cover: finding a matching file and returning its parsed dict and path, raising `FileNotFoundError` for an empty directory, and selecting the correct file when multiple state files are present.

**`tests/core/test_workflows.py`** — `TestWorkflowSkip` class, alongside other workflow tests:

- Tests for `run_workflow(runner, state, steps, skip=N)` cover: skipping the first N steps, running all steps when `skip=0`, verifying `_progress["completed"]` starts at the skip value, consuming `_resume_skip` from state automatically (when `skip=0`), confirming `_resume_skip` is stripped and not present in the final state, verifying sequential calls are unaffected after `_resume_skip` is consumed on the first call, and confirming an explicit `skip` parameter takes precedence over `_resume_skip` in state.

**`tests/test_cli.py`** — `TestResumeCommand` class using `CliRunner`:
- Successful resume loads state, skips completed steps, and executes remaining steps
- Unknown `run_id` → `exit_code == 1`, stderr contains error message
- Already-completed workflow → `exit_code == 1`, stderr mentions "already completed"
- State with no `_progress` → `exit_code == 1`, stderr contains error message
- State with no `workflow_name` → `exit_code == 1`, stderr contains error message

Resume tests use `CliRunner(mix_stderr=False)` and `runner.invoke(cli, ["resume", run_id], ...)` with temp agents files and temp state files.

### State Persistence Testing Patterns

Tests for state persistence (`tests/core/test_state_persistence.py`) verify:
- State directory creation
- State file naming pattern matches log files (`{timestamp}-{run_id}.json`)
- State file contains correct JSON keys (run_id, workflow_name, handler additions)
- State persisted after each `run_workflow()` step
- Handlers can read persisted state mid-workflow to verify persistence timing

`TestWorkflowProgress` in `tests/core/test_workflows.py` covers `_progress` tracking behaviour:

- **`test_run_workflow_final_state_has_progress`** — returned state has `_progress == {"total": N, "completed": N}` after all steps
- **`test_run_workflow_progress_increments_per_step`** — a capturing step verifies `_progress["completed"]` increments correctly across steps (values seen are `[0, 1, 2]` for three steps)
- **`test_run_workflow_single_step_progress`** — single step produces `{"total": 1, "completed": 1}`
- **`test_initial_progress_persisted_before_first_step`** — reads the state file from disk inside the first step and asserts `_progress == {"total": 1, "completed": 0}`. This is the regression test for the bug where `_progress` was not persisted until after the first step completed. Uses `open(runner._state_path)` + `json.load()` directly to verify what is on disk, not just in memory.
- **`test_single_handler_run_has_no_progress`** — `Runner.run()` used directly (without `run_workflow`) produces no `_progress` key

### LLM Agent Testing Patterns

Tests for `ClaudeCodeAgent` (`tests/llm/test_claude_code_agent.py`) patch `subprocess.Popen` at the boundary — no real subprocess invocations.

**Mocking `Popen`** — create a mock with iterable `stdout` lines and a `wait()` that returns 0:

```python
mock_proc = MagicMock()
mock_proc.stdout = iter([
    '{"type":"assistant","content":[{"type":"text","text":"hello"}]}\n',
    '{"type":"result","result":"done","session_id":"s1","duration_ms":100,"usage":{},"total_cost_usd":0.0}\n',
])
mock_proc.wait.return_value = None
mock_proc.returncode = 0
mock_proc.poll.return_value = 0
mock_proc.stderr = MagicMock()
```

All tests that mock a successful subprocess response use JSONL lines corresponding to the `--output-format stream-json` format. Tests for error paths (non-zero exit, binary not found) adjust `returncode` or raise `FileNotFoundError` from `Popen`.

**`test_claude_code_agent.py` key test patterns:**

- `test_prompt_returns_iterator_of_stream_events` — consuming the iterator yields `StreamEvent` instances
- `test_prompt_parses_assistant_events` — assistant JSONL lines become `type="assistant"` events
- `test_prompt_parses_result_event` — result envelope becomes `type="result"` with metadata
- `test_prompt_non_zero_exit_raises` — non-zero exit code raises `AgentExecutionError`
- `test_prompt_binary_not_found` — `FileNotFoundError` from `Popen` raises `AgentExecutionError`
- `test_prompt_malformed_jsonl_raises` — bad JSON raises `ValueError`
- `test_output_format_stream_json_flag` — verify `--output-format stream-json` in `Popen` args
- `test_otel_span_attributes_from_result` — span has session_id, cost, token counts from result metadata
- `test_otel_span_closed_on_incomplete_consumption` — generator close triggers `span.end()`

**`tests/llm/test_run_prompt.py`** — tests for `run_prompt()` and `collect_result()`:

- `test_collect_result_returns_text_and_events` — consumes stream, returns `(text, events)`
- `test_collect_result_empty_stream` — returns `("", [])`
- `test_collect_result_ignores_internal_result` — only non-internal result used as text

**`tests/llm/test_middleware.py`** (new file) — tests for `build_pipeline()` and extraction middleware:

- `test_build_pipeline_no_middlewares` — identity pass-through
- `test_build_pipeline_single_middleware` — transforms stream
- `test_build_pipeline_sequential_order` — middlewares applied left-to-right
- `test_extraction_middleware_intercepts_result` — triggers extraction on result event
- `test_extraction_middleware_splices_internal_events` — extraction events have `internal=True`
- `test_extraction_middleware_passes_non_result_events` — progress events unchanged

**Telemetry log testing** — use pytest's built-in `caplog` fixture; no manual logger patching needed:

```python
def test_telemetry_logged_at_debug(self, caplog):
    with caplog.at_level(logging.DEBUG, logger="antkeeper.llm.claude_code"):
        list(agent.prompt("hello"))  # consume iterator
    debug_text = " ".join(r.message for r in caplog.records)
    assert "s1" in debug_text
```

### Handler Factory Testing Patterns

Tests for the `cc_handler` factory (`tests/handlers/test_factories.py`) unit-test the factory in isolation by mocking the LLM layer.

**Mock at the factory module** — the factory now creates a `ClaudeCodeAgent` directly for the primary call and uses `run_prompt` only inside the extraction middleware. Patch `antkeeper.handlers.claude_code.factories.ClaudeCodeAgent` for the primary stream and `antkeeper.handlers.claude_code.factories.run_prompt` for the extraction call. Both mocks must return iterables of `StreamEvent` instances (not strings):

```python
from antkeeper.core.domain import StreamEvent

def _make_stream(*events):
    return iter(events)

# Fire-and-forget: agent yields a single result event
result_event = StreamEvent(type="result", content="ok")
mock_agent = MagicMock()
mock_agent.prompt.return_value = _make_stream(result_event)

@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent", return_value=mock_agent)
def test_fire_and_forget_returns_state_unchanged(mock_cls, runner_factory):
    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}
```

**Use `runner_factory()` with no arguments** — factory tests do not need a custom `App`, so `runner_factory()` (no args) is idiomatic. This creates a Runner bound to the default `app` fixture.

**Extraction mode** — patch both `ClaudeCodeAgent` (for the primary stream) and `run_prompt` (for the extraction stream inside middleware). Also patch `extract_json` to control parsed output:

```python
@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo", "extra": "ignored"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value=iter([StreamEvent(type="result", content='{"spec_file":"s.md","slug":"foo"}')]))
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_state_updates_extracts_only_named_fields(mock_cls, mock_rp, mock_ej, runner_factory):
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = iter([StreamEvent(type="result", content="raw response")])
    mock_cls.return_value = mock_agent
    h = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
    runner, channel = runner_factory()
    result = h(runner, {"prompt": "build something"})
    assert "extra" not in result
```

**Events forwarded to channel** — assert that `channel.events` contains the events yielded during handler execution. Because `cc_handler` filters events by default (only `result` and `error` pass through), tests that verify all event types reach the channel must pass `verbose=True`:

```python
h = cc_handler("/cmd", verbose=True)
runner, channel = runner_factory()
h(runner, {})
assert any(e.type == "result" for e in channel.events)
assert any(e.type == "assistant" for e in channel.events)  # only visible with verbose=True
```

For tests that verify filtering behaviour (e.g. that assistant events are suppressed by default), omit `verbose=True` and assert the filtered event type is absent from `channel.events`.

**Error handling tests expect `WorkflowFailedError`** — when the agent stream raises `AgentExecutionError`, or `extract_json` raises `ValueError`, or a state key is missing from the command string, the factory routes through `runner.fail()` which raises `WorkflowFailedError`. Test with `pytest.raises(WorkflowFailedError)`.

**Handler-level env tests** — use `os.environ.get()` inside a `run_prompt` `side_effect` to capture environment variable values during execution. Use prefixed keys (`_ANTKEEPER_TEST_HF_*`) to avoid collisions with real environment variables. Each test cleans up any keys it sets:

```python
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
def test_env_sets_vars_during_handler_execution(mock_rp, runner_factory):
    captured = {}

    def capture_env(prompt, logger, **kwargs):
        captured["val"] = os.environ.get("_ANTKEEPER_TEST_HF_KEY")
        return "ok"

    mock_rp.side_effect = capture_env
    h = cc_handler("/cmd", env={"_ANTKEEPER_TEST_HF_KEY": "secret"})
    runner, channel = runner_factory()
    h(runner, {})
    assert captured["val"] == "secret"
```

For tests that verify env restoration after failure, use `pytest.raises(WorkflowFailedError)` and assert the key is absent from `os.environ` after the block exits.

For tests that verify pre-existing keys are restored (not deleted), set the key in `os.environ` directly, wrap the test body in `try/finally`, and pop the key in the `finally` block.

Tests cover: env vars visible during execution, env restored after success, env restored after failure (WorkflowFailedError), pre-existing var overridden during execution and restored after, `env=None` is a no-op, env active during both extraction-mode `run_prompt` calls, and multiple env vars set and cleaned up together.

Tests cover: label derivation (slash stripping, first token, explicit override), extraction mode (two-call sequence, field extraction, progress messages, extraction model always haiku, step 1 and step 2 failure paths), fire-and-forget mode (single call, state unchanged, empty `state_updates` list), `$var` interpolation (single, multiple, non-string values, `${var}` literal passthrough), model override (per-handler model, state fallback, extraction always uses haiku regardless), error handling (AgentExecutionError, bad JSON, missing state key, missing JSON field in response), handler-level env (set during execution, restored after success/failure, noop for None, active across both extraction calls), and verbose mode / event filtering (`_should_report` unit tests for all event types and modes; integration tests for default mode suppressing assistant/tool events, forwarding result/error events, and verbose mode forwarding all event types; empty content always suppressed regardless of mode).

### GitHub Helper Testing Patterns

Tests for `antkeeper.helpers.github` (`tests/helpers/test_github.py`) are pure unit tests that mock `subprocess.run` at the boundary — no real `gh` CLI invocations.

- `TestFetchGhIssue` — patches `subprocess.run` to return mock JSON output; verifies `fetch_gh_issue()` calls `gh issue view` with the correct arguments and returns parsed dict
- `TestBuildIssuesPrompt` — pure function tests requiring no mocks; verify formatted prompt structure

Import pattern:

```python
from antkeeper.helpers.github import fetch_gh_issue, build_issues_prompt
```

### Helper Testing Patterns

Tests for `antkeeper.helpers` utilities (`tests/helpers/`) are pure unit tests with no fixtures and no Runner involvement.

**Patch `datetime` at the module under test** — to make timestamp assertions deterministic, patch `antkeeper.helpers.timestamps.datetime` (not `datetime.datetime`) so `datetime.now()` returns a fixed value:

```python
from datetime import datetime
from unittest.mock import patch
from antkeeper.helpers.timestamps import make_timestamp, make_log_dir

FIXED_DT = datetime(2026, 3, 14, 9, 5, 7)

def test_make_timestamp_format():
    with patch("antkeeper.helpers.timestamps.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DT
        assert make_timestamp() == "20260314090507"
```

**Mock the runner with `Mock(spec=Runner, id=...)`** — `make_log_dir` only needs `runner.id`, so a `Mock(spec=Runner)` is the right double. No `runner_factory` or `App` is needed:

```python
from unittest.mock import Mock, patch
from antkeeper.core.runner import Runner
from antkeeper.helpers.timestamps import make_log_dir

def test_make_log_dir_produces_correct_path():
    with patch("antkeeper.helpers.timestamps.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DT
        mock_runner = Mock(spec=Runner, id="abc123")
        log_dir_fn = make_log_dir("/var/logs")
        assert log_dir_fn(mock_runner) == "/var/logs/20260314090507-abc123/"
```

**Verify timestamp is captured at call time, not factory time** — to test lazy evaluation, obtain the callable first (before patching), then patch and invoke:

```python
def test_make_log_dir_uses_timestamp_at_call_time():
    log_dir_fn = make_log_dir("out")  # create before patching
    with patch("antkeeper.helpers.timestamps.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2099, 12, 31, 23, 59, 59)
        mock_runner = Mock(spec=Runner, id="run1")
        assert log_dir_fn(mock_runner) == "out/20991231235959-run1/"
```

Tests cover: timestamp format (`YYYYMMDDHHmmss`, 14 characters), `make_log_dir` returns a callable, correct path construction (base dir + timestamp + runner.id + trailing slash), and lazy timestamp evaluation.

### OpenTelemetry Tracing Testing Patterns

Tests for OpenTelemetry tracing (`tests/test_tracing.py`) verify that instrumentation points produce correct spans with expected attributes.

**Test-scoped TracerProvider with in-memory exporter** — each test installs a test `TracerProvider` with an `_InMemoryExporter` that collects finished spans in a list. The OTel API only allows `set_tracer_provider` once per process, so the test swaps the internal getter:

```python
@pytest.fixture(autouse=True)
def _otel_provider():
    exporter = _InMemoryExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    original = trace.get_tracer_provider
    trace.get_tracer_provider = lambda: provider
    yield exporter
    trace.get_tracer_provider = original
    provider.shutdown()
```

Because each call site uses `trace.get_tracer("antkeeper")` directly (no singleton), installing a test provider is all that's needed — no per-module monkeypatching.

**`_envelope()` helper** — builds Claude JSON envelopes with span-relevant fields (`session_id`, `duration_ms`, `usage`, `total_cost_usd`, `model`) for mock subprocess responses.

Tests are organized into three classes:

- **`TestRunnerRunSpan`** — verifies `Runner.run()` produces exactly one `antkeeper.run` root span with `run_id`, `workflow_name`, and `channel.type` attributes. Also verifies error recording: exceptions set span status to ERROR and record exception events while still propagating.

- **`TestRunWorkflowSpans`** — verifies `run_workflow()` produces `antkeeper.workflow.step` child spans with `step_name`, `step_index`, `step_total`, `run_id`, and `workflow_name` attributes. Tests span hierarchy (step spans are children of root span), error recording on step failure, and correct span count for multi-step workflows.

- **`TestLLMCallSpan`** — verifies `ClaudeCodeAgent.prompt()` produces `antkeeper.llm.call` spans with `prompt_length`, `session_id`, `duration_ms`, `input_tokens`, `output_tokens`, `total_cost_usd`, and `model` attributes. Tests error paths (non-zero exit code sets span status to ERROR and records exception). Tests generator cleanup: closing the iterator before full consumption triggers `span.end()` via the `finally` block.

**Span assertion pattern** — filter `exporter.get_finished_spans()` by span name to find specific spans:

```python
root_spans = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"]
assert len(root_spans) == 1
assert root_spans[0].attributes["run_id"] == runner.id
```

**Span hierarchy verification** — assert parent-child relationships using span context IDs:

```python
root = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"][0]
step = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.workflow.step"][0]
assert step.parent.span_id == root.context.span_id
```

### Git Testing Patterns

Tests for git functionality should use the `git_repo` fixture from `tests/git/conftest.py`. This fixture:
- Creates a temp directory with a fully initialized git repository
- Adds an initial commit (required for worktree operations)
- Configures local git identity (user.name, user.email) for CI compatibility
- Changes cwd into the repository for the test duration
- Restores the original cwd on teardown

#### Git Command Execution Tests

Tests for `git.core.execute()` (`tests/git/test_core.py`) should verify:
- Successful command execution returns stripped stdout
- Failed commands raise `GitCommandError` with stderr
- Empty stdout is returned as empty string (e.g., `git tag -l` with no tags)

Example:
```python
def test_execute_returns_stdout(git_repo):
    result = execute(["git", "log", "--oneline"])
    assert isinstance(result, str)
    assert len(result) > 0
```

#### Git Branch Tests

Tests for `git.branch.current()` (`tests/git/test_branch.py`) should verify:
- Returns default branch name (main or master, detected via subprocess for portability)
- Returns switched branch name after `git checkout -b`
- Returns "HEAD" when in detached HEAD state

Example:
```python
def test_current_returns_default_branch(git_repo):
    expected = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert current() == expected
```

#### Git Worktree Tests

Tests for git worktree functionality should verify:
- Worktree creation (with and without branch)
- Cwd switching and restoration
- Error handling for missing worktrees
- Cleanup behavior (remove=True/False)

Example:
```python
def test_worktree_create(git_repo):
    wt = Worktree(base_dir="trees", name="feature")
    wt.create(branch="feat/new")
    assert wt.exists
```
