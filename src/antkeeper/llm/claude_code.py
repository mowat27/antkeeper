"""Claude Code agent implementation.

This module provides a concrete Agent implementation that executes prompts
by delegating to the `claude` CLI subprocess. The agent wraps subprocess
calls and handles command construction, error reporting, and response parsing.
"""

import json
import logging
import os
import subprocess
from collections.abc import Iterator

from opentelemetry import context, trace
from opentelemetry.propagate import inject
from opentelemetry.trace import StatusCode

from antkeeper.core.domain import StreamEvent
from antkeeper.llm.errors import AgentExecutionError

logger = logging.getLogger("antkeeper.llm.claude_code")

def _set_span_telemetry(span: trace.Span, metadata: dict | None) -> None:
    """Set OpenTelemetry span attributes from result event metadata.

    Reads the following keys from *metadata* and sets them as span attributes:
    ``session_id``, ``duration_ms``, ``usage.input_tokens``,
    ``usage.output_tokens``, ``total_cost_usd``, and ``model``.
    Missing or ``None`` values fall back to sensible zero-equivalents so the
    attributes are always present on the span.  Does nothing when *metadata*
    is ``None`` or empty.

    Args:
        span: The active OpenTelemetry span to annotate.
        metadata: Metadata dict from a ``result`` StreamEvent, or ``None``.
    """
    if not metadata:
        return
    span.set_attribute("session_id", metadata.get("session_id") or "")
    span.set_attribute("duration_ms", metadata.get("duration_ms") or 0)
    usage = metadata.get("usage") or {}
    span.set_attribute("input_tokens", usage.get("input_tokens") or 0)
    span.set_attribute("output_tokens", usage.get("output_tokens") or 0)
    span.set_attribute("total_cost_usd", metadata.get("total_cost_usd") or 0.0)
    span.set_attribute("model", metadata.get("model") or "")


def _parse_jsonl_line(line: str) -> StreamEvent | None:
    """Parse a single JSONL line into a StreamEvent.

    Args:
        line: A single line of JSONL output from the Claude CLI.

    Returns:
        A StreamEvent, or None for unrecognised event types.

    Raises:
        ValueError: If the line is not valid JSON.
    """
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        raise ValueError(f"Malformed JSONL line: {line[:200]!r}")

    event_type = data.get("type", "")

    if event_type == "assistant":
        content = data.get("content", "")
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        return StreamEvent(type="assistant", content=content)

    if event_type == "system":
        return StreamEvent(type="tool", content=data.get("content", ""))

    if event_type == "result":
        metadata = {
            "session_id": data.get("session_id"),
            "duration_ms": data.get("duration_ms"),
            "usage": data.get("usage"),
            "total_cost_usd": data.get("total_cost_usd"),
            "model": data.get("model"),
        }
        return StreamEvent(
            type="result",
            content=data.get("result", ""),
            metadata=metadata,
        )

    if event_type == "rate_limit":
        metadata = {
            "capacity": data.get("capacity"),
        }
        return StreamEvent(type="rate_limit", content="", metadata=metadata)

    logger.debug(f"Skipping unknown JSONL event type: {event_type}")
    return None


class ClaudeCodeAgent:
    """Agent that delegates prompts to the Claude Code CLI.

    This agent implementation shells out to the `claude` binary installed
    on the system. It constructs appropriate command-line arguments, handles
    subprocess execution, and converts CLI errors into AgentExecutionErrors.

    Attributes:
        model: Optional model identifier passed to the Claude CLI via --model flag.
    """

    def __init__(
        self,
        model: str | None = None,
        yolo: bool = False,
        opts: list[str] | None = None,
    ) -> None:
        """Initialize the Claude Code agent.

        Args:
            model: Optional model identifier to pass to the Claude CLI
                via the --model flag. If None, uses the CLI's default model.
            yolo: When True, passes --dangerously-skip-permissions to the CLI.
            opts: Extra CLI arguments. Override convenience params when flags
                conflict (e.g. opts=["--model", "opus"] overrides model="sonnet").
        """
        self.model = model
        self.yolo = yolo
        self.opts = opts
        logger.debug(
            f"ClaudeCodeAgent initialized: model={self.model} yolo={self.yolo} opts={self.opts}"
        )

    def prompt(self, prompt: str) -> Iterator[StreamEvent]:
        """Execute a prompt via `claude -p` and yield StreamEvents.

        Constructs a subprocess call to the Claude CLI with the -p flag for
        prompt execution and --output-format stream-json for JSONL streaming.
        Yields StreamEvent instances as they arrive from the subprocess.

        Args:
            prompt: The prompt string to send to Claude Code CLI.

        Yields:
            StreamEvent instances parsed from the JSONL stream.

        Raises:
            AgentExecutionError: If the claude binary is not found or if the
                subprocess exits with a non-zero status code.
            ValueError: If a JSONL line cannot be parsed.
        """
        opts_list = self.opts or []
        cmd = ["claude"]
        if self.model and "--model" not in opts_list:
            cmd.extend(["--model", self.model])
        if self.yolo and "--dangerously-skip-permissions" not in opts_list:
            cmd.append("--dangerously-skip-permissions")
        if "--output-format" not in opts_list:
            cmd.extend(["--output-format", "stream-json"])
        cmd.extend(opts_list)
        cmd.extend(["-p", prompt])
        logger.info(f"LLM prompt submitted (length={len(prompt)} chars)")
        logger.debug(f"LLM prompt content: {prompt}")

        span = trace.get_tracer("antkeeper").start_span(
            "antkeeper.llm.call",
            attributes={"prompt_length": len(prompt)},
        )
        ctx = trace.set_span_in_context(span)
        token = context.attach(ctx)

        carrier: dict[str, str] = {}
        inject(carrier)
        env = {**os.environ, **carrier}

        proc: subprocess.Popen | None = None
        try:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    env=env,
                )
            except FileNotFoundError:
                logger.error("claude binary not found")
                raise AgentExecutionError("claude binary not found")

            logger.debug(f"LLM subprocess command: {cmd}")
            assert proc.stdout is not None
            for line in proc.stdout:
                event = _parse_jsonl_line(line)
                if event is None:
                    continue
                if event.type == "result":
                    _set_span_telemetry(span, event.metadata)
                    logger.debug(
                        "LLM session_id=%s duration_ms=%s usage=%s cost=%s",
                        event.metadata.get("session_id") if event.metadata else None,
                        event.metadata.get("duration_ms") if event.metadata else None,
                        event.metadata.get("usage") if event.metadata else None,
                        event.metadata.get("total_cost_usd") if event.metadata else None,
                    )
                    logger.info(f"LLM response received (length={len(event.content)} chars)")
                    logger.debug(f"LLM response content: {event.content}")
                yield event

            proc.wait()
            if proc.returncode != 0:
                stderr_output = proc.stderr.read() if proc.stderr else ""
                logger.error(f"claude exited with code {proc.returncode}: {stderr_output}")
                raise AgentExecutionError(
                    f"claude exited with code {proc.returncode}: {stderr_output}"
                )
        except Exception as exc:
            span.set_status(StatusCode.ERROR)
            span.record_exception(exc)
            raise
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
            span.end()
            context.detach(token)


def run_prompt(
    prompt: str,
    logger: logging.Logger,
    model: str | None = None,
    opts: list[str] | None = None,
) -> Iterator[StreamEvent]:
    """Execute a prompt via ClaudeCodeAgent and return a stream of events.

    Convenience wrapper that creates an agent with yolo=True, sends the prompt,
    and returns the event iterator.

    Args:
        prompt: The prompt string to send.
        logger: Logger for caller-level context.
        model: Optional model identifier passed to the agent.
        opts: Extra CLI arguments forwarded to ClaudeCodeAgent.

    Returns:
        An iterator of StreamEvent instances.
    """
    logger.debug(f"run_prompt called (prompt length={len(prompt)} chars)")
    agent = ClaudeCodeAgent(model=model, yolo=True, opts=opts)
    return agent.prompt(prompt)


def collect_result(events: Iterator[StreamEvent]) -> tuple[str, list[StreamEvent]]:
    """Consume an event stream, returning (result_text, all_events).

    Args:
        events: An iterator of StreamEvent instances.

    Returns:
        A tuple of (result_text, all_events). result_text is the content of
        the last non-internal result event. all_events is the full list of
        events consumed.
    """
    all_events: list[StreamEvent] = []
    result_text = ""
    for event in events:
        all_events.append(event)
        if event.type == "result" and not event.internal:
            result_text = event.content
    return result_text, all_events
