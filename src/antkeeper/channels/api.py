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
    def __init__(self, workflow_name: str, initial_state: dict[str, str] | None = None, *, verbose: bool = False) -> None:
        """Initialize an ApiChannel instance.

        Args:
            workflow_name: Name of the workflow to execute.
            initial_state: Optional initial state dictionary. Defaults to empty dict.
            verbose: When True, all events with content are shown as JSON.
                When False (default), only progress/error events are shown as plain text.
        """
        self.type = "api"
        self.workflow_name = workflow_name
        self.initial_state: State = {**(initial_state or {})}
        self.verbose = verbose

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
        message = f"[{self.workflow_name}, {run_id}] {rendered}"
        if event.type == "error":
            print(message, flush=True, file=sys.stderr)
        else:
            print(message, flush=True)
