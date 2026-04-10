"""Core domain types and protocols for the Antkeeper framework.

This module defines the fundamental types used throughout the framework:
- State: Type alias for workflow data (dict[str, Any])
- StreamEvent: Dataclass for streaming LLM events
- Channel: Protocol for I/O boundaries and workflow configuration
- Handler: Protocol for workflow handler callables

These types form the foundation for handler signatures and runner operations.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from antkeeper.core.runner import Runner


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


@dataclass
class StreamEvent:
    """A single event from an LLM streaming response.

    Attributes:
        type: Event type — "progress", "assistant", "tool", "result",
            "rate_limit", or "error".
        content: Human-readable payload.
        metadata: Optional structured data (usage, cost, rate limit fields).
        internal: True for housekeeping calls (e.g. extraction step).
    """
    type: str
    content: str
    metadata: dict[str, Any] | None = field(default=None)
    internal: bool = field(default=False)

    def to_json(self) -> str:
        """Serialize this event to a JSON string."""
        return json.dumps(dataclasses.asdict(self), default=str)


class Channel(Protocol):
    """Protocol for communication channels that drive workflow execution.

    Channels serve as the I/O boundary for a workflow.  They declare which
    workflow to run, the initial state to seed it with, and how to surface
    progress events to the outside world (stdout, HTTP response, Slack
    message, etc.).

    Implementations adapt the framework to different runtime environments —
    ``CliChannel`` for the command line, ``ApiChannel`` for HTTP endpoints,
    and ``SlackChannel`` for Slack-triggered workflows.

    Attributes:
        type: Short identifier for the channel kind (e.g. ``"cli"``,
            ``"api"``, ``"slack"``).  Used in log messages and metadata.
        workflow_name: Name of the workflow handler to execute.  Must match
            a key registered in the ``App`` handler registry.
        initial_state: Seed state dictionary passed to the workflow before
            the first handler runs.
    """

    type: str
    workflow_name: str
    initial_state: State

    def report(self, run_id: str, event: StreamEvent) -> None:
        """Surface a workflow event to the channel's audience.

        Called by the ``Runner`` whenever a handler emits a ``StreamEvent``
        (progress update, assistant message, tool call, result, or error).

        Args:
            run_id: Unique identifier for the current workflow execution.
            event: The stream event to surface.
        """
        ...


class Handler(Protocol):
    """A workflow handler callable.

    Any function (or callable object) that accepts a ``Runner`` and a ``State``
    and returns an updated ``State`` satisfies this protocol.  The ``__name__``
    attribute is required so that handlers can be looked up by name in the
    ``App`` registry and referenced in log messages.

    Example::

        def my_handler(runner: Runner, state: State) -> State:
            runner.report_progress("Processing…")
            return {**state, "processed": True}

    Attributes:
        __name__: Unique name used as the handler's registry key.
    """

    __name__: str

    def __call__(self, runner: Runner, state: State) -> State:
        """Execute the handler.

        Args:
            runner: The active ``Runner`` instance, providing logging,
                progress reporting, and state persistence helpers.
            state: The current workflow state dictionary.  Treat as
                immutable — return a new dict with any updates.

        Returns:
            The updated workflow state.
        """
        ...
