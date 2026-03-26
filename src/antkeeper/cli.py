"""Command-line interface for Antkeeper workflow framework.

This module provides the Click-based CLI entry point for executing Antkeeper
workflows. It handles argument parsing, app loading, initial state
configuration, and runner setup.
"""

import glob as globmod
import json
import logging
import os
import sys
from pathlib import Path

import click

from antkeeper.channels.cli import CliChannel
from antkeeper.core.domain import WorkflowFailedError
from antkeeper.core.runner import Runner
from antkeeper.loader import load_app

logger = logging.getLogger("antkeeper.cli")

HANDLERS_TEMPLATE = '''\
"""Antkeeper workflow handlers.

Define handlers with @app.handler and chain them with run_workflow().
Run a handler:  antkeeper run <handler_name>
Start the API:  antkeeper server
"""

from datetime import datetime

from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.git.worktrees import Worktree, git_worktree

app = App()


@app.handler
def healthcheck(runner: Runner, state: State) -> State:
    """Verify the pipeline is working."""
    runner.report_progress("Running healthcheck")
    runner.logger.info("healthcheck ok")
    return {**state, "status": "ok"}


# --- Workflow composition example ---
#
# @app.handler
# def step_one(runner: Runner, state: State) -> State:
#     runner.report_progress("Step one")
#     return {**state, "step": 1}
#
# @app.handler
# def step_two(runner: Runner, state: State) -> State:
#     runner.report_progress("Step two")
#     return {**state, "step": 2}
#
# @app.handler
# def my_workflow(runner: Runner, state: State) -> State:
#     return run_workflow(runner, state, [step_one, step_two])


# --- Worktree isolation example ---
#
# @app.handler
# def isolated_workflow(runner: Runner, state: State) -> State:
#     """Run steps inside an isolated git worktree."""
#     worktree_name = f"{datetime.now().strftime(\'%Y%m%d%H%M%S\')}-{runner.id}"
#     wt = Worktree(base_dir=runner.app.worktree_dir, name=worktree_name)
#     with git_worktree(wt, create=True, branch="feat/my-feature", remove=False):
#         state = run_workflow(runner, state, [step_one, step_two])
#     return {**state, "worktree_path": wt.path}
'''


def parse_state_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse command-line state pairs into a dictionary.

    Args:
        pairs: List of strings in "key=value" format.

    Returns:
        dict[str, str]: Dictionary mapping keys to values.

    Raises:
        SystemExit: If any pair is not in "key=value" format.
    """
    state = {}
    for pair in pairs:
        if "=" not in pair:
            print(f"Error: invalid --initial-state value (expected key=val): {pair}", file=sys.stderr)
            sys.exit(1)
        key, val = pair.split("=", 1)
        state[key] = val
    return state


def _run_workflow_cli(agents_file: str, workflow_name: str, state: dict) -> None:
    """Execute a workflow via CLI channel."""
    try:
        app = load_app(agents_file)
    except FileNotFoundError:
        logger.error(f"Agents file not found: {agents_file}")
        click.echo(f"Error: agents file not found: {agents_file}", err=True)
        sys.exit(1)
    except AttributeError:
        logger.error(f"{agents_file} has no 'app' attribute")
        click.echo(f"Error: {agents_file} has no 'app' attribute", err=True)
        sys.exit(1)

    logger.info(f"App loaded from {agents_file}")
    channel = CliChannel(workflow_name=workflow_name, initial_state=state)
    runner = Runner(app, channel)
    logger.info(f"Runner created: run_id={runner.id}")
    try:
        result = runner.run()
    except WorkflowFailedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    logger.info("Workflow run complete")
    print(result)


def _load_state_by_run_id(state_dir: str, run_id: str) -> tuple[dict, str]:
    """Load persisted state for a previous run by its run_id.

    Searches state_dir for a JSON file whose name ends with ``-{run_id}.json``.

    Args:
        state_dir: Directory containing persisted state files.
        run_id: The 8-char hex identifier from a previous run.

    Returns:
        Tuple of (state dict, file path).

    Raises:
        FileNotFoundError: If no matching state file is found.
    """
    matches = globmod.glob(os.path.join(state_dir, f"*-{run_id}.json"))
    if not matches:
        raise FileNotFoundError(f"No state file found for run_id: {run_id}")
    path = matches[0]
    with open(path) as f:
        return json.load(f), path


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Antkeeper workflow framework CLI."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option("--agents-file", default="handlers.py", help="Path to Python file containing the app.")
@click.option("--initial-state", multiple=True, help="Key=value pairs for initial workflow state.")
@click.option("--model", default=None, help="Model identifier to use for LLM operations.")
@click.argument("workflow_name")
@click.argument("prompt_files", nargs=-1, required=False)
def run(agents_file, initial_state, model, workflow_name, prompt_files):
    """Execute a workflow."""
    state = parse_state_pairs(list(initial_state))
    if model is not None:
        state["model"] = model
    if prompt_files:
        parts = []
        for path in prompt_files:
            try:
                parts.append(Path(path).read_text())
            except FileNotFoundError:
                logger.error(f"File not found: {path}")
                click.echo(f"Error: file not found: {path}", err=True)
                sys.exit(1)
        state["prompt"] = "".join(parts)
    elif not sys.stdin.isatty():
        state["prompt"] = sys.stdin.read()
    _run_workflow_cli(agents_file, workflow_name, state)


@cli.command()
@click.option("--agents-file", default="handlers.py", help="Path to Python file containing the app.")
@click.argument("run_id")
def resume(agents_file, run_id):
    """Resume a previously interrupted workflow run."""
    try:
        app = load_app(agents_file)
    except FileNotFoundError:
        logger.error(f"Agents file not found: {agents_file}")
        click.echo(f"Error: agents file not found: {agents_file}", err=True)
        sys.exit(1)
    except AttributeError:
        logger.error(f"{agents_file} has no 'app' attribute")
        click.echo(f"Error: {agents_file} has no 'app' attribute", err=True)
        sys.exit(1)

    try:
        state, state_path = _load_state_by_run_id(app.state_dir, run_id)
    except FileNotFoundError:
        click.echo(f"Error: no state found for run_id: {run_id}", err=True)
        sys.exit(1)

    if "workflow_name" not in state:
        click.echo("Error: cannot resume: state file has no workflow_name", err=True)
        sys.exit(1)

    if "_progress" not in state:
        click.echo("Error: cannot resume: workflow has no progress to resume from", err=True)
        sys.exit(1)

    completed = state["_progress"]["completed"]
    total = state["_progress"]["total"]
    if completed >= total:
        click.echo(f"Error: cannot resume: workflow already completed ({completed}/{total} steps)", err=True)
        sys.exit(1)

    state["_resume_skip"] = completed
    channel = CliChannel(workflow_name=state["workflow_name"], initial_state=state)
    runner = Runner(app, channel)
    logger.info(f"Resuming run_id={run_id} as new run_id={runner.id}")
    try:
        result = runner.run()
    except WorkflowFailedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    print(result)


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host address to bind.")
@click.option("--port", default=8000, type=int, help="Port number to bind.")
@click.option("--reload", is_flag=True, help="Enable auto-reload on code changes.")
@click.option("--agents-file", default="handlers.py", help="Path to Python file containing the app.")
def server(host, port, reload, agents_file):
    """Start the FastAPI server."""
    import uvicorn

    os.environ["ANTKEEPER_HANDLERS_FILE"] = agents_file
    uvicorn.run("antkeeper.server:app", host=host, port=port, reload=reload)


@cli.command()
@click.argument("path", default=".")
def init(path):
    """Scaffold a new Antkeeper project."""
    path = os.path.realpath(path)
    target = os.path.join(path, "handlers.py")
    if os.path.exists(target):
        click.echo(f"Error: handlers.py already exists in {path}", err=True)
        sys.exit(1)
    try:
        with open(target, "w") as f:
            f.write(HANDLERS_TEMPLATE)
    except FileNotFoundError:
        click.echo(f"Error: directory does not exist: {path}", err=True)
        sys.exit(1)
    except PermissionError:
        click.echo(f"Error: no write permission for {path}", err=True)
        sys.exit(1)
    print(f"Created handlers.py in {path}")
    print()
    print("Run your first workflow:")
    print("  antkeeper run healthcheck")
    print()
    print("Start the API server:")
    print("  antkeeper server")
    print()
    print("Environment variables:")
    print("  ANTKEEPER_HANDLERS_FILE  Path to handlers file (default: handlers.py)")
    print("  SLACK_BOT_TOKEN          Slack bot OAuth token (for Slack channel)")
    print("  SLACK_BOT_USER_ID        Slack bot user ID (for Slack channel)")
    print("  SLACK_COOLDOWN_SECONDS   Slack debounce cooldown in seconds (default: 30)")


main = cli


if __name__ == "__main__":
    main()
