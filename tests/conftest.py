"""Shared pytest fixtures and test utilities.

This module provides test doubles and factory fixtures for testing Antkeeper
workflows without I/O side effects.
"""

import tempfile

import pytest

from antkeeper.core.app import App
from antkeeper.core.domain import State, StreamEvent
from antkeeper.core.runner import Runner


class TestChannel:
    """In-memory test double for workflow channels.

    Captures progress and error messages without performing I/O, enabling
    verification of framework behavior in tests.
    """

    def __init__(self, workflow_name: str, initial_state: State | None = None) -> None:
        self.type = "test"
        self.workflow_name = workflow_name
        self.initial_state: State = initial_state or {}
        self.progress_messages: list[str] = []
        self.error_messages: list[str] = []
        self.events: list[StreamEvent] = []

    def report(self, run_id: str, event: StreamEvent) -> None:
        """Capture an event to the in-memory lists.

        Args:
            run_id: Unique identifier for the workflow run.
            event: The stream event to capture.
        """
        self.events.append(event)
        if event.type == "error":
            self.error_messages.append(event.content)
        else:
            self.progress_messages.append(event.content)


@pytest.fixture
def app():
    """Provide a fresh App with logs, worktrees, and state directed to temp directories.

    Returns:
        App: A configured App instance with isolated temporary directories for testing.
    """
    return App(log_dir=tempfile.mkdtemp(), worktree_dir=tempfile.mkdtemp(), state_dir=tempfile.mkdtemp())


@pytest.fixture
def runner_factory(app):
    """Factory fixture for creating test runners with capturing channels.

    Returns a factory function that creates a Runner with a TestChannel,
    allowing tests to exercise workflows and inspect captured messages.

    Args:
        app: The App fixture providing the test application instance.

    Returns:
        Callable: Factory function that creates (Runner, TestChannel) tuples.
    """

    def _create(test_app: App | None = None, workflow_name: str = "test", initial_state: State | None = None):
        """Create a Runner and TestChannel pair for testing.

        Args:
            test_app: Optional App instance to use (defaults to fixture app).
            workflow_name: Name of the workflow being tested.
            initial_state: Initial state dictionary for the workflow.

        Returns:
            tuple: (Runner, TestChannel) pair for testing.
        """
        source = TestChannel(workflow_name, initial_state)
        runner = Runner(test_app or app, source)
        return runner, source
    return _create
