"""Tests for ClaudeCodeAgent.

Unit tests covering subprocess delegation, model flag handling,
and error propagation.
"""

import logging
import subprocess
from unittest.mock import patch

import pytest

from antkeeper.core.domain import State
from antkeeper.llm.claude_code import ClaudeCodeAgent
from antkeeper.llm.errors import AgentExecutionError

ENVELOPE = '{"session_id": "test-session", "result": "ok", "duration_ms": 100, "usage": {}, "total_cost_usd": 0.0}'


class TestClaudeCodeAgent:
    """Test suite for ClaudeCodeAgent subprocess delegation and error handling."""

    def test_successful_prompt_returns_stdout(self):
        """Test that successful subprocess execution returns the result from the envelope."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"session_id": "s1", "result": "answer", "duration_ms": 100, "usage": {}, "total_cost_usd": 0.0}',
                stderr=""
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
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
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
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
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
                args=[], returncode=0,
                stdout='{"session_id": "s1", "result": "", "duration_ms": 100, "usage": {}, "total_cost_usd": 0.0}',
                stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("")
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--output-format", "json", "-p", ""]

    def test_yolo_adds_permissions_flag(self):
        """Test that yolo=True adds --dangerously-skip-permissions to command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
            )
            agent = ClaudeCodeAgent(yolo=True)
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert "--dangerously-skip-permissions" in call_args

    def test_opts_passed_to_command(self):
        """Test that opts are included in the subprocess command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
            )
            agent = ClaudeCodeAgent(opts=["--verbose"])
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--output-format", "json", "--verbose", "-p", "hello"]

    def test_opts_override_convenience_params(self):
        """Test that opts take precedence over convenience params."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
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
                "--output-format",
                "json",
                "--model",
                "opus",
                "--dangerously-skip-permissions",
                "-p",
                "hello",
            ]

    def test_output_format_json_added_to_command(self):
        """Test that --output-format json is automatically added to the command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            idx = call_args.index("--output-format")
            assert call_args[idx + 1] == "json"

    def test_output_format_not_duplicated_when_in_opts(self):
        """Test that --output-format is not duplicated when already in opts."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
            )
            agent = ClaudeCodeAgent(opts=["--output-format", "json"])
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert call_args.count("--output-format") == 1

    def test_output_format_startswith_guard(self):
        """Test that --output-format=stream (equals form) suppresses automatic flag."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=ENVELOPE, stderr=""
            )
            agent = ClaudeCodeAgent(opts=["--output-format=stream"])
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            count = sum(1 for a in call_args if a.startswith("--output-format"))
            assert count == 1

    def test_result_extracted_from_envelope(self):
        """Test that prompt() returns the result field from the JSON envelope."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"session_id": "s1", "result": "the answer", "duration_ms": 100, "usage": {}, "total_cost_usd": 0.0}',
                stderr=""
            )
            agent = ClaudeCodeAgent()
            assert agent.prompt("hello") == "the answer"

    def test_invalid_json_raises_value_error(self):
        """Test that invalid JSON stdout raises ValueError."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="not valid json", stderr=""
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(ValueError):
                agent.prompt("hello")

    def test_missing_result_key_raises_value_error(self):
        """Test that a valid JSON envelope without 'result' key raises ValueError."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"session_id": "s1"}', stderr=""
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(ValueError):
                agent.prompt("hello")

    def test_session_id_logged_at_info(self, caplog):
        """Test that session_id from envelope is logged at INFO level."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"session_id": "abc-123", "result": "ok", "duration_ms": 100, "usage": {}, "total_cost_usd": 0.0}',
                stderr=""
            )
            agent = ClaudeCodeAgent()
            with caplog.at_level(logging.INFO, logger="antkeeper.llm.claude_code"):
                agent.prompt("hello")
            assert any("abc-123" in record.message for record in caplog.records)


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
