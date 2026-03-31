"""Tests for the run_prompt convenience function and collect_result utility.

Verifies that run_prompt() correctly delegates to ClaudeCodeAgent, passes
through model and yolo arguments, and returns an iterator of StreamEvents.
Also tests collect_result() for consuming event streams.
"""

import logging
from unittest.mock import MagicMock, patch

from antkeeper.core.domain import StreamEvent
from antkeeper.llm.claude_code import collect_result, run_prompt


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_returns_iterator(mock_agent_cls):
    """run_prompt() returns the iterator from the agent."""
    events = [StreamEvent(type="result", content="hello")]
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = iter(events)
    mock_agent_cls.return_value = mock_agent

    result = list(run_prompt("test", logging.getLogger("test")))
    assert len(result) == 1
    assert result[0].content == "hello"


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_passes_model_to_agent(mock_agent_cls):
    """run_prompt() passes the model argument to ClaudeCodeAgent."""
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = iter([])
    mock_agent_cls.return_value = mock_agent

    list(run_prompt("test", logging.getLogger("test"), model="opus"))
    mock_agent_cls.assert_called_once_with(model="opus", yolo=True, opts=None)


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_uses_yolo_true(mock_agent_cls):
    """run_prompt() always creates the agent with yolo=True."""
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = iter([])
    mock_agent_cls.return_value = mock_agent

    list(run_prompt("test", logging.getLogger("test")))
    mock_agent_cls.assert_called_once_with(model=None, yolo=True, opts=None)


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_passes_opts_to_agent(mock_agent_cls):
    """run_prompt() forwards opts to ClaudeCodeAgent."""
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = iter([])
    mock_agent_cls.return_value = mock_agent

    list(run_prompt("test", logging.getLogger("test"), opts=["--max-turns", "1"]))
    mock_agent_cls.assert_called_once_with(
        model=None, yolo=True, opts=["--max-turns", "1"]
    )


class TestCollectResult:
    """Tests for the collect_result() utility."""

    def test_collect_result_returns_text_and_events(self):
        """Consumes stream, returns (text, events)."""
        events = [
            StreamEvent(type="assistant", content="thinking"),
            StreamEvent(type="result", content="the answer"),
        ]
        text, all_events = collect_result(iter(events))
        assert text == "the answer"
        assert len(all_events) == 2

    def test_collect_result_empty_stream(self):
        """Returns ('', []) for empty stream."""
        text, all_events = collect_result(iter([]))
        assert text == ""
        assert all_events == []

    def test_collect_result_ignores_internal_result(self):
        """Only non-internal result used as text."""
        events = [
            StreamEvent(type="result", content="primary"),
            StreamEvent(type="result", content="extraction", internal=True),
        ]
        text, all_events = collect_result(iter(events))
        assert text == "primary"
        assert len(all_events) == 2

    def test_collect_result_last_non_internal_result_wins(self):
        """Multiple result events: last non-internal result is used."""
        events = [
            StreamEvent(type="result", content="first"),
            StreamEvent(type="result", content="second"),
        ]
        text, _ = collect_result(iter(events))
        assert text == "second"
