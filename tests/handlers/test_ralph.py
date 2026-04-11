"""Tests for the ralph retry-with-validation handler wrapper."""

import os
import stat

import pytest

from antkeeper.core.domain import WorkflowFailedError
from antkeeper.handlers.ralph import ralph, ValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _always_pass(state):
    """Validator that always returns a passing result."""
    return ValidationResult(success=True, feedback="")


def _always_fail(state):
    """Validator that always returns a failing result with fixed feedback."""
    return ValidationResult(success=False, feedback="always fails")


def _identity(runner, state):
    """Handler that returns a shallow copy of state unchanged."""
    return dict(state)


def _add_result(runner, state):
    """Handler that adds ``result='ok'`` to state."""
    return {**state, "result": "ok"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_pass_on_first_attempt(runner_factory):
    """Handler that passes on the first attempt returns state unchanged."""
    handler = ralph(_identity, validator=_always_pass)
    runner, channel = runner_factory()
    result = handler(runner, {"prompt": "hello"})
    assert result == {"prompt": "hello"}


def test_pass_after_retries(runner_factory):
    """Handler that eventually passes is retried until validation succeeds."""
    call_count = {"n": 0}

    def _count_and_pass_on_third(runner, state):
        call_count["n"] += 1
        return {**state, "count": call_count["n"]}

    def _pass_on_third(state):
        if state.get("count", 0) >= 3:
            return ValidationResult(success=True, feedback="")
        return ValidationResult(success=False, feedback=f"count is {state.get('count')}")

    handler = ralph(_count_and_pass_on_third, validator=_pass_on_third, max_retries=3)
    runner, channel = runner_factory()
    result = handler(runner, {"prompt": "hi"})
    assert call_count["n"] == 3
    assert result["count"] == 3


# ---------------------------------------------------------------------------
# Retry exhaustion
# ---------------------------------------------------------------------------


def test_exhaustion_raises_workflow_failed(runner_factory):
    """WorkflowFailedError is raised after all retries are exhausted."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return dict(state)

    handler = ralph(_count, validator=_always_fail, max_retries=2)
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        handler(runner, {})
    assert call_count["n"] == 3


def test_max_retries_zero_single_attempt(runner_factory):
    """When max_retries=0, the handler is called exactly once before failing."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return dict(state)

    handler = ralph(_count, validator=_always_fail, max_retries=0)
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        handler(runner, {})
    assert call_count["n"] == 1


def test_default_max_retries_is_three(runner_factory):
    """The default max_retries value is 3, giving 4 total attempts."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return dict(state)

    handler = ralph(_count, validator=_always_fail)
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        handler(runner, {})
    assert call_count["n"] == 4


# ---------------------------------------------------------------------------
# Exception propagation
# ---------------------------------------------------------------------------


def test_handler_exception_propagates(runner_factory):
    """Exceptions raised by the inner handler propagate immediately without retrying."""
    call_count = {"n": 0}

    def _boom(runner, state):
        call_count["n"] += 1
        raise ValueError("handler error")

    handler = ralph(_boom, validator=_always_pass)
    runner, channel = runner_factory()
    with pytest.raises(ValueError, match="handler error"):
        handler(runner, {})
    assert call_count["n"] == 1


def test_validator_exception_propagates(runner_factory):
    """Exceptions raised by the validator propagate immediately without retrying."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return dict(state)

    def _boom(state):
        raise RuntimeError("validator error")

    handler = ralph(_count, validator=_boom)
    runner, channel = runner_factory()
    with pytest.raises(RuntimeError, match="validator error"):
        handler(runner, {})
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Progress log
# ---------------------------------------------------------------------------


def _log_path(runner, label):
    """Return the expected ralph progress log path for the given runner and label."""
    log_dir = runner.app.log_dir(runner) if callable(runner.app.log_dir) else runner.app.log_dir
    return os.path.join(log_dir, f"ralph-{label}-{runner.id}.log")


def test_progress_log_created(runner_factory):
    """A progress log file is created in the runner's log directory after a run."""
    handler = ralph(_identity, validator=_always_pass, label="mytest")
    runner, channel = runner_factory()
    handler(runner, {})
    assert os.path.exists(_log_path(runner, "mytest"))


def test_progress_log_contains_feedback(runner_factory):
    """Validator feedback from failed attempts appears in the progress log."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return {**state, "n": call_count["n"]}

    def _fail_then_pass(state):
        if state.get("n", 0) >= 2:
            return ValidationResult(success=True, feedback="")
        return ValidationResult(success=False, feedback="specific feedback message")

    handler = ralph(_count, validator=_fail_then_pass, label="feedbacktest")
    runner, channel = runner_factory()
    handler(runner, {})
    log = open(_log_path(runner, "feedbacktest")).read()
    assert "specific feedback message" in log


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------


def test_label_defaults_to_handler_name(runner_factory):
    """When no label is given, __name__ and the log filename use the handler's name."""
    def my_named_handler(runner, state):
        return dict(state)

    handler = ralph(my_named_handler, validator=_always_pass)
    assert handler.__name__ == "my_named_handler"
    runner, channel = runner_factory()
    handler(runner, {})
    assert os.path.exists(_log_path(runner, "my_named_handler"))


def test_explicit_label(runner_factory):
    """An explicit label is used for __name__ and the log filename."""
    handler = ralph(_identity, validator=_always_pass, label="explicit-label")
    assert handler.__name__ == "explicit-label"
    runner, channel = runner_factory()
    handler(runner, {})
    assert os.path.exists(_log_path(runner, "explicit-label"))


# ---------------------------------------------------------------------------
# Bash validator
# ---------------------------------------------------------------------------


def _make_script(tmp_path, content):
    """Write an executable bash script with the given content to ``tmp_path``."""
    script = tmp_path / "validate.sh"
    script.write_text(content)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_bash_validator_success(runner_factory, tmp_path):
    """A bash validator script that outputs success=true causes the handler to pass."""
    script = _make_script(tmp_path, '#!/bin/bash\necho \'{"success": true, "feedback": ""}\'')
    handler = ralph(_identity, validator=script, label="bash-success")
    runner, channel = runner_factory()
    result = handler(runner, {"prompt": "hi"})
    assert result == {"prompt": "hi"}


def test_bash_validator_failure(runner_factory, tmp_path):
    """A bash validator script that always outputs success=false exhausts retries and raises."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return dict(state)

    script = _make_script(tmp_path, '#!/bin/bash\necho \'{"success": false, "feedback": "bad"}\'')
    handler = ralph(_count, validator=script, max_retries=1, label="bash-fail")
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        handler(runner, {})
    assert call_count["n"] == 2


def test_bash_validator_error_propagates(runner_factory, tmp_path):
    """A bash validator script that exits non-zero raises RuntimeError immediately."""
    script = _make_script(tmp_path, '#!/bin/bash\nexit 1')
    handler = ralph(_identity, validator=script, label="bash-err")
    runner, channel = runner_factory()
    with pytest.raises(RuntimeError):
        handler(runner, {})


# ---------------------------------------------------------------------------
# Learnings file
# ---------------------------------------------------------------------------


def test_learnings_file_written_on_failure(runner_factory, tmp_path):
    """Learnings file is created with labelled heading on validation failure."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return {**state, "n": call_count["n"]}

    def _fail_then_pass(state):
        if state.get("n", 0) >= 2:
            return ValidationResult(success=True, feedback="")
        return ValidationResult(success=False, feedback="specific failure feedback")

    handler = ralph(
        _count,
        validator=_fail_then_pass,
        label="test-learn",
        learnings_file="$dir/learnings.md",
    )
    runner, channel = runner_factory()
    handler(runner, {"dir": str(tmp_path)})

    lf = tmp_path / "learnings.md"
    assert lf.exists()
    content = lf.read_text()
    assert "## test-learn" in content
    assert "Attempt 1/" in content
    assert "specific failure feedback" in content
    assert "---" in content


def test_learnings_file_not_written_on_success(runner_factory, tmp_path):
    """Learnings file is not created when validator passes on first attempt."""
    handler = ralph(
        _identity,
        validator=_always_pass,
        learnings_file="$dir/learnings.md",
    )
    runner, channel = runner_factory()
    handler(runner, {"dir": str(tmp_path)})
    assert not (tmp_path / "learnings.md").exists()


def test_learnings_file_appends_multiple_failures(runner_factory, tmp_path):
    """Multiple failures append multiple labelled entries to the learnings file."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return {**state, "n": call_count["n"]}

    def _fail_twice_then_pass(state):
        if state.get("n", 0) >= 3:
            return ValidationResult(success=True, feedback="")
        return ValidationResult(success=False, feedback=f"failure {state.get('n')}")

    handler = ralph(
        _count,
        validator=_fail_twice_then_pass,
        max_retries=2,
        label="multi-fail",
        learnings_file="$dir/learnings.md",
    )
    runner, channel = runner_factory()
    handler(runner, {"dir": str(tmp_path)})

    content = (tmp_path / "learnings.md").read_text()
    assert "Attempt 1/" in content
    assert "Attempt 2/" in content


def test_learnings_file_variable_interpolation(runner_factory, tmp_path):
    """Learnings file path interpolates multiple $vars from state."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return {**state, "n": call_count["n"], "base": state["base"], "slug": state["slug"]}

    def _fail_then_pass(state):
        if state.get("n", 0) >= 2:
            return ValidationResult(success=True, feedback="")
        return ValidationResult(success=False, feedback="retry needed")

    handler = ralph(
        _count,
        validator=_fail_then_pass,
        learnings_file="$base/work/$slug/learnings.md",
    )
    runner, channel = runner_factory()
    handler(runner, {"base": str(tmp_path), "slug": "my-run"})

    expected = tmp_path / "work" / "my-run" / "learnings.md"
    assert expected.exists()


def test_learnings_file_none_default(runner_factory, tmp_path):
    """No learnings file is created when learnings_file is omitted."""
    call_count = {"n": 0}

    def _count(runner, state):
        call_count["n"] += 1
        return {**state, "n": call_count["n"]}

    def _fail_then_pass(state):
        if state.get("n", 0) >= 2:
            return ValidationResult(success=True, feedback="")
        return ValidationResult(success=False, feedback="no learnings file")

    handler = ralph(_count, validator=_fail_then_pass)
    runner, channel = runner_factory()
    handler(runner, {})

    md_files = list(tmp_path.glob("**/*.md"))
    assert md_files == []


def test_learnings_file_written_on_exhaustion(runner_factory, tmp_path):
    """Learnings entries are written for all failed attempts before WorkflowFailedError."""
    handler = ralph(
        _identity,
        validator=_always_fail,
        max_retries=1,
        label="exhaust-test",
        learnings_file="$dir/learnings.md",
    )
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        handler(runner, {"dir": str(tmp_path)})

    content = (tmp_path / "learnings.md").read_text()
    assert "Attempt 1/" in content
    assert "Attempt 2/" in content


def test_success_returns_result_state_directly(runner_factory):
    """Returned state is exactly what the handler produced — no prompt restoration."""
    handler = ralph(_add_result, validator=_always_pass)
    runner, channel = runner_factory()
    result = handler(runner, {})
    assert result["result"] == "ok"
