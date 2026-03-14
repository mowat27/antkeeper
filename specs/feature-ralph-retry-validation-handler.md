# feature: Ralph retry-with-validation handler wrapper

- Wrap any handler with validate-retry loop; validator checks output after each attempt, retries with feedback on failure
- Progress log accumulates handler output diffs and validator feedback; injected into prompt on retries (mirrors `json_prompt` pattern)
- Supports Python callable and bash script validators; exhausts retries via `runner.fail()`

## Solution Design

### External Interface Change

Channels gain access to a handler wrapper that adds retry-with-validation to any existing handler:

```python
from antkeeper.handlers.ralph import ralph, ValidationResult

# Python validator
def check_output(state):
    if "result" in state:
        return ValidationResult(success=True, feedback="")
    return ValidationResult(success=False, feedback="Missing 'result' key")

validated = ralph(my_handler, validator=check_output, max_retries=3)

# Bash validator (exit 0 = pass, non-zero = fail, stdout = feedback)
validated = ralph(my_handler, validator="./scripts/check.sh")
```

The returned handler conforms to the `Handler` protocol (`(Runner, State) -> State` with `__name__`).

### Architectural Schema Changes

```yaml
types:
    ValidationResult:
        kind: frozen dataclass
        fields:
            - success: bool
            - feedback: str

functions:
    ralph:
        params:
            - handler: Callable[[Runner, State], State]
            - validator: Callable[[State], ValidationResult] | str  # Python callable or bash script path
            - max_retries: int  # default 3 (up to 4 total attempts)
            - prompt_key: str  # default "prompt"
            - label: str | None  # default handler.__name__
        returns: Handler  # conforms to Handler protocol
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/factories.py` — Handler Protocol definition (lines 22-27); `cc_handler` factory pattern to follow for `__name__` setting
- `src/antkeeper/core/runner.py` — `Runner.fail()` (NoReturn, raises `WorkflowFailedError`), `Runner.report_progress()`, `Runner.id` (8-char hex), `app.log_dir` resolution pattern (line 74)
- `src/antkeeper/core/domain.py` — `State` type alias (`dict[str, Any]`); immutability convention (always construct new dict with updates)
- `src/antkeeper/helpers/json.py` — `json_prompt` pattern for prompt augmentation (appends to prompt string)
- `src/antkeeper/handlers/__init__.py` — current exports (docstring only, no imports); needs `ralph` and `ValidationResult` added
- `tests/conftest.py` — `runner_factory` fixture, `TestChannel` (captures `progress_messages`), `app` fixture with temp dirs
- `tests/handlers/test_factories.py` — handler test patterns to follow

### New Files

- `src/antkeeper/handlers/ralph.py` — `ValidationResult`, `ralph()` factory, `_run_bash_validator()`, `_augment_prompt()`
- `tests/handlers/test_ralph.py` — test suite

## Workflow

### Step 1: Create `src/antkeeper/handlers/ralph.py`

- Define `ValidationResult` as a `@dataclass(frozen=True)` with `success: bool` and `feedback: str`
- Define `_run_bash_validator(script_path: str, state: State) -> ValidationResult`:
  - Write state as JSON to a `tempfile.NamedTemporaryFile` (use as context manager for cleanup)
  - Run `subprocess.run([script_path, temp_file_path], capture_output=True, text=True)`
  - Return `ValidationResult(success=(result.returncode == 0), feedback=result.stdout.strip())`
- Define `_augment_prompt(original_prompt: str, log_contents: str, attempt: int) -> str`:
  - Prepend log contents and attempt header to original prompt using the format specified below
  - Pure function: takes strings in, returns string out
- Define `ralph(handler, *, validator, max_retries=3, prompt_key="prompt", label=None)`:
  - Derive `label` from `handler.__name__` if None
  - Return a `wrapper(runner, state)` function with `wrapper.__name__ = label`

**Wrapper logic:**

1. Resolve `log_dir` inside wrapper: `runner.app.log_dir(runner) if callable(runner.app.log_dir) else runner.app.log_dir`
2. Create `log_dir` with `os.makedirs(log_dir, exist_ok=True)`
3. Construct log path: `{log_dir}/ralph-{label}-{runner.id}.log`
4. Save `original_prompt = state[prompt_key]`
5. Loop `for attempt in range(1, max_retries + 2)` (1-indexed, up to `max_retries + 1` total attempts):
   a. `runner.report_progress(f"ralph({label}): attempt {attempt}/{max_retries + 1}")`
   b. If `attempt > 1`: read progress log contents, create new state via `state = {**state, prompt_key: _augment_prompt(original_prompt, log_contents, attempt)}`
   c. `result_state = handler(runner, state)` — exceptions propagate, no try/except
   d. Compute state diff: keys in `result_state` where value differs from `state` or key is new. Serialize diff as JSON. Append to progress log file with `=== Attempt {attempt}: Handler Output ===` header
   e. Run validator: if `str`, call `_run_bash_validator(validator, result_state)`; if callable, call `validator(result_state)` — exceptions propagate
   f. If `validation_result.success`: return `{**result_state, prompt_key: original_prompt}` (restore original prompt)
   g. If failure: append `validation_result.feedback` to progress log with `=== Attempt {attempt}: Validation Failed ===` header
6. After loop: `runner.fail(f"ralph({label}): validation failed after {max_retries + 1} attempts")`

**Critical: State immutability** — never mutate `state` in-place. Always construct new dicts via `{**state, key: val}`.

**Prompt augmentation format** (on retries):
```
PREVIOUS ATTEMPTS:
The following log shows previous attempts and why they failed.
Use this context to avoid repeating the same mistakes.

<progress log contents>

---

CURRENT TASK (attempt N):
<original prompt>
```

### Step 2: Update `src/antkeeper/handlers/__init__.py`

- Add imports: `from antkeeper.handlers.ralph import ralph, ValidationResult`
- Update module docstring to list `ralph` module alongside `claude_code`

### Step 3: Create `tests/handlers/test_ralph.py`

Write tests using `runner_factory` fixture and inline handler/validator definitions. See Testing Strategy below.

### Step 4: Run Validation Commands

Run all checks and fix any issues before considering the feature complete.

## Testing Strategy

### Unit Tests

1. **`test_passes_on_first_attempt`** — validator returns success; handler called once; correct state returned
2. **`test_retries_on_validation_failure`** — validator fails twice then passes (use `side_effect`); handler called 3 times; final state returned
3. **`test_max_retries_exhausted_raises_workflow_failed_error`** — validator always fails; `pytest.raises(WorkflowFailedError)`; handler called `max_retries + 1` times
4. **`test_prompt_augmented_on_retry`** — capture state arg on each handler call; first call has original prompt; second call has progress log prepended
5. **`test_original_prompt_restored_on_success`** — after retry success, returned `state[prompt_key]` equals original prompt exactly
6. **`test_progress_log_file_written`** — verify file exists at expected path; contains handler output diff and validator feedback text
7. **`test_bash_validator_exit_zero_is_success`** — patch `subprocess.run` returning `returncode=0`; handler called once; no retry
8. **`test_bash_validator_exit_nonzero_is_failure`** — patch `subprocess.run` returning `returncode=1` then `returncode=0`; handler called twice; feedback from stdout in progress log
9. **`test_custom_prompt_key`** — use `prompt_key="instructions"`; verify augmentation targets correct key; original restored on success
10. **`test_handler_exception_propagates`** — handler raises `ValueError`; `pytest.raises(ValueError)`; handler called once; validator never called
11. **`test_progress_messages_reported`** — check `channel.progress_messages` contains attempt messages matching expected count

### Edge Cases

- **`test_max_retries_zero`** — `max_retries=0` means single attempt; validator fails → `WorkflowFailedError`
- **`test_validator_exception_propagates`** — validator raises `RuntimeError`; propagates without retry
- **`test_returned_handler_has_correct_name`** — `wrapper.__name__` equals provided label
- **`test_label_defaults_to_handler_name`** — when no label provided, uses `handler.__name__`

## Acceptance Criteria

- `ralph()` returns a handler conforming to the `Handler` protocol
- First attempt runs handler with unmodified state
- On validation failure, progress log updated and prompt augmented for retry
- On validation success, original prompt restored in returned state
- Max retries exhaustion calls `runner.fail()` raising `WorkflowFailedError`
- Bash validators work via subprocess (exit code + stdout)
- Handler and validator exceptions propagate without retry
- Progress messages reported via `runner.report_progress()`
- State is never mutated in-place; new dicts constructed for all modifications

### Validation Commands

```bash
uv run pytest tests/handlers/test_ralph.py -v
uv run pytest tests/ -v
uv run ruff check src/antkeeper/handlers/ralph.py tests/handlers/test_ralph.py
uv run ty check
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- `max_retries=3` means up to 4 total attempts (1 initial + 3 retries), matching the user's API comment
- State diff logging captures keys where values changed or are new (compares values, not just key presence) — serialized as JSON in progress log
- `log_dir` MUST be resolved inside the wrapper function (where `runner` is in scope), not in the `ralph()` factory — `runner` doesn't exist at factory call time
- `runner.fail()` is `NoReturn` — it raises `WorkflowFailedError`. The call must be placed AFTER the loop, not inside the failure branch
- Follow the immutable state convention from `domain.py` — always `{**state, key: val}`, never `state[key] = val`
- Temp file for bash validator must use a context manager (`tempfile.NamedTemporaryFile`) for guaranteed cleanup

## Report

Report: files changed, tests added, validations passed. Include count of handler attempts tested and confirmation that both Python and bash validator paths are covered.
