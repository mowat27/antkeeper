# Antkeeper

A lightweight Python workflow engine for agentic workflows that run AFK.

## Who This Is For

Engineers building agentic workflows — LLM-driven pipelines that spec out features, write code, create branches, open PRs — that need to run reliably without supervision.

Once you're running similar workflows across multiple projects, the duplication in wiring, error handling, and state management becomes unmanageable. Antkeeper extracts all of that into a framework so you can focus on the application-specifics of your agentic layer.

## The Problem

As you build with AI agents, you accumulate scripts that chain LLM calls into workflows. A typical one might take a prompt, generate a spec, create a branch, implement a feature, then document the changes. These scripts tend to:

- **Lose state** — a failure mid-workflow means starting from scratch. No recovery, no way to run unattended.
- **Duplicate wiring** — every script re-implements argument parsing, error handling, progress reporting, and LLM integration. Across repos, this compounds.
- **Lock to one surface** — a CLI script cannot easily become a Slack bot or an API endpoint, but you need the same workflow from all three.
- **Bind to one agent** — the workflow is hardwired to one LLM tool. Switching from Claude Code to Codex or a local model means rewriting.
- **Hide what happened** — no logging, no observability, no progress tracking. When something fails at 2am, there is no trail.

Antkeeper solves all five. State is persisted after every step. Handlers are reducers with no I/O coupling. Channels decouple trigger surfaces. The LLM layer is a protocol. And every workflow run produces file-based logs and optional OpenTelemetry traces.

## How It Works

Antkeeper draws on two ideas:

**From Flask** — decorators register entry points and the framework handles the wiring. In Flask, `@app.route("/hello")` binds a function to a URL. In Antkeeper, `@app.handler` registers a function as a workflow step that can be triggered from any channel.

**From Redux** — state is a plain dictionary that flows through pure functions. Each handler receives the current state and returns a new one, like a reducer. Handlers never mutate state — they return a fresh dict. State is persisted after every step, so a failure at step 3 of 5 preserves the output of steps 1 and 2.

An SDLC pipeline that takes a prompt and produces a specified, implemented, documented feature on a new branch:

```python
from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.handlers.claude_code import cc_handler

app = App()

# Factory-built steps: run an LLM command and thread results through state
specify    = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
implement  = cc_handler("/implement $spec_file")
document   = cc_handler("/document this branch.")

@app.handler
def branch(runner: Runner, state: State) -> State:
    """Create a feature branch from the slug the specify step produced."""
    from antkeeper.git import execute
    slug = state["slug"]
    execute(["checkout", "-b", slug])
    return {**state, "branch_name": slug}

@app.handler
def sdlc(runner: Runner, state: State) -> State:
    """Full pipeline: specify -> branch -> implement -> document."""
    return run_workflow(runner, state, [specify, branch, implement, document])
```

```bash
antkeeper run --model sonnet sdlc prompts/add-auth.md
```

The same workflow runs from an HTTP webhook or a CI job. With a Slack app configured, it can also be triggered by a message. The channel determines how input arrives and how progress is reported. Handlers work with state only.

### Core Concepts

**State** is a plain Python dictionary (`dict[str, Any]`). Each handler receives the current state, does its work, and returns a new dict. State is persisted as JSON after every step. A failure mid-workflow preserves the output of all completed steps, and `antkeeper resume <run_id>` can restart from where it left off.

**Handlers** are workflow steps. They follow the reducer pattern: `(Runner, State) -> State`. Pure functions — state in, new state out, no mutation. Register with `@app.handler` to make them callable by name from any channel. For the common case of running an LLM command and extracting fields from the response, the `cc_handler` factory builds handlers declaratively.

**Runner** is the execution context for a single workflow run. It binds an `App` (handler registry) to a `Channel` (I/O boundary) and manages the run lifecycle: generating a unique run ID, setting up per-run file logging, persisting state, and resolving environment variables. Handlers use the runner to communicate back to the channel (`runner.report_progress()`, `runner.report_error()`) and to signal failure (`runner.fail()`). The runner is passed to every handler but handlers do not need to manage it — it is infrastructure.

**Channels** are I/O adapters. They decouple workflow logic from how it is triggered and how it reports progress. The CLI channel reads from the terminal and writes to stdout. The API channel accepts HTTP POST requests and runs workflows in the background. The Slack channel posts to threads (requires your own Slack app — see below). Handlers do not need to know which channel is active.

**Agents** are the LLM abstraction. Any object with a `prompt(str) -> str` method qualifies. The built-in `ClaudeCodeAgent` delegates to the Claude CLI, but the protocol is deliberately minimal — plug in Codex, a local model, or any other backend. The `cc_handler` factory is a convenience method built on this protocol, but hand-written handlers can use it directly.

### Built-in Integrations

**Git** is available out of the box. `execute()` runs git commands, `current()` returns the branch name, `Worktree` and `git_worktree` manage isolated working directories. Git is ubiquitous in agentic workflows, so it ships as a utility. The same pattern could be extended for other common tools.

**Slack** is supported as a channel. The framework includes a `SlackChannel` that posts workflow progress and results as thread replies, triggered by @mentions. However, using it requires a Slack app installed in your workspace. Antkeeper does not distribute a public Slack app — you would need to create your own. See [Slack Integration](app_docs/slack.md) for details.

### Two Ways to Write Handlers

The **decorator pattern** provides full control:

```python
@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.report_progress("doing work")
    return {**state, "result": "done"}
```

The **handler factory** (`cc_handler`) eliminates boilerplate for steps backed by Claude Code. Most agentic workflow steps interpolate state into a prompt, call an LLM, and extract structured fields from the response:

```python
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
```

This creates a handler that interpolates `$prompt` from state, runs the command, extracts `spec_file` and `slug` from the response, and merges them into state.

Both approaches compose freely. Use the factory for the common pattern, hand-write handlers for custom logic.

## Installation

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

# Run an LLM workflow with a prompt file
antkeeper run --model sonnet specify prompts/describe.md

# Run the full SDLC pipeline
antkeeper run --model sonnet sdlc prompts/add-auth.md

# Start the API server
antkeeper server --host 0.0.0.0 --port 8000

# Resume a partially-completed workflow (run_id shown in the original run output)
antkeeper resume a1b2c3d4

# Trigger via HTTP
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "sdlc", "initial_state": {"prompt": "Add user authentication", "model": "sonnet"}}'
```

For Slack integration (requires your own Slack app), set `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` in a `.env` file and start the server. See [Slack Integration](app_docs/slack.md).

## Design Principles

- **State is a plain dict** — `dict[str, Any]`. Serialisable, inspectable, recoverable. Predictability through constraints, not capability.
- **Handlers are reducers** — `(Runner, State) -> State`. No mutation. Testable in isolation, composable in sequence.
- **Runner is infrastructure** — execution context, logging, state persistence, and channel communication. Handlers receive it but do not manage it.
- **Channels separate I/O from logic** — handlers are unaware of their trigger surface.
- **Agent-agnostic** — the LLM layer is a protocol (`prompt(str) -> str`), not a binding to one tool.
- **Composition over inheritance** — `run_workflow` folds state through a list of steps. No DAG scheduler, no base classes.
- **Convention over configuration** — sensible defaults for log directories, state persistence, and worktree paths.

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager (for development)

## Further Reading

- **[Reference Guide](app_docs/reference.md)** — Handlers, channels, LLM integration, git utilities, state persistence, logging, CLI commands
- **[Instrumentation](app_docs/instrumentation.md)** — Progress reporting, error handling, logging patterns, state persistence, workflow resume, OpenTelemetry tracing, Axiom querying
- **[HTTP Server](app_docs/http_server.md)** — Server architecture and endpoint design
- **[Slack Integration](app_docs/slack.md)** — Bot configuration, event handling, thread-based replies
- **[Testing Policy](app_docs/testing_policy.md)** — Test structure, fixtures, patterns
- **[Engineering Standards](app_docs/standards.md)** — Dependency philosophy, performance, no-singletons policy
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
