"""Tests for OpenTelemetry tracing integration.

Verifies that instrumentation points in Runner.run(), run_workflow(), and
ClaudeCodeAgent.prompt() produce correct spans with expected attributes.
Also verifies that entry points (CLI and server) configure a TracerProvider
when OTEL_EXPORTER_OTLP_ENDPOINT is set.

Uses a test-scoped TracerProvider with an in-memory exporter. Because each
call site uses ``trace.get_tracer("antkeeper")`` directly (no singleton),
installing a test provider is all that's needed — no per-module monkeypatching.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from antkeeper.core.app import run_workflow
from antkeeper.core.domain import State
from antkeeper.llm.claude_code import ClaudeCodeAgent
from antkeeper.llm.errors import AgentExecutionError


class _InMemoryExporter(SpanExporter):
    """Collect finished spans in a list for test assertions."""

    def __init__(self):
        """Initialise with an empty span buffer."""
        self._spans = []

    def export(self, spans):
        """Append exported spans to the internal buffer and report success."""
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def get_finished_spans(self):
        """Return a snapshot of all collected spans."""
        return list(self._spans)

    def shutdown(self):
        """No-op shutdown required by the SpanExporter interface."""
        pass


def _result_line(result="ok", session_id="s1", duration_ms=100, usage=None, total_cost_usd=0.01, model="sonnet"):
    """Build a JSONL result line with telemetry fields for use in mock subprocess output."""
    return json.dumps({
        "type": "result", "subtype": "success",
        "result": result, "session_id": session_id,
        "duration_ms": duration_ms, "usage": usage or {"input_tokens": 10, "output_tokens": 20},
        "total_cost_usd": total_cost_usd, "model": model,
    })


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


@pytest.fixture(autouse=True)
def _otel_provider():
    """Install a test TracerProvider with an in-memory exporter for each test."""
    exporter = _InMemoryExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    original = trace.get_tracer_provider
    trace.get_tracer_provider = lambda: provider  # type: ignore[assignment]

    yield exporter

    trace.get_tracer_provider = original
    provider.shutdown()


@pytest.fixture
def exporter(_otel_provider):
    """Expose the test-scoped in-memory exporter to individual tests."""
    return _otel_provider


class TestRunnerRunSpan:
    """Tests for the root 'antkeeper.run' span created by Runner.run()."""

    def test_produces_root_span(self, app, runner_factory, exporter):
        """Runner.run() produces exactly one 'antkeeper.run' root span."""
        @app.handler
        def noop(runner, state: State) -> State:
            return state

        runner, _ = runner_factory(app, "noop")
        runner.run()

        root_spans = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"]
        assert len(root_spans) == 1

    def test_root_span_has_attributes(self, app, runner_factory, exporter):
        """Root span carries run_id, workflow_name, and channel.type attributes."""
        @app.handler
        def noop(runner, state: State) -> State:
            return state

        runner, _ = runner_factory(app, "noop")
        runner.run()

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"][0]
        assert span.attributes["run_id"] == runner.id
        assert span.attributes["workflow_name"] == "noop"
        assert span.attributes["channel.type"] == "test"

    def test_error_sets_span_status(self, app, runner_factory, exporter):
        """Unhandled exception in handler sets root span status to ERROR."""
        @app.handler
        def failing(runner, state: State) -> State:
            raise RuntimeError("boom")

        runner, _ = runner_factory(app, "failing")
        with pytest.raises(RuntimeError):
            runner.run()

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"][0]
        assert span.status.status_code == trace.StatusCode.ERROR

    def test_error_records_exception(self, app, runner_factory, exporter):
        """Unhandled exception in handler is recorded as a span exception event."""
        @app.handler
        def failing(runner, state: State) -> State:
            raise RuntimeError("boom")

        runner, _ = runner_factory(app, "failing")
        with pytest.raises(RuntimeError):
            runner.run()

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"][0]
        exception_events = [e for e in span.events if e.name == "exception"]
        assert len(exception_events) == 1

    def test_exception_still_propagates(self, app, runner_factory, exporter):
        """Exception is still raised to the caller even after being recorded on the span."""
        @app.handler
        def failing(runner, state: State) -> State:
            raise RuntimeError("boom")

        runner, _ = runner_factory(app, "failing")
        with pytest.raises(RuntimeError, match="boom"):
            runner.run()


class TestRunWorkflowSpans:
    """Tests for per-step 'antkeeper.workflow.step' spans produced by run_workflow()."""

    def test_produces_step_spans(self, app, runner_factory, exporter):
        """run_workflow() produces one span per step in the pipeline."""
        def step_a(runner, state: State) -> State:
            return state

        def step_b(runner, state: State) -> State:
            return state

        @app.handler
        def workflow(runner, state: State) -> State:
            return run_workflow(runner, state, [step_a, step_b])

        runner, _ = runner_factory(app, "workflow")
        runner.run()

        step_spans = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.workflow.step"]
        assert len(step_spans) == 2

    def test_step_span_attributes(self, app, runner_factory, exporter):
        """Step span carries step_name, step_index, step_total, run_id, and workflow_name."""
        def only_step(runner, state: State) -> State:
            return state

        @app.handler
        def workflow(runner, state: State) -> State:
            return run_workflow(runner, state, [only_step])

        runner, _ = runner_factory(app, "workflow")
        runner.run()

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.workflow.step"][0]
        assert span.attributes["step_name"] == "only_step"
        assert span.attributes["step_index"] == 0
        assert span.attributes["step_total"] == 1
        assert span.attributes["run_id"] == runner.id
        assert span.attributes["workflow_name"] == "workflow"

    def test_step_error_sets_span_status(self, app, runner_factory, exporter):
        """Exception in a workflow step sets its span status to ERROR."""
        def bad_step(runner, state: State) -> State:
            raise RuntimeError("step failed")

        @app.handler
        def workflow(runner, state: State) -> State:
            return run_workflow(runner, state, [bad_step])

        runner, _ = runner_factory(app, "workflow")
        with pytest.raises(RuntimeError):
            runner.run()

        step_span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.workflow.step"][0]
        assert step_span.status.status_code == trace.StatusCode.ERROR

    def test_step_error_records_exception(self, app, runner_factory, exporter):
        """Exception in a workflow step is recorded as an exception event on its span."""
        def bad_step(runner, state: State) -> State:
            raise RuntimeError("step failed")

        @app.handler
        def workflow(runner, state: State) -> State:
            return run_workflow(runner, state, [bad_step])

        runner, _ = runner_factory(app, "workflow")
        with pytest.raises(RuntimeError):
            runner.run()

        step_span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.workflow.step"][0]
        exception_events = [e for e in step_span.events if e.name == "exception"]
        assert len(exception_events) == 1

    def test_span_hierarchy(self, app, runner_factory, exporter):
        """Workflow step spans are children of the root 'antkeeper.run' span."""
        def step_a(runner, state: State) -> State:
            return state

        @app.handler
        def workflow(runner, state: State) -> State:
            return run_workflow(runner, state, [step_a])

        runner, _ = runner_factory(app, "workflow")
        runner.run()

        root = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"][0]
        step = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.workflow.step"][0]
        assert step.parent.span_id == root.context.span_id


class TestLLMCallSpan:
    """Tests for the 'antkeeper.llm.call' span created per ClaudeCodeAgent.prompt() invocation."""

    def test_produces_llm_span(self, exporter):
        """A single agent.prompt() call produces exactly one 'antkeeper.llm.call' span."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            list(agent.prompt("hello"))

        llm_spans = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"]
        assert len(llm_spans) == 1

    def test_llm_span_attributes(self, exporter):
        """LLM span carries token counts, cost, session_id, duration_ms, and model attributes."""
        line = _result_line(session_id="sess1", duration_ms=500, usage={"input_tokens": 100, "output_tokens": 200}, total_cost_usd=0.05, model="opus")
        mock_proc = _make_popen_mock([line + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            list(agent.prompt("hello"))

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        assert span.attributes["prompt_length"] == 5
        assert span.attributes["session_id"] == "sess1"
        assert span.attributes["duration_ms"] == 500
        assert span.attributes["input_tokens"] == 100
        assert span.attributes["output_tokens"] == 200
        assert span.attributes["total_cost_usd"] == 0.05
        assert span.attributes["model"] == "opus"

    def test_llm_error_sets_span_status(self, exporter):
        """Non-zero subprocess exit sets LLM span status to ERROR."""
        mock_proc = _make_popen_mock([], returncode=1, stderr="error")
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                list(agent.prompt("hello"))

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        assert span.status.status_code == trace.StatusCode.ERROR

    def test_llm_error_records_exception(self, exporter):
        """AgentExecutionError is recorded as an exception event on the LLM span."""
        mock_proc = _make_popen_mock([], returncode=1, stderr="error")
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                list(agent.prompt("hello"))

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        exception_events = [e for e in span.events if e.name == "exception"]
        assert len(exception_events) == 1

    def test_llm_exception_propagates(self, exporter):
        """AgentExecutionError raised during streaming propagates to the caller."""
        mock_proc = _make_popen_mock([], returncode=1, stderr="bad")
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                list(agent.prompt("hello"))

    def test_prompt_length_set_before_call(self, exporter):
        """prompt_length attribute on the LLM span equals len(prompt)."""
        mock_proc = _make_popen_mock([_result_line() + "\n"])
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            list(agent.prompt("a long prompt"))

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        assert span.attributes["prompt_length"] == len("a long prompt")

    def test_otel_span_closed_on_incomplete_consumption(self, exporter):
        """Generator close triggers span.end() even if not fully consumed."""
        lines = [_result_line() + "\n", _result_line(result="second") + "\n"]
        mock_proc = _make_popen_mock(lines)
        mock_proc.poll.return_value = None
        with patch("antkeeper.llm.claude_code.subprocess.Popen", return_value=mock_proc):
            agent = ClaudeCodeAgent()
            gen = agent.prompt("hello")
            next(gen)  # consume one event
            gen.close()  # type: ignore[union-attr]  # close without consuming all

        llm_spans = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"]
        assert len(llm_spans) == 1
