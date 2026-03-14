# Antkeeper

A lightweight Python workflow engine. Define handlers (workflow steps) via a decorator-based `App`, wire them to a `Channel` (I/O boundary), and execute through a `Runner`. Designed for composable, testable pipelines.

## Installation

### From PyPI

```bash
# Install antkeeper (includes FastAPI, uvicorn, python-dotenv, httpx)
pip install antkeeper
```

### From Source

```bash
# Clone the repository
git clone https://github.com/mowat27/antkeeper.git
cd antkeeper

# Install with uv
uv sync  # Development dependencies
uv pip install .  # Core package
```

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager (for development)

## Quickstart

```bash
# Create a new project with starter handlers
antkeeper init my-project
cd my-project

# Run the healthcheck workflow
antkeeper run healthcheck

# Or manually install dependencies and create handlers
uv sync

# Run a workflow via CLI
antkeeper run --agents-file handlers.py --initial-state result=5 plus_1

# Run an LLM workflow with prompt from file
antkeeper run --model sonnet specify prompts/describe.md

# Run with multiple prompt files (concatenated in order)
antkeeper run --model sonnet specify file1.md file2.md

# Run with prompt from stdin
echo "describe this project" | antkeeper run --model sonnet specify

# Start an API server to trigger workflows via HTTP
antkeeper server --host 0.0.0.0 --port 8000 --agents-file handlers.py

# For Slack integration, create a .env file with:
#   SLACK_BOT_TOKEN=xoxb-...
#   SLACK_BOT_USER_ID=U...
#   SLACK_COOLDOWN_SECONDS=5  (optional, default 5)
#   ANTKEEPER_HANDLERS_FILE=handlers.py  (optional)

# Use just recipes for common workflows
just sdlc "Add authentication" opus           # Standard SDLC workflow
just sdlc_iso "Add dark mode" opus           # Isolated SDLC in git worktree
```

## Project Structure

```
src/antkeeper/
├── core/               # Framework kernel
│   ├── domain.py       # State type alias, Channel protocol, WorkflowFailedError
│   ├── app.py          # App handler registry, run_workflow helper
│   └── runner.py       # Runner execution engine
├── channels/
│   ├── cli.py          # CLI channel adapter (stdout/stderr reporting)
│   ├── api.py          # API channel adapter (server logging)
│   └── slack.py        # Slack channel adapter (thread replies)
├── git/                # Git integration
│   ├── core.py         # Low-level command execution (execute, GitCommandError)
│   ├── branch.py       # Branch operations (current)
│   └── worktrees.py    # Worktree class, git_worktree context manager
├── handlers/           # Pre-built handler collections
│   └── claude_code/    # SDLC handlers using Claude Code as the LLM backend
│       ├── __init__.py # 11 registered handlers + module-level app instance
│       └── factories.py # cc_handler factory for building handlers without boilerplate
├── helpers/
│   └── json.py         # JSON extraction utilities
├── llm/                # LLM agent abstraction layer
│   ├── __init__.py     # Agent protocol
│   ├── errors.py       # AgentExecutionError
│   └── claude_code.py  # ClaudeCodeAgent (subprocess-based)
├── http/               # HTTP server layer
│   ├── __init__.py     # FastAPI app factory
│   ├── webhook.py      # POST /webhook endpoint
│   └── slack_events.py # POST /slack_event endpoint
├── cli.py              # Argparse-based CLI entry point
└── server.py           # Server orchestrator (delegates to http/)
```

### Key Concepts

- **State** (`dict[str, Any]`) — All workflow data flows as a flat dictionary. Handlers receive and return `State`; the `Runner` injects `run_id` and `workflow_name`. State is automatically persisted as JSON on every change.
- **Channel** (Protocol) — I/O boundary adapter. Owns how progress/errors are reported and what initial state is supplied. This is the primary extension point for new I/O adapters.
- **App** — Handler registry. Use the `@app.handler` decorator to register workflow steps by function name. Configure log, worktree, and state directories via `App(log_dir="...", worktree_dir="...", state_dir="...")`. `log_dir` may be a callable `(runner) -> str` for per-handler dynamic paths. Optionally supply `env={"KEY": value}` to inject environment variables for every handler run (values are converted to `str()`). `env` values may also be callables `(runner) -> Any` evaluated per handler invocation.
- **Runner** — Execution engine. Binds an `App` + `Channel`, generates a `run_id`, and drives the workflow lifecycle. Persists state to `{timestamp}-{run_id}.json` in `app.state_dir`.
- **run_workflow** — Composition helper. Folds state through a list of handler callables, enabling composite workflows without inheritance or a DAG scheduler.
- **Agent** (Protocol) — LLM abstraction. Any object with a `prompt(str) -> str` method qualifies. Extension point for new LLM backends.
- **ClaudeCodeAgent** — Concrete `Agent` implementation. Delegates prompts to the `claude` CLI via subprocess. Accepts optional `model`, `yolo` (skip permissions), and `opts` (arbitrary CLI args) parameters.
- **execute** — Low-level git command execution. Takes a command list (e.g., `["git", "status"]`), returns stripped stdout, raises `GitCommandError` on failure. Logs commands at debug level.
- **current** — Returns current branch name (or "HEAD" if detached). Delegates to `execute(["git", "rev-parse", "--abbrev-ref", "HEAD"])`.
- **GitCommandError** — Exception raised when git commands fail with non-zero exit codes. Contains stderr as message.
- **Worktree** — Git worktree wrapper. Provides `create()`, `remove()`, and `exists` for managing isolated git working directories. Paths are absolute for safety after cwd changes.
- **git_worktree** — Context manager that enters a worktree, guarantees cwd restoration via try/finally, and optionally creates/removes the worktree.
- **SlackChannel** — Channel implementation that posts workflow progress and results to Slack threads via the Slack API.

### Data Flow

**CLI Execution:**
1. CLI parses args and loads an agents file (Python module exporting `app`)
2. Builds a `CliChannel(workflow_name, initial_state)`
3. `Runner(app, channel).run()` merges initial state with `{run_id, workflow_name}`
4. Handler receives `(runner, state)` and returns new `State`
5. Composite handlers use `run_workflow` to chain sub-steps
6. For LLM workflows: handler creates an `Agent`, calls `agent.prompt()`, and spreads the response into state
7. Result state is printed to stdout
8. If handler calls `runner.fail()`, CLI catches `WorkflowFailedError`, prints to stderr, exits 1

**API Execution:**
1. POST `/webhook` with `{"workflow_name": "my_wf", "initial_state": {...}}`
2. Server validates workflow exists, creates `ApiChannel(workflow_name, initial_state)`
3. Returns `{"run_id": "abc123"}` immediately
4. Workflow runs in background task
5. Progress/errors appear in server logs (stdout/stderr)
6. If handler calls `runner.fail()`, server catches `WorkflowFailedError`, logs error, continues serving

**Slack Execution:**
1. User @mentions the bot in a Slack thread
2. POST `/slack_event` receives the event, debounces rapid mentions (cooldown via `SLACK_COOLDOWN_SECONDS`)
3. Server dispatches the workflow using `SlackChannel` bound to the originating thread
4. Workflow progress and results are posted as thread replies
5. Errors are reported back to the Slack thread

### Writing Handlers

Create a Python file with an `App` instance and decorated handlers:

```python
from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State

app = App()  # Defaults: log_dir="agents/logs/", worktree_dir="trees/", state_dir=".antkeeper/state/"
# Or configure: App(log_dir="my/logs/", worktree_dir="worktrees/", state_dir=".antkeeper/state/")
# Inject env vars for every handler: App(env={"API_KEY": "sk-123", "TIMEOUT": 30})
#   - Values are converted to str() before setting on os.environ
#   - Original values are restored after each handler completes (success or failure)
#   - Keys absent from os.environ before are removed after handler completes (not set to "None")
#   - Values may be callables: App(env={"RUN_ID": lambda runner: runner.id})
#     The callable receives the runner and is evaluated per handler invocation
# log_dir may also be a callable: App(log_dir=lambda runner: f"logs/{runner.workflow_name}/{runner.id}")
#   - Evaluated once per handler invocation, before the log file is created

@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.report_progress("doing work")
    runner.logger.info("Custom log entry")  # per-run log file
    return {**state, "result": "done"}
```

Handlers always return a **new** dict (spread pattern) — never mutate incoming state.

Handlers can delegate to LLM agents:

```python
from antkeeper.llm.claude_code import ClaudeCodeAgent

@app.handler
def ask_llm(runner: Runner, state: State) -> State:
    agent = ClaudeCodeAgent(
        model=state.get("model"),
        yolo=state.get("skip_permissions", False),
        opts=state.get("claude_opts")
    )
    response = agent.prompt(state["prompt"])
    return {**state, "result": response}
```

Handlers can compose steps using `run_workflow`, which folds state through a list of functions sequentially. Each step receives the state returned by the previous step, so steps communicate by adding keys to the state dict:

```python
from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State

app = App()

@app.handler
def fetch_data(runner: Runner, state: State) -> State:
    runner.report_progress("fetching data")
    return {**state, "raw_data": [1, 2, 3]}

@app.handler
def transform(runner: Runner, state: State) -> State:
    doubled = [x * 2 for x in state["raw_data"]]
    return {**state, "transformed": doubled}

@app.handler
def summarise(runner: Runner, state: State) -> State:
    total = sum(state["transformed"])
    return {**state, "summary": f"total={total}"}

@app.handler
def pipeline(runner: Runner, state: State) -> State:
    return run_workflow(runner, state, [fetch_data, transform, summarise])
```

`fetch_data` writes `raw_data`, `transform` reads it and writes `transformed`, and `summarise` reads that. State is persisted after each step, so a failure mid-pipeline preserves the progress so far.

Registering the individual steps with `@app.handler` is optional, but doing so allows them to be run individually from the CLI using `--initial-state` to supply the keys they expect:

```bash
antkeeper run --agents-file handlers.py --initial-state raw_data='[1, 2, 3]' transform
```

Handlers can use git utilities:

```python
from antkeeper.git import execute, current, GitCommandError, Worktree, git_worktree
from datetime import datetime

@app.handler
def git_operations(runner: Runner, state: State) -> State:
    # Get current branch
    branch = current()

    # Execute arbitrary git commands
    status = execute(["git", "status", "--short"])

    # Handle git errors
    try:
        execute(["git", "checkout", "nonexistent"])
    except GitCommandError as e:
        runner.report_error(f"Git failed: {e}")

    return {**state, "branch": branch, "status": status}

@app.handler
def isolated_workflow(runner: Runner, state: State) -> State:
    worktree_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{runner.id}"
    wt = Worktree(base_dir=runner.app.worktree_dir, name=worktree_name)

    with git_worktree(wt, create=True, branch="feat/new", remove=False):
        # Execute steps inside worktree - cwd is wt.path
        state = run_workflow(runner, state, [step1, step2])

    # Cwd restored, worktree kept for review
    return {**state, "worktree_path": wt.path}
```

### Logging and State Persistence

The framework creates a log file and state file for each workflow run:

- **Log file**: `{log_dir}/{timestamp}-{run_id}.log` (default: `agents/logs/`)
- **State file**: `{state_dir}/{timestamp}-{run_id}.json` (default: `.antkeeper/state/`)

Configure via `App(log_dir="path/", state_dir="path/")`. `log_dir` may be a callable `(runner) -> str` for per-handler dynamic directories (e.g. `lambda runner: f"logs/{runner.workflow_name}/{runner.id}"`). File naming ensures correlation between logs and state.

Logs capture framework lifecycle events (runner init, workflow start/complete), handler execution (step names, state keys at DEBUG level), and errors. State is persisted as JSON after initial creation, before the first `run_workflow()` step (with `_progress` initialized to `{"total": N, "completed": 0}`), after each `run_workflow()` step, and after final handler return.

Access the logger in handlers via `runner.logger`:

```python
@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.logger.info("Starting work")
    runner.logger.debug(f"State: {state}")
    return {**state, "done": True}
```

Log format: `YYYY-MM-DD HH:MM:SS,mmm [LEVEL] antkeeper.run.{run_id} - message`

Logs do not appear in stdout/stderr (propagation disabled).

### CLI Commands

**antkeeper init** - Scaffold a new project:
- `antkeeper init [path]` - Create a handlers.py file with starter workflows and examples (defaults to current directory)
- Generates a working `healthcheck` handler, commented examples for workflow composition and worktree isolation
- Prints guidance for environment variables (server and Slack integration)

**antkeeper run** - Execute a workflow via CLI:
- `--agents-file <path>` - Python file exporting `app` (default: `handlers.py`)
- `--model <name>` - Model name to inject as `state["model"]` (e.g., `opus`, `sonnet`)
- `--initial-state key=value` - Set additional state keys (repeatable)
- Positional file args after `workflow_name` are read and concatenated into `state["prompt"]`
- If no files provided and stdin is piped, stdin is read as the prompt

**antkeeper server** - Start FastAPI webhook server:
- `--host <host>` - Bind address (default: `127.0.0.1`)
- `--port <port>` - Port number (default: `8000`)
- `--reload` - Enable auto-reload on code changes
- `--agents-file <path>` - Python file exporting `app` (default: `handlers.py`)
- For Slack integration, set env vars `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` (via `.env` or environment)

**API Usage:**
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "healthcheck"}'
# Returns: {"run_id": "abc123"}
```

The justfile provides convenient recipes:
- `just sdlc "prompt" opus` - Run standard SDLC workflow, auto-detects if prompt is a file path
- `just sdlc_iso "prompt" opus` - Run isolated SDLC workflow in a git worktree
- `just server` - Start the API/Slack server

## Development

### Quality Checks

```bash
# Run all checks (default just target)
just

# Individual checks
just ruff    # Lint
just ty      # Type-check
just test    # Tests
```

### Testing

```bash
uv run -m pytest tests/ -v
```

Tests are organized to mirror the source layout (`tests/core/`, `tests/channels/`, `tests/handlers/`, `tests/llm/`, `tests/git/`). Each test owns its setup using shared fixtures from `tests/conftest.py`. The `app` fixture provides log, worktree, and state isolation via temp directories. Git-specific tests use the `git_repo` fixture from `tests/git/conftest.py`.

### Navigating the Codebase

Start with the **core layer** (`src/antkeeper/core/`):
- `domain.py` defines `State` and the `Channel` protocol — the two types everything else depends on
- `app.py` has the `App` registry and `run_workflow` composition helper
- `runner.py` ties `App` + `Channel` together and drives execution

The **channels layer** (`src/antkeeper/channels/`) has I/O adapters. `CliChannel` writes to stdout/stderr for terminal usage. `ApiChannel` writes to stdout/stderr for server logs. `SlackChannel` posts progress and results to Slack threads. Add new channels here for other I/O patterns.

The **http layer** (`src/antkeeper/http/`) contains HTTP endpoint logic:
- `__init__.py` exports `run_workflow_background()` (shared background task execution)
- `webhook.py` exports `handle_webhook()` (POST `/webhook` implementation)
- `slack_events.py` exports `SlackEventProcessor` class (POST `/slack_event` implementation with debounce state)
- `server.py` in the root defines routes with `@api.post()` decorators and delegates to these modules

The **handlers layer** (`src/antkeeper/handlers/`) contains pre-built handler collections. `handlers/claude_code/` provides 11 SDLC handlers using Claude Code as the LLM backend, exportable as a module-level `app` instance. `factories.py` inside that package exports `cc_handler`, a factory for building `(Runner, State) -> State` handlers in simple mode (static state updates) or JSON mode (LLM response parsing) without boilerplate.

The **llm layer** (`src/antkeeper/llm/`) abstracts LLM interactions behind the `Agent` protocol. `ClaudeCodeAgent` is the concrete implementation. Add new LLM backends by implementing `prompt(str) -> str`.

The **git layer** (`src/antkeeper/git/`) provides git integration for workflows. `core.py` exports `execute()` for low-level command execution and `GitCommandError` for failures. `branch.py` exports `current()` for getting the current branch name. `worktrees.py` provides the `Worktree` class and `git_worktree` context manager for isolated execution in separate working directories.

The **CLI** (`src/antkeeper/cli.py`) is the entry point. It loads user-defined handlers from a Python file (default: `handlers.py`) and wires everything together. Supports positional file args and stdin piping for injecting prompts into state.

### Framework Documentation

For detailed framework development documentation, see `app_docs/`:
- `app_docs/releasing.md` - Packaging, dependency management, PyPI release process
- `app_docs/testing_policy.md` - Testing approach, fixture management, patterns
- `app_docs/instrumentation.md` - Logging, state persistence, error handling
- `app_docs/http_server.md` - HTTP server architecture and endpoint design
- `app_docs/slack.md` - Slack integration details and runtime behavior

For a concise reference card, see `CLAUDE.md`.
