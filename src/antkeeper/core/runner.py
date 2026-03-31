"""Workflow execution engine.

The Runner is the core execution engine that brings together an App (handler
registry) and a Channel (I/O boundary). It manages the workflow lifecycle:
- Generates unique run IDs
- Sets up per-run file logging
- Injects run_id and workflow_name into state
- Applies app-level environment variables around each handler invocation
- Invokes workflow handlers
- Provides progress/error reporting utilities
- Handles workflow failures

Each Runner instance represents a single workflow execution.
"""
from __future__ import annotations

import json
import logging
import os
import uuid

from datetime import datetime
from typing import TYPE_CHECKING, NoReturn

from opentelemetry import trace

from antkeeper.core.domain import State, Channel, StreamEvent, WorkflowFailedError
from antkeeper.core.app import App, _app_env

if TYPE_CHECKING:
    from typing import Callable


class Runner:
    """Executes workflows by invoking handlers with state management.

    The Runner bridges the gap between channels (which define what to run)
    and apps (which define how to run it), managing execution lifecycle
    and providing utilities for progress reporting and error handling.

    Each Runner instance is specific to a single workflow execution and includes:
    - A unique 8-character hex ID for tracking
    - A dedicated file logger writing to app.log_dir
    - A dedicated state file writing to app.state_dir
    - Methods for progress/error reporting that delegate to the channel
    - A fail() method for terminating workflows with error messages

    Attributes:
        id: Unique 8-character hex identifier for this run.
        channel: The Channel defining workflow configuration and I/O.
        app: The App containing registered workflow handlers.
        logger: Per-run file logger instance.
    """
    def __init__(self, app: App, channel: Channel) -> None:
        """Initialize a new Runner instance.

        Creates a unique run ID, resolves the log directory (calling
        ``app.log_dir(self)`` if it is callable, otherwise using it directly),
        sets up a dedicated file logger in that directory, and stores references
        to the app and channel. The logger is configured with DEBUG level and
        writes to a timestamped file.

        Args:
            app: The App instance containing registered handlers. ``app.log_dir``
                may be a plain string or a callable that accepts a Runner and
                returns the directory path; it is resolved here at init time.
            channel: The Channel instance defining the workflow to execute.
        """
        self.id: str = uuid.uuid4().hex[:8]
        self.channel = channel
        self.app = app

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

        # Resolve log_dir (may be a callable that receives the runner)
        log_dir = app.log_dir(self) if callable(app.log_dir) else app.log_dir

        # Set up per-run file logger
        os.makedirs(log_dir, exist_ok=True)
        log_filename = f"{timestamp}-{self.id}.log"
        log_path = os.path.join(log_dir, log_filename)

        # Set up per-run state file
        os.makedirs(app.state_dir, exist_ok=True)
        self._state_path = os.path.realpath(os.path.join(app.state_dir, f"{timestamp}-{self.id}.json"))
        self.logger = logging.getLogger(f"antkeeper.run.{self.id}")
        self.logger.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
        self.logger.addHandler(file_handler)
        self.logger.propagate = False

        self.logger.info(f"Runner initialized: run_id={self.id}, workflow={self.channel.workflow_name}")
        self.logger.debug(f"Log file: {log_path}")
        self.logger.debug(f"Channel type: {self.channel.type}")

    def run(self) -> State:
        """Execute the workflow with initial state setup.

        Execution order
        ---------------
        1. Merges ``channel.initial_state`` with framework keys ``run_id`` and
           ``workflow_name`` to form the starting state.
        2. Persists that state immediately via ``_persist_state`` so the state
           file exists on disk before any handler logic runs.  This is important
           for multi-step workflows that use ``run_workflow``, where ``_progress``
           is written during step sequencing — the initial persist ensures the
           file is present even in the event of an early failure.
        3. Resolves any callable values in ``app.env`` by calling each one with
           ``self`` (the Runner).
        4. Invokes the workflow handler inside an ``_app_env`` context so that
           resolved environment variables are exported to ``os.environ`` for the
           duration of the handler and restored afterward.
        5. Persists the final state returned by the handler.

        Any exception raised by the workflow handler is logged and re-raised
        unchanged so that the calling channel can handle it appropriately.

        Returns:
            The final state after workflow execution completes.

        Raises:
            Exception: Any exception raised by the workflow handler is logged
                and re-raised.
        """
        state = {**self.channel.initial_state, "run_id": self.id, "workflow_name": self.workflow_name}
        self._persist_state(state)

        self.logger.info(f"Workflow started: {self.workflow_name}")
        self.logger.debug(f"Initial state: {state}")
        with trace.get_tracer("antkeeper").start_as_current_span(
            "antkeeper.run",
            attributes={
                "run_id": self.id,
                "workflow_name": self.workflow_name,
                "channel.type": self.channel.type,
            },
        ):
            try:
                resolved_env = (
                    {k: (v(self) if callable(v) else v) for k, v in self.app.env.items()}
                    if self.app.env
                    else self.app.env
                )
                with _app_env(resolved_env):
                    state = self.workflow(self, state)
            except Exception as e:
                self.logger.error(f"Workflow failed: {self.workflow_name} - {type(e).__name__}: {e}")
                raise
        self._persist_state(state)
        self.logger.info(f"Workflow completed: {self.workflow_name}")
        self.logger.debug(f"Final state: {state}")
        return state

    @property
    def workflow_name(self) -> str:
        """Get the workflow name from the channel.

        Returns:
            The workflow name string.
        """
        return self.channel.workflow_name

    @property
    def workflow(self) -> Callable:
        """Get the workflow handler callable from the app.

        Returns:
            The workflow handler function that accepts a Runner and State.
        """
        return self.app.get_handler(self.workflow_name)

    def _persist_state(self, state: State) -> None:
        """Persist the current state to a JSON file.

        Writes the state dictionary to the state file path established during
        ``__init__`` (``<state_dir>/<timestamp>-<run_id>.json``).  The file is
        overwritten on each call so it always reflects the most recent snapshot.
        State is written as indented JSON for human readability.

        This method is called at several points during a run:

        - By ``Runner.run()`` after building the initial state (before any
          handler executes), ensuring the file exists on disk immediately.
        - By ``run_workflow()`` after initialising ``_progress`` (before the
          first step runs) and after each individual step completes.
        - By ``Runner.run()`` again with the handler's final return value.

        Args:
            state: The state dictionary to persist.
        """
        with open(self._state_path, "w") as f:
            json.dump(state, f, indent=2)

    def report_progress(self, message: str) -> None:
        """Report progress through the channel.

        Logs the progress message and delegates to the channel's report method.

        Args:
            message: Progress message to report.
        """
        self.logger.info(f"Progress: {message}")
        self.channel.report(self.id, StreamEvent(type="progress", content=message))

    def report_error(self, message: str) -> None:
        """Report an error through the channel.

        Logs the error message and delegates to the channel's report method.

        Args:
            message: Error message to report.
        """
        self.logger.error(f"Error reported: {message}")
        self.channel.report(self.id, StreamEvent(type="error", content=message))

    def fail(self, message: str) -> NoReturn:
        """Fail the workflow by raising WorkflowFailedError.

        Args:
            message: Error message describing the failure.

        Raises:
            WorkflowFailedError: Always raised to signal workflow failure.
        """
        self.logger.error(f"Workflow fatal error: {message}")
        raise WorkflowFailedError(message)
