"""Tests for the cc_handler factory.

Covers:
    - Construction-time validation (ValueError when args are wrong).
    - Handler ``__name__`` / label derivation.
    - Simple mode: state updates, command interpolation, and progress messages.
    - JSON mode: prompt wrapping, field extraction, and progress messages.
    - Error handling: AgentExecutionError, bad JSON, missing state keys, and
      missing JSON fields all cause runner.fail() / WorkflowFailedError.
    - Edge cases: no placeholders, multiple placeholders, empty updates, single
      JSON field.
"""

from unittest.mock import patch

import pytest

from antkeeper.core.domain import WorkflowFailedError
from antkeeper.handlers.claude_code.factories import cc_handler
from antkeeper.llm.errors import AgentExecutionError


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_raises_when_both_updates_and_json_fields_provided():
    """cc_handler raises ValueError when both updates and json_fields are given."""
    with pytest.raises(ValueError, match="exactly one"):
        cc_handler("/cmd", updates={"a": 1}, json_fields=["a"])


def test_raises_when_neither_updates_nor_json_fields_provided():
    """cc_handler raises ValueError when neither updates nor json_fields are given."""
    with pytest.raises(ValueError, match="exactly one"):
        cc_handler("/cmd")


# ---------------------------------------------------------------------------
# Label / __name__
# ---------------------------------------------------------------------------


def test_default_label_strips_leading_slash():
    """Default label removes the leading slash from the first command token."""
    h = cc_handler("/commit arg", updates={"done": True})
    assert h.__name__ == "commit"


def test_default_label_first_token():
    """Default label is the first whitespace-delimited token of the command."""
    h = cc_handler("do_stuff arg1", updates={"done": True})
    assert h.__name__ == "do_stuff"


def test_custom_label_overrides_default():
    """Explicitly supplied label is used as the handler __name__."""
    h = cc_handler("/foo bar", updates={"done": True}, label="my_label")
    assert h.__name__ == "my_label"


# ---------------------------------------------------------------------------
# Simple mode
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_simple_mode_merges_updates_into_state(mock_rp, runner_factory):
    """Simple mode merges the static updates dict into the returned state."""
    h = cc_handler("/cmd", updates={"status": "done"})
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1, "status": "done"}


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_simple_mode_interpolates_command_with_state(mock_rp, runner_factory):
    """Simple mode interpolates {placeholder} tokens in the command from state."""
    h = cc_handler("/implement {spec_file}", updates={"done": True})
    runner, channel = runner_factory()
    h(runner, {"spec_file": "specs/foo.md"})
    mock_rp.assert_called_once_with("/implement specs/foo.md", runner.logger, model=None)


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_simple_mode_reports_progress(mock_rp, runner_factory):
    """Simple mode emits 'Running <label>' and '<label> complete' progress messages."""
    h = cc_handler("/implement {spec_file}", updates={"done": True})
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    assert "Running implement" in channel.progress_messages
    assert "implement complete" in channel.progress_messages


# ---------------------------------------------------------------------------
# JSON mode
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo", "extra": "ignored"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{"spec_file":"s.md","slug":"foo"}')
def test_json_mode_extracts_only_named_fields(mock_rp, mock_ej, runner_factory):
    """JSON mode only merges fields listed in json_fields; extra fields are dropped."""
    h = cc_handler("/specify {prompt}", json_fields=["spec_file", "slug"])
    runner, channel = runner_factory()
    result = h(runner, {"prompt": "build something"})
    assert "spec_file" in result
    assert "slug" in result
    assert "extra" not in result


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_json_mode_wraps_prompt_with_json_prompt(mock_rp, mock_ej, runner_factory):
    """JSON mode passes the command through json_prompt, appending JSON instructions."""
    h = cc_handler("/specify {prompt}", json_fields=["spec_file", "slug"])
    runner, channel = runner_factory()
    h(runner, {"prompt": "build it"})
    call_args = mock_rp.call_args[0][0]
    assert "JSON" in call_args  # json_prompt appends JSON instructions


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"branch_name": "feat/x"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_json_mode_reports_progress(mock_rp, mock_ej, runner_factory):
    """JSON mode emits 'Running <label>' and '<label> complete' progress messages."""
    h = cc_handler("/branch {spec_file}", json_fields=["branch_name"], label="branch_if_on_main")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    assert "Running branch_if_on_main" in channel.progress_messages
    assert "branch_if_on_main complete" in channel.progress_messages


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.run_prompt", side_effect=AgentExecutionError("boom"))
def test_agent_execution_error_calls_runner_fail(mock_rp, runner_factory):
    """AgentExecutionError from run_prompt causes runner.fail(), raising WorkflowFailedError."""
    h = cc_handler("/cmd", updates={"done": True})
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='not json')
@patch("antkeeper.handlers.claude_code.factories.extract_json", side_effect=ValueError("bad json"))
def test_bad_json_calls_runner_fail(mock_rp, mock_ej, runner_factory):
    """ValueError from extract_json (unparseable response) causes WorkflowFailedError."""
    h = cc_handler("/cmd", json_fields=["x"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_missing_state_key_calls_runner_fail(mock_rp, runner_factory):
    """A {placeholder} absent from state raises WorkflowFailedError via runner.fail()."""
    h = cc_handler("/cmd {missing}", updates={"done": True})
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_command_with_no_placeholders_succeeds(mock_rp, runner_factory):
    """A command with no placeholders runs and returns the merged state unchanged."""
    h = cc_handler("/commit", updates={"committed": True})
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1, "committed": True}


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_command_with_multiple_placeholders(mock_rp, runner_factory):
    """Multiple {placeholder} tokens are all interpolated from state correctly."""
    h = cc_handler("/cmd {a} {b}", updates={"done": True})
    runner, channel = runner_factory()
    h(runner, {"a": "1", "b": "2"})
    mock_rp.assert_called_once_with("/cmd 1 2", runner.logger, model=None)


@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value="ok")
def test_empty_updates_merges_nothing(mock_rp, runner_factory):
    """An empty updates dict leaves the state dict unchanged (only existing keys remain)."""
    h = cc_handler("/cmd", updates={})
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"result": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_single_json_field(mock_rp, mock_ej, runner_factory):
    """JSON mode with a single requested field extracts and merges it into state."""
    h = cc_handler("/cmd", json_fields=["result"])
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1, "result": "val"}


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"other": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt", return_value='{}')
def test_missing_field_in_json_response_calls_runner_fail(mock_rp, mock_ej, runner_factory):
    """A json_field absent from the parsed response causes WorkflowFailedError."""
    h = cc_handler("/cmd", json_fields=["expected"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})
