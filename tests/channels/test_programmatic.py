"""Tests for the programmatic channel implementation.

Verifies that ProgrammaticChannel and _InnerChannel correctly handle
callback routing, workflow execution, error propagation, and state isolation.
"""
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from antkeeper.channels.programmatic import ProgrammaticChannel, _InnerChannel
from antkeeper.core.domain import StreamEvent, WorkflowFailedError


class TestInnerChannel:
    """Test suite for _InnerChannel report routing."""

    def test_report_progress_calls_on_progress(self):
        """Progress events are routed to on_progress callback."""
        on_progress = MagicMock()
        inner = _InnerChannel("wf", {}, on_progress=on_progress, on_error=None)
        event = StreamEvent(type="progress", content="step done")
        inner.report("run1", event)
        on_progress.assert_called_once_with("run1", event)

    def test_report_error_calls_on_error(self):
        """Error events are routed to on_error with string content."""
        on_error = MagicMock()
        inner = _InnerChannel("wf", {}, on_progress=None, on_error=on_error)
        inner.report("run1", StreamEvent(type="error", content="broke"))
        on_error.assert_called_once_with("run1", "broke")

    def test_report_skips_internal_events(self):
        """Internal events are silently discarded."""
        on_progress = MagicMock()
        on_error = MagicMock()
        inner = _InnerChannel("wf", {}, on_progress=on_progress, on_error=on_error)
        inner.report("run1", StreamEvent(type="progress", content="hidden", internal=True))
        on_progress.assert_not_called()
        on_error.assert_not_called()

    def test_report_skips_empty_content(self):
        """Events with empty content are silently discarded."""
        on_progress = MagicMock()
        on_error = MagicMock()
        inner = _InnerChannel("wf", {}, on_progress=on_progress, on_error=on_error)
        inner.report("run1", StreamEvent(type="progress", content=""))
        on_progress.assert_not_called()
        on_error.assert_not_called()

    def test_report_non_error_types_go_to_on_progress(self):
        """Assistant, result, and tool events are all routed to on_progress."""
        on_progress = MagicMock()
        on_error = MagicMock()
        inner = _InnerChannel("wf", {}, on_progress=on_progress, on_error=on_error)
        for event_type in ("assistant", "result", "tool"):
            inner.report("run1", StreamEvent(type=event_type, content="data"))
        assert on_progress.call_count == 3
        on_error.assert_not_called()

    def test_report_no_callbacks_does_not_raise(self):
        """No exception when both callbacks are None."""
        inner = _InnerChannel("wf", {}, on_progress=None, on_error=None)
        inner.report("run1", StreamEvent(type="progress", content="ok"))
        inner.report("run1", StreamEvent(type="error", content="fail"))

    def test_inner_channel_attributes(self):
        """Type, workflow_name, and initial_state are stored correctly."""
        inner = _InnerChannel("my_wf", {"k": "v"}, on_progress=None, on_error=None)
        assert inner.type == "programmatic"
        assert inner.workflow_name == "my_wf"
        assert inner.initial_state == {"k": "v"}


def _write_handlers_file(code: str) -> str:
    """Write a temporary handlers file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f.write(code)
    f.flush()
    f.close()
    return f.name


class TestProgrammaticChannel:
    """Test suite for ProgrammaticChannel.run_handler()."""

    def test_run_handler_returns_final_state(self):
        """run_handler() returns the handler's final state dict."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def greet(runner, state):
    return {**state, "greeting": "hello"}
""")
        try:
            channel = ProgrammaticChannel()
            result = channel.run_handler("greet", handlers_file=path)
            assert result["greeting"] == "hello"
            assert "run_id" in result
        finally:
            os.unlink(path)

    def test_run_handler_default_initial_state(self):
        """Omitting initial_state results in only framework-injected keys."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def noop(runner, state):
    return state
""")
        try:
            channel = ProgrammaticChannel()
            result = channel.run_handler("noop", handlers_file=path)
            assert "run_id" in result
            assert "workflow_name" in result
        finally:
            os.unlink(path)

    def test_run_handler_propagates_workflow_failed_error(self):
        """WorkflowFailedError propagates to the caller."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def boom(runner, state):
    runner.fail("boom")
""")
        try:
            channel = ProgrammaticChannel()
            with pytest.raises(WorkflowFailedError):
                channel.run_handler("boom", handlers_file=path)
        finally:
            os.unlink(path)

    def test_run_handler_calls_on_progress(self):
        """on_progress callback is invoked when handler reports progress."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def step(runner, state):
    runner.report_progress("step done")
    return state
""")
        try:
            on_progress = MagicMock()
            channel = ProgrammaticChannel(on_progress=on_progress)
            channel.run_handler("step", handlers_file=path)
            assert on_progress.call_count >= 1
            _, event = on_progress.call_args[0]
            assert event.content == "step done"
        finally:
            os.unlink(path)

    def test_run_handler_calls_on_error(self):
        """on_error callback is invoked with string message."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def warn(runner, state):
    runner.report_error("something wrong")
    return state
""")
        try:
            on_error = MagicMock()
            channel = ProgrammaticChannel(on_error=on_error)
            channel.run_handler("warn", handlers_file=path)
            on_error.assert_called_once()
            _, message = on_error.call_args[0]
            assert message == "something wrong"
        finally:
            os.unlink(path)

    def test_run_handler_no_state_carries_between_calls(self):
        """Each run_handler() call is isolated — no shared state."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def add_key(runner, state):
    return {**state, "added": True}
""")
        try:
            channel = ProgrammaticChannel()
            initial = {"base": 1}
            result1 = channel.run_handler("add_key", initial_state=initial, handlers_file=path)
            assert result1["added"] is True

            result2 = channel.run_handler("add_key", initial_state=initial, handlers_file=path)
            assert result2["base"] == 1
            assert result2["added"] is True
            # Second call should not carry first call's run_id
            assert result2["run_id"] != result1["run_id"]
        finally:
            os.unlink(path)

    def test_run_handler_initial_state_not_mutated(self):
        """The original initial_state dict is not mutated by run_handler()."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def mutate(runner, state):
    return {**state, "new_key": "new_value"}
""")
        try:
            channel = ProgrammaticChannel()
            original = {"keep": "this"}
            original_copy = dict(original)
            channel.run_handler("mutate", initial_state=original, handlers_file=path)
            assert original == original_copy
        finally:
            os.unlink(path)

    def test_run_handler_file_not_found(self):
        """FileNotFoundError propagates for missing handlers_file."""
        channel = ProgrammaticChannel()
        with pytest.raises(FileNotFoundError):
            channel.run_handler("wf", handlers_file="/nonexistent/handlers.py")

    def test_run_handler_unknown_workflow(self):
        """Exception propagates for unregistered workflow name."""
        path = _write_handlers_file("""\
from antkeeper.core.app import App
app = App()

@app.handler
def exists(runner, state):
    return state
""")
        try:
            channel = ProgrammaticChannel()
            with pytest.raises(Exception):
                channel.run_handler("does_not_exist", handlers_file=path)
        finally:
            os.unlink(path)
