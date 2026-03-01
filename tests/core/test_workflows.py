"""Core workflow execution tests.

Tests the framework's ability to execute single handlers, multi-step workflows,
error handling, and handler resolution.
"""

import os
import tempfile

import pytest

from antkeeper.core.app import App, run_workflow
from antkeeper.core.domain import State, WorkflowFailedError
from antkeeper.core.runner import Runner


class TestWorkflows:
    """Test suite for workflow execution and handler composition."""
    def test_single_handler(self, app, runner_factory):
        """Test execution of a workflow with a single handler."""

        @app.handler
        def add_1(runner, state: State) -> State:
            runner.report_progress("adding 1")
            return {**state, "result": state["result"] + 1}

        runner, source = runner_factory(app, "add_1", {"result": 10})
        result = runner.run()
        assert result["result"] == 11
        assert source.progress_messages == ["adding 1"]

    def test_multi_step_workflow(self, app, runner_factory):
        """Test execution of a workflow composed of multiple sequential handlers."""

        @app.handler
        def add_1(runner, state: State) -> State:
            runner.report_progress("adding 1")
            return {**state, "result": state["result"] + 1}

        @app.handler
        def double(runner, state: State) -> State:
            runner.report_progress("doubling")
            return {**state, "result": state["result"] * 2}

        @app.handler
        def add_1_then_double(runner, state: State) -> State:
            return run_workflow(runner, state, [add_1, double])

        runner, source = runner_factory(app, "add_1_then_double", {"result": 10})
        result = runner.run()
        assert result["result"] == 22
        assert source.progress_messages == ["adding 1", "doubling"]

    def test_failure(self, app, runner_factory):
        """Test that workflow failure is propagated correctly via WorkflowFailedError."""

        @app.handler
        def blow_up(runner, _state: State):
            runner.report_error("something broke")
            runner.fail("Workflow failed")

        runner, source = runner_factory(app, "blow_up", {"result": 1})
        with pytest.raises(WorkflowFailedError):
            runner.run()
        assert source.error_messages == ["something broke"]

    def test_unknown_workflow(self, app, runner_factory):
        """Test that attempting to run an unregistered handler raises ValueError."""
        runner, _source = runner_factory(app, "nonexistent")
        with pytest.raises(ValueError, match="Unknown handler: nonexistent"):
            runner.run()


# Use a unique prefix to avoid collisions with real env vars
_ENV_PREFIX = "_ANTKEEPER_TEST_ENV_"


class _SimpleChannel:
    """Minimal channel for env var tests."""
    def __init__(self, workflow_name, initial_state=None):
        self.type = "test"
        self.workflow_name = workflow_name
        self.initial_state = initial_state or {}
    def report_progress(self, run_id, message, **opts): pass
    def report_error(self, run_id, message): pass


def _make_env_app(**kwargs):
    """Create an App with temp dirs and given kwargs."""
    return App(
        log_dir=tempfile.mkdtemp(),
        worktree_dir=tempfile.mkdtemp(),
        state_dir=tempfile.mkdtemp(),
        **kwargs,
    )


def _run_handler(app, handler_fn, initial_state=None):
    """Register a handler on app, run it, return final state."""
    app.add_handler(handler_fn)
    channel = _SimpleChannel(handler_fn.__name__, initial_state or {})
    runner = Runner(app, channel)
    return runner.run()


class TestAppEnvironment:
    """Tests for App env parameter and env var lifecycle during handler execution."""

    def test_handler_sees_env_vars(self):
        key = f"{_ENV_PREFIX}VAR1"
        app = _make_env_app(env={key: "hello"})

        def read_env(runner, state):
            return {**state, "val": os.environ[key]}

        result = _run_handler(app, read_env)
        assert result["val"] == "hello"

    def test_env_values_converted_to_string(self):
        key = f"{_ENV_PREFIX}NUM"
        app = _make_env_app(env={key: 42})

        def read_env(runner, state):
            return {**state, "val": os.environ[key]}

        result = _run_handler(app, read_env)
        assert result["val"] == "42"

    def test_env_restored_after_successful_handler(self):
        key = f"{_ENV_PREFIX}RESTORE"
        os.environ.pop(key, None)
        app = _make_env_app(env={key: "temp"})

        def noop(runner, state):
            return state

        _run_handler(app, noop)
        assert key not in os.environ

    def test_env_restored_after_failed_handler(self):
        key = f"{_ENV_PREFIX}FAIL"
        os.environ.pop(key, None)
        app = _make_env_app(env={key: "temp"})

        def blow_up(runner, state):
            raise RuntimeError("boom")

        app.add_handler(blow_up)
        channel = _SimpleChannel("blow_up")
        runner = Runner(app, channel)
        with pytest.raises(RuntimeError):
            runner.run()
        assert key not in os.environ

    def test_existing_env_var_preserved(self):
        key = f"{_ENV_PREFIX}EXISTING"
        os.environ[key] = "original"
        try:
            app = _make_env_app(env={key: "override"})

            def read_env(runner, state):
                return {**state, "val": os.environ[key]}

            result = _run_handler(app, read_env)
            assert result["val"] == "override"
            assert os.environ[key] == "original"
        finally:
            os.environ.pop(key, None)

    def test_none_env_is_noop(self):
        app = _make_env_app(env=None)

        def noop(runner, state):
            return state

        result = _run_handler(app, noop)
        assert "run_id" in result

    def test_empty_env_dict_is_noop(self):
        app = _make_env_app(env={})

        def noop(runner, state):
            return state

        result = _run_handler(app, noop)
        assert "run_id" in result

    def test_invalid_env_value_propagates(self):
        class BadStr:
            def __str__(self):
                raise ValueError("cannot convert")

        key = f"{_ENV_PREFIX}BAD"
        os.environ.pop(key, None)
        app = _make_env_app(env={key: BadStr()})

        def noop(runner, state):
            return state

        app.add_handler(noop)
        channel = _SimpleChannel("noop")
        runner = Runner(app, channel)
        with pytest.raises(ValueError, match="cannot convert"):
            runner.run()
        assert key not in os.environ

    def test_run_workflow_steps_see_env_vars(self):
        key = f"{_ENV_PREFIX}STEPS"
        app = _make_env_app(env={key: "visible"})

        def step_a(runner, state):
            return {**state, "a": os.environ[key]}

        def step_b(runner, state):
            return {**state, "b": os.environ[key]}

        def orchestrator(runner, state):
            return run_workflow(runner, state, [step_a, step_b])

        result = _run_handler(app, orchestrator)
        assert result["a"] == "visible"
        assert result["b"] == "visible"

    def test_env_restored_after_run_workflow_step_failure(self):
        key = f"{_ENV_PREFIX}STEPFAIL"
        os.environ.pop(key, None)
        app = _make_env_app(env={key: "temp"})

        def failing_step(runner, state):
            raise RuntimeError("step failed")

        def orchestrator(runner, state):
            return run_workflow(runner, state, [failing_step])

        app.add_handler(orchestrator)
        channel = _SimpleChannel("orchestrator")
        runner = Runner(app, channel)
        with pytest.raises(RuntimeError):
            runner.run()
        assert key not in os.environ
