"""Tests for ClaudeCodeAgent.

Unit tests covering subprocess delegation, model flag handling,
JSONL streaming, telemetry logging, and error propagation.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from antkeeper.core.domain import State, StreamEvent
from antkeeper.llm.claude_code import ClaudeCodeAgent, _parse_jsonl_line
from antkeeper.llm.errors import AgentExecutionError


def _make_popen_mock(stdout_lines: list[str], returncode: int = 0, stderr: str = ""):
    """Build a mock Popen that yields stdout_lines and returns the given exit code."""
    mock_proc = MagicMock()
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = stderr
    mock_proc.returncode = returncode
    mock_proc.wait.side_effect = lambda: setattr(mock_proc, 'returncode', returncode)
    mock_proc.poll.return_value = returncode
    return mock_proc


def _result_line(result="ok", session_id="s1", duration_ms=100, usage=None, total_cost_usd=0.0):
    """Build a JSONL result line."""
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "result": result,
        "session_id": session_id,
        "duration_ms": duration_ms,
        "usage": usage or {},
        "total_cost_usd": total_cost_usd,
    })


def _assistant_line(content="hello"):
    """Build a JSONL assistant line."""
    return json.dumps({"type": "assistant", "content": content})


def _system_line(content="tool output"):
    """Build a JSONL system line."""
    return json.dumps({"type": "system", "content": content})


class TestClaudeCodeAgent:
    """Test suite for ClaudeCodeAgent subprocess delegation and error handling."""

    def test_prompt_returns_iterator_of_stream_events(self):
        """Consuming the iterator yields StreamEvent instances."""
        mock_proc = _make_popen_mock([_result_line(result="answer") + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            events = list(agent.prompt("hello"))
            assert len(events) == 1
            assert isinstance(events[0], StreamEvent)
            assert events[0].type == "result"
            assert events[0].content == "answer"

    def test_prompt_parses_assistant_events(self):
        """Assistant JSONL lines become type='assistant' events."""
        lines = [_assistant_line("thinking...") + "\n", _result_line() + "\n"]
        mock_proc = _make_popen_mock(lines)
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            events = list(agent.prompt("hello"))
            assert events[0].type == "assistant"
            assert events[0].content == "thinking..."

    def test_prompt_parses_result_event(self):
        """Result envelope becomes type='result' with metadata."""
        line = _result_line(result="the answer", session_id="sess1", duration_ms=500, total_cost_usd=0.05)
        mock_proc = _make_popen_mock([line + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            events = list(agent.prompt("q"))
            assert events[0].type == "result"
            assert events[0].content == "the answer"
            assert events[0].metadata is not None
            assert events[0].metadata["session_id"] == "sess1"

    def test_prompt_non_zero_exit_raises(self):
        """Non-zero exit code raises AgentExecutionError."""
        mock_proc = _make_popen_mock([], returncode=1, stderr="boom")
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                list(agent.prompt("hello"))

    def test_prompt_binary_not_found(self):
        """FileNotFoundError from Popen raises AgentExecutionError."""
        with patch("antkeeper.llm.claude_code.subprocess.Popen", side_effect=FileNotFoundError("claude")):
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError, match="claude binary not found"):
                list(agent.prompt("hello"))

    def test_prompt_malformed_jsonl_raises(self):
        """Bad JSON raises ValueError."""
        mock_proc = _make_popen_mock(["not json\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            with pytest.raises(ValueError, match="Malformed JSONL"):
                list(agent.prompt("hello"))

    def test_output_format_stream_json_flag(self):
        """Verify --output-format stream-json in Popen args."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent()
            list(agent.prompt("hello"))
            call_args = mock_popen.call_args[0][0]
            idx = call_args.index("--output-format")
            assert call_args[idx + 1] == "stream-json"

    def test_model_passed_to_subprocess(self):
        """Model flag is included in subprocess args when set."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent(model="opus")
            list(agent.prompt("hello"))
            call_args = mock_popen.call_args[0][0]
            assert "--model" in call_args
            assert "opus" in call_args

    def test_no_model_omits_flag(self):
        """Model flag is omitted when model is None."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent()
            list(agent.prompt("hello"))
            call_args = mock_popen.call_args[0][0]
            assert "--model" not in call_args

    def test_yolo_adds_permissions_flag(self):
        """yolo=True adds --dangerously-skip-permissions to command."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent(yolo=True)
            list(agent.prompt("hello"))
            call_args = mock_popen.call_args[0][0]
            assert "--dangerously-skip-permissions" in call_args

    def test_opts_passed_to_command(self):
        """Opts are included in the subprocess command."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent(opts=["--verbose"])
            list(agent.prompt("hello"))
            call_args = mock_popen.call_args[0][0]
            assert call_args == ["claude", "--output-format", "stream-json", "--verbose", "-p", "hello"]

    def test_opts_override_convenience_params(self):
        """Opts take precedence over convenience params."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent(
                model="sonnet",
                yolo=True,
                opts=["--model", "opus", "--dangerously-skip-permissions"],
            )
            list(agent.prompt("hello"))
            call_args = mock_popen.call_args[0][0]
            assert call_args == [
                "claude",
                "--output-format",
                "stream-json",
                "--model",
                "opus",
                "--dangerously-skip-permissions",
                "-p",
                "hello",
            ]

    def test_empty_prompt_passed_through(self):
        """Empty string prompt is passed to subprocess as-is."""
        mock_proc = _make_popen_mock([_result_line(result="") + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent()
            list(agent.prompt(""))
            call_args = mock_popen.call_args[0][0]
            assert call_args == ["claude", "--output-format", "stream-json", "-p", ""]

    def test_output_format_not_duplicated_when_in_opts(self):
        """--output-format is not duplicated when provided in opts."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc) as mock_popen:
            agent = ClaudeCodeAgent(opts=["--output-format", "stream-json"])
            list(agent.prompt("hello"))
            call_args = mock_popen.call_args[0][0]
            assert call_args.count("--output-format") == 1

    def test_system_events_become_tool_type(self):
        """System JSONL lines become type='tool' events."""
        lines = [_system_line("running tool") + "\n", _result_line() + "\n"]
        mock_proc = _make_popen_mock(lines)
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            events = list(agent.prompt("hello"))
            assert events[0].type == "tool"
            assert events[0].content == "running tool"

    def test_unknown_event_type_skipped(self):
        """Unknown event types are silently skipped."""
        lines = [json.dumps({"type": "unknown_type"}) + "\n", _result_line() + "\n"]
        mock_proc = _make_popen_mock(lines)
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            events = list(agent.prompt("hello"))
            assert len(events) == 1
            assert events[0].type == "result"

    def test_empty_stream_returns_empty_iterator(self):
        """Empty JSONL stream (process exits 0 with no output) yields nothing."""
        mock_proc = _make_popen_mock([])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            events = list(agent.prompt("hello"))
            assert events == []


class TestParseJsonlLine:
    """Tests for the _parse_jsonl_line helper."""

    def test_assistant_event(self):
        """String content on an assistant line is parsed into a StreamEvent."""
        event = _parse_jsonl_line(_assistant_line("hi"))
        assert event is not None
        assert event.type == "assistant"
        assert event.content == "hi"

    def test_assistant_with_content_blocks(self):
        """Content block list on an assistant line is concatenated into a single string."""
        line = json.dumps({"type": "assistant", "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]})
        event = _parse_jsonl_line(line)
        assert event is not None
        assert event.content == "hello world"

    def test_result_event_has_metadata(self):
        """Result line produces a StreamEvent with metadata including session_id."""
        event = _parse_jsonl_line(_result_line(session_id="s1", duration_ms=100))
        assert event is not None
        assert event.type == "result"
        assert event.metadata is not None
        assert event.metadata["session_id"] == "s1"

    def test_rate_limit_event(self):
        """Rate-limit line is parsed into a rate_limit StreamEvent with capacity metadata."""
        line = json.dumps({"type": "rate_limit", "capacity": 0.5})
        event = _parse_jsonl_line(line)
        assert event is not None
        assert event.type == "rate_limit"
        assert event.metadata is not None
        assert event.metadata["capacity"] == 0.5

    def test_empty_line_returns_none(self):
        """Empty or whitespace-only lines return None without raising."""
        assert _parse_jsonl_line("") is None
        assert _parse_jsonl_line("  \n") is None

    def test_malformed_json_raises(self):
        """Non-JSON input raises ValueError with 'Malformed JSONL' message."""
        with pytest.raises(ValueError, match="Malformed JSONL"):
            _parse_jsonl_line("not json")

    def test_unknown_type_returns_none(self):
        """Lines with an unrecognised type field return None."""
        line = json.dumps({"type": "future_type"})
        assert _parse_jsonl_line(line) is None


class TestTelemetryLogging:
    """Tests for telemetry logging in streaming mode."""

    def test_telemetry_logged_at_debug(self, caplog):
        """session_id and duration_ms are logged at DEBUG level."""
        line = _result_line(session_id="abc123", duration_ms=500) + "\n"
        mock_proc = _make_popen_mock([line])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            with caplog.at_level(logging.DEBUG, logger="antkeeper.llm.claude_code"):
                list(agent.prompt("hello"))
            debug_text = " ".join(r.message for r in caplog.records)
            assert "abc123" in debug_text
            assert "500" in debug_text


class TestIntegration:
    """Integration tests for agent execution within the framework."""

    def test_handler_using_mock_agent_in_runner(self, app, runner_factory):
        """Full pipeline with a fake streaming agent (no subprocess) runs end-to-end."""

        @app.handler
        def ask(runner, state: State) -> State:
            class FakeAgent:
                def prompt(self, prompt: str):
                    yield StreamEvent(type="result", content="canned")
            agent = FakeAgent()
            events = list(agent.prompt(state["prompt"]))
            return {**state, "result": events[0].content}

        runner, _source = runner_factory(app, "ask", {"prompt": "hi"})
        result = runner.run()
        assert result["result"] == "canned"

    def test_agent_execution_error_propagates(self, app, runner_factory):
        """AgentExecutionError raised inside a handler propagates out of runner.run()."""

        @app.handler
        def fail_agent(runner, state: State) -> State:
            raise AgentExecutionError("broken")

        runner, _source = runner_factory(app, "fail_agent", {})
        with pytest.raises(AgentExecutionError, match="broken"):
            runner.run()
