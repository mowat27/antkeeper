# Instrumentation

## Progress Reporting

Handlers report progress via the `Runner`:

```python
@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.report_progress("doing work")
    return {**state, "result": "done"}
```

The `Runner` delegates to the `Channel`, which formats and outputs the message based on its implementation:

- **CliChannel**: Writes to stdout with format `[workflow_name, run_id] message`
- **ApiChannel**: Writes to stdout with format `[workflow_name, run_id] message` (appears in server logs)
- **SlackChannel**: Posts to Slack thread via httpx sync POST with format `[workflow_name, run_id] message`
- **TestChannel**: Appends to `progress_messages` list for verification

## Error Reporting

Report non-fatal errors (informational warnings) via `runner.report_error()`:

```python
runner.report_error("optional validation failed, continuing")
```

For fatal errors, use `runner.fail()`:

```python
if "required_key" not in state:
    runner.fail("Missing required_key in state")
```

`fail()` raises `WorkflowFailedError` with the message. The CLI catches this exception, prints to stderr, and exits with code 1. API channels log the error and allow the server to continue. SlackChannel posts error messages to the thread with `[ERROR]` prefix: `[workflow_name, run_id] [ERROR] message`.

## Run Identification

Every workflow execution gets a unique `run_id` (8-character hex string). The `Runner` injects it into state along with `workflow_name`:

```python
state = {
    **channel.initial_state,
    "run_id": runner.id,
    "workflow_name": runner.workflow_name
}
```

Progress and error messages include the `run_id` for correlation.

## State Persistence

The framework automatically persists state as JSON on every change. State files are created in `app.state_dir` (default `.antkeeper/state/`) and named `{timestamp}-{run_id}.json` to match log file naming.

### Configuration

```python
app = App(state_dir=".antkeeper/state/")  # custom directory
app = App()                              # defaults to ".antkeeper/state/"
```

### Persistence Points

The `Runner` writes state to disk at four points:
1. **Initial state creation** - After injecting `run_id` and `workflow_name` but before handler execution
2. **Before the first workflow step** - When using `run_workflow()`, `_progress` is initialized and persisted immediately, before any step executes. When running fresh, `completed` starts at `0`; when resuming, it starts at the skip count. This guarantees external consumers reading state between workflow start and first-step completion always see `_progress`.
3. **After each workflow step** - When using `run_workflow()`, state is persisted after each step completes (with `_progress.completed` incremented)
4. **Final state** - After the handler returns successfully

Each write overwrites the file with the latest state snapshot (one file per run).

### State File Format

State files contain valid JSON with `indent=2` for readability:

```json
{
  "run_id": "a1b2c3d4",
  "workflow_name": "my_workflow",
  "result": "done"
}
```

State file stems match log file stems for correlation: `20260207143000-a1b2c3d4.json` pairs with `20260207143000-a1b2c3d4.log`.

### Workflow Resume

Because state is persisted after every step, a partially-completed workflow can be resumed from its last-known-good position. The `antkeeper resume <run_id>` CLI command loads the state file for a previous run, injects the `_resume_skip` signal into state, and re-executes the workflow using the original `workflow_name`.

`run_workflow` consumes `_resume_skip` on first call:

1. Strips `_resume_skip` from state before execution (it is never persisted and never visible to handlers).
2. Skips the first *N* steps, where *N* is the number of already-completed steps from `_progress["completed"]`.
3. Initialises `_progress["completed"]` to *N* rather than 0, so the progress counter accurately reflects the total steps completed across both runs.

The resumed execution creates a **new** `run_id`, new state file, and new log file. The original state file is not modified. Resuming the same `run_id` multiple times is therefore safe — each creates an independent execution.

Handlers require zero changes to support resume. The skip logic is entirely inside `run_workflow`.

### Error Handling

If a handler raises an exception, the state file contains the last successfully persisted state (typically the initial state). If state contains non-JSON-serializable values, `json.dump` raises `TypeError` - this is a handler bug, not a framework error.

## Logging

The framework provides file-based Python logging via the `Runner`. Each workflow run creates a dedicated log file.

### Configuration

```python
from antkeeper import make_log_dir

app = App(log_dir="my/logs/")          # custom static directory
app = App()                             # defaults to "agents/logs/"

# log_dir may also be a callable that receives the runner and returns a string.
# The callable is evaluated once per handler invocation, before the log file is created.
app = App(log_dir=lambda runner: f"logs/{runner.workflow_name}/{runner.id}")

# Use make_log_dir() for the standard timestamped-per-run pattern:
app = App(log_dir=make_log_dir("agents/logs"))
# Produces: "agents/logs/20260314120000-a1b2c3d4/"
```

`make_log_dir(base_dir)` returns a callable `(runner) -> str` that generates `"{base_dir}/{timestamp}-{runner.id}/"`. The timestamp is captured at invocation time (when the Runner initialises), not when `make_log_dir` is called.

When `log_dir` is a callable it is resolved inside `Runner.__init__`, so `runner.id` and `runner.channel` (including `runner.workflow_name`) are available. State is not yet available at that point — `log_dir` is infrastructure set up before the handler runs.

Static string values continue to work identically to current behaviour.

### Callable env Values

Values in the `env` dict passed to `App(env={...})` may also be callables. Each callable receives the `runner` and is evaluated immediately before the handler runs (inside `Runner.run()`), so `runner.id`, `runner.workflow_name`, and the full `runner.channel` are available. State is not passed — env resolution happens before state is processed by the handler.

```python
# Static env vars (existing behaviour — unchanged)
app = App(env={"API_KEY": "sk-123", "TIMEOUT": 30})

# Callable env vars — resolved per handler invocation
app = App(env={
    "STATIC_KEY": "always-this",
    "RUN_ID": lambda runner: runner.id,
    "LOG_PATH": lambda runner: f"logs/{runner.id}.log",
})
```

Mixed dicts (some static, some callable values) are supported. The save/restore lifecycle is the same as for static values: env vars are set before the handler runs and restored (or removed) after it returns, whether it succeeds or raises.

Errors raised by callable values propagate immediately; the `finally` block in `_app_env` still restores any variables that were already set.

### Per-Run Log Files

`Runner.__init__` creates a log file at `{log_dir}/{YYYYMMDDhhmmss}-{run_id}.log` with format:

```
2026-02-07 14:30:00,123 [INFO] antkeeper.run.a1b2c3d4 - Workflow started: my_workflow
```

The framework logs lifecycle events (runner init, workflow start/complete), handler execution (step names, state keys), and errors at INFO/DEBUG/ERROR levels. Log output does not leak to stdout/stderr (logger propagation is disabled).

### Using the Logger in Handlers

Handlers can access `runner.logger` for custom logging:

```python
@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.logger.info("Starting work")
    runner.logger.debug(f"State: {state}")
    return {**state, "done": True}
```

### Module-Level Loggers

Module-level loggers exist in `cli.py`, `channels/cli.py`, `channels/slack.py`, and `llm/claude_code.py`. These only produce output if a user configures handlers on them or their parents — they serve as extension points for additional logging.

## Claude Code Handler Factory

The `cc_handler` factory (`antkeeper.handlers.claude_code.factories`) eliminates boilerplate for building Claude Code handlers. It produces `(Runner, State) -> State` callables in two modes:

- **Fire-and-forget mode** — run the LLM command with a single `run_prompt` call and return state unchanged.
- **Extraction mode** — run the command first (Step 1), then send the response to haiku via `_extraction_prompt` (Step 2) to extract structured JSON fields. Parse the result with `extract_json` and merge the requested `state_updates` fields into state.

The extraction step always uses the `haiku` model (constant `_EXTRACTION_MODEL`), regardless of the handler's configured model. This is an implementation detail, not a caller-facing knob.

```python
from antkeeper.handlers.claude_code import cc_handler

# Fire-and-forget mode: single run_prompt call, return state unchanged
implement = cc_handler("/implement $spec_file")

# Extraction mode: two run_prompt calls — raw prompt then extraction prompt to haiku
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
```

### Per-Handler Env Override

Pass `env` to set environment variables for the duration of that handler's execution only. The dict merges with App-level env using `{**app_env, **handler_env}` semantics — handler values win for overlapping keys. Variables are restored after the handler completes, whether it succeeds or raises.

```python
# Set a specific effort level for one heavyweight handler
implement_team = cc_handler(
    "/implement-team $spec_file",
    label="Implement spec_file using a team",
    env={"CLAUDE_CODE_EFFORT_LEVEL": "high"},
)

# Combined with model override
specify_slice = cc_handler(
    "/design-importer specify-slice $prompt",
    label="Specify design slice",
    model='sonnet',
    env={"CLAUDE_CODE_EFFORT_LEVEL": "medium"},
    state_updates=["spec_file"],
)

# No env override — behaves exactly as before
review = cc_handler("/review $spec_file", label="Review spec_file")
```

The `env` dict contains static `str` values only (no callables). Values are active for the entire handler execution, including both `run_prompt` calls in extraction mode. `env=None` (the default) is a no-op — fully backward compatible.

The implementation wraps the handler body in `with _app_env(env):`, reusing the same context manager that handles App-level env. Handler-level env nests inside any App-level env that is already active.

### Model Override

Pass `model` to pin a specific LLM model at factory time, overriding `state.get("model")`. When omitted, the handler falls back to the model from state.

```python
# Pin to a specific model regardless of state
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"], model="claude-sonnet-4")

# Default: uses state.get("model")
implement = cc_handler("/implement $spec_file")
```

### Label and Progress Messages

The factory standardises progress reporting to `"Running {label}"` and `"{label} complete"`. The label defaults to the first whitespace-delimited token of the command with any leading `/` stripped:

- `/implement $spec_file` → label `implement`
- `/branch $spec_file` with explicit `label="branch_if_on_main"` → label `branch_if_on_main`

The generated handler's `__name__` attribute is set to the label, making it compatible with `app.add_handler()`.

### Command Interpolation

Command strings use `$var` placeholders. Each `$name` token is substituted with `str(state[name])` at call time. A missing state key raises `WorkflowFailedError` (via `runner.fail()`). The `${var}` brace form is intentionally not interpolated and passes through as literal text.

### Error Handling

The factory wraps the LLM call, interpolation, and response parsing in a single `try/except` that catches:
- `KeyError` — missing state key for a `$var` placeholder
- `AgentExecutionError` — LLM subprocess failure
- `ValueError` — unparseable JSON response or missing required JSON field

All three route through `runner.fail(f"{label} failed: {error}")`, which raises `WorkflowFailedError`. This is an improvement over the hand-written handlers it replaces, which let exceptions propagate uncaught.

### When to Use the Factory vs Hand-Written Handlers

Use `cc_handler` for handlers that:
- Run a single LLM command and either discard the response or extract named JSON fields into state
- Need no post-LLM logic beyond the standard state merge

Write handlers by hand when:
- Additional computation is needed after the LLM call (e.g. `commit` calls `latest_commit()` on the result)
- The handler logs or posts the raw LLM response directly (e.g. `healthcheck`)
- The handler composes multiple steps via `run_workflow()`

### Registering Factory-Built Handlers

Factory-built handlers are not decorated with `@app.handler`, so they must be explicitly registered:

```python
implement = cc_handler("/implement $spec_file")
app.add_handler(implement)  # uses handler.__name__ as the registered name
```

## LLM Agent Execution

The `ClaudeCodeAgent` provides flexible configuration for invoking the Claude CLI:

```python
from antkeeper.llm.claude_code import ClaudeCodeAgent

# Basic usage with model selection
agent = ClaudeCodeAgent(model="claude-opus-4")

# Skip permissions prompts (yolo mode)
agent = ClaudeCodeAgent(yolo=True)

# Pass arbitrary CLI arguments
agent = ClaudeCodeAgent(opts=["--verbose", "--max-tokens", "4096"])

# Combine options (opts override convenience params)
agent = ClaudeCodeAgent(model="sonnet", yolo=True, opts=["--fast"])
```

### Constructor Parameters

- **model** (`str | None`): Model identifier passed as `--model` flag. If None, uses CLI default.
- **yolo** (`bool`): When True, passes `--dangerously-skip-permissions` to skip permission prompts.
- **opts** (`list[str] | None`): Arbitrary CLI arguments. When opts contains a flag that matches a convenience param (e.g., `--model`), the opts version takes precedence.

### JSON Output and Telemetry

`ClaudeCodeAgent.prompt()` always passes `--output-format json` to the Claude CLI (unless the caller already includes `--output-format` in `opts`). It parses the JSON envelope from stdout and returns `data["result"]` — the plain string result. Callers see no change in the return type.

After each successful call, the following fields are logged at DEBUG level on the `antkeeper.llm.claude_code` logger:

```
LLM session_id=<id> duration_ms=<ms> usage=<dict> cost=<usd>
```

All fields are read via `.get()` and may be `None` if absent from the envelope. To correlate a run with its Claude session transcript, use the logged `session_id` to locate:

```
~/.claude/projects/<project>/<session_id>.jsonl
```

### Error Handling

The agent raises two distinct exception types:

- **`AgentExecutionError`** — subprocess execution failures: binary not found, or non-zero exit code.
- **`ValueError`** — output parse failures: stdout is not valid JSON, or the parsed envelope is missing the `result` field. The error message includes a truncated excerpt of raw stdout for diagnostics.

```python
try:
    response = agent.prompt("/specify build a feature")
except AgentExecutionError as e:
    runner.fail(f"Agent failed: {e}")
except ValueError as e:
    runner.fail(f"Unexpected LLM output: {e}")
```

The `cc_handler` factory catches both `AgentExecutionError` and `ValueError` and routes them through `runner.fail()`.

No automatic retry. Handlers are responsible for error handling policy.

## OpenTelemetry Tracing

The framework emits OpenTelemetry spans at three instrumentation points. Tracing is activated entirely via standard OTel environment variables — when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, spans are exported; when unset, the no-op tracer is used with zero overhead.

### Activation

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.axiom.co"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer api_xxx,X-Axiom-Dataset=antkeeper"
export OTEL_SERVICE_NAME="antkeeper"
antkeeper run --model sonnet sdlc prompts/add-auth.md
```

No channel-specific changes are needed. All channels (CLI, API, Slack) benefit automatically because tracing is in the core execution path.

### Instrumentation Points

Each call site uses `trace.get_tracer("antkeeper")` directly — no singleton wrapper or tracing module. This follows the "No Singletons" standard in [standards.md](standards.md).

**1. `Runner.run()` — root span**

Span name: `antkeeper.run`
Attributes: `run_id`, `workflow_name`, `channel.type`
On exception: records exception on span, sets span status to ERROR, re-raises.

**2. `run_workflow()` — per-step child spans**

Span name: `antkeeper.workflow.step`
Attributes: `run_id`, `workflow_name`, `step_name`, `step_index`, `step_total`
On exception: records exception on span, sets span status to ERROR, re-raises.

**3. `ClaudeCodeAgent.prompt()` — per-LLM-call child spans**

Span name: `antkeeper.llm.call`
Attributes set before call: `prompt_length`
Attributes set after successful call: `session_id`, `duration_ms`, `input_tokens`, `output_tokens`, `total_cost_usd`, `model`
On exception: records exception on span, sets span status to ERROR, re-raises.

### Span Hierarchy

A typical multi-step workflow produces this span tree:

```
antkeeper.run (run_id, workflow_name, channel.type)
  └─ antkeeper.workflow.step (step_name="specify", step_index=0)
  │    └─ antkeeper.llm.call (session_id, cost, tokens)
  │    └─ antkeeper.llm.call (extraction call to haiku)
  └─ antkeeper.workflow.step (step_name="branch", step_index=1)
  └─ antkeeper.workflow.step (step_name="implement", step_index=2)
       └─ antkeeper.llm.call (session_id, cost, tokens)
```

Context propagation is automatic. Because `run_workflow` calls steps synchronously and steps call `ClaudeCodeAgent.prompt()` synchronously, Python's `contextvars`-based OTel propagation creates correct parent-child relationships with no extra wiring.

### Design Decisions

- **No `@traced` decorator or tracing middleware.** Instrumentation is explicit `with tracer.start_as_current_span(...)` at three specific call sites.
- **No `TracingConfig` or configuration abstraction.** OTel's own env-var-based configuration is sufficient.
- **No TracerProvider setup in library code.** Provider configuration is the deployer's responsibility via `OTEL_*` env vars or `opentelemetry-distro` auto-configuration.
- **Flat attribute names.** Uses `run_id`, `session_id`, `input_tokens` rather than OTel semantic convention namespaces. These are domain-specific attributes.
- **OTel packages are core dependencies.** See [standards.md](standards.md) for the rationale.

## Git Integration

The `antkeeper.git` module provides git utilities for workflow execution, including low-level command execution, branch operations, and worktree isolation.

### Git Command Execution

The `git.core` module provides low-level command execution:

```python
from antkeeper.git import execute, GitCommandError

# Execute any git command (git prefix is auto-prepended if missing)
output = execute(["status"])
output = execute(["log", "--oneline", "-n", "5"])

# Explicit prefix still works
output = execute(["git", "status"])

# Raises GitCommandError on non-zero exit
try:
    execute(["checkout", "nonexistent-branch"])
except GitCommandError as e:
    runner.fail(f"Git command failed: {e}")
```

The `execute()` function:
- Automatically prepends `"git"` if not present; accepts commands with or without the prefix
- Returns stripped stdout on success
- Raises `GitCommandError` with stderr on failure
- Logs commands at debug level via `antkeeper.git.core` logger
- Returns empty string for successful commands with no output

**Design principle**: No input validation for impossible scenarios. The function delegates directly to `subprocess.run()`, which naturally handles edge cases like empty command lists. This follows the framework philosophy of avoiding validation for scenarios that can't happen in practice.

### Branch Operations

The `git.branch` module provides high-level branch utilities:

```python
from antkeeper.git import current

# Get current branch name
branch_name = current()  # "main", "feat/new-feature", or "HEAD" (detached)
```

The `current()` function:
- Returns current branch name or "HEAD" if in detached HEAD state
- Delegates to `execute(["rev-parse", "--abbrev-ref", "HEAD"])`
- Propagates `GitCommandError` on failure

### Worktree Configuration

```python
app = App(worktree_dir="trees/")  # custom directory
app = App()                        # defaults to "trees/"
```

Access the configured worktree directory via `runner.app.worktree_dir`.

### Worktree Class

The `Worktree` class wraps git worktree subprocess operations:

```python
from antkeeper.git import Worktree, WorktreeError

wt = Worktree(base_dir=runner.app.worktree_dir, name="20260207-a1b2c3d4")
wt.create(branch="feat/new-feature")  # Creates worktree with new branch
# wt.path is absolute, safe after cwd changes
wt.remove()  # Removes worktree
```

All paths are stored as absolute (`os.path.realpath`) so they remain valid after `os.chdir()`.

### git_worktree Context Manager

The `git_worktree` context manager guarantees cwd restoration via try/finally:

```python
from antkeeper.git import git_worktree, Worktree, WorktreeError

wt = Worktree(base_dir=runner.app.worktree_dir, name="feature-work")

# Create, enter, and clean up
with git_worktree(wt, create=True, branch="feat/x", remove=True):
    # Work inside worktree - cwd is wt.path
    state = run_workflow(runner, state, [step1, step2])
# Worktree is removed, cwd is restored

# Enter existing worktree
with git_worktree(wt, create=False):
    # Work inside existing worktree
    pass
# cwd restored, worktree kept
```

Key guarantees:
- **Cwd restoration**: `os.chdir()` back to original directory in finally block
- **Error propagation**: Git failures raise `WorktreeError` with stderr
- **Cleanup safety**: Removal happens after cwd restoration (not while inside worktree)
- **Validation**: Raises `WorktreeError` if `create=False` and worktree doesn't exist

Cwd changes are process-wide. The context manager is designed for single-threaded execution.

### Worktree Naming Pattern

Follow the log file naming convention for correlation:

```python
from antkeeper import make_timestamp

worktree_name = f"{make_timestamp()}-{runner.id}"
# Example: "20260207143000-a1b2c3d4"
```

This allows matching worktrees to their log files via the run_id.

### Error Handling

Git operations raise specific exceptions based on their failure domain:

- **GitCommandError** - Raised by `execute()` and propagates through `current()`. Indicates a git command failed with non-zero exit code.
- **WorktreeError** - Raised by `Worktree` class methods and `git_worktree` context manager. Indicates worktree-specific failures.

These exceptions are intentionally separate to represent different failure domains:

```python
from antkeeper.git import GitCommandError, WorktreeError

# Handle command execution failures
try:
    execute(["checkout", "nonexistent"])
except GitCommandError as e:
    runner.fail(f"Git command failed: {e}")

# Handle worktree operation failures
try:
    wt.create(branch="feat/x")
except WorktreeError as e:
    runner.fail(f"Worktree creation failed: {e}")
```

The framework does not catch these errors. Handlers are responsible for error policy.
