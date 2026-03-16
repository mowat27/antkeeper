# feature: cc_handler two-step run and extract

- Replace single-call delegation pattern with two-step process: run command then extract JSON separately
- Step 1 sends raw prompt to configured model; Step 2 sends extraction prompt to haiku
- Fixes unreliable delegation where agent conflates execution with structured output (observed in run `2fd95671`)

**BREAKING CHANGE**: `_delegation_prompt()` is removed entirely. Ignore backwards compatibility.

## Solution Design

### External Interface Change

No change to the public `cc_handler()` signature or its return type. Callers using `state_updates` will get the same behaviour — fields extracted from LLM output merged into state — but via two sequential `run_prompt` calls instead of one delegation-wrapped call.

**Fire-and-forget mode** (no `state_updates`): Completely unchanged — single `run_prompt` call.

**State-updates mode**: Two `run_prompt` calls:
1. Raw interpolated prompt sent to the handler's configured model (same as fire-and-forget)
2. Extraction prompt with response text sent to haiku, parsed by `extract_json`

### Architectural Schema Changes

```yaml
types:
  # No type changes — Handler protocol and cc_handler signature unchanged

private_functions:
  _delegation_prompt:
    status: REMOVED

  _extraction_prompt:
    status: NEW
    signature: "(response: str, *, required_fields: list[str]) -> str"
    purpose: "Build prompt for haiku to extract JSON fields from response text"

constants:
  _EXTRACTION_MODEL:
    status: NEW
    value: "haiku"
    purpose: "Model used for the extraction step — implementation detail, not caller-facing"
```

## Relevant Files

- `src/antkeeper/handlers/claude_code/factories.py` — main file to change; contains `_delegation_prompt`, `cc_handler`, and the handler body
- `tests/handlers/test_factories.py` — existing tests that mock `run_prompt` and `extract_json`; several need updating for two-call pattern

## Workflow

### Step 1: Replace `_delegation_prompt` with `_extraction_prompt` in factories.py

- Delete `_delegation_prompt()` (lines 28-49)
- Add module-level constant `_EXTRACTION_MODEL = "haiku"`
- Add `_extraction_prompt(response: str, *, required_fields: list[str]) -> str` that builds a short prompt:
  - Lists required field names via `json.dumps(required_fields)`
  - Wraps the response text in `<response>...</response>` XML tags to prevent the LLM response content from being misread as prompt structure
  - Asks for ONLY a JSON object, no markdown fences, no explanation
  - Instructs to use `null` for missing fields

### Step 2: Split handler body into two `run_prompt` calls

- Modify the `handler()` inner function:
  - Remove the `if state_updates: prompt = _delegation_prompt(...)` wrapping
  - Step 1: call `run_prompt(prompt, runner.logger, model=effective_model)` with the raw interpolated prompt
  - Step 2 (only when `state_updates` is truthy): call `run_prompt(_extraction_prompt(response, required_fields=state_updates), runner.logger, model=_EXTRACTION_MODEL)`
  - Pass haiku's output to `extract_json` and extract the requested fields
- The existing `except (KeyError, AgentExecutionError, ValueError)` block handles errors from both steps — no change needed

### Step 3: Update module docstring

- Replace "delegation" bullet with "extraction" describing the two-step process
- Remove references to `_delegation_prompt`

### Step 4: Update tests

- Update all `state_updates` mode tests to use `side_effect=[step1_response, step2_response]` instead of single `return_value` on the `run_prompt` mock
- Rewrite `test_state_updates_uses_delegation_prompt` to assert:
  - First `run_prompt` call receives raw interpolated prompt (no wrapping) with configured model
  - Second `run_prompt` call uses `"haiku"` model with prompt containing required field names
- Add new test: verify extraction call always uses `_EXTRACTION_MODEL` regardless of handler model
- Add new test: verify step 1 failure (AgentExecutionError) routes through `runner.fail()` without calling step 2
- Fire-and-forget tests (no `state_updates`) remain unchanged — single `run_prompt` call

### Step 5: Validate

- Run all validation commands below

## Testing Strategy

### Unit Tests

- **`_extraction_prompt` output**: Assert it contains all required field names, wraps response in `<response>` tags, and includes JSON-only instructions
- **Two-call sequence**: Mock `run_prompt` with `side_effect=[work_response, extraction_response]`; verify first call gets raw prompt + handler model, second call gets extraction prompt + `"haiku"`
- **Extraction model constant**: Assert second `run_prompt` call uses `"haiku"` regardless of handler's `model` parameter
- **Step 1 failure**: `run_prompt` raises `AgentExecutionError` on first call; assert `runner.fail()` called, `run_prompt` called only once
- **Step 2 failure**: `side_effect=["good response", AgentExecutionError("boom")]`; assert `runner.fail()` called
- **Fire-and-forget unchanged**: `run_prompt` called exactly once with no extraction step

### Edge Cases

- Step 1 returns empty string — extraction prompt still sent with empty response body
- Single required field vs multiple fields in `state_updates`
- `extract_json` raises `ValueError` on haiku output — handled by existing except block

## Acceptance Criteria

- `_delegation_prompt` is completely removed from the codebase
- `_extraction_prompt` builds a clear, delimited prompt with XML-tagged response text
- State-updates mode makes exactly two `run_prompt` calls (work + extraction)
- Fire-and-forget mode makes exactly one `run_prompt` call (unchanged)
- Extraction step always uses `"haiku"` model regardless of handler configuration
- All existing tests pass (with mock pattern updates)
- New tests cover the two-call sequence, extraction model, and step failure scenarios
- `ruff`, `ty`, and `pytest` all pass with zero errors

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run -m pytest tests/ -v
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The `"haiku"` model string follows the CLI short-name convention used elsewhere (e.g. `"opus"`, `"sonnet"`)
- The extraction prompt wraps response text in `<response>` XML tags to prevent LLM output containing field-like text from corrupting the prompt structure (identified by Eduard review)
- Craig recommended keeping the current single-call delegation pattern. This was rejected because the issue documents a concrete production failure (run `2fd95671`) where the delegation pattern caused the agent to conflate execution with structured output. The two-step approach is explicitly requested by the issue author and is simpler in practice — each LLM call has exactly one job.
- The hardcoded extraction model is intentional per the issue: "it's an implementation detail, not a caller-facing knob"

## Report

Report on completion:
- Files changed (with line counts)
- Tests added/modified (with names)
- All validation command results (ruff, ty, pytest)
- Confirmation that `_delegation_prompt` is fully removed
- Confirmation that two-call pattern works for state_updates mode
