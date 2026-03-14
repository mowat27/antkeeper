"""Factory for building Claude Code handler functions.

The ``cc_handler`` factory eliminates boilerplate by producing
``(Runner, State) -> State`` handlers in two modes:

* **fire-and-forget** – run the LLM command, discard the response, return
  state unchanged.
* **delegation** – wrap the command with ``_delegation_prompt`` so a sub-agent
  runs the command while the outer agent returns JSON.  Parse the response with
  ``extract_json`` and merge the requested *state_updates* fields into state.

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


def _delegation_prompt(command: str, *, required_fields: list[str]) -> str:
    """Build a prompt that delegates the command to a sub-agent and asks the outer agent to return JSON."""
    example = {field: f"<{field}>" for field in required_fields}
    return (
        f"Use an agent to run the following command:\n"
        f"\n"
        f"{command}\n"
        f"\n"
        f"Wait for the agent to finish. Then, using the agent's output, "
        f"return ONLY a JSON object with these fields — no other text, "
        f"no markdown fences, no explanation:\n"
        f"\n"
        f"{_json.dumps(example)}\n"
        f"\n"
        f"Replace each placeholder with the actual value from the agent's output."
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
        runner.report_progress(f"Running {label}")
        try:
            prompt = re.sub(
                r'\$([a-zA-Z_]\w*)',
                lambda m: str(state[m.group(1)]),
                command,
            )
            if state_updates:
                prompt = _delegation_prompt(prompt, required_fields=state_updates)
            response = run_prompt(prompt, runner.logger, model=model if model is not None else state.get("model"))
            if state_updates:
                parsed = extract_json(response)
                result = {k: parsed[k] for k in state_updates}
            else:
                result = {}
        except (KeyError, AgentExecutionError, ValueError) as error:
            runner.fail(f"{label} failed: {error}")
        runner.report_progress(f"{label} complete")
        return {**state, **result}

    handler.__name__ = label
    return handler
