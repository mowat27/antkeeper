# feature: Retry-with-validation handler wrapper (ralph)

- Factory function `ralph()` wraps any handler with a retry-validation loop, accumulating feedback in a progress log between attempts.
- Validators are Python callables or bash scripts; on exhaustion the workflow fails via `runner.fail()`.
- Includes a deterministic `test_ralph` workflow exercising the full retry loop with no LLM dependency.

## Solution Design

### Architectural Schema Changes

```yaml
types:
  ValidationResult:
    kind: frozen dataclass
    module: antkeeper.handlers.ralph
    fields:
      - success: bool
      - feedback: str

functions:
  ralph:
    module: antkeeper.handlers.ralph
    signature: |
      ralph(
          handler: Callable[[Runner, State], State],
          *,
          validator: Callable[[State], ValidationResult] | str,
          max_retries: int = 3,
          prompt_key: str = "prompt",
          label: str | None = None,
      ) -> Callable[[Runner, State], State]
    returns: A handler callable with __name__ set to label (or handler.__name__)
```

### External Interface Change

Ralph is a handler wrapper — channels are unaffected. Any handler registered via `@app.handler` or built with `cc_handler()` can be wrapped:

```python
from antkeeper.handlers.ralph import ralph, ValidationResult

def my_validator(state):
    if "result" not in state:
        return ValidationResult(success=False, feedback="Missing result key")
    return ValidationResult(success=True, feedback="")

wrapped = ralph(my_handler, validator=my_validator, max_retries=3)
```

Bash script validators receive state as JSON on stdin and must write JSON `{"success": bool, "feedback": "..."}` to stdout. Exit 0 with valid JSON is required; non-zero exit or invalid JSON raises an exception that propagates immediately.

```python
wrapped = ralph(my_handler, validator="/path/to/validate.sh")
```

## Relevant Files

- `src/antkeeper/core/domain.py` — defines `State`, `WorkflowFailedError`, `StreamEvent` used by ralph
- `src/antkeeper/core/runner.py` — defines `Runner` (ralph uses `runner.report_progress()`, `runner.fail()`, `runner.id`, `runner.app.log_dir`, `runner.logger`)
- `src/antkeeper/core/app.py` — defines `App` and `app.handler` decorator; ralph-wrapped handlers are registered here
- `src/antkeeper/handlers/__init__.py` — package init; needs re-export of `ralph` and `ValidationResult`
- `handlers.py` — application handlers file; `test_ralph` workflow added here
- `tests/handlers/test_factories.py` — reference for existing handler test patterns and fixtures
- `tests/conftest.py` — test fixtures (`app`, `runner_factory`, etc.)

### New Files

- `src/antkeeper/handlers/ralph.py` — the `ralph()` factory, `ValidationResult` dataclass, bash validator wrapper, and retry loop logic
- `tests/handlers/test_ralph.py` — unit tests for ralph

## Workflow

### Step 1: Create `src/antkeeper/handlers/ralph.py`

- Define `ValidationResult` as a frozen dataclass with `success: bool` and `feedback: str`
- Implement the bash validator wrapper as a private function `_bash_validator(script_path: str) -> Callable[[State], ValidationResult]`:
  - Serializes state to JSON, passes as stdin to `subprocess.run([script_path], ...)`
  - Parses stdout as JSON, returns `ValidationResult`
  - Non-zero exit or invalid JSON raises an exception (propagates per invariant)
  - Conversion happens once at factory time inside `ralph()`
- Implement `ralph()` factory function:
  - When `validator` is a `str`, wrap it with `_bash_validator()` at factory time
  - When `label` is `None`, derive from `handler.__name__`
  - Return a wrapper function with `__name__` set to the resolved label
- Wrapper loop logic inside the returned handler:
  1. Resolve log dir: `runner.app.log_dir(runner) if callable(runner.app.log_dir) else runner.app.log_dir`
  2. Create progress log file at `{log_dir}/ralph-{label}-{runner.id}.log` (use `os.makedirs(log_dir, exist_ok=True)`)
  3. Save original prompt: `state.get(prompt_key)`
  4. Loop `max_retries + 1` total attempts:
     - `runner.report_progress(f"ralph {label}: attempt {attempt + 1}/{max_retries + 1}")`
     - On retries (attempt > 0): read progress log content, build augmented prompt by prepending prior attempts context to the original prompt, update state with augmented prompt
     - Call `handler(runner, current_state)` — exceptions propagate immediately
     - Compute state diff (keys added/changed/removed vs state before handler call), append diff to progress log
     - Call `validator(result_state)` — exceptions propagate immediately
     - On `success=True`: return `{**result_state, prompt_key: original_prompt}` (restore original prompt)
     - On `success=False`: append feedback to progress log, set `current_state = result_state` for next iteration
  5. After loop exhausted: `runner.fail(f"ralph {label}: validation failed after {max_retries + 1} attempts")`

- Prompt augmentation format on retries:
  ```
  Previous attempts have not passed validation. Here is the history:

  <prior_attempts>
  {progress_log_content}
  </prior_attempts>

  Please address the feedback and try again.

  {original_prompt}
  ```

- Progress log format: plain text, append-only. Each entry separated by a delimiter line (`---`). Entries contain: attempt number, state diff (keys added/changed/removed as human-readable text), validation result (success/failure + feedback).

### Step 2: Update `src/antkeeper/handlers/__init__.py`

- Add re-exports: `from antkeeper.handlers.ralph import ralph, ValidationResult`

### Step 3: Add `test_ralph` workflow to `handlers.py`

- Import `ralph` and `ValidationResult` from `antkeeper.handlers.ralph`
- Define a deterministic inner handler (no LLM) that increments `attempt_count` in state on each call:
  ```python
  def _increment(runner, state):
      count = state.get("attempt_count", 0) + 1
      return {**state, "attempt_count": count}
  ```
- Define a deterministic validator that rejects until `attempt_count >= 4`:
  ```python
  def _needs_four(state):
      count = state.get("attempt_count", 0)
      if count >= 4:
          return ValidationResult(success=True, feedback="")
      return ValidationResult(success=False, feedback=f"attempt_count is {count}, need 4")
  ```
- Wrap with `ralph(_increment, validator=_needs_four, max_retries=3, label="test-ralph")`
- Register as `@app.handler` named `test_ralph` that calls the wrapped handler and returns the result
- Runnable with `antkeeper run test_ralph`

### Step 4: Create `tests/handlers/test_ralph.py`

- See Testing Strategy below

### Step 5: Run validation commands

## Testing Strategy

### Unit Tests

Test file: `tests/handlers/test_ralph.py`

All tests use `runner_factory` fixture with a custom `App`. Inner handlers and validators are simple callables defined in the test module.

**Happy path tests:**
- `test_pass_on_first_attempt` — validator passes immediately; handler called once; result returned with original prompt restored
- `test_pass_after_retries` — validator fails twice, passes on third attempt; handler called 3 times; original prompt restored in result
- `test_original_prompt_restored` — handler modifies prompt_key; validator passes; returned state has original prompt value
- `test_custom_prompt_key` — use `prompt_key="instruction"`; verify save/restore works on custom key

**Retry exhaustion tests:**
- `test_exhaustion_raises_workflow_failed` — validator always fails, `max_retries=2`; handler called 3 times; `WorkflowFailedError` raised
- `test_max_retries_zero_single_attempt` — `max_retries=0`, validator fails; handler called once; `WorkflowFailedError` raised
- `test_default_max_retries_is_three` — default `max_retries`, validator always fails; handler called 4 times; `WorkflowFailedError` raised

**Exception propagation tests:**
- `test_handler_exception_propagates` — inner handler raises `ValueError`; propagates immediately; no retry
- `test_validator_exception_propagates` — validator raises `RuntimeError`; propagates immediately; no retry

**Progress log tests:**
- `test_progress_log_created` — after execution, file exists at expected path
- `test_progress_log_contains_feedback` — validator fails with specific feedback, then passes; feedback string appears in log
- `test_retry_prompt_augmented` — capture prompt seen by handler on retry; verify it contains prior attempts context, not the bare original prompt

**Label tests:**
- `test_label_defaults_to_handler_name` — no explicit label; log filename uses `handler.__name__`
- `test_explicit_label` — explicit label; log filename uses it

**Bash validator tests:**
- `test_bash_validator_success` — temp script that outputs `{"success": true, "feedback": ""}`; validator passes
- `test_bash_validator_failure` — temp script outputs `{"success": false, "feedback": "bad"}`; validator fails
- `test_bash_validator_error_propagates` — temp script exits non-zero; exception propagates

Use `tmp_path` fixture to create real temp bash scripts for bash validator tests.

### Integration

No integration tests needed — ralph is a pure handler wrapper with no external dependencies.

### Edge Cases

- `max_retries=0` means exactly 1 attempt (no retries)
- `max_retries=3` means 4 total attempts (1 initial + 3 retries)
- Handler exceptions on first attempt propagate without any retry
- Validator exceptions on first attempt propagate without any retry
- State dict passed to handler is never mutated in place
- Prompt key absent from state — handler runs without prompt augmentation on retries

## Acceptance Criteria

- `ralph()` returns a handler callable with `__name__` attribute
- Wrapped handler retries up to `max_retries` times on validation failure
- Original prompt restored in returned state on success
- `WorkflowFailedError` raised via `runner.fail()` when retries exhausted
- Handler and validator exceptions propagate immediately without retry
- Progress log file created at `{log_dir}/ralph-{label}-{runner.id}.log`
- Progress log accumulates state diffs and validation feedback across attempts
- Prompt augmented with prior attempts context on retries
- Bash script validators work via stdin/stdout JSON contract
- `test_ralph` workflow runnable with `antkeeper run test_ralph` and passes on 4th attempt
- All existing tests continue to pass

### Validation Commands

```bash
uv run just check
```

This runs `ruff check` (linter), `ty check` (typechecker), and `pytest` (all tests).

Additionally, verify the test workflow runs:

```bash
uv run antkeeper run test_ralph
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- Ralph has zero LLM dependencies — it wraps any handler, whether LLM-backed or pure Python.
- The `Handler` protocol in `factories.py` is not imported by ralph. Ralph uses structural typing — any callable matching `(Runner, State) -> State` with a `__name__` attribute works. This avoids a cross-sibling dependency.
- The progress log is a separate file from runner's log — it is read back by the augmentation step on retries, which is why it cannot be the runner logger.
- State diff in the progress log should be concise: keys added, keys changed, keys removed. Do not log full values for large content — truncate if needed.

## Report

Report the following on completion:
- Files created (ralph.py, test_ralph.py)
- Files modified (handlers.py, handlers/__init__.py)
- Number of tests added and their pass/fail status
- Output of `uv run just check` (all green)
- Output of `uv run antkeeper run test_ralph` (passes on 4th attempt)
