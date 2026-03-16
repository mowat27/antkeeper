"""Tests for ClaudeCodeAgent.

Unit tests covering subprocess delegation, model flag handling,
and error propagation.
"""

import subprocess
from unittest.mock import patch

import pytest

from antkeeper.core.domain import State
from antkeeper.llm.claude_code import ClaudeCodeAgent
from antkeeper.llm.errors import AgentExecutionError


class TestClaudeCodeAgent:
    """Test suite for ClaudeCodeAgent subprocess delegation and error handling."""

    def test_successful_prompt_returns_stdout(self):
        """Test that successful subprocess execution returns stdout."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="answer", stderr=""
            )
            agent = ClaudeCodeAgent()
            assert agent.prompt("hello") == "answer"

    def test_failed_prompt_raises_agent_execution_error(self):
        """Test that non-zero exit code raises AgentExecutionError."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="boom"
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                agent.prompt("hello")

    def test_model_passed_to_subprocess(self):
        """Test that model flag is included in subprocess args when set."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            agent = ClaudeCodeAgent(model="opus")
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert "--model" in call_args
            assert "opus" in call_args

    def test_no_model_omits_flag(self):
        """Test that model flag is omitted when model is None."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert "--model" not in call_args

    def test_missing_binary_raises_agent_execution_error(self):
        """Test that FileNotFoundError from subprocess is wrapped in AgentExecutionError."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("claude")
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError, match="claude binary not found"):
                agent.prompt("hello")

    def test_empty_prompt_passed_through(self):
        """Test that empty string prompt is passed to subprocess as-is."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("")
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "-p", ""]

    def test_yolo_adds_permissions_flag(self):
        """Test that yolo=True adds --dangerously-skip-permissions to command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            agent = ClaudeCodeAgent(yolo=True)
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert "--dangerously-skip-permissions" in call_args

    def test_opts_passed_to_command(self):
        """Test that opts are included in the subprocess command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            agent = ClaudeCodeAgent(opts=["--verbose"])
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--verbose", "-p", "hello"]

    def test_opts_override_convenience_params(self):
        """Test that opts take precedence over convenience params."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            agent = ClaudeCodeAgent(
                model="sonnet",
                yolo=True,
                opts=["--model", "opus", "--dangerously-skip-permissions"],
            )
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert call_args == [
                "claude",
                "--model",
                "opus",
                "--dangerously-skip-permissions",
                "-p",
                "hello",
            ]


class TestIntegration:
    """Integration tests for agent execution within the framework."""

    def test_handler_using_mock_agent_in_runner(self, app, runner_factory):
        """Test full pipeline with a fake agent (no subprocess)."""

        @app.handler
        def ask(runner, state: State) -> State:
            class FakeAgent:
                def prompt(self, prompt: str) -> str:
                    return "canned"
            agent = FakeAgent()
            return {**state, "result": agent.prompt(state["prompt"])}

        runner, _source = runner_factory(app, "ask", {"prompt": "hi"})
        result = runner.run()
        assert result["result"] == "canned"

    def test_agent_execution_error_propagates(self, app, runner_factory):
        """Test that AgentExecutionError propagates through the runner."""

        @app.handler
        def fail_agent(runner, state: State) -> State:
            raise AgentExecutionError("broken")

        runner, _source = runner_factory(app, "fail_agent", {})
        with pytest.raises(AgentExecutionError, match="broken"):
            runner.run()
