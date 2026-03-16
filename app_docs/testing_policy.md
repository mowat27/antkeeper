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
- Captures `report_progress()` calls into `progress_messages: list[str]`
- Captures `report_error()` calls into `error_messages: list[str]`
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
├── channels/          # Tests for src/antkeeper/channels/
│   └── test_slack_channel.py  # SlackChannel unit tests
├── handlers/          # Tests for src/antkeeper/handlers/
│   ├── test_claude_code.py    # Claude Code handler registration tests
│   └── test_factories.py      # cc_handler factory unit tests
├── helpers/           # Tests for src/antkeeper/helpers/
│   └── test_timestamps.py     # make_timestamp() and make_log_dir() unit tests
├── llm/               # Tests for src/antkeeper/llm/
├── git/               # Tests for src/antkeeper/git/
│   ├── conftest.py    # git_repo fixture
│   ├── test_core.py          # execute() function tests
│   ├── test_branch.py        # current() function tests
│   ├── test_worktree.py      # Worktree class tests
│   └── test_context.py       # git_worktree context manager tests
├── test_cli.py        # Tests for src/antkeeper/cli.py
└── test_slack_server.py  # Tests for Slack event endpoint
```

### CLI Testing Patterns

CLI tests are split into two categories:

**Argument parsing tests** (`TestArgParsing`) - Test argparse behavior in isolation:
- Build a parser mirror in `_build_parser()` to avoid loading the full CLI machinery
- Test flag parsing, mutual exclusion, and invalid input handling
- Use `pytest.raises(SystemExit)` for argparse error cases

**Integration tests** (`TestCliIntegration`) - Test end-to-end CLI execution:
- Create temp files for handlers and input files
- Use `monkeypatch.setattr("sys.argv", ...)` to simulate CLI invocation
- Use `capsys` to capture stdout/stderr
- Clean up temp files in `finally` blocks
- Test error handling: CLI catches `WorkflowFailedError`, prints to stderr, exits with code 1

For file-based inputs (e.g., positional file arguments), integration tests should write known content to a temp file and verify it flows through to the handler state.

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
    channel.report_progress("run1", "step done")

    mock_client.post.assert_called_once_with(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": "Bearer xoxb-test"},
        json={"channel": "C123", "thread_ts": "1234.5678", "text": "[wf, run1] step done"},
    )
```

**HTTP failure resilience** - Verify that `httpx.HTTPError` is caught and logged, not raised:

```python
@patch("antkeeper.channels.slack.httpx.Client")
def test_report_progress_survives_http_failure(self, mock_client_cls):
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.HTTPError("connection failed")
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    channel = SlackChannel("wf", slack_token="xoxb-test", channel_id="C123", thread_ts="1234.5678")
    channel.report_progress("run1", "step done")  # should not raise
```

Tests cover: channel type identifier, initial state handling (parametrized for None default), progress message format, error message `[ERROR]` prefix, and HTTP failure resilience.

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

Tests for `ClaudeCodeAgent` (`tests/llm/test_claude_code_agent.py`) patch `subprocess.run` at the boundary — no real subprocess invocations.

**`_envelope()` helper** — a module-level helper builds valid JSON envelopes for use as mock subprocess stdout:

```python
def _envelope(result="ok", session_id="s1", duration_ms=100, usage=None, total_cost_usd=0.0):
    return json.dumps({
        "type": "result", "subtype": "success",
        "result": result, "session_id": session_id,
        "duration_ms": duration_ms, "usage": usage or {},
        "total_cost_usd": total_cost_usd,
    })
```

All tests that mock a successful subprocess response use `_envelope()` to produce the stdout value. Tests for error paths (non-zero exit, binary not found) do not need an envelope.

**`TestJsonOutputMode` test class** — groups tests for JSON envelope parsing, telemetry logging, and edge cases:

- `test_output_format_json_flag_always_present` / `test_output_format_not_duplicated_when_in_opts` — flag injection and deduplication
- `test_invalid_json_raises_value_error` / `test_missing_result_key_raises_value_error` — `ValueError` paths
- `test_telemetry_logged_at_debug` — uses `caplog.at_level(logging.DEBUG, logger="antkeeper.llm.claude_code")` to assert `session_id` and `duration_ms` values appear in debug records
- Edge cases: `test_empty_result_string_returned`, `test_missing_session_id_does_not_raise`, `test_none_total_cost_does_not_raise`

**Telemetry log testing** — use pytest's built-in `caplog` fixture; no manual logger patching needed:

```python
def test_telemetry_logged_at_debug(self, caplog):
    with caplog.at_level(logging.DEBUG, logger="antkeeper.llm.claude_code"):
        agent.prompt("hello")
    debug_text = " ".join(r.message for r in caplog.records)
    assert "abc123" in debug_text
```

### Handler Factory Testing Patterns

Tests for the `cc_handler` factory (`tests/handlers/test_factories.py`) unit-test the factory in isolation by mocking the LLM layer.

**Mock `run_prompt` at the factory module** — patch `antkeeper.handlers.claude_code.factories.run_prompt` (not the source module) to intercept LLM calls. Fire-and-forget tests use a single `return_value`; extraction mode tests use `side_effect` with two values to cover both `run_prompt` calls:

```python
# Fire-and-forget: single call
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_fire_and_forget_returns_state_unchanged(mock_rp, runner_factory):
    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}

# Extraction mode: two calls — Step 1 raw prompt, Step 2 extraction prompt
@patch("antkeeper.handlers.claude_code.factories.run_prompt", side_effect=["raw response", '{"spec_file":"s.md","slug":"foo"}'])
def test_state_updates_extracts_fields(mock_rp, mock_ej, runner_factory):
    ...
```

**Use `runner_factory()` with no arguments** — factory tests do not need a custom `App`, so `runner_factory()` (no args) is idiomatic. This creates a Runner bound to the default `app` fixture.

**Mock `extract_json` for extraction mode** — when testing extraction mode, also patch `antkeeper.handlers.claude_code.factories.extract_json` to control parsed output without needing valid LLM responses:

```python
@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo", "extra": "ignored"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", side_effect=["raw response", '{"spec_file":"s.md","slug":"foo"}'])
def test_state_updates_extracts_only_named_fields(mock_rp, mock_ej, runner_factory):
    h = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
    runner, channel = runner_factory()
    result = h(runner, {"prompt": "build something"})
    assert "extra" not in result
```

**Assert two-call sequence for extraction mode** — verify the first `run_prompt` call receives the raw interpolated prompt with the handler's configured model, and the second call uses `"haiku"` as the model with an extraction prompt containing the required field names wrapped in `<response>` XML tags:

```python
assert mock_rp.call_count == 2
first_call = mock_rp.call_args_list[0]
assert first_call[0][0] == "/specify build it"       # raw prompt
second_call = mock_rp.call_args_list[1]
assert second_call[1]["model"] == "haiku"             # always haiku
assert "<response>" in second_call[0][0]              # XML-tagged response
assert "spec_file" in second_call[0][0]               # required fields listed
```

**Error handling tests expect `WorkflowFailedError`** — when `run_prompt` raises `AgentExecutionError` (on either Step 1 or Step 2), or `extract_json` raises `ValueError`, or a state key is missing from the command string, the factory routes through `runner.fail()` which raises `WorkflowFailedError`. Test with `pytest.raises(WorkflowFailedError)`.

**Step 1 failure skips Step 2** — use `side_effect=AgentExecutionError("boom")` (not a list) so `run_prompt` raises on the first call. Assert `mock_rp.assert_called_once()` to confirm Step 2 was never reached.

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

Tests cover: label derivation (slash stripping, first token, explicit override), extraction mode (two-call sequence, field extraction, progress messages, extraction model always haiku, step 1 and step 2 failure paths), fire-and-forget mode (single call, state unchanged, empty `state_updates` list), `$var` interpolation (single, multiple, non-string values, `${var}` literal passthrough), model override (per-handler model, state fallback, extraction always uses haiku regardless), error handling (AgentExecutionError, bad JSON, missing state key, missing JSON field in response), and handler-level env (set during execution, restored after success/failure, noop for None, active across both extraction calls).

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
