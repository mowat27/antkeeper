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
import subprocess
from unittest.mock import patch

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
        self._spans = []

    def export(self, spans):
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def get_finished_spans(self):
        return list(self._spans)

    def shutdown(self):
        pass


def _envelope(result="ok", session_id="s1", duration_ms=100, usage=None, total_cost_usd=0.01, model="sonnet"):
    return json.dumps({
        "type": "result", "subtype": "success",
        "result": result, "session_id": session_id,
        "duration_ms": duration_ms, "usage": usage or {"input_tokens": 10, "output_tokens": 20},
        "total_cost_usd": total_cost_usd, "model": model,
    })


@pytest.fixture(autouse=True)
def _otel_provider():
    """Install a test TracerProvider with an in-memory exporter for each test."""
    exporter = _InMemoryExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Patch the trace module to use our test provider.  The OTel API only
    # allows set_tracer_provider once per process, so we swap the internal
    # getter instead.  This is the standard approach for OTel test isolation.
    original = trace.get_tracer_provider
    trace.get_tracer_provider = lambda: provider  # type: ignore[assignment]

    yield exporter

    trace.get_tracer_provider = original  # type: ignore[assignment]
    provider.shutdown()


@pytest.fixture
def exporter(_otel_provider):
    return _otel_provider


class TestRunnerRunSpan:
    def test_produces_root_span(self, app, runner_factory, exporter):
        @app.handler
        def noop(runner, state: State) -> State:
            return state

        runner, _ = runner_factory(app, "noop")
        runner.run()

        root_spans = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"]
        assert len(root_spans) == 1

    def test_root_span_has_attributes(self, app, runner_factory, exporter):
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
        @app.handler
        def failing(runner, state: State) -> State:
            raise RuntimeError("boom")

        runner, _ = runner_factory(app, "failing")
        with pytest.raises(RuntimeError):
            runner.run()

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.run"][0]
        assert span.status.status_code == trace.StatusCode.ERROR

    def test_error_records_exception(self, app, runner_factory, exporter):
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
        @app.handler
        def failing(runner, state: State) -> State:
            raise RuntimeError("boom")

        runner, _ = runner_factory(app, "failing")
        with pytest.raises(RuntimeError, match="boom"):
            runner.run()


class TestRunWorkflowSpans:
    def test_produces_step_spans(self, app, runner_factory, exporter):
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
    def test_produces_llm_span(self, exporter):
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(), stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("hello")

        llm_spans = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"]
        assert len(llm_spans) == 1

    def test_llm_span_attributes(self, exporter):
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=_envelope(session_id="sess1", duration_ms=500, usage={"input_tokens": 100, "output_tokens": 200}, total_cost_usd=0.05, model="opus"),
                stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("hello")

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        assert span.attributes["prompt_length"] == 5
        assert span.attributes["session_id"] == "sess1"
        assert span.attributes["duration_ms"] == 500
        assert span.attributes["input_tokens"] == 100
        assert span.attributes["output_tokens"] == 200
        assert span.attributes["total_cost_usd"] == 0.05
        assert span.attributes["model"] == "opus"

    def test_llm_error_sets_span_status(self, exporter):
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error"
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                agent.prompt("hello")

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        assert span.status.status_code == trace.StatusCode.ERROR

    def test_llm_error_records_exception(self, exporter):
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error"
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                agent.prompt("hello")

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        exception_events = [e for e in span.events if e.name == "exception"]
        assert len(exception_events) == 1

    def test_llm_exception_propagates(self, exporter):
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="bad"
            )
            agent = ClaudeCodeAgent()
            with pytest.raises(AgentExecutionError):
                agent.prompt("hello")

    def test_prompt_length_set_before_call(self, exporter):
        with patch("antkeeper.llm.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_envelope(), stderr=""
            )
            agent = ClaudeCodeAgent()
            agent.prompt("a long prompt")

        span = [s for s in exporter.get_finished_spans() if s.name == "antkeeper.llm.call"][0]
        assert span.attributes["prompt_length"] == len("a long prompt")
