"""Command-line interface for Antkeeper workflow framework.

This module provides the CLI entry point for executing Antkeeper workflows.
It handles argument parsing, app loading from Python files, initial state
configuration, and runner setup.

The CLI supports a 'run' command that loads an app from a Python file,
configures initial state from command-line arguments, and executes the
requested workflow through a CliChannel.
"""
import argparse
import glob as globmod
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from antkeeper.channels.cli import CliChannel
from antkeeper.core.domain import WorkflowFailedError
from antkeeper.core.runner import Runner

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


def load_app(path: str):
    """Dynamically load an Antkeeper app from a Python file.

    Uses importlib to dynamically import a Python module and extract its
    'app' attribute, which should be an instance of antkeeper.core.app.App.

    Args:
        path: File path to the Python module containing the app.

    Returns:
        App: The app object from the loaded module.

    Raises:
        FileNotFoundError: If the file cannot be found or the module spec
            cannot be created.
        AttributeError: If the loaded module does not have an 'app' attribute.
    """
    spec = importlib.util.spec_from_file_location("agents", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


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


def fetch_gh_issue(issue_number: int) -> dict:
    """Fetch a GitHub issue via the gh CLI.

    Args:
        issue_number: The GitHub issue number to fetch.

    Returns:
        dict: Parsed JSON response from gh containing issue details.

    Raises:
        FileNotFoundError: If gh CLI is not installed.
        subprocess.CalledProcessError: If gh command fails.
        json.JSONDecodeError: If gh response is not valid JSON.
    """
    result = subprocess.run(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--json",
            "number,title,body,comments,labels,state",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def build_issues_prompt(issues: list[dict]) -> str:
    """Build a prompt from a list of GitHub issues.

    Args:
        issues: List of issue dictionaries from fetch_gh_issue.

    Returns:
        str: Formatted prompt containing all issues.
    """
    parts = ["Fix the following GitHub issue(s).\n"]
    for issue in issues:
        parts.append(f"--- Issue #{issue['number']} ---\n")
        parts.append(json.dumps(issue, indent=2))
        parts.append("\n\n")
    return "".join(parts)


def _build_common_state(args) -> dict:
    """Build initial state from shared CLI flags.

    Args:
        args: Parsed argparse namespace with initial_state and model attributes.

    Returns:
        dict: State dictionary with parsed pairs and optional model.
    """
    state = parse_state_pairs(args.initial_state)
    if args.model is not None:
        state["model"] = args.model
    return state


def _run_workflow_cli(agents_file: str, workflow_name: str, state: dict) -> None:
    """Execute a workflow via CLI channel.

    Loads the app, creates a CLI channel, runs the workflow, and handles errors.

    Args:
        agents_file: Path to Python file containing the app.
        workflow_name: Name of the workflow to execute.
        state: Initial state dictionary for the workflow.

    Raises:
        SystemExit: On file not found, missing app attribute, or workflow failure.
    """
    try:
        app = load_app(agents_file)
    except FileNotFoundError:
        logger.error(f"Agents file not found: {agents_file}")
        print(f"Error: agents file not found: {agents_file}", file=sys.stderr)
        sys.exit(1)
    except AttributeError:
        logger.error(f"{agents_file} has no 'app' attribute")
        print(f"Error: {agents_file} has no 'app' attribute", file=sys.stderr)
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


def main() -> None:
    """Main entry point for the Antkeeper CLI.

    Parses command-line arguments and executes the requested workflow or starts
    the server based on the subcommand.

    Commands:
        run: Execute a workflow with the following options:
            --agents-file: Path to Python file containing the app
                (default: handlers.py)
            --initial-state: Key=value pairs for initial workflow state
                (repeatable)
            --model: Model identifier to use for LLM operations
            workflow_name: Name of the workflow to execute (positional)
            prompt_files: Optional file paths whose contents are concatenated
                into state["prompt"]. If no files given and stdin is piped,
                stdin is read as the prompt.

        fix-gh-issues: Fetch GitHub issues and run a workflow against them:
            --agents-file: Path to Python file containing the app
                (default: handlers.py)
            --initial-state: Key=value pairs for initial workflow state
                (repeatable)
            --model: Model identifier to use for LLM operations
            workflow_name: Name of the workflow to execute (positional)
            issue_numbers: One or more GitHub issue numbers to fetch and
                pass as state["prompt"] and state["issue_numbers"].

        server: Start the FastAPI server with the following options:
            --host: Host address to bind (default: 127.0.0.1)
            --port: Port number to bind (default: 8000)
            --reload: Enable auto-reload on code changes
            --agents-file: Path to Python file containing the app
                (default: handlers.py)

        resume: Resume a previously interrupted workflow run:
            --agents-file: Path to Python file containing the app
                (default: handlers.py)
            run_id: The 8-character hex run identifier from the interrupted run.
                Loads the persisted state from app.state_dir, skips already-
                completed steps, and re-executes the remaining steps as a new
                run.

        init: Scaffold a new Antkeeper project with the following options:
            path: Directory in which to create handlers.py
                (default: current directory). Exits with an error if
                handlers.py already exists or the directory does not exist.

    Raises:
        SystemExit: Exit code 0 for success, 1 for errors (file not found,
            invalid arguments, workflow failure).

    Examples:
        antkeeper run my_workflow
        antkeeper run --model sonnet specify prompts/describe.md
        antkeeper run --model sonnet specify file1.md file2.md
        echo "describe this project" | antkeeper run --model sonnet specify
        antkeeper run --initial-state key1=val1 --initial-state key2=val2 my_workflow
        antkeeper server --host 0.0.0.0 --port 8000
    """
    parser = argparse.ArgumentParser(prog="antkeeper")
    subparsers = parser.add_subparsers(dest="command")

    common_run_parent = argparse.ArgumentParser(add_help=False)
    common_run_parent.add_argument("--agents-file", default="handlers.py")
    common_run_parent.add_argument("--initial-state", action="append", default=[])
    common_run_parent.add_argument("--model", default=None)
    common_run_parent.add_argument("workflow_name")

    run_parser = subparsers.add_parser("run", parents=[common_run_parent])
    run_parser.add_argument("prompt_files", nargs="*")

    fix_gh_issues_parser = subparsers.add_parser("fix-gh-issues", parents=[common_run_parent])
    fix_gh_issues_parser.add_argument("issue_numbers", nargs="+", type=int)

    server_parser = subparsers.add_parser("server")
    server_parser.add_argument("--host", default="127.0.0.1")
    server_parser.add_argument("--port", type=int, default=8000)
    server_parser.add_argument("--reload", action="store_true")
    server_parser.add_argument("--agents-file", default="handlers.py")

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--agents-file", default="handlers.py")
    resume_parser.add_argument("run_id")

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("path", nargs="?", default=".")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    logger.debug(f"CLI args parsed: command={args.command}")

    if args.command == "run":
        state = _build_common_state(args)
        if args.prompt_files:
            parts = []
            for path in args.prompt_files:
                try:
                    parts.append(Path(path).read_text())
                except FileNotFoundError:
                    logger.error(f"File not found: {path}")
                    print(f"Error: file not found: {path}", file=sys.stderr)
                    sys.exit(1)
            state["prompt"] = "".join(parts)
        elif not sys.stdin.isatty():
            state["prompt"] = sys.stdin.read()
        _run_workflow_cli(args.agents_file, args.workflow_name, state)

    elif args.command == "fix-gh-issues":
        issues = []
        try:
            for issue_number in args.issue_numbers:
                issues.append(fetch_gh_issue(issue_number))
        except FileNotFoundError:
            print("`gh` CLI not found", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"Failed to fetch issue: {e.stderr}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError:
            print("Unexpected response from `gh` CLI", file=sys.stderr)
            sys.exit(1)

        state = _build_common_state(args)
        state["prompt"] = build_issues_prompt(issues)
        state["issue_numbers"] = args.issue_numbers
        _run_workflow_cli(args.agents_file, args.workflow_name, state)

    elif args.command == "resume":
        try:
            app = load_app(args.agents_file)
        except FileNotFoundError:
            logger.error(f"Agents file not found: {args.agents_file}")
            print(f"Error: agents file not found: {args.agents_file}", file=sys.stderr)
            sys.exit(1)
        except AttributeError:
            logger.error(f"{args.agents_file} has no 'app' attribute")
            print(f"Error: {args.agents_file} has no 'app' attribute", file=sys.stderr)
            sys.exit(1)

        try:
            state, state_path = _load_state_by_run_id(app.state_dir, args.run_id)
        except FileNotFoundError:
            print(f"Error: no state found for run_id: {args.run_id}", file=sys.stderr)
            sys.exit(1)

        if "workflow_name" not in state:
            print("Error: cannot resume: state file has no workflow_name", file=sys.stderr)
            sys.exit(1)

        if "_progress" not in state:
            print("Error: cannot resume: workflow has no progress to resume from", file=sys.stderr)
            sys.exit(1)

        completed = state["_progress"]["completed"]
        total = state["_progress"]["total"]
        if completed >= total:
            print(f"Error: cannot resume: workflow already completed ({completed}/{total} steps)", file=sys.stderr)
            sys.exit(1)

        state["_resume_skip"] = completed
        channel = CliChannel(workflow_name=state["workflow_name"], initial_state=state)
        runner = Runner(app, channel)
        logger.info(f"Resuming run_id={args.run_id} as new run_id={runner.id}")
        try:
            result = runner.run()
        except WorkflowFailedError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        print(result)

    elif args.command == "init":
        path = os.path.realpath(args.path)
        target = os.path.join(path, "handlers.py")
        if os.path.exists(target):
            print(f"Error: handlers.py already exists in {path}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(target, "w") as f:
                f.write(HANDLERS_TEMPLATE)
        except FileNotFoundError:
            print(f"Error: directory does not exist: {path}", file=sys.stderr)
            sys.exit(1)
        except PermissionError:
            print(f"Error: no write permission for {path}", file=sys.stderr)
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

    elif args.command == "server":
        import uvicorn

        os.environ["ANTKEEPER_HANDLERS_FILE"] = args.agents_file
        uvicorn.run("antkeeper.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
