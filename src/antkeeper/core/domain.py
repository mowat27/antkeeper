"""Core domain types and protocols for the Antkeeper framework.

This module defines the fundamental types used throughout the framework:
- State: Type alias for workflow data (dict[str, Any])
- Channel: Protocol for I/O boundaries and workflow configuration

These types form the foundation for handler signatures and runner operations.
"""
from typing import Any, Protocol


class WorkflowFailedError(Exception):
    """Raised by Runner.fail() to signal a workflow failure.

    This exception is raised when a workflow encounters a fatal error that
    should terminate execution. It is caught by channels to handle workflow
    failures appropriately (e.g., CLI exits with status 1, API logs error).
    """


type State = dict[str, Any]
"""Workflow data represented as a plain dictionary.

Handlers receive a ``State`` as input and must return a new ``State`` as
output.  State should be treated as immutable — always construct a new dict
with updates (e.g. ``{**state, "key": value}``) rather than modifying in
place.

Framework-reserved keys (written by the runner and helpers, not by handlers
directly):

- ``"run_id"``: unique 8-character hex identifier for the current execution.
- ``"workflow_name"``: name of the workflow being executed.
- ``"_progress"``: ``{"total": int, "completed": int}`` inserted by
  ``run_workflow`` before the first step executes and updated after each
  subsequent step.
- ``"_resume_skip"``: ``int`` — one-shot signal consumed by ``run_workflow``
  to skip already-completed steps when resuming.  Set by the CLI ``resume``
  command; stripped from state before execution and never persisted.
"""


class Channel(Protocol):
    """Protocol for communication channels that drive workflow execution.

    Channels serve as I/O boundaries for workflows, defining what workflow to
    run (workflow_name), what data to start with (initial_state), and how to
    communicate progress (report_progress, report_error). Implementations adapt
    workflows to different environments like CLI, web servers, or message queues.

    Attributes:
        type: The channel type identifier (e.g., "cli", "api", "web").
        workflow_name: The name of the workflow to execute.
        initial_state: The initial state dictionary for the workflow.
    """
    type: str
    workflow_name: str
    initial_state: State

    def report_progress(self, run_id: str, message: str, **opts: Any) -> None:
        """Report workflow progress.

        Args:
            run_id: Unique identifier for the workflow run.
            message: Progress message to report.
            **opts: Additional options for progress reporting.
        """
        ...

    def report_error(self, run_id: str, message: str) -> None:
        """Report a workflow error.

        Args:
            run_id: Unique identifier for the workflow run.
            message: Error message to report.
        """
        ...
