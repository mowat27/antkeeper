"""CLI channel implementation for Antkeeper workflows.

This module provides the CliChannel class, which implements the Channel
protocol for command-line interface environments. It handles progress
reporting to stdout and error reporting to stderr.
"""
import logging
import sys

from antkeeper.core.domain import State, StreamEvent

logger = logging.getLogger("antkeeper.channels.cli")


class CliChannel:
    """Channel adapter for command-line interface workflows.

    Implements the Channel protocol for CLI environments. Progress messages
    are written to stdout with flush=True for immediate display. Error messages
    are written to stderr.

    Attributes:
        type: Always "cli" to identify this channel type.
        workflow_name: The name of the workflow being executed.
        initial_state: The initial state dictionary for the workflow.
    """

    def __init__(self, workflow_name: str, initial_state: dict[str, str] | None = None, *, verbose: bool = False) -> None:
        """Initialize CLI channel with workflow configuration.

        Args:
            workflow_name: Name of the workflow for display purposes and logging.
            initial_state: Optional dictionary of initial state key-value pairs.
                Defaults to an empty dict if not provided.
            verbose: When True, all events with content are shown as JSON.
                When False (default), only progress/error events are shown as plain text.
        """
        self.type = "cli"
        self.workflow_name = workflow_name
        self.initial_state: State = {**(initial_state or {})}
        self.verbose = verbose
        logger.debug(f"CliChannel initialized: workflow_name={workflow_name}")

    def report(self, run_id: str, event: StreamEvent) -> None:
        """Report a workflow event to stdout/stderr.

        Args:
            run_id: Unique identifier for the workflow run.
            event: The stream event to report.
        """
        if event.internal:
            return
        if not event.content:
            return
        if not self.verbose and event.type not in ("progress", "error"):
            return
        rendered = event.to_json() if self.verbose else event.content
        logger.debug(f"{event.type.title()} [{run_id}]: {event.to_json()}")
        message = f"[{self.workflow_name}, {run_id}] {rendered}"
        if event.type == "error":
            print(message, flush=True, file=sys.stderr)
        else:
            print(message, flush=True)
