"""Factory for building Claude Code handler functions.

The ``cc_handler`` factory eliminates boilerplate by producing
``(Runner, State) -> State`` handlers in two modes:

* **fire-and-forget** – run the LLM command, discard the response, return
  state unchanged.
* **extraction** – run the command first, then send the response through
  extraction middleware (haiku) to extract structured JSON fields.
  Parse the result with ``extract_json`` and merge the requested
  *state_updates* fields into state.

An optional ``model`` argument allows overriding the LLM model on a
per-handler basis.  When omitted, the model is read from ``state["model"]``
at call time (i.e. the workflow-level default).

An optional ``env`` dict sets environment variables for the handler's
execution only.  Handler-level env merges with App-level env using
``{**app_env, **handler_env}`` semantics (handler values win).

An optional ``verbose`` flag controls how much of the event stream is
forwarded to the channel.  When ``False`` (the default) only ``result``
and ``error`` events with non-empty content are forwarded.  When ``True``
every event with non-empty content is forwarded, which is useful for
debugging or when intermediate progress messages are desired.
"""

import logging
import re
from collections.abc import Callable, Iterator
from typing import Protocol

from antkeeper.core.app import _app_env
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State, StreamEvent
from antkeeper.helpers.json import extract_json
from antkeeper.llm.claude_code import ClaudeCodeAgent, run_prompt
from antkeeper.llm.errors import AgentExecutionError

_EXTRACTION_MODEL = "haiku"

Middleware = Callable[[Iterator[StreamEvent]], Iterator[StreamEvent]]


def build_pipeline(stream: Iterator[StreamEvent], middlewares: list[Middleware]) -> Iterator[StreamEvent]:
    """Chain middlewares around a stream, left-to-right.

    Args:
        stream: The source event stream.
        middlewares: List of middleware functions to apply.

    Returns:
        The transformed event stream.
    """
    for mw in middlewares:
        stream = mw(stream)
    return stream


def _extraction_prompt(response: str, *, required_fields: list[str]) -> str:
    """Build a prompt instructing haiku to extract structured fields from LLM output.

    Args:
        response: The raw text output from the first ``run_prompt`` call.
        required_fields: Names of the JSON fields to extract from *response*.

    Returns:
        A plain-text prompt that asks the model to return a JSON object
        containing exactly the *required_fields*, with ``null`` for any field
        not found in *response*.
    """
    import json as _json
    return (
        f"Extract the following fields from the response below: "
        f"{_json.dumps(required_fields)}\n"
        f"\n"
        f"<response>\n"
        f"{response}\n"
        f"</response>\n"
        f"\n"
        f"Return ONLY a JSON object with those fields. "
        f"No markdown fences, no explanation. "
        f"If a field's value is not present in the response, use null."
    )


def _extraction_middleware(
    required_fields: list[str],
    log: logging.Logger,
    model_opts: tuple[str, list[str] | None],
) -> Middleware:
    """Create middleware that extracts structured data from result events.

    Args:
        required_fields: Field names to extract from the result.
        log: Logger for the extraction call.
        model_opts: Tuple of (model, opts) for the extraction agent.

    Returns:
        A middleware function.
    """
    def middleware(stream: Iterator[StreamEvent]) -> Iterator[StreamEvent]:
        """Pass events through, then run extraction after each result event.

        Yields every event from *stream* unchanged.  When a ``result`` event is
        encountered a second ``run_prompt`` call is made using the extraction
        prompt; its events are re-yielded with ``internal=True`` so downstream
        consumers can distinguish them from the primary response.

        Args:
            stream: The upstream event iterator to wrap.

        Yields:
            StreamEvent instances — originals first, then extraction events
            (``internal=True``) immediately after each ``result`` event.
        """
        for event in stream:
            yield event
            if event.type == "result":
                extraction_stream = run_prompt(
                    _extraction_prompt(event.content, required_fields=required_fields),
                    log,
                    model=model_opts[0],
                    opts=model_opts[1],
                )
                for ext_event in extraction_stream:
                    yield StreamEvent(
                        type=ext_event.type,
                        content=ext_event.content,
                        metadata=ext_event.metadata,
                        internal=True,
                    )
    return middleware


def _should_report(event: StreamEvent, verbose: bool) -> bool:
    """Decide whether to forward an event to the channel.

    Args:
        event: The stream event to evaluate.
        verbose: When ``True``, all events with non-empty content are forwarded.
            When ``False``, only ``result`` and ``error`` events with content pass through.

    Returns:
        ``True`` if the event should be forwarded to the channel.
    """
    if not event.content:
        return False
    if verbose:
        return True
    return event.type in ("result", "error")


class Handler(Protocol):
    """A handler callable with a ``__name__`` attribute.

    Attributes:
        __name__: Human-readable label used in progress messages and logging.

    Methods:
        __call__: Run the handler against the given runner and state, returning
            updated state.
    """

    __name__: str

    def __call__(self, runner: Runner, state: State, /) -> State: ...


def cc_handler(
    command: str,
    *,
    state_updates: list[str] | None = None,
    label: str | None = None,
    model: str | None = None,
    env: dict[str, str] | None = None,
    verbose: bool = False,
) -> Handler:
    """Build a handler that runs a Claude Code command and updates state.

    Args:
        command: Command string with ``$var`` placeholders interpolated from state.
        state_updates: Field names to extract from the JSON LLM response and
            merge into state.  When ``None`` or empty the handler runs the
            command and returns state unchanged (fire-and-forget mode).
        label: Human-readable label for progress messages. Defaults to the first
            token of *command* with any leading ``/`` stripped.
        model: LLM model identifier. When provided, overrides the model from
            state. Defaults to ``state.get("model")``.
        env: Environment variables to set for this handler's execution only.
            Merges with App-level env (handler values win).  Restored after
            the handler completes, even on failure.
        verbose: When ``True``, all events with non-empty content are forwarded
            to the channel.  When ``False`` (default), only ``result`` and
            ``error`` events with non-empty content are forwarded.

    Returns:
        A handler function with signature ``(Runner, State) -> State``.
    """
    if label is None:
        label = command.split()[0].lstrip("/")

    def handler(runner: Runner, state: State) -> State:
        """Execute the Claude Code command and return updated state.

        Interpolates ``$var`` placeholders in *command* from *state*, selects
        the effective model, builds the middleware pipeline, drains the event
        stream (forwarding each event to the channel), and — when
        *state_updates* was specified — parses the extraction result and merges
        the requested fields into a copy of *state*.

        Args:
            runner: The active Runner instance used for progress reporting,
                channel access, and failure signalling.
            state: The current workflow state dict.  ``$var`` references in
                *command* are resolved against this dict.

        Returns:
            A new state dict with extracted fields merged in (fire-and-forget
            mode returns *state* unchanged).

        Raises:
            WorkflowFailedError: Via ``runner.fail()`` when the command or
                extraction step raises ``KeyError``, ``AgentExecutionError``,
                or ``ValueError``.
        """
        runner.report_progress(f"Running {label}")
        with _app_env(env):
            try:
                prompt = re.sub(
                    r'\$([a-zA-Z_]\w*)',
                    lambda m: str(state[m.group(1)]),
                    command,
                )
                effective_model = model if model is not None else state.get("model")
                agent = ClaudeCodeAgent(model=effective_model, yolo=True)
                stream: Iterator[StreamEvent] = agent.prompt(prompt)

                middlewares: list[Middleware] = []
                if state_updates:
                    middlewares.append(
                        _extraction_middleware(
                            required_fields=state_updates,
                            log=runner.logger,
                            model_opts=(_EXTRACTION_MODEL, ["--max-turns", "1"]),
                        )
                    )

                pipeline = build_pipeline(stream, middlewares)

                extraction_result: dict | None = None
                try:
                    for event in pipeline:
                        if _should_report(event, verbose):
                            runner.channel.report(runner.id, event)
                        if event.type == "result" and event.internal:
                            extraction_result = extract_json(event.content)
                finally:
                    close = getattr(pipeline, 'close', None)
                    if close is not None:
                        close()

                if state_updates:
                    if extraction_result is None:
                        raise KeyError(f"No extraction result for {state_updates}")
                    result = {k: extraction_result[k] for k in state_updates}
                else:
                    result = {}
            except (KeyError, AgentExecutionError, ValueError) as error:
                runner.fail(f"{label} failed: {error}")
        runner.report_progress(f"{label} complete")
        return {**state, **result}

    handler.__name__ = label
    return handler
