"""Core workflow execution tests.

Covers the full surface area of workflow execution in the Antkeeper framework:

* Basic execution — single-handler and multi-step sequential workflows.
* Error handling — ``WorkflowFailedError`` propagation and unknown handler lookup.
* App environment — ``env`` lifecycle (set before handler, restored after success
  and failure, callable env values, mixed static/callable maps).
* State persistence — per-step persistence via ``run_workflow``.
* Callable ``log_dir`` — resolver receives the Runner, resulting dir is created.
* Handler composability — plain functions, ``@app.handler`` decorated handlers,
  ``ralph``-wrapped handlers, and handlers with ``**kwargs``, all usable as
  ``run_workflow`` steps.
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
    """Minimal channel implementation satisfying the channel protocol.

    Used by env var and callable log_dir tests where event capture is not
    required. Accepts all events and discards them silently.
    """

    def __init__(self, workflow_name, initial_state=None):
        """Initialise the channel with a workflow name and optional initial state.

        Args:
            workflow_name: Name of the workflow this channel represents.
            initial_state: Optional mapping of initial state values. Defaults to
                an empty dict when not provided.
        """
        self.type = "test"
        self.workflow_name = workflow_name
        self.initial_state = initial_state or {}

    def report(self, run_id, event):
        """Accept a stream event; no-op for this minimal channel.

        Args:
            run_id: Unique identifier for the workflow run.
            event: The stream event to discard.
        """


def _make_env_app(**kwargs):
    """Create an App backed by temporary directories with the given keyword arguments.

    Convenience factory that wires up isolated temp dirs for log, worktree, and
    state so individual tests do not need to manage directory setup.

    Args:
        **kwargs: Additional keyword arguments forwarded to the App constructor
            (e.g. ``env``).

    Returns:
        App: A configured App instance ready for use in a test.
    """
    return App(
        log_dir=tempfile.mkdtemp(),
        worktree_dir=tempfile.mkdtemp(),
        state_dir=tempfile.mkdtemp(),
        **kwargs,
    )


def _run_handler(app, handler_fn, initial_state=None):
    """Register a handler on ``app``, execute it, and return the final state.

    Args:
        app: The App instance to register the handler against.
        handler_fn: The handler callable to register and run.
        initial_state: Optional initial state dict. Defaults to an empty dict.

    Returns:
        State: The state dict produced by the handler after execution.
    """
    app.add_handler(handler_fn)
    channel = _SimpleChannel(handler_fn.__name__, initial_state or {})
    runner = Runner(app, channel)
    return runner.run()


class TestAppEnvironment:
    """Tests for App env parameter and env var lifecycle during handler execution."""

    def test_handler_sees_env_vars(self):
        """Test that env vars defined on App are visible to the handler via os.environ."""
        key = f"{_ENV_PREFIX}VAR1"
        app = _make_env_app(env={key: "hello"})

        def read_env(runner, state):
            return {**state, "val": os.environ[key]}

        result = _run_handler(app, read_env)
        assert result["val"] == "hello"

    def test_env_values_converted_to_string(self):
        """Test that non-string env values are converted to strings before being set."""
        key = f"{_ENV_PREFIX}NUM"
        app = _make_env_app(env={key: 42})

        def read_env(runner, state):
            return {**state, "val": os.environ[key]}

        result = _run_handler(app, read_env)
        assert result["val"] == "42"

    def test_env_restored_after_successful_handler(self):
        """Test that env vars set by App are removed from os.environ after a successful run."""
        key = f"{_ENV_PREFIX}RESTORE"
        os.environ.pop(key, None)
        app = _make_env_app(env={key: "temp"})

        def noop(runner, state):
            return state

        _run_handler(app, noop)
        assert key not in os.environ

    def test_env_restored_after_failed_handler(self):
        """Test that env vars are removed from os.environ even when the handler raises."""
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
        """Test that a pre-existing env var is restored to its original value after the run."""
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
        """Test that passing env=None has no effect on environment or handler execution."""
        app = _make_env_app(env=None)

        def noop(runner, state):
            return state

        result = _run_handler(app, noop)
        assert "run_id" in result

    def test_empty_env_dict_is_noop(self):
        """Test that passing an empty env dict has no effect on handler execution."""
        app = _make_env_app(env={})

        def noop(runner, state):
            return state

        result = _run_handler(app, noop)
        assert "run_id" in result

    def test_invalid_env_value_propagates(self):
        """Test that an env value that cannot be converted to string raises ValueError."""
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
        """Test that env vars are visible to all steps within a run_workflow call."""
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
        """Test that env vars are cleaned up when a step inside run_workflow raises."""
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

    def test_callable_env_value_resolved_before_handler(self):
        """Test that a callable env value is resolved and set before the handler runs."""
        key = f"{_ENV_PREFIX}CALLABLE"
        app = _make_env_app(env={key: lambda runner: "computed"})

        def read_env(runner, state):
            return {**state, "val": os.environ[key]}

        result = _run_handler(app, read_env)
        assert result["val"] == "computed"

    def test_mixed_callable_and_static_env(self):
        """Test that a mix of static and callable env values are both resolved correctly."""
        key_a = f"{_ENV_PREFIX}STATIC"
        key_b = f"{_ENV_PREFIX}DYNAMIC"
        app = _make_env_app(env={key_a: "static", key_b: lambda runner: "dynamic"})

        def read_env(runner, state):
            return {**state, "a": os.environ[key_a], "b": os.environ[key_b]}

        result = _run_handler(app, read_env)
        assert result["a"] == "static"
        assert result["b"] == "dynamic"

    def test_callable_env_receives_runner_properties(self):
        """Test that callable env values receive the Runner instance and can use its properties."""
        key = f"{_ENV_PREFIX}RUNID"
        app = _make_env_app(env={key: lambda runner: runner.id})

        def read_env(runner, state):
            return {**state, "env_val": os.environ[key], "run_id": runner.id}

        result = _run_handler(app, read_env)
        assert result["env_val"] == result["run_id"]

    def test_callable_env_restored_after_run(self):
        """Test that env vars set via callable are removed from os.environ after the run."""
        key = f"{_ENV_PREFIX}CALLABLE_RESTORE"
        os.environ.pop(key, None)
        app = _make_env_app(env={key: lambda runner: "temp_value"})

        def noop(runner, state):
            return state

        _run_handler(app, noop)
        assert key not in os.environ

    def test_callable_env_that_raises_propagates(self):
        """Test that an exception raised inside a callable env value propagates to the caller."""
        key = f"{_ENV_PREFIX}CALLABLE_ERR"
        os.environ.pop(key, None)

        def bad_callable(runner):
            raise ValueError("callable failed")

        app = _make_env_app(env={key: bad_callable})

        def noop(runner, state):
            return state

        app.add_handler(noop)
        channel = _SimpleChannel("noop")
        runner = Runner(app, channel)
        with pytest.raises(ValueError, match="callable failed"):
            runner.run()
        assert key not in os.environ

    def test_env_with_no_callables_unchanged(self):
        """Test that a static env dict without callables is applied without modification."""
        key = f"{_ENV_PREFIX}PLAIN"
        app = _make_env_app(env={key: "plain_value"})

        def read_env(runner, state):
            return {**state, "val": os.environ[key]}

        result = _run_handler(app, read_env)
        assert result["val"] == "plain_value"


class TestCallableLogDir:
    """Tests for callable log_dir support in App."""

    def test_callable_log_dir_resolves_with_runner(self):
        """Test that a callable log_dir is resolved using the Runner and the resulting dir is created."""
        base = tempfile.mkdtemp()
        app = App(
            log_dir=lambda runner: os.path.join(base, runner.id),
            worktree_dir=tempfile.mkdtemp(),
            state_dir=tempfile.mkdtemp(),
        )

        def noop(runner, state):
            return state

        app.add_handler(noop)
        channel = _SimpleChannel("noop")
        runner = Runner(app, channel)
        # The resolved log dir should exist and contain the runner ID
        resolved_dir = os.path.join(base, runner.id)
        assert os.path.isdir(resolved_dir)
        # Should have a log file in it
        log_files = os.listdir(resolved_dir)
        assert len(log_files) == 1
        assert log_files[0].endswith(".log")

    def test_static_log_dir_still_works(self):
        """Test that a plain string log_dir continues to work correctly alongside callable support."""
        log_dir = tempfile.mkdtemp()
        app = App(
            log_dir=log_dir,
            worktree_dir=tempfile.mkdtemp(),
            state_dir=tempfile.mkdtemp(),
        )

        def noop(runner, state):
            return state

        app.add_handler(noop)
        channel = _SimpleChannel("noop")
        Runner(app, channel)
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        assert len(log_files) == 1

    def test_callable_log_dir_that_raises_propagates(self):
        """Test that an exception raised by the callable log_dir propagates during Runner init."""
        def bad_log_dir(runner):
            raise RuntimeError("cannot compute log dir")

        app = App(
            log_dir=bad_log_dir,
            worktree_dir=tempfile.mkdtemp(),
            state_dir=tempfile.mkdtemp(),
        )

        def noop(runner, state):
            return state

        app.add_handler(noop)
        channel = _SimpleChannel("noop")
        with pytest.raises(RuntimeError, match="cannot compute log dir"):
            Runner(app, channel)


class TestStatePersistence:
    """Tests for per-step state persistence in run_workflow."""

    def test_state_persisted_after_each_step(self, app, runner_factory):
        """Verify _persist_state is called after each step in a multi-step workflow."""
        persist_calls = []

        def step_a(runner, state):
            return {**state, "a": 1}

        def step_b(runner, state):
            return {**state, "b": 2}

        @app.handler
        def workflow(runner, state):
            original_persist = runner._persist_state

            def tracking_persist(s):
                persist_calls.append(dict(s))
                return original_persist(s)

            runner._persist_state = tracking_persist
            return run_workflow(runner, state, [step_a, step_b])

        runner, _ = runner_factory(app, "workflow", {})
        runner.run()
        # run_workflow persists after each step (2 calls), then Runner.run()
        # persists the final state (1 call) = 3 total
        assert len(persist_calls) == 3
        assert "a" in persist_calls[0]
        assert "a" in persist_calls[1] and "b" in persist_calls[1]

    def test_final_state_has_no_progress_or_resume_keys(self, app, runner_factory):
        """Run a multi-step workflow, assert _progress and _resume_skip absent from returned state."""

        def step_a(runner, state):
            return {**state, "a": 1}

        def step_b(runner, state):
            return {**state, "b": 2}

        @app.handler
        def workflow(runner, state):
            return run_workflow(runner, state, [step_a, step_b])

        runner, _ = runner_factory(app, "workflow", {})
        result = runner.run()
        assert "_progress" not in result
        assert "_resume_skip" not in result

    def test_nested_run_workflow(self, app, runner_factory):
        """Outer handler calls run_workflow with an inner step that itself calls run_workflow."""

        def inner_step_a(runner, state):
            return {**state, "inner": state.get("inner", []) + ["a"]}

        def inner_step_b(runner, state):
            return {**state, "inner": state.get("inner", []) + ["b"]}

        def outer_step_one(runner, state):
            return run_workflow(runner, state, [inner_step_a, inner_step_b])

        def outer_step_two(runner, state):
            return {**state, "outer_done": True}

        @app.handler
        def workflow(runner, state):
            return run_workflow(runner, state, [outer_step_one, outer_step_two])

        runner, _ = runner_factory(app, "workflow", {})
        result = runner.run()
        assert result["inner"] == ["a", "b"]
        assert result["outer_done"] is True
        assert "_progress" not in result
        assert "_resume_skip" not in result


class TestHandlerComposability:
    """Tests for handler protocol composability across decorators, ralph, and run_workflow."""

    def test_decorated_handler_usable_in_run_workflow(self, app, runner_factory):
        """@app.handler decorated function passed as a step to run_workflow executes correctly."""

        @app.handler
        def increment(runner, state: State) -> State:
            return {**state, "n": state["n"] + 1}

        @app.handler
        def use_increment(runner, state: State) -> State:
            return run_workflow(runner, state, [increment])

        runner, _ = runner_factory(app, "use_increment", {"n": 0})
        result = runner.run()
        assert result["n"] == 1

    def test_mixed_handler_sources_in_run_workflow(self, app, runner_factory):
        """A steps list containing a plain function and a decorated handler all execute in sequence."""

        def plain_step(runner, state: State) -> State:
            return {**state, "steps": state.get("steps", []) + ["plain"]}

        @app.handler
        def decorated_step(runner, state: State) -> State:
            return {**state, "steps": state.get("steps", []) + ["decorated"]}

        @app.handler
        def orchestrator(runner, state: State) -> State:
            return run_workflow(runner, state, [plain_step, decorated_step])

        runner, _ = runner_factory(app, "orchestrator", {})
        result = runner.run()
        assert result["steps"] == ["plain", "decorated"]

    def test_decorated_handler_composable_with_ralph(self, app, runner_factory):
        """ralph(decorated_fn, validator=v) works and the resulting handler runs in run_workflow."""
        from antkeeper.handlers.ralph import ralph, ValidationResult

        @app.handler
        def do_work(runner, state: State) -> State:
            return {**state, "done": True}

        def always_pass(state: State) -> ValidationResult:
            return ValidationResult(success=True, feedback="")

        wrapped = ralph(do_work, validator=always_pass)

        @app.handler
        def orchestrator(runner, state: State) -> State:
            return run_workflow(runner, state, [wrapped])

        runner, _ = runner_factory(app, "orchestrator", {})
        result = runner.run()
        assert result["done"] is True

    def test_ralph_wrapping_cc_handler_pattern(self, app, runner_factory):
        """A handler mimicking cc_handler output, wrapped with ralph, runs in run_workflow."""
        from antkeeper.handlers.ralph import ralph, ValidationResult

        def fake_cc_handler(runner, state: State) -> State:
            return {**state, "cc_ran": True}

        fake_cc_handler.__name__ = "fake_cc"

        def always_pass(state: State) -> ValidationResult:
            return ValidationResult(success=True, feedback="")

        wrapped = ralph(fake_cc_handler, validator=always_pass)

        @app.handler
        def orchestrator(runner, state: State) -> State:
            return run_workflow(runner, state, [wrapped])

        runner, _ = runner_factory(app, "orchestrator", {})
        result = runner.run()
        assert result["cc_ran"] is True

    def test_lambda_handler_in_run_workflow(self, app, runner_factory):
        """A lambda assigned to a variable still works in run_workflow (has __name__ == '<lambda>')."""
        def step(runner, state):
            return {**state, "lambda_ran": True}
        step.__name__ = "<lambda>"

        @app.handler
        def orchestrator(runner, state: State) -> State:
            return run_workflow(runner, state, [step])

        runner, _ = runner_factory(app, "orchestrator", {})
        result = runner.run()
        assert result["lambda_ran"] is True

    def test_handler_with_kwargs_in_run_workflow(self, app, runner_factory):
        """A handler defined with **kwargs satisfies the protocol and works in run_workflow."""

        def flexible_handler(runner, state, **kwargs):
            return {**state, "flex": True}

        flexible_handler.__name__ = "flexible"

        @app.handler
        def orchestrator(runner, state: State) -> State:
            return run_workflow(runner, state, [flexible_handler])

        runner, _ = runner_factory(app, "orchestrator", {})
        result = runner.run()
        assert result["flex"] is True
