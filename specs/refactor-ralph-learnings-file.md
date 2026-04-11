# refactor: ralph learnings file replaces prompt augmentation

- Replace ralph's prompt augmentation mechanism with a `learnings_file` parameter that appends validation feedback to a shared markdown file on disk.
- Remove `prompt_key` parameter and all prompt save/restore/augment logic from ralph.
- Multiple nested ralph loops append to the same file under labelled headings, giving the LLM unified failure context.

## Solution Design

### Architectural Schema Changes

```yaml
types:
  ralph:
    kind: function
    parameters:
      - handler: Handler
      - validator: _Validator | str  # unchanged
      - max_retries: int  # default 3, unchanged
      - label: str | None  # unchanged
      - learnings_file: str | None  # NEW — path template with $var interpolation
      # prompt_key: REMOVED
```

## Relevant Files

- `src/antkeeper/handlers/ralph.py` — main implementation. Remove `prompt_key`, add `learnings_file`, delete prompt augmentation block (lines 158, 165-176, 191).
- `tests/handlers/test_ralph.py` — delete 3 tests for removed behaviour, add new tests for `learnings_file`.

## Workflow

### Step 1: Modify ralph signature and remove prompt augmentation

- In `ralph()` (ralph.py:102-108):
  - Remove `prompt_key: str = "prompt"` parameter
  - Add `learnings_file: str | None = None` parameter
  - Update docstring to describe new behaviour

- Delete prompt save (line 158): `original_prompt: object = state.get(prompt_key)`

- Delete prompt augmentation block (lines 165-176): the entire `if attempt > 0:` block that reads the log and builds `augmented_prompt`

- Change success return (line 191): replace `return {**result_state, prompt_key: original_prompt}` with `return result_state`

- Update `_wrapper` docstring to remove references to prompt augmentation and restoration

### Step 2: Add learnings file append on validation failure

- Add `import re` at the top of ralph.py (already has `import os`)

- Inside the `else` branch (validation failed, line 192-195), after `_append_log(...)`, when `learnings_file is not None`:
  - Resolve path: `resolved_path = re.sub(r'\$([a-zA-Z_]\w*)', lambda m: str(result_state[m.group(1)]), learnings_file)`
  - Create directory: `dirname = os.path.dirname(resolved_path)` then `if dirname: os.makedirs(dirname, exist_ok=True)`
  - Build entry: `f"## {resolved_label} \u2014 Attempt {attempt + 1}/{total_attempts}\n\n{validation.feedback}\n\n---\n"`
  - Append: `_append_log(resolved_path, entry)`

- Use `resolved_label` (line 129) for the heading, not raw `label`. This ensures a meaningful fallback to `handler.__name__` when `label` is `None`.

### Step 3: Delete removed-behaviour tests

- Delete `test_original_prompt_restored` (test_ralph.py:70-78)
- Delete `test_custom_prompt_key` (test_ralph.py:81-89)
- Delete `test_retry_prompt_augmented` (test_ralph.py:219-237)

### Step 4: Add learnings file tests

Add these tests to `tests/handlers/test_ralph.py`:

- `test_learnings_file_written_on_failure` — validator fails once then passes, `learnings_file="$dir/learnings.md"`, state has `{"dir": str(tmp_path)}`, label `"test-learn"`. Assert file exists, contains `## test-learn`, contains `Attempt 1/`, contains the feedback string, contains `---`.

- `test_learnings_file_not_written_on_success` — validator passes first time, `learnings_file="$dir/learnings.md"`. Assert the file does not exist.

- `test_learnings_file_appends_multiple_failures` — validator fails twice then passes, `max_retries=2`. Assert file contains two labelled headings with `Attempt 1/` and `Attempt 2/`.

- `test_learnings_file_variable_interpolation` — use `learnings_file="$base/work/$slug/learnings.md"` with state `{"base": str(tmp_path), "slug": "my-run"}`. Assert file at `tmp_path / "work" / "my-run" / "learnings.md"` exists.

- `test_learnings_file_none_default` — omit `learnings_file`, validator fails then passes. Assert no `.md` file created in `tmp_path`. Confirms backward compatibility.

- `test_learnings_file_written_on_exhaustion` — validator always fails, `max_retries=1`. Expect `WorkflowFailedError`. Assert learnings file contains entries for both attempts.

- `test_success_returns_result_state_directly` — handler adds `"result": "ok"` to state, validator passes. Assert returned state contains `"result": "ok"` and the prompt key is whatever the handler returned (no restoration).

### Step 5: Run validation commands

- Run all checks to verify zero errors and zero regressions.

## Testing Strategy

### Unit Tests

- Delete 3 tests covering removed prompt augmentation/restoration behaviour
- Add 7 new tests covering: learnings file creation on failure, no creation on success, multiple appends, path interpolation, default None behaviour, exhaustion writes, and direct result_state return

### Edge Cases

- `learnings_file` with no directory component (just a filename) — `os.path.dirname` returns `""`, guarded by `if dirname`
- Missing state key in `$var` interpolation — raises `KeyError`, propagates per design philosophy (same behaviour as `cc_handler`)
- `label=None` — uses `resolved_label` which falls back to `handler.__name__`
- Exhaustion — learnings entries appended for all failed attempts before `WorkflowFailedError` raised

## Acceptance Criteria

- All existing tests pass unchanged (minus the 3 deleted tests)
- `prompt_key` parameter removed — passing it raises `TypeError`
- `learnings_file=None` (default) produces no learnings file
- `learnings_file` with `$var` interpolation resolves correctly from state
- Validation failure appends labelled markdown to the resolved learnings file path
- Intermediate directories created automatically
- Multiple failures append multiple entries
- Progress `.log` file unchanged
- `resolved_label` used in headings (falls back to `handler.__name__`)

### Validation Commands

```bash
just check
```

```bash
just test
```

```bash
uv run ty check
```

Bespoke: verify the 3 deleted tests no longer exist:
```bash
grep -c "test_original_prompt_restored\|test_custom_prompt_key\|test_retry_prompt_augmented" tests/handlers/test_ralph.py && echo "FAIL: deleted tests still present" || echo "OK: deleted tests removed"
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The `_append_log` helper (ralph.py:203) is reused for writing to the learnings file — no new I/O helper needed.
- The interpolation pattern (`re.sub(r'\$([a-zA-Z_]\w*)', ...)`) matches `cc_handler` exactly. Do not add error handling for missing keys — let `KeyError` propagate per design philosophy.
- The learnings file format is plain markdown. No schema, no structured format.
- `cc_handler` changes are out of scope — prompt templates referencing the learnings file are the caller's responsibility.

## Report

Files changed: `src/antkeeper/handlers/ralph.py`, `tests/handlers/test_ralph.py`. Tests deleted: 3 (prompt augmentation/restoration). Tests added: 7 (learnings file behaviour). Validation: `just check`, `just test`, `uv run ty check`, grep for deleted tests.
