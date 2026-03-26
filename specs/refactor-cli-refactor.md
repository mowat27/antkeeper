# refactor: Simplify CLI before channels/streaming work

- Extract `load_app` to `core/loader.py` so server no longer depends on CLI module
- Replace argparse with click — each subcommand becomes a thin, declarative function
- Remove `fix-gh-issues` CLI command; move helpers to `helpers/github.py` for programmatic use

## Solution Design

### External Interface Change

The CLI surface changes from argparse to click. All existing subcommands (`run`, `resume`, `server`, `init`) keep the same arguments and flags. The `fix-gh-issues` subcommand is removed — its helper functions (`fetch_gh_issue`, `build_issues_prompt`) move to `antkeeper.helpers.github` for direct use by handlers.

Help output changes slightly (click formatting vs argparse), but all flag names, defaults, and positional argument order remain identical.

### Architectural Schema Changes

```yaml
modules:
  core/loader.py:
    kind: module (new)
    exports:
      - load_app(path: str) -> App

  helpers/github.py:
    kind: module (new)
    exports:
      - fetch_gh_issue(issue_number: int) -> dict
      - build_issues_prompt(issues: list[dict]) -> str

  cli.py:
    kind: module (modified)
    removes:
      - load_app  # moved to core/loader
      - fetch_gh_issue  # moved to helpers/github
      - build_issues_prompt  # moved to helpers/github
      - _build_common_state  # inlined into click commands
      - fix-gh-issues subcommand  # removed
    keeps:
      - HANDLERS_TEMPLATE  # stays as string constant
      - parse_state_pairs  # CLI-layer concern (sys.exit -> click.UsageError)
      - _run_workflow_cli  # stays, updates load_app import
      - _load_state_by_run_id  # stays, only used by resume command
    adds:
      - click group with run, resume, server, init commands
```

## Relevant Files

- `src/antkeeper/cli.py` — the file being refactored; all changes centre here
- `src/antkeeper/server.py` — imports `load_app` from `cli.py` (line 22); must update import to `core.loader`
- `src/antkeeper/core/__init__.py` — may need to export `load_app` if other consumers expect it from `core`
- `src/antkeeper/helpers/__init__.py` — no change needed; `github.py` is a standalone helper
- `pyproject.toml` — add `click` dependency; entry point unchanged
- `tests/test_cli.py` — rewrite argparse mirror tests to use `click.testing.CliRunner`; remove `fix-gh-issues` test classes; update imports
- `tests/core/test_resume.py` — no change; `_load_state_by_run_id` stays in cli.py

### New Files

- `src/antkeeper/core/loader.py` — receives `load_app()` from cli.py
- `src/antkeeper/helpers/github.py` — receives `fetch_gh_issue()` and `build_issues_prompt()` from cli.py
- `tests/core/test_loader.py` — unit tests for `load_app`
- `tests/helpers/test_github.py` — moved tests for `fetch_gh_issue` and `build_issues_prompt`

## Workflow

### Step 1: Extract `load_app` to `core/loader.py`

- Create `src/antkeeper/core/loader.py` with `load_app()` moved verbatim from cli.py
- Update `src/antkeeper/server.py` line 22: `from antkeeper.core.loader import load_app`
- Update `src/antkeeper/cli.py`: `from antkeeper.core.loader import load_app`
- Create `tests/core/test_loader.py` with tests for `load_app` (valid file, file not found, no app attribute)

### Step 2: Move GitHub helpers to `helpers/github.py`

- Create `src/antkeeper/helpers/github.py` with `fetch_gh_issue()` and `build_issues_prompt()` moved from cli.py
- Move corresponding tests from `tests/test_cli.py` (`TestFetchGhIssue`, `TestBuildIssuesPrompt`) to `tests/helpers/test_github.py`
- Update patch targets in moved tests: `antkeeper.helpers.github.subprocess.run` (was `antkeeper.cli.subprocess.run`)

### Step 3: Add click dependency

- Add `click` to `dependencies` in `pyproject.toml`
- Run `uv sync` to install

### Step 4: Rewrite CLI with click

- Replace argparse setup with a `@click.group()` and individual `@cli.command()` functions
- Inline `_build_common_state` into the `run` command (click passes explicit params, no `Namespace`)
- Convert `parse_state_pairs` error handling from `sys.exit(1)` to `raise click.UsageError(...)`
- Keep `_run_workflow_cli` as-is (update its `load_app` import to `from antkeeper.core.loader import load_app`)
- Keep `_load_state_by_run_id` as-is (only used by resume)
- Keep `HANDLERS_TEMPLATE` as a string constant in cli.py
- Remove the `fix-gh-issues` subcommand entirely
- The `main()` function becomes: `def main(): cli()`
- stdin handling: keep `sys.stdin.isatty()` check in the `run` command — works fine under click

Click command structure:
```python
@click.group()
def cli(): ...

@cli.command()
@click.argument("workflow_name")
@click.argument("prompt_files", nargs=-1)
@click.option("--agents-file", default="handlers.py")
@click.option("--initial-state", multiple=True)
@click.option("--model", default=None)
def run(workflow_name, prompt_files, agents_file, initial_state, model): ...

@cli.command()
@click.argument("run_id")
@click.option("--agents-file", default="handlers.py")
def resume(run_id, agents_file): ...

@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.option("--reload", is_flag=True)
@click.option("--agents-file", default="handlers.py")
def server(host, port, reload, agents_file): ...

@cli.command()
@click.argument("path", default=".")
def init(path): ...
```

### Step 5: Rewrite CLI tests for click

- Replace `_build_parser()` argparse mirror with `click.testing.CliRunner`
- Rewrite `TestArgParsing` to invoke `cli` commands via `CliRunner().invoke(cli, [...])`
- Rewrite integration tests to use `CliRunner` instead of `monkeypatch.setattr("sys.argv", ...)`
- Assert on `result.exit_code` and `result.output` instead of `capsys` and `SystemExit`
- Delete `TestFixGhIssuesArgParsing` and `TestFixGhIssuesIntegration` entirely
- Keep `TestParseStatePairs` (update to expect `click.UsageError` instead of `SystemExit`)
- `TestResumeArgParsing` and `TestResumeIntegration`: rewrite for CliRunner

### Step 6: Run validation commands

- Run all tests, linter, and type checker to verify zero errors

## Testing Strategy

### Unit Tests

**`tests/core/test_loader.py`** (new):
- `test_load_app_returns_app` — valid agents file returns app with handlers
- `test_load_app_file_not_found` — nonexistent path raises `FileNotFoundError`
- `test_load_app_no_app_attribute` — file without `app` raises `AttributeError`

**`tests/helpers/test_github.py`** (moved from test_cli.py):
- All existing `TestFetchGhIssue` tests (subprocess mock, gh not found, gh failure, JSON decode error)
- All existing `TestBuildIssuesPrompt` tests (single issue, multiple issues)
- Update patch targets to `antkeeper.helpers.github.subprocess.run`

### Unit Tests (rewritten)

**`tests/test_cli.py`** — all argparse tests rewritten with `CliRunner`:
- `run` command: workflow_name required, prompt_files optional, --initial-state multiple, --model, --agents-file
- `resume` command: run_id required, --agents-file
- `server` command: --host, --port, --reload, --agents-file
- `init` command: path defaults to "."
- Integration tests: CliRunner with temp handler files, verify exit codes and output

### Edge Cases

- `run` with no arguments → click shows usage error
- `--initial-state` with no `=` → `click.UsageError`
- `--initial-state` repeated → both values collected (click `multiple=True` returns tuple)
- Piped stdin with CliRunner: `CliRunner().invoke(cli, ["run", "wf"], input="prompt text")`
- Unknown subcommand → click shows error and available commands
- `init` when `handlers.py` already exists → error message, exit code 1
- `resume` with completed workflow → error message, exit code 1

## Acceptance Criteria

- `antkeeper run`, `antkeeper resume`, `antkeeper server`, `antkeeper init` all work with identical arguments as before
- `antkeeper fix-gh-issues` is removed; running it shows "No such command"
- `server.py` imports `load_app` from `core.loader`, not from `cli`
- `cli.py` is under 200 lines (down from 464)
- `click` is a core dependency in `pyproject.toml`
- All existing tests pass (minus deleted `fix-gh-issues` tests)
- Zero linter warnings, zero type-check errors

### Validation Commands

```bash
uv run -m pytest tests/ -v
uv run ruff check src/ tests/
uv run ty check src/
```

IMPORTANT: If any of the checks above fail you must investigate and fix the error. It is not acceptable to simply explain away the problem. You must reach zero errors, zero warnings before you move on. This includes pre-existing issues and other issues that you don't think are related to this bugfix.

## Notes

- `HANDLERS_TEMPLATE` stays as a string constant in `cli.py`. Extracting it to a template file adds a directory, a file, runtime I/O, and an error path for a single-use constant — not worth it.
- `_load_state_by_run_id` stays in `cli.py`. It has one caller (the resume command). Move it only when a second consumer appears.
- `fetch_gh_issue` and `build_issues_prompt` move to `helpers/github.py` even though they lose their CLI caller, because the user's design explicitly wants them available for handler use.
- `_build_common_state` is eliminated entirely — with click, each command receives explicit parameters, so the argparse `Namespace` wrapper is unnecessary.
- `sys.stdin.isatty()` works fine under click for the piped-stdin case. No need for `click.get_text_stream`.

## Report

Files changed: `cli.py` (rewritten), `server.py` (import update), `pyproject.toml` (add click). Files created: `core/loader.py`, `helpers/github.py`, `tests/core/test_loader.py`, `tests/helpers/test_github.py`. Files deleted: none. Tests added: loader tests, github helper tests. Tests rewritten: all CLI arg-parsing and integration tests (CliRunner). Tests deleted: `fix-gh-issues` test classes. Validations: pytest, ruff, ty.
