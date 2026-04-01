"""Programmatic channel for in-process workflow execution.

This module provides ProgrammaticChannel, which allows external Python code
to run antkeeper workflows via run_handler() and receive events through
callbacks. Each run_handler() call is self-contained: load app, run workflow,
return final state as a plain dict.
"""
from __future__ import annotations

from typing import Any, Callable

from antkeeper.core.domain import State, StreamEvent
from antkeeper.core.runner import Runner
from antkeeper.loader import load_app


class _InnerChannel:
    """Private channel satisfying the Channel protocol for a single run_handler() call."""

    def __init__(
        self,
        workflow_name: str,
        initial_state: State,
        on_progress: Callable[[str, StreamEvent], None] | None,
        on_error: Callable[[str, str], None] | None,
    ) -> None:
        """Initialise an inner channel for a single workflow run.

        Args:
            workflow_name: Name of the workflow handler to execute.
            initial_state: Initial state mapping passed to the runner.
                A shallow copy is taken so the caller's dict is not mutated.
            on_progress: Callback invoked with (run_id, StreamEvent) for
                non-error, non-internal events that carry content.
                Pass None to suppress progress delivery.
            on_error: Callback invoked with (run_id, message) for error events
                that carry content.  Pass None to suppress error delivery.
        """
        self.type = "programmatic"
        self.workflow_name = workflow_name
        self.initial_state = {**initial_state}
        self._on_progress = on_progress
        self._on_error = on_error

    def report(self, run_id: str, event: StreamEvent) -> None:
        """Route a stream event to the appropriate callback.

        Internal events and events with empty content are silently discarded.
        Error-type events are forwarded to ``on_error``; all other events are
        forwarded to ``on_progress``.  If the relevant callback is None the
        event is dropped without raising.

        Args:
            run_id: Opaque identifier for the current workflow run.
            event: The stream event emitted by the runner.
        """
        if event.internal:
            return
        if not event.content:
            return
        if event.type == "error":
            if self._on_error is not None:
                self._on_error(run_id, event.content)
        else:
            if self._on_progress is not None:
                self._on_progress(run_id, event)


class ProgrammaticChannel:
    """Channel for running workflows from external Python code.

    Construct once with optional callbacks, then call run_handler() for each
    workflow execution. Each call is self-contained with no shared state.

    Args:
        on_progress: Optional callback receiving (run_id, StreamEvent) for
            non-error, non-internal events with content.
        on_error: Optional callback receiving (run_id, message) for error events.
    """

    def __init__(
        self,
        on_progress: Callable[[str, StreamEvent], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        """Store optional callbacks for use across all run_handler() calls.

        Args:
            on_progress: Optional callback receiving (run_id, StreamEvent) for
                non-error, non-internal events with content.
            on_error: Optional callback receiving (run_id, message) for error
                events with content.
        """
        self._on_progress = on_progress
        self._on_error = on_error

    def run_handler(
        self,
        workflow_name: str,
        initial_state: dict[str, Any] | None = None,
        handlers_file: str = "handlers.py",
    ) -> dict[str, Any]:
        """Load an app and execute a workflow, returning final state.

        Args:
            workflow_name: Name of the registered workflow handler to execute.
            initial_state: Optional initial state dict. Defaults to empty dict.
            handlers_file: Path to the Python file containing the app.
                Defaults to "handlers.py".

        Returns:
            The final state dictionary after workflow execution.

        Raises:
            WorkflowFailedError: If the workflow calls runner.fail().
            FileNotFoundError: If handlers_file cannot be found.
            AttributeError: If the loaded module has no 'app' attribute.
            ValueError: If the workflow_name is not registered.
        """
        app = load_app(handlers_file)
        inner = _InnerChannel(
            workflow_name=workflow_name,
            initial_state=initial_state or {},
            on_progress=self._on_progress,
            on_error=self._on_error,
        )
        runner = Runner(app, inner)
        return runner.run()
