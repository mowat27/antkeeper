"""Tests for the run_prompt convenience function."""

import logging
from unittest.mock import MagicMock, patch

from antkeeper.llm.claude_code import run_prompt


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_returns_response(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent.prompt.return_value = "hello"
    mock_agent_cls.return_value = mock_agent

    result = run_prompt("test", logging.getLogger("test"))
    assert result == "hello"


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_passes_model_to_agent(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    run_prompt("test", logging.getLogger("test"), model="opus")
    mock_agent_cls.assert_called_once_with(model="opus", yolo=True)


@patch("antkeeper.llm.claude_code.ClaudeCodeAgent")
def test_run_prompt_uses_yolo_true(mock_agent_cls):
    mock_agent = MagicMock()
    mock_agent_cls.return_value = mock_agent

    run_prompt("test", logging.getLogger("test"))
    mock_agent_cls.assert_called_once_with(model=None, yolo=True)
