# Antkeeper

A lightweight Python workflow engine for building agentic workflows you can run AFK. Define workflow steps, wire them to I/O channels (CLI, API, Slack), and walk away.

## Who This Is For

If you're building agentic workflows — LLM-driven pipelines that spec out features, write code, create branches, open PRs — and you want them to run reliably without you watching, Antkeeper was built for this.

If you work in one repo and your automation is a single script, you probably don't need this. But once you're running similar agentic workflows across multiple projects, the duplication in wiring, error handling, and state management starts to hurt.

## The Problem

As you build with AI agents, you accumulate scripts that chain LLM calls together into workflows. A typical one might: take a prompt, generate a spec, create a branch, implement the feature, then document the changes. These scripts tend to:

- **Lose state** — if a step fails halfway through, you start from scratch. You can't walk away from the keyboard because there's no way to recover.
- **Duplicate wiring** — every script re-implements argument parsing, error handling, progress reporting, and LLM integration. Across multiple repos, this adds up fast.
- **Lock you into one surface** — a CLI script can't easily become a Slack bot or an API endpoint. But you want to trigger the same workflow from all three.
- **Bind to one agent** — your workflow is hardwired to one LLM tool. Switching from Claude Code to Codex or a local model means rewriting everything.
- **Hide what's happening** — no logging, no observability, no way to track progress. When something fails at 2am, you have no idea what happened.

## How It Works

Antkeeper draws on two ideas:

**From Flask** — use decorators to register entry points and let the framework handle the wiring. In Flask, `@app.route("/hello")` binds a function to a URL. In Antkeeper, `@app.handler` registers a function as a workflow step that can be triggered from any channel.

**From Redux** — state is a plain dictionary that flows through pure functions. Each handler receives the current state and returns a new one, like a Redux reducer. Handlers never mutate state — they always return a fresh dict. This makes workflows predictable, testable, and recoverable: state is persisted after every step, so if something fails, you know exactly where it got to.

Here's what a real workflow looks like — an SDLC pipeline that takes a prompt and turns it into a specified, implemented, documented feature on a new branch:

```python
from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.handlers.claude_code import cc_handler

app = App()

# Factory-built steps — each one runs an LLM command and threads results through state
specify    = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
implement  = cc_handler("/sdlc:implement $spec_file")
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
    """Full pipeline: specify → branch → implement → document."""
    return run_workflow(runner, state, [specify, branch, implement, document])
```

Then trigger it and walk away:

```bash
antkeeper run --model sonnet sdlc prompts/add-auth.md
```

That same workflow can run from a Slack message, an HTTP webhook, or a CI job — the channel handles how input arrives and how progress is reported. The handlers just work with state.

### Core Concepts

**State** is a plain Python dictionary (`dict[str, Any]`). Each handler receives the current state, does its work, and returns a new dict. State is automatically persisted as JSON after every step. If something fails mid-workflow, the progress so far is saved — you can see exactly where it got to and what each step produced.

**Handlers** are the steps in your workflow. They follow the reducer pattern: `(Runner, State) -> State`. Pure functions that take state in and return new state out, never mutating the input. Register them with `@app.handler` and they become callable by name from any channel. For the common case of "run an LLM command and extract some fields", the `cc_handler` factory builds handlers declaratively without the boilerplate.

**Channels** are I/O adapters that decouple your workflow logic from how it's triggered and how it reports progress. The CLI channel reads from the terminal and writes to stdout. The API channel accepts HTTP POST requests and runs workflows in the background. The Slack channel reads @mentions in threads and replies in-thread. Your handlers don't need to know which channel is active.

**Agents** are the LLM abstraction layer. Any object with a `prompt(str) -> str` method qualifies. The built-in `ClaudeCodeAgent` delegates to the Claude CLI, but the protocol is deliberately simple so you can plug in other backends — Codex, a local model, a custom chatbot wrapper. The `cc_handler` factory is built on top of this, but you can use the `Agent` protocol directly in hand-written handlers.

### Built-in Integrations

**Git** is available out of the box because it's ubiquitous in agentic workflows. `execute()` runs arbitrary git commands, `current()` returns the branch name, `Worktree` and `git_worktree` manage isolated working directories for parallel workflows. These are provided as utilities, not as a core abstraction — the same pattern could be extended for other common tools.

**Slack** is a first-class channel, not an afterthought. Start the server with bot credentials and workflows are triggered by @mentions, with progress and results posted as thread replies. This matters because agentic workflows are most useful when you can fire them off and check back later.

### Two Ways to Write Handlers

The **decorator pattern** gives you full control. Write a function, decorate it with `@app.handler`, and do whatever you need inside:

```python
@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.report_progress("doing work")
    # ... any logic you need
    return {**state, "result": "done"}
```

The **handler factory** (`cc_handler`) eliminates boilerplate for LLM-backed steps. Most agentic workflow steps follow the same pattern: interpolate some state into a prompt, call an LLM, maybe extract structured fields from the response. The factory encodes that pattern:

```python
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
```

This creates a handler that interpolates `$prompt` from state, runs the command, extracts `spec_file` and `slug` from the response, and merges them back into state. One line instead of fifteen.

You can mix both freely. Use the factory for the common case, hand-write handlers when you need custom logic.

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

# Start an API/Slack server
antkeeper server --host 0.0.0.0 --port 8000

# Trigger via HTTP
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "sdlc", "initial_state": {"prompt": "Add user authentication", "model": "sonnet"}}'
```

For Slack integration, set `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` in a `.env` file and start the server. The bot responds to @mentions in threads.

## Design Principles

- **State is a plain dict** — no special types, no ORM. Serialisable, inspectable, recoverable. Borrowed from Redux: predictability comes from constraints, not capability.
- **Handlers are reducers** — `(state) -> new_state`. Pure functions, no mutation. Testable in isolation, composable in sequence.
- **Channels separate I/O from logic** — handlers don't know whether they're running from a terminal, an API call, or a Slack message.
- **Agent-agnostic** — the LLM layer is a protocol (`prompt(str) -> str`), not a binding to one tool. Swap backends without rewriting workflows.
- **Composition over inheritance** — `run_workflow` folds state through a list of steps. No DAG scheduler, no base classes, no framework superclasses.
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
