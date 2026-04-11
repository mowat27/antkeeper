"""Antkeeper: A lightweight workflow framework for building agentic systems.

Antkeeper provides a simple, composable architecture for defining workflows
with handlers, state management, and multiple execution channels (CLI, API,
Slack).  All public symbols are re-exported from this top-level package so
that application code only needs a single import site::

    from antkeeper import App, Runner, CliChannel, State

Public API
----------
App
    Central handler registry; use the ``@app.handler`` decorator to register
    workflow functions.
Runner
    Executes a registered workflow for a given channel, wiring together
    logging, state persistence, and progress reporting.
run_workflow
    Helper for running an ordered sequence of handler steps with state
    threading and per-step persistence.
State
    Type alias for workflow data (``dict[str, Any]``).
Channel
    Protocol that all channel implementations must satisfy.
Handler
    Protocol for workflow handler callables.
WorkflowFailedError
    Exception raised (via ``Runner.fail()``) to signal a fatal workflow error.
CliChannel
    Channel implementation for command-line execution.
ApiChannel
    Channel implementation for HTTP/API execution.
SlackChannel
    Channel implementation for Slack-driven execution.
Worktree, git_worktree
    Utilities for managing git worktrees inside workflow handlers.
make_log_dir, make_timestamp
    Timestamp helpers used when constructing log-file paths.
"""

from antkeeper.core.domain import State, Channel, Handler, WorkflowFailedError
from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.channels.cli import CliChannel
from antkeeper.channels.api import ApiChannel
from antkeeper.channels.slack import SlackChannel
from antkeeper.git import Worktree, git_worktree
from antkeeper.helpers.timestamps import make_log_dir, make_timestamp

__all__ = [
    "App",
    "Runner",
    "run_workflow",
    "State",
    "Channel",
    "Handler",
    "WorkflowFailedError",
    "CliChannel",
    "ApiChannel",
    "SlackChannel",
    "Worktree",
    "git_worktree",
    "make_log_dir",
    "make_timestamp",
]
