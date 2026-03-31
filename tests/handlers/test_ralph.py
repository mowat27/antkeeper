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


def test_original_prompt_restored(runner_factory):
    """Original prompt is restored in state even if the handler modifies it."""
    def _modify_prompt(runner, state):
        return {**state, "prompt": "modified by handler"}

    handler = ralph(_modify_prompt, validator=_always_pass)
    runner, channel = runner_factory()
    result = handler(runner, {"prompt": "original"})
    assert result["prompt"] == "original"


def test_custom_prompt_key(runner_factory):
    """A non-default ``prompt_key`` is restored correctly after a successful run."""
    def _modify_instruction(runner, state):
        return {**state, "instruction": "modified"}

    handler = ralph(_modify_instruction, validator=_always_pass, prompt_key="instruction")
    runner, channel = runner_factory()
    result = handler(runner, {"instruction": "original instruction"})
    assert result["instruction"] == "original instruction"


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


def test_retry_prompt_augmented(runner_factory):
    """On retry the prompt is augmented with prior-attempts context from the log."""
    seen_prompts = []

    def _capture(runner, state):
        seen_prompts.append(state.get("prompt"))
        return {**state, "n": len(seen_prompts)}

    def _fail_first(state):
        if state.get("n", 0) >= 2:
            return ValidationResult(success=True, feedback="")
        return ValidationResult(success=False, feedback="need more tries")

    handler = ralph(_capture, validator=_fail_first, label="augtest")
    runner, channel = runner_factory()
    handler(runner, {"prompt": "original prompt"})
    assert seen_prompts[0] == "original prompt"
    assert "prior_attempts" in seen_prompts[1]
    assert "original prompt" in seen_prompts[1]


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
