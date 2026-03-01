# feat: Roll utility functions and built-in handlers into framework

- Extract `run_prompt`, `json_prompt`, `latest_commit` from external handlers into framework modules.
- Create `antkeeper.handlers.claude_code` package with pre-registered SDLC handlers.
- Add `handlers` constructor arg and `add_handler` method to `App`.

## Solution Design

### API / Interface Changes

**`run_prompt` function** (`antkeeper.llm.claude_code`):
```python
def run_prompt(prompt: str, logger: Logger, model: str | None = None) -> str:
```
Convenience wrapper: creates `ClaudeCodeAgent(model=model, yolo=True)`, calls `agent.prompt(prompt)`, returns response. Logs only caller-level context at DEBUG (the agent already logs prompt/response at INFO).

**`json_prompt` function** (`antkeeper.helpers.json`):
```python
def json_prompt(prompt: str, *, required_fields: list[str]) -> str:
```
Appends JSON output instructions and an example JSON object to the prompt string. Uses the existing `_json` private alias for `json.dumps`.

**`latest_commit` function** (`antkeeper.git.core`):
```python
def latest_commit() -> dict:
```
Returns `{"sha": str, "message": str}` for the most recent commit. Uses a unit-separator delimiter format (`%H\x1f%s`) and constructs the dict manually — does NOT embed raw commit data into a JSON format string (commit messages containing quotes would break `json.loads`).

**`App(handlers=...)` constructor arg**:
```python
def __init__(self, log_dir="agents/logs/", worktree_dir="trees/",
             state_dir=".antkeeper/state/", handlers: dict[str, Callable] | None = None):
```
If `handlers` is provided, merges into `self.handlers` via `self.handlers.update(handlers)`.

**`App.add_handler` method**:
```python
def add_handler(self, fn: Callable) -> None:
```
Programmatic equivalent of `@app.handler`. Uses `fn.__name__` as the key, matching the decorator's existing behaviour. No explicit name parameter — keeps the single registration path consistent.

**`antkeeper.handlers.claude_code` package**:
Module-level `app = App()` with 11 handlers registered: `healthcheck`, `derive_feature`, `specify`, `commit`, `branch_if_on_main`, `implement`, `push`, `raise_a_pr`, `specify_implement`, `sdlc`, `sdlc_iso`. The `document` handler is excluded. The `sdlc` and `sdlc_iso` composite workflows drop the `document` step (and its surrounding `commit` step where applicable).

Consumer usage:
```python
from antkeeper.handlers.claude_code import app as claude_code_app
app = App(handlers=claude_code_app.handlers)
```

## Relevant Files

- `src/antkeeper/core/app.py` — Add `handlers` param to `__init__`, add `add_handler` method
- `src/antkeeper/llm/claude_code.py` — Add `run_prompt` function
- `src/antkeeper/helpers/json.py` — Add `json_prompt` function
- `src/antkeeper/helpers/__init__.py` — Add `json_prompt` to exports and `__all__`
- `src/antkeeper/git/core.py` — Add `latest_commit` function (plus `import json`)
- `src/antkeeper/git/__init__.py` — Add `latest_commit` to imports and `__all__`

### New Files

- `src/antkeeper/handlers/__init__.py` — Package init, minimal docstring
- `src/antkeeper/handlers/claude_code/__init__.py` — Module-level `app`, all 11 handlers
- `tests/core/test_app.py` — Tests for `App(handlers=...)` and `add_handler`
- `tests/helpers/test_json_prompt.py` — Tests for `json_prompt`
- `tests/llm/test_run_prompt.py` — Tests for `run_prompt`
- `tests/git/test_latest_commit.py` — Tests for `latest_commit`
- `tests/handlers/__init__.py` — Package init
- `tests/handlers/test_claude_code.py` — Tests for built-in handlers package

## Workflow

### Step 1: Add utility functions to framework modules

- Add `run_prompt` to `src/antkeeper/llm/claude_code.py` after the class definition. Import `Logger` from `logging`. The function creates `ClaudeCodeAgent(model=model, yolo=True)`, calls `agent.prompt(prompt)`, and returns the response. Log only a DEBUG message with the prompt length (the agent handles its own INFO-level logging).
- Add `json_prompt` to `src/antkeeper/helpers/json.py`. Use the existing `_json` alias for `_json.dumps`. The function takes a prompt and keyword-only `required_fields`, builds an example JSON object, and appends instructions to the prompt.
- Update `src/antkeeper/helpers/__init__.py`: add `json_prompt` to the import line and `__all__`.
- Add `latest_commit` to `src/antkeeper/git/core.py`. Add `import json` at the top. Use `execute(['log', '-1', '--pretty=format:%H\x1f%s'])` with unit separator, then `output.partition("\x1f")` to split, and return `{"sha": sha, "message": message}`.
- Update `src/antkeeper/git/__init__.py`: add `latest_commit` to the import from `core` and to `__all__`.

### Step 2: Add `handlers` param and `add_handler` to App

- Modify `App.__init__` in `src/antkeeper/core/app.py`: add `handlers: dict[str, Callable] | None = None` as the last parameter. After `self.handlers = {}`, add `if handlers: self.handlers.update(handlers)`.
- Add `add_handler(self, fn)` method to `App`. It should do `self.handlers[fn.__name__] = fn` — matching the decorator's existing key derivation.

### Step 3: Create handlers package

- Create `src/antkeeper/handlers/__init__.py` with a docstring only.
- Create `src/antkeeper/handlers/claude_code/__init__.py` with:
  - Imports: `datetime`, `App`, `run_workflow`, `Runner`, `State`, `run_prompt`, `json_prompt`, `extract_json`, `git`, `Worktree`, `git_worktree`, `latest_commit`
  - Module-level `app = App()`
  - All 11 handlers decorated with `@app.handler`, adapted from the external handlers file:
    - Replace `cc(...)` calls with `run_prompt(...)`
    - Replace inline `json_prompt(...)` usage with the framework version
    - Replace inline `latest_commit()` with the framework version
    - Fix the `derive_feature` handler to pass `required_fields=["feature_type", "slug"]` to `json_prompt` (this is a bug fix — the external handler omits this required keyword argument)
    - Remove `document` from `sdlc` and `sdlc_iso` step lists. In `sdlc`, the step list becomes: `[specify, branch_if_on_main, commit, implement, commit, push, raise_a_pr]`. In `sdlc_iso`, the step list becomes: `[specify, commit, implement, commit, push, raise_a_pr]`.

### Step 4: Write tests

- Create `tests/core/test_app.py`:
  - `test_app_constructor_with_handlers_dict` — pass `handlers={"greet": some_fn}`, assert `app.handlers["greet"] is some_fn`
  - `test_app_constructor_default_no_handlers` — `App()` has empty handlers dict
  - `test_add_handler_registers_function` — call `app.add_handler(fn)`, assert `app.handlers[fn.__name__] is fn`
  - `test_add_handler_overwrites_existing` — register same name twice, assert latest wins

- Create `tests/llm/test_run_prompt.py`:
  - `test_run_prompt_returns_response` — mock `ClaudeCodeAgent`, assert return value matches mock response
  - `test_run_prompt_passes_model_to_agent` — mock `ClaudeCodeAgent`, call with `model="opus"`, assert agent created with `model="opus"`
  - `test_run_prompt_uses_yolo_true` — mock `ClaudeCodeAgent`, assert `yolo=True`

- Create `tests/helpers/test_json_prompt.py`:
  - `test_json_prompt_includes_original_prompt` — assert original prompt text appears in result
  - `test_json_prompt_includes_required_fields` — assert all field names appear in result
  - `test_json_prompt_includes_example_json` — assert valid JSON example is embedded

- Create `tests/git/test_latest_commit.py`:
  - `test_latest_commit_returns_sha_and_message` — use `git_repo` fixture, assert dict has "sha" (40 hex chars) and "message" keys
  - `test_latest_commit_importable_from_git_package` — `from antkeeper.git import latest_commit`, assert callable

- Create `tests/handlers/__init__.py` (empty)
- Create `tests/handlers/test_claude_code.py`:
  - `test_package_exposes_app_instance` — import app, assert `isinstance(app, App)`
  - `test_app_has_expected_handlers` — assert `len(app.handlers) == 11` and all expected names present

### Step 5: Run validation commands

- Run all validation commands listed below. Fix any failures before completing.

## Testing Strategy

### Unit Tests

- **`run_prompt`**: Mock `ClaudeCodeAgent` class to verify it is instantiated with correct args (`model`, `yolo=True`), prompt is forwarded, and response is returned.
- **`json_prompt`**: Pure function tests — verify output contains original prompt, required field names, and a valid JSON example.
- **`latest_commit`**: Use `git_repo` fixture (real temp repo). Assert returned dict has correct keys and SHA format.
- **`App(handlers=...)`**: Verify constructor merges dict into `app.handlers`. Verify `add_handler` registers by `fn.__name__`.
- **Handlers package**: Verify module-level `app` is an `App` instance with exactly 11 handlers registered.

### Edge Cases

- `App(handlers=None)` (default) — no error, empty handlers dict
- `App(handlers={})` — no error, empty handlers dict
- `add_handler` with a function whose name collides with existing handler — last write wins
- `latest_commit` with commit message containing quotes or special characters — safe because delimiter-based parsing is used, not JSON format string
- `json_prompt` with single-element `required_fields` list — still works

## Acceptance Criteria

- `from antkeeper.llm.claude_code import run_prompt` works and function has correct signature
- `from antkeeper.helpers.json import json_prompt` works and function has correct signature
- `from antkeeper.helpers import json_prompt` works
- `from antkeeper.git.core import latest_commit` works and function has correct signature
- `from antkeeper.git import latest_commit` works
- `App(handlers={"x": fn})` merges handlers at construction
- `app.add_handler(fn)` registers fn under `fn.__name__`
- `from antkeeper.handlers.claude_code import app` returns an App with 11 handlers
- The 11 handlers are: healthcheck, derive_feature, specify, commit, branch_if_on_main, implement, push, raise_a_pr, specify_implement, sdlc, sdlc_iso
- `document` handler is NOT in the built-in handlers
- All tests pass, linter clean, type checker clean

### Validation Commands

```bash
uv run -m pytest tests/ -v
uv run ruff check src/ tests/
uv run ty check src/
just
```

IMPORTANT: If any checks fail you must investigate and fix the error. You must reach zero errors, zero warnings before moving on. This includes pre-existing issues.

## Notes

- The `derive_feature` handler in the external file calls `json_prompt` without `required_fields`. This is a bug — `required_fields` is a required keyword-only argument. The built-in handler must fix this by passing `required_fields=["feature_type", "slug"]`.
- The `sdlc` and `sdlc_iso` handlers drop the `document` step and its surrounding `commit` step. Consumers who need `document` can define it themselves and compose a custom workflow using `run_workflow`.
- The built-in `app` instance in `antkeeper.handlers.claude_code` uses default App config (log_dir, worktree_dir, state_dir). These are irrelevant — the instance serves only as a handler registry. The consumer's own App (which receives the handlers dict) is the one whose config is used at runtime.
- `run_prompt` hard-codes `yolo=True` matching the established usage pattern from the external handlers. This is a convenience function for automated SDLC workflows where permission skipping is expected.

## Report

**Files changed:** 6 existing files modified (`app.py`, `claude_code.py`, `helpers/json.py`, `helpers/__init__.py`, `git/core.py`, `git/__init__.py`). 8 new files created (2 source packages, 6 test files).

**Tests added:** 13 unit tests across 5 test files covering all new public APIs.

**Validations:** pytest, ruff, ty, and `just` (default target) must all pass clean.
