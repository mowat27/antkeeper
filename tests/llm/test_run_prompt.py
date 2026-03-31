"""Tests for the run_prompt convenience function.

Verifies that run_prompt() correctly delegates to ClaudeCodeAgent, passes
through model and yolo arguments, and returns an iterator of StreamEvents.
"""

import logging
from unittest.mock import MagicMock, patch

from antkeeper.core.domain import StreamEvent
from antkeeper.llm.claude_code import run_prompt


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
