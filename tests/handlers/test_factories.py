"""Tests for the cc_handler factory.

Covers:
    - Handler ``__name__`` / label derivation.
    - state_updates mode: prompt wrapping, field extraction, and progress messages.
    - Fire-and-forget mode (no state_updates): runs command, returns state unchanged.
    - $var interpolation from state.
    - Model override: per-handler ``model`` argument takes precedence over the
      state model; absence of override falls back to ``state["model"]``.
    - Error handling: AgentExecutionError, bad JSON, missing state keys, and
      missing JSON fields all cause runner.fail() / WorkflowFailedError.
    - Edge cases: no placeholders, multiple placeholders, empty list, ${var} literal.
"""

from unittest.mock import patch

import pytest

from antkeeper.core.domain import WorkflowFailedError
from antkeeper.handlers.claude_code.factories import cc_handler
from antkeeper.llm.errors import AgentExecutionError


# ---------------------------------------------------------------------------
# Label / __name__
# ---------------------------------------------------------------------------


def test_default_label_strips_leading_slash():
    """Default label removes the leading slash from the first command token."""
    h = cc_handler("/commit arg")
    assert h.__name__ == "commit"


def test_default_label_first_token():
    """Default label is the first whitespace-delimited token of the command."""
    h = cc_handler("do_stuff arg1")
    assert h.__name__ == "do_stuff"


def test_custom_label_overrides_default():
    """Explicitly supplied label is used as the handler __name__."""
    h = cc_handler("/foo bar", label="my_label")
    assert h.__name__ == "my_label"


# ---------------------------------------------------------------------------
# state_updates mode (JSON extraction)
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo", "extra": "ignored"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{"spec_file":"s.md","slug":"foo"}')
def test_state_updates_extracts_only_named_fields(mock_rp, mock_ej, runner_factory):
    """state_updates mode only merges fields listed in state_updates; extra fields are dropped."""
    h = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
    runner, channel = runner_factory()
    result = h(runner, {"prompt": "build something"})
    assert "spec_file" in result
    assert "slug" in result
    assert "extra" not in result


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_state_updates_wraps_prompt_with_json_prompt(mock_rp, mock_ej, runner_factory):
    """state_updates mode passes the command through json_prompt, appending JSON instructions."""
    h = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
    runner, channel = runner_factory()
    h(runner, {"prompt": "build it"})
    call_args = mock_rp.call_args[0][0]
    assert "JSON" in call_args  # json_prompt appends JSON instructions


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"branch_name": "feat/x"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_state_updates_reports_progress(mock_rp, mock_ej, runner_factory):
    """state_updates mode emits 'Running <label>' and '<label> complete' progress messages."""
    h = cc_handler("/branch $spec_file", state_updates=["branch_name"], label="branch_if_on_main")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    assert "Running branch_if_on_main" in channel.progress_messages
    assert "branch_if_on_main complete" in channel.progress_messages


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"result": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_single_state_update_field(mock_rp, mock_ej, runner_factory):
    """state_updates with a single field extracts and merges it into state."""
    h = cc_handler("/cmd", state_updates=["result"])
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1, "result": "val"}


# ---------------------------------------------------------------------------
# Fire-and-forget mode (no state_updates)
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_fire_and_forget_returns_state_unchanged(mock_rp, runner_factory):
    """Fire-and-forget mode runs command and returns state unchanged."""
    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_empty_list_state_updates_is_fire_and_forget(mock_rp, runner_factory):
    """state_updates=[] behaves the same as None (fire-and-forget)."""
    h = cc_handler("/cmd", state_updates=[])
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_fire_and_forget_reports_progress(mock_rp, runner_factory):
    """Fire-and-forget mode emits progress messages."""
    h = cc_handler("/implement $spec_file")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    assert "Running implement" in channel.progress_messages
    assert "implement complete" in channel.progress_messages


# ---------------------------------------------------------------------------
# $var interpolation
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_dollar_var_interpolation(mock_rp, runner_factory):
    """$var placeholders are interpolated from state."""
    h = cc_handler("/implement $spec_file")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "specs/foo.md"})
    mock_rp.assert_called_once_with("/implement specs/foo.md", runner.logger, model=None)


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_multiple_dollar_var_placeholders(mock_rp, runner_factory):
    """Multiple $var tokens are all interpolated from state correctly."""
    h = cc_handler("/cmd $a $b")
    runner, channel = runner_factory()
    h(runner, {"a": "1", "b": "2"})
    mock_rp.assert_called_once_with("/cmd 1 2", runner.logger, model=None)


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_no_dollar_vars_passes_through_unchanged(mock_rp, runner_factory):
    """A command with no $ placeholders passes through unchanged."""
    h = cc_handler("/commit")
    runner, channel = runner_factory()
    h(runner, {"x": 1})
    mock_rp.assert_called_once_with("/commit", runner.logger, model=None)


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_dollar_var_non_string_converted(mock_rp, runner_factory):
    """$var where value is non-string is converted via str()."""
    h = cc_handler("/cmd $count")
    runner, channel = runner_factory()
    h(runner, {"count": 42})
    mock_rp.assert_called_once_with("/cmd 42", runner.logger, model=None)


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_dollar_brace_var_not_interpolated(mock_rp, runner_factory):
    """${var} is NOT interpolated — left as literal text."""
    h = cc_handler("/cmd ${spec_file}")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    mock_rp.assert_called_once_with("/cmd ${spec_file}", runner.logger, model=None)


# ---------------------------------------------------------------------------
# model override
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_model_override_passed_to_run_prompt(mock_rp, runner_factory):
    """Factory model override is passed to run_prompt when state has no model."""
    h = cc_handler("/cmd", model="claude-opus-4")
    runner, channel = runner_factory()
    h(runner, {})
    mock_rp.assert_called_once_with("/cmd", runner.logger, model="claude-opus-4")


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_model_override_beats_state_model(mock_rp, runner_factory):
    """Factory model override takes precedence over state model."""
    h = cc_handler("/cmd", model="claude-opus-4")
    runner, channel = runner_factory()
    h(runner, {"model": "claude-sonnet-4"})
    mock_rp.assert_called_once_with("/cmd", runner.logger, model="claude-opus-4")


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_no_model_override_falls_back_to_state(mock_rp, runner_factory):
    """When no factory model override, state model is used."""
    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    h(runner, {"model": "claude-sonnet-4"})
    mock_rp.assert_called_once_with("/cmd", runner.logger, model="claude-sonnet-4")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.run_prompt", side_effect=AgentExecutionError("boom"))
def test_agent_execution_error_calls_runner_fail(mock_rp, runner_factory):
    """AgentExecutionError from run_prompt causes runner.fail(), raising WorkflowFailedError."""
    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='not json')
@patch("antkeeper.handlers.claude_code.factories.extract_json", side_effect=ValueError("bad json"))
def test_bad_json_calls_runner_fail(mock_rp, mock_ej, runner_factory):
    """ValueError from extract_json (unparseable response) causes WorkflowFailedError."""
    h = cc_handler("/cmd", state_updates=["x"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_missing_state_key_calls_runner_fail(mock_rp, runner_factory):
    """A $placeholder absent from state raises WorkflowFailedError via runner.fail()."""
    h = cc_handler("/cmd $missing")
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"other": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_missing_field_in_json_response_calls_runner_fail(mock_rp, mock_ej, runner_factory):
    """A state_updates field absent from the parsed response causes WorkflowFailedError."""
    h = cc_handler("/cmd", state_updates=["expected"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})
