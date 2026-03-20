# Antkeeper Reference Guide

Detailed reference for the Antkeeper workflow framework. For an introduction to the concepts, see the main [README](../README.md).

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
│       ├── __init__.py # Exports cc_handler factory
│       └── factories.py # cc_handler factory implementation
├── helpers/
│   ├── json.py         # JSON extraction utilities
│   └── timestamps.py   # make_timestamp() and make_log_dir() utilities
├── llm/                # LLM agent abstraction layer
│   ├── __init__.py     # Agent protocol
│   ├── errors.py       # AgentExecutionError
│   └── claude_code.py  # ClaudeCodeAgent (subprocess-based)
├── http/               # HTTP server layer
│   ├── __init__.py     # Shared utilities: run_workflow_background()
│   ├── webhook.py      # POST /webhook endpoint
│   └── slack_events.py # POST /slack_event endpoint
├── cli.py              # Argparse-based CLI entry point
└── server.py           # Server orchestrator (delegates to http/)
```

## Core Concepts in Detail

### State

`State` is `dict[str, Any]`. All workflow data flows as a flat dictionary. Handlers receive and return `State`; the `Runner` injects `run_id` and `workflow_name`. State is automatically persisted as JSON on every change.

### Channel Protocol

Channels are I/O boundary adapters. They own how progress and errors are reported and what initial state is supplied. This is the primary extension point for new I/O adapters.

The framework ships three channels:

- **CliChannel** — writes to stdout/stderr for terminal usage
- **ApiChannel** — writes to stdout/stderr for server logs
- **SlackChannel** — posts progress and results to Slack threads

### App

The handler registry. Use `@app.handler` to register workflow steps by function name. Configure directories via `App(log_dir="...", worktree_dir="...", state_dir="...")`.

```python
app = App()  # Defaults: log_dir="agents/logs/", worktree_dir="trees/", state_dir=".antkeeper/state/"
```

**Dynamic log directories**: `log_dir` may be a callable `(runner) -> str` for per-handler paths. Use `make_log_dir()` for the standard timestamped per-run pattern:

```python
from antkeeper import make_log_dir
app = App(log_dir=make_log_dir("agents/logs"))  # → "agents/logs/20260314120000-a1b2c3d4/"
```

**App-level environment variables**: Inject env vars for every handler with `App(env={"KEY": "value"})`. Values are converted to `str()`, set before each handler runs, and restored afterward. Values may be callables `(runner) -> Any` evaluated per handler invocation:

```python
app = App(env={"RUN_ID": lambda runner: runner.id, "API_KEY": "sk-123"})
```

### Runner

The execution engine. Binds an `App` + `Channel`, generates a `run_id`, and drives the workflow lifecycle. Persists state to `{timestamp}-{run_id}.json` in `app.state_dir`.

### run_workflow

Composition helper. Folds state through a list of handler callables, enabling composite workflows without inheritance or a DAG scheduler. Tracks progress via a `_progress` key in state.

Accepts an optional `skip: int = 0` parameter. When `skip > 0`, the first *N* steps are not executed and `_progress["completed"]` starts at *N*. When `skip == 0` (the default), `run_workflow` checks state for `_resume_skip` and uses it as the skip value if present. The `_resume_skip` key is consumed on the first call and never persisted.

### Agent Protocol

LLM abstraction. Any object with a `prompt(str) -> str` method qualifies. Extension point for new LLM backends.

### ClaudeCodeAgent

Concrete `Agent` implementation. Delegates prompts to the `claude` CLI via subprocess. Accepts optional `model`, `yolo` (skip permissions), and `opts` (arbitrary CLI args) parameters.

## Writing Handlers

### Decorator Pattern

Create a Python file with an `App` instance and decorated handlers:

```python
from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State

app = App()

@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.report_progress("doing work")
    runner.logger.info("Custom log entry")
    return {**state, "result": "done"}
```

Handlers always return a **new** dict (spread pattern) — never mutate incoming state.

### Handler Factory (cc_handler)

For LLM-backed handlers, the `cc_handler` factory eliminates boilerplate. It operates in two modes:

**Fire-and-forget** — runs the command, returns state unchanged:

```python
from antkeeper.handlers.claude_code import cc_handler

implement = cc_handler("/sdlc:implement $spec_file")
```

**Extraction** — runs the command, then sends the response to a fast model (haiku) to extract structured JSON fields into state:

```python
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
```

Factory options:
- `command` — command string with `$var` placeholders interpolated from state
- `state_updates` — field names to extract from the LLM response. When empty or `None`, runs in fire-and-forget mode
- `label` — human-readable name for progress messages. Defaults to the first token of the command
- `model` — override the LLM model for this handler. Defaults to `state.get("model")`
- `env` — per-handler environment variable overrides. Merges with App-level env (handler values win)

Register factory-built handlers with `app.add_handler()`:

```python
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
app.add_handler(specify)
```

Or use them directly in `run_workflow` without registering:

```python
@app.handler
def sdlc(runner, state):
    return run_workflow(runner, state, [specify, branch, implement, document])
```

### LLM Integration in Hand-Written Handlers

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

### Git Utilities

```python
from antkeeper.git import execute, current, GitCommandError, Worktree, git_worktree
from antkeeper import make_timestamp

@app.handler
def git_operations(runner: Runner, state: State) -> State:
    branch = current()
    status = execute(["git", "status", "--short"])

    try:
        execute(["git", "checkout", "nonexistent"])
    except GitCommandError as e:
        runner.report_error(f"Git failed: {e}")

    return {**state, "branch": branch, "status": status}

@app.handler
def isolated_workflow(runner: Runner, state: State) -> State:
    worktree_name = f"{make_timestamp()}-{runner.id}"
    wt = Worktree(base_dir=runner.app.worktree_dir, name=worktree_name)

    with git_worktree(wt, create=True, branch="feat/new", remove=False):
        state = run_workflow(runner, state, [step1, step2])

    return {**state, "worktree_path": wt.path}
```

**Key git types:**
- **execute** — low-level git command execution. Returns stripped stdout, raises `GitCommandError` on failure
- **current** — returns current branch name (or "HEAD" if detached)
- **GitCommandError** — exception for non-zero exit codes. Contains stderr as message
- **Worktree** — git worktree wrapper with `create()`, `remove()`, and `exists`
- **git_worktree** — context manager that enters a worktree, guarantees cwd restoration, and optionally creates/removes the worktree

## Data Flow

### CLI Execution

1. CLI parses args and loads an agents file (Python module exporting `app`)
2. Builds a `CliChannel(workflow_name, initial_state)`
3. `Runner(app, channel).run()` merges initial state with `{run_id, workflow_name}`
4. Handler receives `(runner, state)` and returns new `State`
5. Composite handlers use `run_workflow` to chain sub-steps
6. For LLM workflows: handler creates an `Agent`, calls `agent.prompt()`, and spreads the response into state
7. Result state is printed to stdout
8. If handler calls `runner.fail()`, CLI catches `WorkflowFailedError`, prints to stderr, exits 1

### API Execution

1. POST `/webhook` with `{"workflow_name": "my_wf", "initial_state": {...}}`
2. Server validates workflow exists, creates `ApiChannel(workflow_name, initial_state)`
3. Returns `{"run_id": "abc123"}` immediately
4. Workflow runs in background task
5. Progress/errors appear in server logs

### Slack Execution

1. User @mentions the bot in a Slack thread
2. POST `/slack_event` receives the event, debounces rapid mentions
3. Server dispatches the workflow using `SlackChannel` bound to the originating thread
4. Workflow progress and results are posted as thread replies
5. Errors are reported back to the Slack thread

## Logging and State Persistence

The framework creates a log file and state file for each workflow run:

- **Log file**: `{log_dir}/{timestamp}-{run_id}.log` (default: `agents/logs/`)
- **State file**: `{state_dir}/{timestamp}-{run_id}.json` (default: `.antkeeper/state/`)

Logs capture framework lifecycle events, handler execution, and errors. State is persisted as JSON after initial creation, before the first `run_workflow()` step, after each step, and after final handler return.

### OpenTelemetry Tracing

The framework emits OpenTelemetry spans at `Runner.run()` (root span), each `run_workflow()` step (child spans), and each `ClaudeCodeAgent.prompt()` call (child spans). LLM call spans also inject `traceparent` into the subprocess environment for downstream trace correlation. To export spans, wrap your command with `opentelemetry-instrument` and set `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf`. Without `opentelemetry-instrument`, the no-op tracer is used. See [Instrumentation](instrumentation.md) for activation, resource attributes, querying, and design decisions.

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

## CLI Commands

### antkeeper init

Scaffold a new project:
- `antkeeper init [path]` — create a `handlers.py` with starter workflows (defaults to current directory)
- Generates a working `healthcheck` handler and commented examples

### antkeeper run

Execute a workflow via CLI:
- `--agents-file <path>` — Python file exporting `app` (default: `handlers.py`)
- `--model <name>` — model name injected as `state["model"]`
- `--initial-state key=value` — set additional state keys (repeatable)
- Positional file args after `workflow_name` are read and concatenated into `state["prompt"]`
- If no files provided and stdin is piped, stdin is read as the prompt

### antkeeper resume

Resume a partially-completed workflow run:
- `antkeeper resume [--agents-file PATH] <run_id>` — load the persisted state for `run_id`, skip already-completed steps, and continue from the next one
- `run_id` is the 8-character hex identifier printed by a previous `antkeeper run` invocation
- `--agents-file` defaults to `handlers.py`
- The resumed execution creates a **new** `run_id`, state file, and log file — the original is unchanged
- Fails with a clear stderr message and exit 1 if: `run_id` not found, state has no `_progress`, state has no `workflow_name`, or the workflow was already completed

### antkeeper server

Start FastAPI webhook server:
- `--host <host>` — bind address (default: `127.0.0.1`)
- `--port <port>` — port number (default: `8000`)
- `--reload` — enable auto-reload on code changes
- `--agents-file <path>` — Python file exporting `app` (default: `handlers.py`)
- For Slack: set `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` via `.env` or environment

### Justfile Recipes

- `just sdlc "prompt" opus` — run standard SDLC workflow
- `just sdlc_iso "prompt" opus` — run isolated SDLC workflow in a git worktree
- `just server` — start the API/Slack server

## Navigating the Codebase

Start with the **core layer** (`src/antkeeper/core/`):
- `domain.py` defines `State` and the `Channel` protocol — the two types everything else depends on
- `app.py` has the `App` registry and `run_workflow` composition helper
- `runner.py` ties `App` + `Channel` together and drives execution

The **channels layer** (`src/antkeeper/channels/`) has I/O adapters. Add new channels here for other I/O patterns.

The **http layer** (`src/antkeeper/http/`) contains HTTP endpoint logic. `webhook.py` handles POST `/webhook`, `slack_events.py` handles POST `/slack_event` with debounce state.

The **handlers layer** (`src/antkeeper/handlers/`) contains pre-built handler collections. `handlers/claude_code/` provides the `cc_handler` factory for building LLM-backed handlers.

The **llm layer** (`src/antkeeper/llm/`) abstracts LLM interactions behind the `Agent` protocol. Add new LLM backends by implementing `prompt(str) -> str`.

The **git layer** (`src/antkeeper/git/`) provides git integration. `core.py` for command execution, `branch.py` for branch operations, `worktrees.py` for isolated working directories.

The **CLI** (`src/antkeeper/cli.py`) is the entry point. Loads user-defined handlers and wires everything together.
