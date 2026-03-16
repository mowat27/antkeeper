# feature: CLI shorthand to fix GitHub issues

- Add `fix-gh-issues` subcommand that fetches GitHub issues via `gh` CLI and runs a workflow with the issue content as the prompt.
- Resolves to a normal `antkeeper run` execution path — fetching and prompt assembly happen before the standard CliChannel/Runner flow.
- All GitHub-specific logic stays in `cli.py` (outer layer); no core changes.

## Solution Design

### External Interface Change

New CLI subcommand:

```bash
antkeeper fix-gh-issues <workflow> <issue_number> [issue_number...]
antkeeper fix-gh-issues --model opus --agents-file handlers.py specify 42 99
```

Behaviour identical to `antkeeper run` except:
- `state["prompt"]` is auto-constructed from fetched GitHub issue JSON (including comments)
- `state["issue_numbers"]` contains the list of issue numbers as integers
- `--model`, `--agents-file`, `--initial-state` flags work identically to `run`

Handlers receive a normal `State` dict — they see `prompt`, `issue_numbers`, and any other keys from `--initial-state`. No handler changes needed.

**CLI example:**
```bash
antkeeper fix-gh-issues specify 42
# Equivalent to fetching issue #42, building a prompt, and running:
# antkeeper run --initial-state issue_numbers='[42]' specify <prompt-from-issue>
```

**API/Slack channels:** Not affected. This is a CLI-only shorthand.

## Relevant Files

- `src/antkeeper/cli.py` — add `fix-gh-issues` subparser, `fetch_gh_issue()` function, prompt assembly, and execution branch in `main()`. Extract shared run-execution tail into `_run_workflow_cli()` helper to avoid duplicating the load-app/channel/runner/error-handling block.
- `tests/test_cli.py` — add arg parsing tests, unit tests for `fetch_gh_issue` and prompt assembly, and integration tests for the full subcommand.

## Workflow

### Step 1: Add `fetch_gh_issue` function to `cli.py`

- Add `import subprocess` and `import json` to `cli.py`
- Add `fetch_gh_issue(issue_number: int) -> dict` function:
  - Calls `subprocess.run(["gh", "issue", "view", str(issue_number), "--json", "number,title,body,comments,labels,state"], capture_output=True, text=True, check=True)`
  - Returns `json.loads(result.stdout)`
  - Does NOT catch exceptions — lets `FileNotFoundError`, `subprocess.CalledProcessError`, and `json.JSONDecodeError` propagate to the caller (matches framework philosophy)

### Step 2: Extract shared CLI execution helper

- Extract the common tail of the `run` branch (load app, create CliChannel, create Runner, run, handle WorkflowFailedError, print result) into a private helper function `_run_workflow_cli(agents_file: str, workflow_name: str, state: dict) -> None`
- Refactor the existing `run` branch to call this helper
- The `fix-gh-issues` branch will also call this helper

### Step 3: Add `fix-gh-issues` subparser and execution branch

- Add subparser with: `--agents-file` (default `handlers.py`), `--initial-state` (append), `--model` (default None), positional `workflow_name`, positional `issue_numbers` (`nargs="+"`, `type=int`)
- In the `elif args.command == "fix-gh-issues"` branch:
  - Fetch issues in a try/except block at the CLI layer:
    - `FileNotFoundError` → print "`gh` CLI not found" to stderr, exit 1
    - `subprocess.CalledProcessError` → print failed-to-fetch message with stderr from `gh`, exit 1
    - `json.JSONDecodeError` → print unexpected-response message to stderr, exit 1
  - Build prompt: `"Fix the following GitHub issue(s).\n\n"` followed by `"--- Issue #N ---\n"` + `json.dumps(issue, indent=2)` + `"\n\n"` for each issue
  - Build state from `parse_state_pairs(args.initial_state)`, set `state["prompt"]`, `state["issue_numbers"]`, and optionally `state["model"]`
  - Call `_run_workflow_cli(args.agents_file, args.workflow_name, state)`

### Step 4: Add tests

- See Testing Strategy below

### Step 5: Validate

- Run validation commands below

## Testing Strategy

### Unit Tests

**`TestFetchGhIssue`** (patch `antkeeper.cli.subprocess.run`):
- `test_fetch_gh_issue_returns_parsed_json` — mock returns `CompletedProcess(returncode=0, stdout='{"number":42,"title":"bug"}')`, assert returns parsed dict, assert subprocess called with correct args including `check=True`
- `test_fetch_gh_issue_raises_on_nonzero_returncode` — mock raises `subprocess.CalledProcessError`, assert it propagates (not caught)
- `test_fetch_gh_issue_raises_on_gh_not_found` — mock raises `FileNotFoundError`, assert it propagates
- `test_fetch_gh_issue_raises_on_invalid_json` — mock returns `CompletedProcess(returncode=0, stdout="not json")`, assert `json.JSONDecodeError` propagates

**`TestBuildIssuesPrompt`** (pure function, no mocks):
- `test_single_issue_prompt` — verify format: header, separator with issue number, JSON dump
- `test_multiple_issues_prompt` — verify both issues appear with correct separators

### Integration

**`TestFixGhIssuesArgParsing`** (mirrors existing `TestArgParsing` pattern):
- Parse workflow + single issue number → `args.issue_numbers == [42]`
- Parse workflow + multiple issue numbers → `args.issue_numbers == [42, 99]`
- Missing issue numbers → `SystemExit`
- `--model`, `--agents-file`, `--initial-state` flags parsed correctly

**`TestFixGhIssuesIntegration`** (patch `antkeeper.cli.subprocess.run`, temp agents file with echo handler):
- `test_fix_gh_issues_fetches_and_runs` — mock gh returning valid JSON, verify handler sees `state["prompt"]` with issue content and `state["issue_numbers"] == [42]`
- `test_fix_gh_issues_multiple_issues` — mock gh with `side_effect` for two issues, verify both in prompt
- `test_fix_gh_issues_gh_failure_exits` — mock raises `CalledProcessError`, verify stderr + exit 1
- `test_fix_gh_issues_gh_not_found_exits` — mock raises `FileNotFoundError`, verify stderr + exit 1
- `test_fix_gh_issues_model_merged` — verify `--model` flows into state
- `test_fix_gh_issues_initial_state_merged` — verify `--initial-state k=v` merged alongside issue data

### Edge Cases

- Non-integer issue number: argparse enforces `type=int`, exits automatically
- Zero issue numbers: argparse enforces `nargs="+"`, exits automatically
- `gh` returns valid JSON but unexpected shape: no validation needed — the JSON is passed through to the prompt as-is; handlers deal with content

## Acceptance Criteria

- `antkeeper fix-gh-issues <workflow> <issue_number>` fetches the issue via `gh` and runs the workflow with a prompt containing the issue JSON
- Multiple issue numbers are all fetched and included in the prompt
- `state["issue_numbers"]` contains the integer list of issue numbers
- `--model`, `--agents-file`, `--initial-state` flags work identically to `run`
- Missing or invalid `gh` CLI produces a clear error message on stderr and exits 1
- Non-existent issue produces a clear error from `gh` stderr and exits 1
- No changes to core framework modules
- All existing tests continue to pass

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run -m pytest tests/ -v
uv run antkeeper fix-gh-issues --help
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- `fetch_gh_issue` deliberately does not catch exceptions. The framework philosophy is that exceptions propagate and the outer layer (the `main()` function) handles them. This keeps `fetch_gh_issue` simple, testable, and consistent with other helpers.
- `build_issues_prompt` is kept as a named function (not inlined) for testability — the prompt format matters and should be directly testable.
- The `_run_workflow_cli` extraction is a minimal DRY refactor — it extracts the load-app/channel/runner block that would otherwise be duplicated verbatim between `run` and `fix-gh-issues`.
- `state["issue_numbers"]` is explicitly required by the issue spec ("Add issue numbers to the initial state"). It is set at the CLI layer and is opaque to the core — just another state key.

## Report

**Files changed:** `src/antkeeper/cli.py`, `tests/test_cli.py`
**New functions:** `fetch_gh_issue()`, `_run_workflow_cli()` (extracted helper), prompt assembly logic
**Tests added:** ~12 tests across 4 test classes (unit tests for fetch/prompt, arg parsing, integration)
**Validations:** ruff lint, ty typecheck, pytest, CLI help output
