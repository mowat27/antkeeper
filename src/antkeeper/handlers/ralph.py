"""Retry-with-validation handler wrapper (ralph).

``ralph()`` wraps any handler with a retry-validation loop, accumulating
feedback in a progress log between attempts. On exhaustion the workflow fails
via ``runner.fail()``.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

from antkeeper.core.domain import State

if TYPE_CHECKING:
    from antkeeper.core.runner import Runner


class _NamedHandler(Protocol):
    """A handler callable that exposes a ``__name__`` attribute."""
    __name__: str

    def __call__(self, runner: Runner, state: State) -> State:
        ...


_Validator = Callable[["State"], "ValidationResult"]
_MAX_VALUE_LEN = 200


@dataclass(frozen=True)
class ValidationResult:
    """Result of a validator call.

    Attributes:
        success: True if validation passed, False otherwise.
        feedback: Human-readable feedback; empty string on success.
    """
    success: bool
    feedback: str


def _bash_validator(script_path: str) -> _Validator:
    """Wrap a bash script as a validator callable.

    The script receives state as JSON on stdin and must write JSON
    ``{"success": bool, "feedback": "..."}`` to stdout. Non-zero exit or
    invalid JSON raises an exception that propagates immediately.

    Args:
        script_path: Path to the bash script.

    Returns:
        A callable that accepts state and returns a ValidationResult.
    """
    def _validate(state: State) -> ValidationResult:
        state_json = json.dumps(state)
        result = subprocess.run(
            [script_path],
            input=state_json,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Bash validator exited with code {result.returncode}: {result.stderr}"
            )
        parsed = json.loads(result.stdout)
        return ValidationResult(success=parsed["success"], feedback=parsed.get("feedback", ""))

    return _validate


def _state_diff(before: State, after: State) -> str:
    """Compute a concise human-readable diff between two states.

    Args:
        before: State before handler execution.
        after: State after handler execution.

    Returns:
        Multi-line string describing added, changed, and removed keys.
    """
    lines: list[str] = []
    before_keys = set(before)
    after_keys = set(after)

    added = after_keys - before_keys
    removed = before_keys - after_keys
    changed = {k for k in before_keys & after_keys if before[k] != after[k]}

    def _fmt(v: object) -> str:
        s = repr(v)
        if len(s) > _MAX_VALUE_LEN:
            s = s[:_MAX_VALUE_LEN] + "..."
        return s

    for k in sorted(added):
        lines.append(f"  added   {k} = {_fmt(after[k])}")
    for k in sorted(changed):
        lines.append(f"  changed {k}: {_fmt(before[k])} -> {_fmt(after[k])}")
    for k in sorted(removed):
        lines.append(f"  removed {k}")

    return "\n".join(lines) if lines else "  (no changes)"


def ralph(
    handler: _NamedHandler,
    *,
    validator: _Validator | str,
    max_retries: int = 3,
    prompt_key: str = "prompt",
    label: str | None = None,
) -> _NamedHandler:
    """Wrap a handler with a retry-validation loop.

    On each attempt the inner handler is called, then the validator is invoked.
    If validation fails, feedback is appended to a progress log and the prompt
    is augmented with prior-attempts context before the next attempt. On
    exhaustion, ``runner.fail()`` is called which raises ``WorkflowFailedError``.

    Args:
        handler: The handler to wrap. Must be ``(Runner, State) -> State``.
        validator: Either a callable ``(State) -> ValidationResult`` or a path
            to a bash script that implements the stdin/stdout JSON contract.
        max_retries: Number of retries after the initial attempt (default 3,
            meaning 4 total attempts).
        prompt_key: State key holding the prompt to augment on retries.
        label: Name for the wrapper; defaults to ``handler.__name__``.

    Returns:
        A handler callable with ``__name__`` set to the resolved label.
    """
    resolved_label: str = label if label is not None else handler.__name__
    resolved_validator: _Validator
    if isinstance(validator, str):
        resolved_validator = _bash_validator(validator)
    else:
        resolved_validator = validator

    def _wrapper(runner: Runner, state: State) -> State:
        """Execute the wrapped handler with retry-validation logic.

        Runs up to ``max_retries + 1`` attempts. On each failure the validator
        feedback is appended to a per-run log file and the prompt is augmented
        with the failure history before the next attempt. On success the
        original prompt value is restored in the returned state. On exhaustion
        ``runner.fail()`` is called, raising ``WorkflowFailedError``.

        Args:
            runner: The active workflow runner used for progress reporting and
                log-directory resolution.
            state: Current workflow state passed to the inner handler.

        Returns:
            Updated state from the first passing attempt, with the original
            prompt value restored under ``prompt_key``.
        """
        log_dir = runner.app.log_dir(runner) if callable(runner.app.log_dir) else runner.app.log_dir
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"ralph-{resolved_label}-{runner.id}.log")

        original_prompt: object = state.get(prompt_key)
        current_state: State = state
        total_attempts = max_retries + 1

        for attempt in range(total_attempts):
            runner.report_progress(f"ralph {resolved_label}: attempt {attempt + 1}/{total_attempts}")

            if attempt > 0:
                with open(log_path) as f:
                    prior_log = f.read()
                augmented_prompt = (
                    "Previous attempts have not passed validation. Here is the history:\n\n"
                    "<prior_attempts>\n"
                    f"{prior_log}\n"
                    "</prior_attempts>\n\n"
                    "Please address the feedback and try again.\n\n"
                    f"{original_prompt}"
                )
                current_state = {**current_state, prompt_key: augmented_prompt}

            state_before = current_state
            result_state = handler(runner, current_state)

            diff = _state_diff(state_before, result_state)
            log_entry = (
                f"Attempt {attempt + 1}/{total_attempts}\n"
                f"State changes:\n{diff}\n"
            )

            validation = resolved_validator(result_state)

            if validation.success:
                _append_log(log_path, log_entry + "Validation: PASSED\n---\n")
                return {**result_state, prompt_key: original_prompt}
            else:
                log_entry += f"Validation: FAILED\nFeedback: {validation.feedback}\n---\n"
                _append_log(log_path, log_entry)
                current_state = result_state

        runner.fail(f"ralph {resolved_label}: validation failed after {total_attempts} attempts")

    _wrapper.__name__ = resolved_label
    return _wrapper


def _append_log(log_path: str, content: str) -> None:
    """Append ``content`` to the log file at ``log_path``.

    Creates the file if it does not exist.

    Args:
        log_path: Filesystem path to the log file.
        content: Text to append.
    """
    with open(log_path, "a") as f:
        f.write(content)
