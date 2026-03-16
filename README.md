# Antkeeper

A lightweight Python workflow engine inspired by frameworks like Flask. Define workflow steps, wire them to I/O channels (CLI, API, Slack), and let the framework handle the plumbing.

## Who This Is For

If you're building multi-step workflows — especially ones involving LLM agents, git operations, or deployment pipelines — and you want a clean way to compose, observe, and trigger them from different surfaces, Antkeeper was built for this.

If you have a single script that runs once and you're happy with it, you probably don't need this.

## The Problem

As you automate more with AI agents, you accumulate scripts that chain LLM calls, git commands, and other steps together. These scripts tend to:

- **Lose state** — if a step fails halfway through, you start from scratch
- **Duplicate wiring** — every script re-implements argument parsing, error handling, and progress reporting
- **Lock you into one surface** — a CLI script can't easily become a Slack bot or an API endpoint
- **Hide what's happening** — no logging, no observability, no way to track progress

You end up with a collection of bespoke scripts that each solve the same infrastructure problems slightly differently.

## How It Works

Antkeeper borrows an idea from web frameworks like Flask: use decorators to register entry points, and let the framework handle the wiring.

In Flask, you write a function and decorate it to bind it to a URL:

```python
@app.route("/hello")
def hello():
    return "Hello, World!"
```

In Antkeeper, you write a function and decorate it to register it as a workflow step:

```python
from antkeeper.core.app import App
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State

app = App()

@app.handler
def greet(runner: Runner, state: State) -> State:
    runner.report_progress("saying hello")
    return {**state, "message": "Hello, World!"}
```

Then run it:

```bash
antkeeper run greet
```

That one handler can be triggered from the CLI, an HTTP endpoint, or a Slack message — the channel handles how input arrives and how output is reported. The handler just works with state.

### Three Core Concepts

**State** is a plain Python dictionary that flows through your workflow. Each step receives the current state, does its work, and returns a new state dict. State is automatically persisted as JSON after every step, so if something fails mid-workflow, the progress so far is preserved.

**Handlers** are the steps in your workflow. They're functions with the signature `(Runner, State) -> State`. Register them with `@app.handler` and they become callable by name from any channel.

**Channels** are I/O adapters. They determine where input comes from and where output goes. The CLI channel reads from the terminal and writes to stdout. The API channel accepts HTTP requests. The Slack channel reads thread messages and replies in-thread. Your handlers don't need to know which channel is active.

### Composing Workflows

Individual handlers can be composed into multi-step workflows using `run_workflow`:

```python
from antkeeper.core.app import App, run_workflow

app = App()

@app.handler
def fetch_data(runner, state):
    return {**state, "raw_data": [1, 2, 3]}

@app.handler
def transform(runner, state):
    doubled = [x * 2 for x in state["raw_data"]]
    return {**state, "transformed": doubled}

@app.handler
def pipeline(runner, state):
    return run_workflow(runner, state, [fetch_data, transform])
```

State threads through each step — `fetch_data` writes `raw_data`, `transform` reads it. Each step can also be run individually from the CLI.

### The Handler Factory

For LLM-backed workflows, writing full handler functions for every step creates a lot of repetition. The `cc_handler` factory builds handlers declaratively:

```python
from antkeeper.handlers.claude_code import cc_handler

specify    = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
implement  = cc_handler("/sdlc:implement $spec_file")
document   = cc_handler("/document this branch.")
```

Each line creates a handler that runs a command (with `$var` placeholders interpolated from state), optionally extracts structured fields from the response, and merges them back into state. This is how the built-in SDLC workflow is defined — the full pipeline is just:

```python
@app.handler
def sdlc(runner, state):
    return run_workflow(runner, state, [specify, branch, implement, document])
```

You can mix factory-built and hand-written handlers freely. The factory handles the common case; hand-written handlers handle everything else.

## Installation

### From PyPI

```bash
pip install antkeeper
```

### From Source

```bash
git clone https://github.com/mowat27/antkeeper.git
cd antkeeper
uv sync
```

## Quickstart

```bash
# Scaffold a new project with starter handlers
antkeeper init my-project
cd my-project

# Run the healthcheck workflow
antkeeper run healthcheck

# Run a workflow with initial state
antkeeper run --initial-state result=5 plus_1

# Run an LLM workflow with a prompt file
antkeeper run --model sonnet specify prompts/describe.md

# Start an API server
antkeeper server --host 0.0.0.0 --port 8000

# Trigger via HTTP
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "healthcheck"}'
```

For Slack integration, set `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` in a `.env` file and start the server. The bot responds to @mentions in threads.

## Design Principles

- **State is a plain dict** — no special types, no ORM. Every handler receives and returns `dict[str, Any]`.
- **Handlers are pure functions** — input state in, output state out. No mutation, no side-channel communication.
- **Channels separate I/O from logic** — handlers don't know whether they're running from a terminal, an API call, or a Slack message.
- **Composition over inheritance** — `run_workflow` folds state through a list of steps. No DAG scheduler, no base classes.
- **Slack is a first-class citizen** — not an afterthought or a plugin. It's a channel like CLI and API.
- **Convention over configuration** — sensible defaults for log directories, state persistence, and worktree paths. Override when you need to.

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager (for development)

## Further Reading

- **[Reference Guide](app_docs/reference.md)** — Detailed coverage of handlers, channels, LLM integration, git utilities, state persistence, logging, and CLI commands
- **[Instrumentation](app_docs/instrumentation.md)** — Progress reporting, error handling, logging patterns, state persistence
- **[HTTP Server](app_docs/http_server.md)** — Server architecture and endpoint design
- **[Slack Integration](app_docs/slack.md)** — Bot configuration, event handling, thread-based replies
- **[Testing Policy](app_docs/testing_policy.md)** — Test structure, fixtures, patterns
- **[Releasing](app_docs/releasing.md)** — Packaging, dependencies, PyPI release process

## Development

```bash
# Run all checks (default just target)
just

# Individual checks
just ruff    # Lint
just ty      # Type-check
just test    # Tests
```
