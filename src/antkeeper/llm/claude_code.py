"""Claude Code agent implementation.

This module provides a concrete Agent implementation that executes prompts
by delegating to the `claude` CLI subprocess. The agent wraps subprocess
calls and handles command construction, error reporting, and response parsing.
"""

import json
import logging
import subprocess

from antkeeper.llm.errors import AgentExecutionError

logger = logging.getLogger("antkeeper.llm.claude_code")


class ClaudeCodeAgent:
    """Agent that delegates prompts to the Claude Code CLI.

    This agent implementation shells out to the `claude` binary installed
    on the system. It constructs appropriate command-line arguments, handles
    subprocess execution, and converts CLI errors into AgentExecutionErrors.

    Attributes:
        model: Optional model identifier passed to the Claude CLI via --model flag.

    Example:
        >>> agent = ClaudeCodeAgent(model="claude-opus-4")
        >>> response = agent.prompt("What is 2+2?")

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

    def prompt(self, prompt: str) -> str:
        """Execute a prompt via `claude -p` and return stdout.

        Constructs a subprocess call to the Claude CLI with the -p flag for
        prompt execution. If a model was specified during initialization, adds
        the --model flag. Logs all prompt activity and responses.

        Args:
            prompt: The prompt string to send to Claude Code CLI.

        Returns:
            The CLI's response as a string (stdout).

        Raises:
            AgentExecutionError: If the claude binary is not found or if the
                subprocess exits with a non-zero status code.

        """
        opts_list = self.opts or []
        cmd = ["claude"]
        if self.model and "--model" not in opts_list:
            cmd.extend(["--model", self.model])
        if self.yolo and "--dangerously-skip-permissions" not in opts_list:
            cmd.append("--dangerously-skip-permissions")
        if not any(o.startswith("--output-format") for o in opts_list):
            cmd.extend(["--output-format", "json"])
        cmd.extend(opts_list)
        cmd.extend(["-p", prompt])
        logger.info(f"LLM prompt submitted (length={len(prompt)} chars)")
        logger.debug(f"LLM prompt content: {prompt}")
        logger.debug(f"LLM subprocess command: {cmd}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            logger.error("claude binary not found")
            raise AgentExecutionError("claude binary not found")
        if result.returncode != 0:
            logger.error(f"claude exited with code {result.returncode}: {result.stderr}")
            raise AgentExecutionError(
                f"claude exited with code {result.returncode}: {result.stderr}"
            )
        try:
            envelope = json.loads(result.stdout)
            result_text = envelope["result"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"Failed to parse claude JSON output: {result.stdout!r}") from exc
        session_id = envelope.get("session_id")
        logger.info(f"LLM session_id: {session_id}")
        logger.info(f"LLM response received (length={len(result_text)} chars)")
        logger.debug(f"LLM response content: {result_text}")
        return result_text


def run_prompt(prompt: str, logger: logging.Logger, model: str | None = None) -> str:
    """Execute a prompt via ClaudeCodeAgent and return the response.

    Convenience wrapper that creates an agent with yolo=True, sends the prompt,
    and returns the response string.

    Args:
        prompt: The prompt string to send.
        logger: Logger for caller-level context.
        model: Optional model identifier passed to the agent.

    Returns:
        The agent's response string.
    """
    logger.debug(f"run_prompt called (prompt length={len(prompt)} chars)")
    agent = ClaudeCodeAgent(model=model, yolo=True)
    return agent.prompt(prompt)
