"""Tests for ClaudeCodeAgent.

Unit tests covering subprocess delegation, model flag handling,
JSON envelope parsing, telemetry logging, and error propagation.
"""

import json
import logging
import subprocess
from unittest.mock import patch

import pytest

from antkeeper.core.domain import State
from antkeeper.llm.claude_code import ClaudeCodeAgent
from antkeeper.llm.errors import AgentExecutionError


def _envelope(result="ok", session_id="s1", duration_ms=100, usage=None, total_cost_usd=0.0):
    """Build a minimal Claude JSON envelope for use in mocked subprocess responses.

    Args:
        result: Value for the ``result`` field returned by ``agent.prompt()``.
        session_id: Simulated Claude session identifier.
        duration_ms: Simulated wall-clock duration of the CLI call.
        usage: Token usage dict. Defaults to an empty dict when None.
        total_cost_usd: Simulated cost of the call in USD.

    Returns:
        JSON-serialised envelope string suitable for use as ``stdout`` in a
        ``subprocess.CompletedProcess`` mock.
    """
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "result": result,
        "session_id": session_id,
        "duration_ms": duration_ms,
        "usage": usage or {},
        "total_cost_usd": total_cost_usd,
    })


class TestClaudeCodeAgent:
    """Test suite for ClaudeCodeAgent subprocess delegation and error handling."""

    def test_successful_prompt_returns_stdout(self):
        """Test that a successful subprocess execution returns the result field from the JSON envelope."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(result="answer"), stderr=""
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
                args=[], returncode=0, stdout=_envelope(), stderr=""
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
                args=[], returncode=0, stdout=_envelope(), stderr=""
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
                args=[], returncode=0, stdout=_envelope(result=""), stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("")
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--output-format", "json", "-p", ""]

    def test_yolo_adds_permissions_flag(self):
        """Test that yolo=True adds --dangerously-skip-permissions to command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(), stderr=""
            )
            agent = ClaudeCodeAgent(yolo=True)
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert "--dangerously-skip-permissions" in call_args

    def test_opts_passed_to_command(self):
        """Test that opts are included in the subprocess command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(), stderr=""
            )
            agent = ClaudeCodeAgent(opts=["--verbose"])
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert call_args == ["claude", "--output-format", "json", "--verbose", "-p", "hello"]

    def test_opts_override_convenience_params(self):
        """Test that opts take precedence over convenience params."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(), stderr=""
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


class TestJsonOutputMode:
    """Tests for JSON output mode, envelope parsing, and telemetry logging."""

    def test_output_format_json_flag_always_present(self):
        """Test that --output-format json is always added to the command."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(), stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            idx = call_args.index("--output-format")
            assert call_args[idx + 1] == "json"

    def test_output_format_not_duplicated_when_in_opts(self):
        """Test that --output-format is not duplicated when provided in opts."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(), stderr=""
            )
            agent = ClaudeCodeAgent(opts=["--output-format", "json"])
            agent.prompt("hello")
            call_args = mock_run.call_args[0][0]
            assert call_args.count("--output-format") == 1

    def test_successful_prompt_returns_result_field(self):
        """Test that prompt() returns the result field from the JSON envelope."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(result="the answer"), stderr=""
            )
            agent = ClaudeCodeAgent()
            assert agent.prompt("question") == "the answer"

    def test_invalid_json_raises_value_error(self):
        """Test that non-JSON stdout raises ValueError."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="not json", stderr=""
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(ValueError, match="non-JSON"):
                agent.prompt("hello")

    def test_missing_result_key_raises_value_error(self):
        """Test that a JSON envelope without 'result' key raises ValueError."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            envelope = json.dumps({"type": "result", "session_id": "s1"})
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=envelope, stderr=""
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(ValueError, match="missing 'result' field"):
                agent.prompt("hello")

    def test_telemetry_logged_at_debug(self, caplog):
        """Test that session_id and duration_ms are logged at DEBUG level."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=_envelope(session_id="abc123", duration_ms=500),
                stderr=""
            )
            agent = ClaudeCodeAgent()
            with caplog.at_level(logging.DEBUG, logger="antkeeper.llm.claude_code"):
                agent.prompt("hello")
            debug_text = " ".join(r.message for r in caplog.records)
            assert "abc123" in debug_text
            assert "500" in debug_text

    def test_empty_result_string_returned(self):
        """Test that an empty result string is returned without error."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(result=""), stderr=""
            )
            agent = ClaudeCodeAgent()
            assert agent.prompt("x") == ""

    def test_missing_session_id_does_not_raise(self):
        """Test that a missing session_id in the envelope does not raise."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            envelope = json.dumps({"type": "result", "result": "fine"})
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=envelope, stderr=""
            )
            agent = ClaudeCodeAgent()
            assert agent.prompt("hello") == "fine"

    def test_none_total_cost_does_not_raise(self):
        """Test that total_cost_usd: null in the envelope does not raise."""
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=_envelope(total_cost_usd=None),
                stderr=""
            )
            agent = ClaudeCodeAgent()
            assert agent.prompt("hello") == "ok"


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
