"""Factory for building Claude Code handler functions.

The ``cc_handler`` factory eliminates boilerplate by producing
``(Runner, State) -> State`` handlers in two modes:

* **fire-and-forget** – run the LLM command, discard the response, return
  state unchanged.
* **extraction** – run the command first, then send the response to a fast
  model (haiku) with ``_extraction_prompt`` to extract structured JSON fields.
  Parse the result with ``extract_json`` and merge the requested
  *state_updates* fields into state.

An optional ``model`` argument allows overriding the LLM model on a
per-handler basis.  When omitted, the model is read from ``state["model"]``
at call time (i.e. the workflow-level default).
"""

import json as _json
import re
from typing import Protocol

from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.helpers.json import extract_json
from antkeeper.llm.claude_code import run_prompt
from antkeeper.llm.errors import AgentExecutionError

_EXTRACTION_MODEL = "haiku"


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


class Handler(Protocol):
    """A handler callable with a ``__name__`` attribute."""

    __name__: str

    def __call__(self, runner: Runner, state: State, /) -> State: ...


def cc_handler(
    command: str,
    *,
    state_updates: list[str] | None = None,
    label: str | None = None,
    model: str | None = None,
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

    Returns:
        A handler function with signature ``(Runner, State) -> State``.
    """
    if label is None:
        label = command.split()[0].lstrip("/")

    def handler(runner: Runner, state: State) -> State:
        """Run the Claude Code command and return updated state.

        In **fire-and-forget** mode (``state_updates`` is falsy) a single
        ``run_prompt`` call is made and *state* is returned unchanged.

        In **extraction** mode (``state_updates`` is truthy) two calls are made:

        1. The interpolated *command* is sent to the primary model.
        2. ``_extraction_prompt`` wrapping the response is sent to
           ``_EXTRACTION_MODEL`` (haiku) to obtain a structured JSON object.

        The fields listed in ``state_updates`` are extracted from the parsed
        JSON and merged into *state* before it is returned.

        Args:
            runner: Workflow runner used for progress reporting and failure signalling.
            state: Current workflow state; ``$var`` placeholders in *command* are
                resolved against it.

        Returns:
            Updated state dict with extracted fields merged in, or the original
            *state* unchanged if ``state_updates`` is falsy.

        Raises:
            WorkflowFailedError: Via ``runner.fail()`` when interpolation,
                LLM execution, JSON parsing, or field extraction fails.
        """
        runner.report_progress(f"Running {label}")
        try:
            prompt = re.sub(
                r'\$([a-zA-Z_]\w*)',
                lambda m: str(state[m.group(1)]),
                command,
            )
            effective_model = model if model is not None else state.get("model")
            response = run_prompt(prompt, runner.logger, model=effective_model)
            if state_updates:
                extraction_response = run_prompt(
                    _extraction_prompt(response, required_fields=state_updates),
                    runner.logger,
                    model=_EXTRACTION_MODEL,
                    opts=["--max-turns", "1"],
                )
                parsed = extract_json(extraction_response)
                result = {k: parsed[k] for k in state_updates}
            else:
                result = {}
        except (KeyError, AgentExecutionError, ValueError) as error:
            runner.fail(f"{label} failed: {error}")
        runner.report_progress(f"{label} complete")
        return {**state, **result}

    handler.__name__ = label
    return handler
