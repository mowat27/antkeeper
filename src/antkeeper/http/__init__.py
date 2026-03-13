"""HTTP package for Antkeeper server.

This package provides shared utilities used by HTTP route handlers across the
Antkeeper web server. It contains background task helpers that allow workflows
to run asynchronously without blocking HTTP responses.

Modules:
    slack_events: Slack Events API payload handling with debounce and dispatch.
    webhook: Webhook endpoint logic for triggering workflows via HTTP POST.
"""
import sys

from antkeeper.core.domain import WorkflowFailedError
from antkeeper.core.runner import Runner


def run_workflow_background(runner: Runner) -> None:
    """Execute a workflow in the background, handling errors gracefully.

    This function is designed to run as a background task in web servers
    and async contexts. It catches WorkflowFailedError silently (as it's
    an expected error when workflows fail) and logs unexpected errors to stderr.

    Args:
        runner: The Runner instance to execute.

    Raises:
        Does not raise exceptions - all errors are caught and handled internally.
    """
    try:
        runner.run()
    except WorkflowFailedError:
        pass
    except Exception as e:
        print(f"Unexpected error in workflow: {e}", file=sys.stderr)
