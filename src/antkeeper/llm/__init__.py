"""LLM agent abstractions for Antkeeper workflows.

This module defines the Agent protocol that all LLM implementations must follow.
Agents provide a uniform interface for executing prompts regardless of the
underlying LLM provider (Claude Code CLI, OpenAI, etc.).
"""

from collections.abc import Iterator
from typing import Protocol

from antkeeper.core.domain import StreamEvent


class Agent(Protocol):
    """Protocol for LLM agents that execute prompts.

    Implementations must provide a prompt() method that accepts a string
    and returns an iterator of StreamEvents. The protocol allows for dependency
    injection and easy testing via mock agents.
    """

    def prompt(self, prompt: str) -> Iterator[StreamEvent]:
        """Execute a prompt and return a stream of events.

        Args:
            prompt: The prompt string to send to the LLM.

        Returns:
            An iterator of StreamEvent instances.

        Raises:
            AgentExecutionError: If the agent fails to execute the prompt.

        """
        ...
