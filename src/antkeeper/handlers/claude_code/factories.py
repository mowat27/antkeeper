"""Factory for building Claude Code handler functions.

The ``cc_handler`` factory eliminates boilerplate by producing
``(Runner, State) -> State`` handlers in two modes:

* **fire-and-forget** – run the LLM command, discard the response, return
  state unchanged.
* **JSON** – wrap the command with ``json_prompt``, parse the response with
  ``extract_json``, and merge the requested *state_updates* fields into state.
"""

import re
from typing import Protocol

from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.helpers.json import json_prompt, extract_json
from antkeeper.llm.claude_code import run_prompt
from antkeeper.llm.errors import AgentExecutionError


class Handler(Protocol):
    """A handler callable with a ``__name__`` attribute."""

    __name__: str

    def __call__(self, runner: Runner, state: State, /) -> State: ...


def cc_handler(
    command: str,
    *,
    state_updates: list[str] | None = None,
    label: str | None = None,
) -> Handler:
    """Build a handler that runs a Claude Code command and updates state.

    Args:
        command: Command string with ``$var`` placeholders interpolated from state.
        state_updates: Field names to extract from the JSON LLM response and
            merge into state.  When ``None`` or empty the handler runs the
            command and returns state unchanged (fire-and-forget mode).
        label: Human-readable label for progress messages. Defaults to the first
            token of *command* with any leading ``/`` stripped.

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
                prompt = json_prompt(prompt, required_fields=state_updates)
            response = run_prompt(prompt, runner.logger, model=state.get("model"))
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
