"""Tests for the cc_handler factory.

Covers:
    - Handler ``__name__`` / label derivation.
    - state_updates mode: streaming pipeline with extraction middleware.
    - Fire-and-forget mode (no state_updates): runs command, returns state unchanged.
    - $var interpolation from state.
    - Model override: per-handler ``model`` argument takes precedence over the
      state model; absence of override falls back to ``state["model"]``.
    - Error handling: AgentExecutionError, bad JSON, missing state keys, and
      missing JSON fields all cause runner.fail() / WorkflowFailedError.
    - Edge cases: no placeholders, multiple placeholders, empty list, ${var} literal.
    - Handler-level env: per-handler environment variable overrides.
    - Events forwarded to channel during handler execution.
    - opts parameter: extra CLI flags forwarded verbatim to ClaudeCodeAgent;
      defaults to None; not passed to the extraction step.
    - yolo parameter: controls --dangerously-skip-permissions; defaults to True
      for backward compatibility; False is forwarded correctly.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from antkeeper.core.domain import StreamEvent, WorkflowFailedError
from antkeeper.handlers.claude_code.factories import cc_handler
from antkeeper.llm.errors import AgentExecutionError


def _mock_agent_prompt(events: list[StreamEvent]):
    """Return a mock ClaudeCodeAgent whose prompt() yields the given events."""
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = iter(events)
    return mock_agent


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
# state_updates mode (streaming extraction)
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo", "extra": "ignored"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_state_updates_extracts_only_named_fields(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """state_updates mode only merges fields listed in state_updates; extra fields are dropped."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="raw response"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content='{"spec_file":"s.md","slug":"foo"}'),
    ])

    h = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
    runner, channel = runner_factory()
    result = h(runner, {"prompt": "build something"})
    assert "spec_file" in result
    assert "slug" in result
    assert "extra" not in result


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"spec_file": "s.md", "slug": "foo"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_state_updates_uses_two_step_extraction(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """state_updates mode streams primary prompt, then triggers extraction via middleware."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="work output"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content='{"spec_file":"s.md","slug":"foo"}'),
    ])

    h = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
    runner, channel = runner_factory()
    h(runner, {"prompt": "build it"})

    # Primary agent called via ClaudeCodeAgent, extraction via run_prompt
    mock_agent_cls.return_value.prompt.assert_called_once()
    mock_rp.assert_called_once()
    # Extraction uses haiku
    assert mock_rp.call_args[1]["model"] == "haiku"


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"branch_name": "feat/x"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_state_updates_reports_progress(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """state_updates mode emits 'Running <label>' and '<label> complete' progress messages."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="raw output"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content='{}'),
    ])

    h = cc_handler("/branch $spec_file", state_updates=["branch_name"], label="branch_if_on_main")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    assert "Running branch_if_on_main" in channel.progress_messages
    assert "branch_if_on_main complete" in channel.progress_messages


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"result": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_single_state_update_field(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """state_updates with a single field extracts and merges it into state."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="raw output"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content='{}'),
    ])

    h = cc_handler("/cmd", state_updates=["result"])
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1, "result": "val"}


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"x": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_extraction_always_uses_haiku(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """Extraction step always uses 'haiku' even when handler has a different model."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="raw output"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content='{}'),
    ])

    h = cc_handler("/cmd", state_updates=["x"], model="opus")
    runner, channel = runner_factory()
    h(runner, {})
    # Primary agent uses opus
    mock_agent_cls.assert_called_once_with(model="opus", yolo=True, opts=None)
    # Extraction uses haiku
    assert mock_rp.call_args[1]["model"] == "haiku"


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_step1_failure_skips_extraction(mock_agent_cls, runner_factory):
    """Step 1 failure routes through runner.fail() without extraction."""
    mock_agent_cls.return_value.prompt.side_effect = AgentExecutionError("boom")

    h = cc_handler("/cmd", state_updates=["x"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.run_prompt", side_effect=AgentExecutionError("boom"))
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_step2_failure_calls_runner_fail(mock_agent_cls, mock_rp, runner_factory):
    """Step 2 (extraction) failure causes WorkflowFailedError."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="good response"),
    ])

    h = cc_handler("/cmd", state_updates=["x"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


# ---------------------------------------------------------------------------
# Fire-and-forget mode (no state_updates)
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_fire_and_forget_returns_state_unchanged(mock_agent_cls, runner_factory):
    """Fire-and-forget mode runs command and returns state unchanged."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_fire_and_forget_consumes_stream(mock_agent_cls, runner_factory):
    """Fire-and-forget mode consumes the full stream."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="assistant", content="thinking"),
        StreamEvent(type="result", content="done"),
    ])

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    h(runner, {})
    # Both events forwarded to channel
    assert len(channel.events) >= 2


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_empty_list_state_updates_is_fire_and_forget(mock_agent_cls, runner_factory):
    """state_updates=[] behaves the same as None (fire-and-forget)."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", state_updates=[])
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_fire_and_forget_reports_progress(mock_agent_cls, runner_factory):
    """Fire-and-forget mode emits progress messages."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/implement $spec_file")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    assert "Running implement" in channel.progress_messages
    assert "implement complete" in channel.progress_messages


# ---------------------------------------------------------------------------
# Events forwarded to channel
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_events_forwarded_to_channel(mock_agent_cls, runner_factory):
    """Channel receives events during handler execution."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="assistant", content="thinking"),
        StreamEvent(type="result", content="done"),
    ])

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    h(runner, {})
    event_types = [e.type for e in channel.events]
    assert "assistant" in event_types
    assert "result" in event_types


# ---------------------------------------------------------------------------
# $var interpolation
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_dollar_var_interpolation(mock_agent_cls, runner_factory):
    """$var placeholders are interpolated from state."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/implement $spec_file")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "specs/foo.md"})
    call_args = mock_agent_cls.return_value.prompt.call_args[0][0]
    assert call_args == "/implement specs/foo.md"


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_multiple_dollar_var_placeholders(mock_agent_cls, runner_factory):
    """Multiple $var tokens are all interpolated from state correctly."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd $a $b")
    runner, channel = runner_factory()
    h(runner, {"a": "1", "b": "2"})
    call_args = mock_agent_cls.return_value.prompt.call_args[0][0]
    assert call_args == "/cmd 1 2"


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_no_dollar_vars_passes_through_unchanged(mock_agent_cls, runner_factory):
    """A command with no $ placeholders passes through unchanged."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/commit")
    runner, channel = runner_factory()
    h(runner, {"x": 1})
    call_args = mock_agent_cls.return_value.prompt.call_args[0][0]
    assert call_args == "/commit"


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_dollar_var_non_string_converted(mock_agent_cls, runner_factory):
    """$var where value is non-string is converted via str()."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd $count")
    runner, channel = runner_factory()
    h(runner, {"count": 42})
    call_args = mock_agent_cls.return_value.prompt.call_args[0][0]
    assert call_args == "/cmd 42"


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_dollar_brace_var_not_interpolated(mock_agent_cls, runner_factory):
    """${var} is NOT interpolated — left as literal text."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd ${spec_file}")
    runner, channel = runner_factory()
    h(runner, {"spec_file": "s.md"})
    call_args = mock_agent_cls.return_value.prompt.call_args[0][0]
    assert call_args == "/cmd ${spec_file}"


# ---------------------------------------------------------------------------
# model override
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_model_override_passed_to_agent(mock_agent_cls, runner_factory):
    """Factory model override is passed to ClaudeCodeAgent."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", model="claude-opus-4")
    runner, channel = runner_factory()
    h(runner, {})
    mock_agent_cls.assert_called_once_with(model="claude-opus-4", yolo=True, opts=None)


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_model_override_beats_state_model(mock_agent_cls, runner_factory):
    """Factory model override takes precedence over state model."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", model="claude-opus-4")
    runner, channel = runner_factory()
    h(runner, {"model": "claude-sonnet-4"})
    mock_agent_cls.assert_called_once_with(model="claude-opus-4", yolo=True, opts=None)


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_no_model_override_falls_back_to_state(mock_agent_cls, runner_factory):
    """When no factory model override, state model is used."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    h(runner, {"model": "claude-sonnet-4"})
    mock_agent_cls.assert_called_once_with(model="claude-sonnet-4", yolo=True, opts=None)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_agent_execution_error_calls_runner_fail(mock_agent_cls, runner_factory):
    """AgentExecutionError from stream causes runner.fail(), raising WorkflowFailedError."""
    mock_agent_cls.return_value.prompt.side_effect = AgentExecutionError("boom")

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.extract_json", side_effect=ValueError("bad json"))
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_bad_json_calls_runner_fail(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """ValueError from extract_json (unparseable response) causes WorkflowFailedError."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="raw output"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content="not json"),
    ])

    h = cc_handler("/cmd", state_updates=["x"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_missing_state_key_calls_runner_fail(mock_agent_cls, runner_factory):
    """A $placeholder absent from state raises WorkflowFailedError via runner.fail()."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd $missing")
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"other": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_missing_field_in_json_response_calls_runner_fail(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """A state_updates field absent from the parsed response causes WorkflowFailedError."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="raw output"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content='{}'),
    ])

    h = cc_handler("/cmd", state_updates=["expected"])
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


# ---------------------------------------------------------------------------
# Generator cleanup on error
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_generator_cleanup_on_error(mock_agent_cls, runner_factory):
    """Pipeline.close() is called on failure to ensure generator cleanup."""
    def failing_stream(prompt):
        yield StreamEvent(type="assistant", content="start")
        raise AgentExecutionError("mid-stream failure")

    mock_agent_cls.return_value.prompt = failing_stream

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})


# ---------------------------------------------------------------------------
# Handler-level env
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_env_sets_vars_during_handler_execution(mock_agent_cls, runner_factory):
    """Handler env vars are visible in os.environ during execution."""
    captured = {}

    def capture_env(prompt):
        captured["val"] = os.environ.get("_ANTKEEPER_TEST_HF_KEY")
        return iter([StreamEvent(type="result", content="ok")])

    mock_agent_cls.return_value.prompt = capture_env
    h = cc_handler("/cmd", env={"_ANTKEEPER_TEST_HF_KEY": "secret"})
    runner, channel = runner_factory()
    h(runner, {})
    assert captured["val"] == "secret"


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_env_restored_after_handler(mock_agent_cls, runner_factory):
    """Handler env vars are removed from os.environ after execution."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    assert "_ANTKEEPER_TEST_HF_RESTORE" not in os.environ
    h = cc_handler("/cmd", env={"_ANTKEEPER_TEST_HF_RESTORE": "val"})
    runner, channel = runner_factory()
    h(runner, {})
    assert "_ANTKEEPER_TEST_HF_RESTORE" not in os.environ


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_env_restored_after_handler_failure(mock_agent_cls, runner_factory):
    """Handler env vars are cleaned up even when the handler fails."""
    mock_agent_cls.return_value.prompt.side_effect = AgentExecutionError("boom")

    h = cc_handler("/cmd", env={"_ANTKEEPER_TEST_HF_FAIL": "val"})
    runner, channel = runner_factory()
    with pytest.raises(WorkflowFailedError):
        h(runner, {})
    assert "_ANTKEEPER_TEST_HF_FAIL" not in os.environ


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_env_preserves_existing_var(mock_agent_cls, runner_factory):
    """Handler env overrides existing var during execution, restores original after."""
    captured = {}
    os.environ["_ANTKEEPER_TEST_HF_ORIG"] = "original"
    try:
        def capture_env(prompt):
            captured["val"] = os.environ.get("_ANTKEEPER_TEST_HF_ORIG")
            return iter([StreamEvent(type="result", content="ok")])

        mock_agent_cls.return_value.prompt = capture_env
        h = cc_handler("/cmd", env={"_ANTKEEPER_TEST_HF_ORIG": "override"})
        runner, channel = runner_factory()
        h(runner, {})
        assert captured["val"] == "override"
        assert os.environ["_ANTKEEPER_TEST_HF_ORIG"] == "original"
    finally:
        os.environ.pop("_ANTKEEPER_TEST_HF_ORIG", None)


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_env_none_is_noop(mock_agent_cls, runner_factory):
    """env=None is a no-op — handler works identically to no env argument."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", env=None)
    runner, channel = runner_factory()
    result = h(runner, {"x": 1})
    assert result == {"x": 1}


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"x": "v"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_env_active_during_extraction_step(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """Handler env vars are visible during both primary and extraction calls."""
    captured = []

    def capture_primary(prompt):
        captured.append(os.environ.get("_ANTKEEPER_TEST_HF_EXT"))
        return iter([StreamEvent(type="result", content="ok")])

    def capture_extraction(prompt, logger, **kwargs):
        captured.append(os.environ.get("_ANTKEEPER_TEST_HF_EXT"))
        return iter([StreamEvent(type="result", content='{"x": "v"}')])

    mock_agent_cls.return_value.prompt = capture_primary
    mock_rp.side_effect = capture_extraction
    h = cc_handler("/cmd", state_updates=["x"], env={"_ANTKEEPER_TEST_HF_EXT": "val"})
    runner, channel = runner_factory()
    h(runner, {})
    assert captured == ["val", "val"]


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_env_with_multiple_vars(mock_agent_cls, runner_factory):
    """Multiple env vars are all set during execution and all removed after."""
    captured = {}

    def capture_env(prompt):
        captured["a"] = os.environ.get("_ANTKEEPER_TEST_HF_A")
        captured["b"] = os.environ.get("_ANTKEEPER_TEST_HF_B")
        return iter([StreamEvent(type="result", content="ok")])

    mock_agent_cls.return_value.prompt = capture_env
    h = cc_handler("/cmd", env={"_ANTKEEPER_TEST_HF_A": "1", "_ANTKEEPER_TEST_HF_B": "2"})
    runner, channel = runner_factory()
    h(runner, {})
    assert captured == {"a": "1", "b": "2"}
    assert "_ANTKEEPER_TEST_HF_A" not in os.environ
    assert "_ANTKEEPER_TEST_HF_B" not in os.environ


# ---------------------------------------------------------------------------
# opts and yolo parameters
# ---------------------------------------------------------------------------


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_opts_forwarded_to_agent(mock_agent_cls, runner_factory):
    """opts list is forwarded verbatim to ClaudeCodeAgent."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", opts=["--max-turns", "5"])
    runner, channel = runner_factory()
    h(runner, {})
    mock_agent_cls.assert_called_once_with(model=None, yolo=True, opts=["--max-turns", "5"])


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_opts_default_is_none(mock_agent_cls, runner_factory):
    """opts defaults to None when not specified."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    h(runner, {})
    mock_agent_cls.assert_called_once_with(model=None, yolo=True, opts=None)


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_yolo_default_is_true(mock_agent_cls, runner_factory):
    """yolo defaults to True for backward compatibility."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd")
    runner, channel = runner_factory()
    h(runner, {})
    mock_agent_cls.assert_called_once_with(model=None, yolo=True, opts=None)


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_yolo_false_forwarded_to_agent(mock_agent_cls, runner_factory):
    """yolo=False is forwarded to ClaudeCodeAgent."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", yolo=False)
    runner, channel = runner_factory()
    h(runner, {})
    mock_agent_cls.assert_called_once_with(model=None, yolo=False, opts=None)


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_opts_and_yolo_combined(mock_agent_cls, runner_factory):
    """opts and yolo can be combined and both are forwarded."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", yolo=False, opts=["--verbose"])
    runner, channel = runner_factory()
    h(runner, {})
    mock_agent_cls.assert_called_once_with(model=None, yolo=False, opts=["--verbose"])


@patch("antkeeper.handlers.claude_code.factories.extract_json", return_value={"x": "val"})
@patch("antkeeper.handlers.claude_code.factories.run_prompt")
@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_opts_with_state_updates_mode(mock_agent_cls, mock_rp, mock_ej, runner_factory):
    """In extraction mode, opts is forwarded to primary agent; extraction uses its own hardcoded opts."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="raw output"),
    ])
    mock_rp.return_value = iter([
        StreamEvent(type="result", content="{}"),
    ])

    h = cc_handler("/cmd", state_updates=["x"], opts=["--max-turns", "3"])
    runner, channel = runner_factory()
    h(runner, {})
    # Primary agent gets handler opts
    mock_agent_cls.assert_called_once_with(model=None, yolo=True, opts=["--max-turns", "3"])
    # Extraction uses its own hardcoded opts, not the handler opts
    assert mock_rp.call_args[1]["opts"] == ["--max-turns", "1"]


@patch("antkeeper.handlers.claude_code.factories.ClaudeCodeAgent")
def test_opts_empty_list_forwarded_as_is(mock_agent_cls, runner_factory):
    """opts=[] is forwarded as-is, not converted to None."""
    mock_agent_cls.return_value = _mock_agent_prompt([
        StreamEvent(type="result", content="ok"),
    ])

    h = cc_handler("/cmd", opts=[])
    runner, channel = runner_factory()
    h(runner, {})
    mock_agent_cls.assert_called_once_with(model=None, yolo=True, opts=[])
