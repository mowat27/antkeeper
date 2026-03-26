"""API channel implementation for Antkeeper workflows.

This module provides an ApiChannel that adapts workflows for use in
web servers and HTTP APIs. Progress and errors are written to stdout/stderr.
"""
import sys

from antkeeper.core.domain import State, StreamEvent


class ApiChannel:
    """Channel implementation for API-based workflow execution.

    The ApiChannel is designed for use with web servers and HTTP APIs,
    where workflows are triggered by API requests. Progress messages
    are written to stdout, and errors to stderr, making them visible
    in server logs.

    Attributes:
        type: Channel type identifier ("api").
        workflow_name: Name of the workflow to execute.
        initial_state: Initial state dictionary for the workflow.
    """
    def __init__(self, workflow_name: str, initial_state: dict[str, str] | None = None) -> None:
        """Initialize an ApiChannel instance.

        Args:
            workflow_name: Name of the workflow to execute.
            initial_state: Optional initial state dictionary. Defaults to empty dict.
        """
        self.type = "api"
        self.workflow_name = workflow_name
        self.initial_state: State = {**(initial_state or {})}

    def report(self, run_id: str, event: StreamEvent) -> None:
        """Report a workflow event to stdout/stderr.

        Args:
            run_id: Unique identifier for the workflow run.
            event: The stream event to report.
        """
        if event.internal:
            return
        message = f"[{self.workflow_name}, {run_id}] {event.content}"
        if event.type == "error":
            print(message, flush=True, file=sys.stderr)
        else:
            print(message, flush=True)
