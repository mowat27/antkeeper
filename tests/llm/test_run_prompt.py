"""Tests for the run_prompt convenience function.

Verifies that run_prompt() correctly delegates to ClaudeCodeAgent, passes
through model and yolo arguments, and returns the agent's response.
"""

import logging
from unittest.mock import MagicMock, patch

from antkeeper.llm.claude_code import run_prompt


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_returns_response(mock_agent_cls):
    """Test that run_prompt() returns the response from the agent."""
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = "hello"
    mock_agent_cls.return_value = mock_agent

    result = run_prompt("test", logging.getLogger("test"))
    assert result == "hello"


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_passes_model_to_agent(mock_agent_cls):
    """Test that run_prompt() passes the model argument to ClaudeCodeAgent."""
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    run_prompt("test", logging.getLogger("test"), model="opus")
    mock_agent_cls.assert_called_once_with(model="opus", yolo=True)


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_uses_yolo_true(mock_agent_cls):
    """Test that run_prompt() always creates the agent with yolo=True."""
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    run_prompt("test", logging.getLogger("test"))
    mock_agent_cls.assert_called_once_with(model=None, yolo=True)
