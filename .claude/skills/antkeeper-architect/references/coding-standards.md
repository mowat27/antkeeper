# Antkeeper Coding Standards

## Contents

1. [Handlers are reducers](#handlers-are-reducers)
2. [State is a plain dict — never mutate](#state-is-a-plain-dict--never-mutate)
3. [Use cc_handler for LLM-backed steps](#use-cc_handler-for-llm-backed-steps)
4. [cc_handler factory options](#cc_handler-factory-options)
5. [Compose workflows with run_workflow](#compose-workflows-with-run_workflow)
6. [Register vs inline handlers](#register-vs-inline-handlers)
7. [Use runner for communication — not print](#use-runner-for-communication--not-print)
8. [Stream events through the channel](#stream-events-through-the-channel)
9. [All commands run via uv](#all-commands-run-via-uv)
10. [Retry with validation using ralph](#retry-with-validation-using-ralph)

---

## Handlers are reducers

**Rule:** Every handler has the signature `(Runner, State) -> State`. No side-channel returns, no mutations.

**Why:** This makes handlers testable in isolation, composable in sequence, and resumable after failure. State is persisted after every step — a crash at step 3 preserves steps 1 and 2.

**Pattern:**
```python
# Good
@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.report_progress("doing work")
    return {**state, "result": "done"}

# Bad — mutates state
@app.handler
def my_step(runner: Runner, state: State) -> State:
    state["result"] = "done"  # mutation breaks the reducer contract
    return state
```

---

## State is a plain dict — never mutate

**Rule:** Always return a new dict using the spread pattern `{**state, "key": value}`. Never assign into the incoming state dict.

**Why:** Immutable state enables reliable persistence, resume, and debugging. If a handler mutates state and then fails, the persisted state is in an undefined intermediate condition.

**Pattern:**
```python
# Good — new dict
return {**state, "branch_name": slug, "spec_file": path}

# Bad — mutation
state["branch_name"] = slug
return state
```

**Framework-reserved keys** (set by the runner, not by handlers):
- `run_id` — 8-character hex identifier
- `workflow_name` — name of the executing workflow
- `_progress` — `{"total": int, "completed": int}` (set by `run_workflow`)
- `_resume_skip` — one-shot signal consumed by `run_workflow` for resume

---

## Use cc_handler for LLM-backed steps

**Rule:** When a handler's job is "interpolate state into a prompt, call the LLM, optionally extract fields from the response", use `cc_handler` instead of writing it by hand.

**Why:** The factory handles prompt interpolation, model selection, streaming, extraction via a fast model, error handling, and progress reporting. Hand-writing this for every step duplicates ~30 lines of boilerplate.

**Pattern:**
```python
from antkeeper.handlers.claude_code import cc_handler

# Fire-and-forget — runs the command, returns state unchanged
implement = cc_handler("/sdlc:implement $spec_file")

# Extraction — runs the command, extracts fields into state
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
```

**When to hand-write instead:** When the handler has custom logic beyond "call LLM and extract" — e.g. git operations, conditional branching, calling multiple agents, or custom state transformations.

---

## cc_handler factory options

**Rule:** Know all the options available to `cc_handler` and use them appropriately.

**Why:** The factory is more capable than it looks. Using the right options avoids hand-writing handlers unnecessarily.

**Full signature:**
```python
cc_handler(
    command: str,           # Command with $var placeholders from state
    *,
    state_updates: list[str] | None = None,  # Fields to extract into state
    label: str | None = None,                # Progress message label
    model: str | None = None,                # Override LLM model
    env: dict[str, str] | None = None,       # Per-handler env vars
    opts: list[str] | None = None,           # Extra CLI flags forwarded verbatim to ClaudeCodeAgent
    yolo: bool = True,                       # Controls --dangerously-skip-permissions (default True for backward compat)
)
```

**Options in detail:**

| Option | Default | Purpose |
|--------|---------|---------|
| `command` | (required) | Command string. `$var` placeholders are interpolated from state at runtime. E.g. `"/specify $prompt"` reads `state["prompt"]`. |
| `state_updates` | `None` | List of field names to extract from the LLM response. When set, triggers extraction mode: the response is sent to a fast model (haiku) which returns JSON with the requested fields. These are merged into state. When `None`, fire-and-forget mode. |
| `label` | First token of command | Human-readable label for progress messages. E.g. `cc_handler("/sdlc:implement $spec_file", label="implement")`. |
| `model` | `state.get("model")` | Pin a specific LLM model for this handler, ignoring whatever model is in state. |
| `env` | `None` | Environment variables set only for this handler's execution. Merges with App-level env (handler values win). |
| `opts` | `None` | List of extra CLI flags forwarded verbatim to `ClaudeCodeAgent`. E.g. `opts=["--max-turns", "5"]`. `ClaudeCodeAgent` handles deduplication — if `opts` contains `--model`, `--dangerously-skip-permissions`, `--output-format`, or `--verbose`, the agent skips adding those from its convenience params. |
| `yolo` | `True` | Controls whether `--dangerously-skip-permissions` is passed to the Claude CLI. Defaults to `True` for backward compatibility. Set to `False` for handlers that should prompt for permissions. |

**Extraction mode detail:** When `state_updates` is set, after the primary LLM call completes, the factory sends the response to haiku with `--max-turns 1` asking it to extract the specified fields as JSON. The extraction events are marked `internal=True` so channels can filter them. The extracted dict is merged into state.

---

## Compose workflows with run_workflow

**Rule:** Use `run_workflow(runner, state, steps)` to chain handlers into multi-step workflows. Don't hand-roll sequential handler calls.

**Why:** `run_workflow` provides progress tracking (`_progress` key), state persistence after each step, resume support, and OpenTelemetry span creation per step — all for free.

**Pattern:**
```python
from antkeeper.core.app import run_workflow

@app.handler
def sdlc(runner: Runner, state: State) -> State:
    return run_workflow(runner, state, [specify, branch, implement, document])
```

Steps can be any mix of factory-built handlers and decorated handlers:
```python
STEPS = [specify, branch, implement, document]  # constants for reuse

@app.handler
def partial(runner: Runner, state: State) -> State:
    return run_workflow(runner, state, STEPS[:2])  # specify + branch only
```

---

## Register vs inline handlers

**Rule:** Use `@app.handler` for handlers called by name from CLI/API/Slack. Use `app.add_handler()` for factory-built handlers that need to be callable by name. Use neither for handlers that only appear as steps in `run_workflow`.

**Why:** Registration makes a handler addressable by name (`antkeeper run my_handler`). Steps in `run_workflow` don't need registration — they're called directly as functions.

**Pattern:**
```python
# Registered — callable by name from CLI
@app.handler
def healthcheck(runner: Runner, state: State) -> State: ...

# Registered factory handler — callable by name
commit = cc_handler("/commit_push_raise_pr", state_updates=["pr_url"])
app.add_handler(commit)

# Unregistered — only used as a step in run_workflow
specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
```

You can also pass a `handlers` dict to `App()` at construction:
```python
app = App(handlers={"commit": commit_handler, "deploy": deploy_handler})
```

---

## Use runner for communication — not print

**Rule:** Use `runner.report_progress()` and `runner.report_error()` for all output. Use `runner.logger` for debug/info logging. Never use `print()`.

**Why:** `report_progress` and `report_error` route through the channel, so the same handler works on CLI (stdout), API (server logs), and Slack (thread replies). `print()` bypasses the channel and breaks non-CLI execution.

**Pattern:**
```python
@app.handler
def my_step(runner: Runner, state: State) -> State:
    runner.report_progress("Starting work")       # → channel
    runner.logger.info("Debug detail")             # → per-run log file
    runner.report_error("Something went wrong")    # → channel (stderr/error)
    runner.fail("Fatal error")                     # → raises WorkflowFailedError
```

---

## Stream events through the channel

**Rule:** When calling the LLM directly in a hand-written handler (not via `cc_handler`), stream events through the channel as they arrive rather than buffering with `collect_result`.

**Why:** Streaming gives real-time visibility into LLM progress. The channel decides how to display events — CLI prints them, Slack posts them, API logs them. Buffering hides all intermediate output until the call completes.

**Pattern:**
```python
from antkeeper.llm.claude_code import run_prompt

@app.handler
def my_llm_step(runner: Runner, state: State) -> State:
    stream = run_prompt("Do something", runner.logger, model=state.get("model"))
    result_text = ""
    for event in stream:
        runner.channel.report(runner.id, event)
        if event.type == "result" and not event.internal:
            result_text = event.content
    return {**state, "output": result_text}
```

Each `StreamEvent` has: `type` (progress/assistant/tool/result/rate_limit/error), `content`, `metadata` (usage, cost, session_id on result events), `internal` flag, and a `to_json()` method.

**CLI flag control in hand-written handlers:** `run_prompt()` accepts an `opts` parameter for arbitrary CLI flags (e.g. `run_prompt(prompt, logger, model=model, opts=["--max-turns", "1"])`). Note that `run_prompt()` hardcodes `yolo=True` and does not expose it — it is a convenience wrapper for the common case. For full control (including `yolo=False`), construct `ClaudeCodeAgent` directly:

```python
from antkeeper.llm.claude_code import ClaudeCodeAgent

agent = ClaudeCodeAgent(model=state.get("model"), yolo=False, opts=["--allowedTools", "Bash"])
for event in agent.prompt("Do something carefully"):
    runner.channel.report(runner.id, event)
```

---

## All commands run via uv

**Rule:** All antkeeper CLI commands must be run via `uv run`. Never install antkeeper globally or run it outside of `uv`.

**Why:** `uv run` ensures the correct virtual environment and dependency versions are used. Global installs can lead to version drift.

**Pattern:**
```bash
# Good
uv run antkeeper run healthcheck
uv run antkeeper run --model sonnet sdlc prompts/my-feature.md
uv run antkeeper server --port 8000
uv run antkeeper resume a1b2c3d4
uv run antkeeper init my-project

# Bad
antkeeper run healthcheck
python -m antkeeper run healthcheck
```

---

## Environment Model

| Environment | Antkeeper behaviour | Notes |
|-------------|-------------------|-------|
| Local dev | CLI channel, file-based logs and state | Default. Run via `uv run antkeeper run` |
| API server | API channel, background task execution | `uv run antkeeper server`. Workflows triggered via POST `/webhook` |
| Slack | Slack channel, thread-based replies | Requires `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` in `.env` |
| CI / headless | Same as local dev | No special config needed. Ensure `claude` CLI is available |

---

## Testing Patterns

Handlers are pure reducers, so they're straightforward to test:

```python
def test_my_handler(app, runner_factory):
    @app.handler
    def my_step(runner, state):
        return {**state, "done": True}

    runner, _ = runner_factory(app, "my_step", {"input": "value"})
    result = runner.run()
    assert result["done"] is True
```

For LLM-backed handlers, mock the agent to avoid real LLM calls:

```python
from antkeeper.core.domain import StreamEvent

def test_with_fake_agent(app, runner_factory):
    @app.handler
    def ask(runner, state):
        class FakeAgent:
            def prompt(self, prompt):
                yield StreamEvent(type="result", content="canned")
        events = list(FakeAgent().prompt(state["prompt"]))
        return {**state, "result": events[0].content}

    runner, _ = runner_factory(app, "ask", {"prompt": "hi"})
    result = runner.run()
    assert result["result"] == "canned"
```

---

## Retry with validation using ralph

**Rule:** When a handler needs to retry until a validation check passes, wrap it with `ralph()` rather than hand-rolling a retry loop.

**Why:** `ralph` handles the retry counter, augments the prompt with prior-attempt history and feedback, writes a per-run log file, and calls `runner.fail()` on exhaustion. Hand-rolling this is ~50 lines of boilerplate and is easy to get wrong.

**Pattern:**
```python
from antkeeper.handlers.ralph import ralph, ValidationResult

implement = cc_handler("/implement $spec_file")

def tests_pass(state: State) -> ValidationResult:
    import subprocess
    result = subprocess.run(["uv", "run", "pytest", "--tb=no", "-q"], capture_output=True, text=True)
    if result.returncode == 0:
        return ValidationResult(success=True, feedback="")
    return ValidationResult(success=False, feedback=result.stdout[-500:])

implement_with_retry = ralph(implement, validator=tests_pass, max_retries=3)
```

Or use a bash script as the validator:
```python
implement_with_retry = ralph(implement, validator="scripts/validate.sh")
```

The bash script receives state as JSON on stdin and must write `{"success": bool, "feedback": "..."}` to stdout; non-zero exit propagates as an exception.

**Full signature:**
```python
ralph(
    handler: Handler,           # The handler to wrap
    *,
    validator: Callable | str,  # Callable (State) -> ValidationResult, or path to bash script
    max_retries: int = 3,       # Retries after first attempt (4 total by default)
    prompt_key: str = "prompt", # State key to augment with prior-attempt context
    label: str | None = None,   # Name for the wrapper; defaults to handler.__name__
) -> Handler
```

**Behaviour:**
- Attempt 1: calls handler with current state unchanged
- Attempts 2+: augments `state[prompt_key]` with the full prior-attempts log before calling the handler
- On each failure: appends attempt number, state diff, and validator feedback to a log at `<log_dir>/ralph-<label>-<run_id>.log`
- On success: restores original `state[prompt_key]` in the returned state
- On exhaustion: calls `runner.fail()` raising `WorkflowFailedError`

**When NOT to use ralph:** When the retry condition is not a simple pass/fail on the output state. Ralph is for "run, validate, retry with feedback" loops. Complex conditional branching needs a hand-written handler.
