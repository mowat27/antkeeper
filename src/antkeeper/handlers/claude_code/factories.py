"""Factory for building Claude Code handler functions.

The ``cc_handler`` factory eliminates boilerplate by producing
``(Runner, State) -> State`` handlers in two modes:

* **simple** – run the LLM command then merge static *updates* into state.
* **JSON** – wrap the command with ``json_prompt``, parse the response with
  ``extract_json``, and merge the requested *json_fields* into state.
"""

from typing import Any, Callable

from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.helpers.json import json_prompt, extract_json
from antkeeper.llm.claude_code import run_prompt
from antkeeper.llm.errors import AgentExecutionError


def cc_handler(
    command: str,
    *,
    updates: dict[str, Any] | None = None,
    json_fields: list[str] | None = None,
    label: str | None = None,
) -> Callable[[Runner, State], State]:
    """Build a handler that runs a Claude Code command and updates state.

    Args:
        command: Format string with ``{key}`` placeholders interpolated from state.
        updates: Static key/value pairs merged into state after the LLM call (simple mode).
        json_fields: Field names to extract from the JSON LLM response (JSON mode).
        label: Human-readable label for progress messages. Defaults to the first
            token of *command* with any leading ``/`` stripped.

    Returns:
        A handler function with signature ``(Runner, State) -> State``.

    Raises:
        ValueError: If both or neither of *updates* and *json_fields* are provided.
    """
    if (updates is None) == (json_fields is None):
        raise ValueError("Provide exactly one of 'updates' or 'json_fields', not both or neither.")

    if label is None:
        label = command.split()[0].lstrip("/")

    # Capture the non-None value for the type checker
    _updates: dict[str, Any] = updates if updates is not None else {}

    def handler(runner: Runner, state: State) -> State:
        """Execute the Claude Code command and return updated state.

        Interpolates *command* with values from *state*, sends the resulting
        prompt to the Claude Code CLI, then merges the response data back into
        state.  In JSON mode the response is parsed and only the requested
        *json_fields* are merged; in simple mode the static *updates* dict is
        merged instead.

        Args:
            runner: The active workflow runner used for progress reporting and
                failure signalling.
            state: Current workflow state.  Provides values for any
                ``{placeholder}`` tokens in *command*.

        Returns:
            A new state dict with the handler's output merged in.

        Raises:
            WorkflowFailedError: If the LLM call fails, the response cannot be
                parsed, a required JSON field is missing, or a state key
                referenced in *command* is absent.
        """
        runner.report_progress(f"Running {label}")
        try:
            prompt = command.format_map(state)
            if json_fields is not None:
                prompt = json_prompt(prompt, required_fields=json_fields)
            response = run_prompt(prompt, runner.logger, model=state.get("model"))
            if json_fields is not None:
                parsed = extract_json(response)
                result = {k: parsed[k] for k in json_fields}
            else:
                result = _updates
        except (KeyError, AgentExecutionError, ValueError) as error:
            runner.fail(f"{label} failed: {error}")
        runner.report_progress(f"{label} complete")
        return {**state, **result}

    handler.__name__ = label
    return handler
