# refactor: Simplify cli.py with click and extract shared code

- Decouple server from CLI by extracting `load_app` to a top-level `loader.py` module
- Replace argparse with click for declarative subcommand definitions
- Remove `fix-gh-issues` subcommand; move GitHub helpers to `helpers/github.py` for handler use

## Solution Design

### External Interface Change

After this refactor, the CLI commands remain the same except `fix-gh-issues` is removed:

```bash
# Unchanged
antkeeper run my_workflow
antkeeper run --model sonnet specify prompts/describe.md
echo "prompt" | antkeeper run --model sonnet specify
antkeeper server --host 0.0.0.0 --port 8000
antkeeper resume abcd1234
antkeeper init ./my_project

# REMOVED
antkeeper fix-gh-issues my_workflow 42 43  # No longer available
```

Handlers that need GitHub issue fetching can import directly:

```python
from antkeeper.helpers.github import fetch_gh_issue, build_issues_prompt
```

### Architectural Schema Changes

```yaml
modules:
  antkeeper.loader:
    kind: module
    description: Shared app-loading utility, used by CLI and server
    functions:
      - load_app(path: str) -> App

  antkeeper.helpers.github:
    kind: module
    description: GitHub CLI helpers for handler use
    functions:
      - fetch_gh_issue(issue_number: int) -> dict
      - build_issues_prompt(issues: list[dict]) -> str

  antkeeper.cli:
    kind: module
    description: Click-based CLI (single file, not a package)
    functions:
      - main(): click group entry point
    commands:
      - run
      - resume
      - server
      - init
```

## Relevant Files

- `src/antkeeper/cli.py` — the file being refactored; rewritten in-place with click
- `src/antkeeper/server.py` — imports `load_app` from cli; must update import to `antkeeper.loader`
- `src/antkeeper/__main__.py` — imports `main` from `antkeeper.cli`; no change needed
- `pyproject.toml` — add `click` dependency; entry point unchanged
- `src/antkeeper/helpers/__init__.py` — reference for helpers module pattern (do NOT add github exports here)
- `tests/test_cli.py` — rewrite for click CliRunner; remove fix-gh-issues tests
- `tests/core/test_resume.py` — no change needed (imports stay from `antkeeper.cli`)

### New Files

- `src/antkeeper/loader.py` — extracted `load_app` function
- `src/antkeeper/helpers/github.py` — extracted `fetch_gh_issue` and `build_issues_prompt`
- `tests/helpers/test_github.py` — tests migrated from `test_cli.py`
- `tests/core/test_loader.py` — tests for `load_app`

## Workflow

### Step 1: Create `src/antkeeper/loader.py`

- Move `load_app` function from `cli.py` to `loader.py`
- Keep the exact same signature: `load_app(path: str) -> App`
- Keep the exact same error semantics: raises `FileNotFoundError` and `AttributeError`
- Include the `importlib.util` imports it needs

### Step 2: Create `src/antkeeper/helpers/github.py`

- Move `fetch_gh_issue` and `build_issues_prompt` from `cli.py`
- Keep exact same signatures and error semantics
- Include `subprocess`, `json` imports
- Do NOT add these to `helpers/__init__.py` (they are not generic helpers)

### Step 3: Update `src/antkeeper/server.py`

- Change `from antkeeper.cli import load_app` to `from antkeeper.loader import load_app`
- No other changes

### Step 4: Add `click` to `pyproject.toml`

- Add `"click"` to the `dependencies` list

### Step 5: Rewrite `src/antkeeper/cli.py` with click

- Replace all argparse code with a click group and subcommands
- Remove `fix-gh-issues` subcommand entirely
- Remove `fetch_gh_issue`, `build_issues_prompt`, `load_app` (now in other modules)
- Import `load_app` from `antkeeper.loader`
- Keep `HANDLERS_TEMPLATE` as an inline string constant (do NOT extract to a separate file)
- Keep `_load_state_by_run_id` as a private function (only used by resume)
- Keep `parse_state_pairs` as a private function
- Replace `sys.exit(1)` calls with `click.echo` to stderr + `sys.exit(1)` (or `raise SystemExit(1)`)
- The click group function should be named `cli`, and `main = cli` at module level for the entry point
- Each subcommand should be a thin function:

**`run` command:**
- Options: `--agents-file` (default "handlers.py"), `--initial-state` (multiple), `--model`
- Arguments: `workflow_name`, `prompt_files` (variadic, optional)
- Body: build state from options, read prompt files or stdin, call `_run_workflow_cli`

**`resume` command:**
- Options: `--agents-file` (default "handlers.py")
- Arguments: `run_id`
- Body: load app, load state by run_id, validate progress, construct CliChannel + Runner, run

**`server` command:**
- Options: `--host` (default "127.0.0.1"), `--port` (default 8000), `--reload` (flag), `--agents-file` (default "handlers.py")
- Body: set env var, call uvicorn.run

**`init` command:**
- Arguments: `path` (optional, default ".")
- Body: write template to disk, print instructions

### Step 6: Rewrite `tests/test_cli.py` for click

- Replace all argparse mirror tests with click `CliRunner` tests
- Import `from click.testing import CliRunner` and `from antkeeper.cli import cli`
- Delete `TestArgParsing`, `TestInitArgParsing`, `TestResumeArgParsing` classes (argparse-specific)
- Delete `TestFixGhIssuesArgParsing`, `TestFixGhIssuesIntegration` classes (subcommand removed)
- Keep `TestParseStatePairs` (update import if needed)
- Rewrite `TestCliIntegration` as `TestRunCommand` using CliRunner
- Rewrite `TestInitIntegration` as `TestInitCommand` using CliRunner
- Rewrite `TestResumeIntegration` as `TestResumeCommand` using CliRunner
- For stdin tests: use `CliRunner(mix_stderr=False)` and `runner.invoke(cli, args, input="text")`

### Step 7: Create `tests/helpers/test_github.py`

- Move `TestFetchGhIssue` and `TestBuildIssuesPrompt` from `test_cli.py`
- Update imports to `from antkeeper.helpers.github import fetch_gh_issue, build_issues_prompt`
- Tests remain unchanged otherwise

### Step 8: Create `tests/core/test_loader.py`

- Add tests for `load_app`:
  - `test_load_app_returns_app_object` — load a temp file with valid app
  - `test_load_app_file_not_found` — missing file raises FileNotFoundError
  - `test_load_app_missing_app_attribute` — valid Python without app raises AttributeError

### Step 9: Validation

- Run all validation commands below

## Testing Strategy

### Unit Tests

**`tests/core/test_loader.py`** (new):
- `test_load_app_returns_app_object` — write a temp handlers file, load it, verify app is returned
- `test_load_app_file_not_found` — nonexistent path raises FileNotFoundError
- `test_load_app_missing_app_attribute` — temp file without `app` variable raises AttributeError

**`tests/helpers/test_github.py`** (migrated from test_cli.py):
- Existing `TestFetchGhIssue` tests (mock subprocess.run)
- Existing `TestBuildIssuesPrompt` tests (pure function, no mocks)

**`tests/test_cli.py`** (rewritten):
- `TestParseStatePairs` — unchanged (3 tests)
- `TestRunCommand` — CliRunner tests for run subcommand
- `TestInitCommand` — CliRunner tests for init subcommand
- `TestResumeCommand` — CliRunner tests for resume subcommand

### Edge Cases

- `antkeeper` with no subcommand shows help (exit code 0)
- Unknown subcommand shows error
- `--agents-file` pointing to nonexistent file produces clear error
- `run` with no workflow_name shows usage error
- `run` with nonexistent prompt file exits with error
- `resume` with run_id not found exits with error
- `resume` with already-completed workflow exits with error
- Stdin piping works via CliRunner `input` parameter

## Acceptance Criteria

- `antkeeper run`, `resume`, `server`, `init` commands work identically to before (minus fix-gh-issues)
- `antkeeper fix-gh-issues` is no longer available
- `server.py` imports `load_app` from `antkeeper.loader`, not `antkeeper.cli`
- `helpers/github.py` exports `fetch_gh_issue` and `build_issues_prompt`
- `cli.py` uses click, not argparse
- `cli.py` is a single file (not a package)
- `HANDLERS_TEMPLATE` remains an inline constant in `cli.py`
- All tests pass with zero errors
- Type checks pass
- Linter passes

### Validation Commands

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/
uv run ty check src/
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- The `helpers/__init__.py` must NOT be updated to re-export GitHub helpers. They are domain-specific, not generic utilities.
- `_load_state_by_run_id` stays in `cli.py` as a private function — it is only used by the resume command and does not need to be shared.
- The entry point `antkeeper.cli:main` in `pyproject.toml` continues to work because `cli.py` exports `main = cli` (the click group).
- `__main__.py` import (`from antkeeper.cli import main`) requires no change.
- `tests/core/test_resume.py` import (`from antkeeper.cli import _load_state_by_run_id`) requires no change since the function stays in cli.py.

## Report

Report the following on completion:
- Files created, modified, and deleted
- Number of tests added, modified, and removed
- All validation command results (must be zero errors)
- Confirmation that server.py no longer depends on cli module
- Confirmation that fix-gh-issues subcommand is removed
