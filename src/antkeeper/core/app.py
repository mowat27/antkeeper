"""Application framework for registering and managing workflow handlers.

This module provides:
- _app_env: Context manager that temporarily sets os.environ variables for a block
- App: Central registry for workflow handlers with decorator-based registration
- run_workflow: Helper function for executing sequential handler chains

The App class is the main entry point for defining workflows. Use the @app.handler
decorator to register workflow functions, then pass the app to a Runner for execution.
"""
from __future__ import annotations

import functools
import os
from contextlib import contextmanager
from typing import Any, Callable, Generator, NoReturn, TYPE_CHECKING

from antkeeper.core.domain import State

if TYPE_CHECKING:
    from antkeeper.core.runner import Runner


# -- Core ----------------------------------------------------------------------


@contextmanager
def _app_env(env: dict[str, Any] | None) -> Generator[None]:
    """Set environment variables for the duration of a block, then restore originals.

    A no-op context manager when ``env`` is ``None`` or an empty dict. For non-empty
    ``env``, saves the current values of all named variables, sets them in
    ``os.environ`` (converting each value with ``str()``), yields control, then
    restores the saved values in a ``finally`` block so that cleanup is guaranteed
    even if the body raises.

    If ``str()`` conversion raises for any value the exception propagates immediately;
    the ``finally`` block still restores any variables that were already set.

    Args:
        env: A mapping of environment variable names to values, or ``None``.

    Yields:
        None
    """
    if not env:
        yield
        return

    saved: dict[str, str | None] = {k: os.environ.get(k) for k in env}
    try:
        for k, v in env.items():
            os.environ[k] = str(v)
        yield
    finally:
        for k, original in saved.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original


class App:
    """Central registry for workflow handlers.

    The App class manages handler registration and retrieval, allowing workflows
    to be defined as decorated functions and later executed by runners. Each app
    instance maintains its own handler registry and log directory configuration.

    Example:
        >>> app = App(log_dir="logs/")
        >>> @app.handler
        ... def my_workflow(runner: Runner, state: State) -> State:
        ...     return {**state, "result": "done"}

    Attributes:
        handlers: Dictionary mapping handler names to their functions.
        log_dir: Directory path where Runner instances will write log files.
        worktree_dir: Directory path where git worktrees will be created.
        state_dir: Directory path where Runner instances will write state files.
        env: Optional dict of environment variable names to values that will be
            temporarily applied to os.environ for each handler invocation.
    """
    def __init__(self, log_dir: str = "agents/logs/", worktree_dir: str = "trees/", state_dir: str = ".antkeeper/state/", env: dict[str, Any] | None = None, handlers: dict[str, Callable] | None = None) -> None:
        """Initialize a new App instance.

        Creates an empty handler registry and sets directory paths for logs,
        worktrees, and state files that will be used by Runner instances.

        Args:
            log_dir: Directory for log files. Defaults to "agents/logs/".
            worktree_dir: Directory for git worktrees. Defaults to "trees/".
            state_dir: Directory for state files. Defaults to ".antkeeper/state/".
            env: Optional dict of environment variable names to values. When set,
                these are exported to os.environ before each handler runs and
                restored afterward. Values are converted to str().
            handlers: Optional dict of pre-registered handlers to merge in.
        """
        self.handlers = {}
        self.log_dir = log_dir
        self.worktree_dir = worktree_dir
        self.state_dir = state_dir
        self.env = env
        if handlers:
            self.handlers.update(handlers)

    def add_handler(self, fn: Callable) -> None:
        """Register a function as a handler using its __name__ as the key.

        Programmatic equivalent of @app.handler. If a handler with the same
        name already exists, it is overwritten.

        Args:
            fn: The handler function to register.
        """
        self.handlers[fn.__name__] = fn  # type: ignore[attr-defined]

    def handler(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a function as a workflow handler.

        This decorator registers a workflow handler function and wraps it for execution.
        The handler's name becomes its registry key for lookup by runners.

        Args:
            fn: A callable that accepts a Runner and State and returns a State
                or NoReturn (exits). The function's name is used as the handler key.

        Returns:
            The wrapped handler function that can be invoked by runners.
        """
        @functools.wraps(fn)
        def wrapper(runner: Runner, state: State) -> State | NoReturn:
            return fn(runner, state)

        name: str = fn.__name__  # type: ignore[attr-defined]
        self.handlers[name] = fn
        return wrapper

    def get_handler(self, name: str) -> Callable[[Runner, State], State | NoReturn]:
        """Retrieve a registered handler by name.

        Args:
            name: The handler function name to retrieve.

        Returns:
            The handler callable that accepts a Runner and State.

        Raises:
            ValueError: If no handler with the given name is registered.
        """
        try:
            return self.handlers[name]
        except KeyError:
            raise ValueError(f"Unknown handler: {name}")


def run_workflow(runner: Runner, state: State, steps: list[Callable[[Runner, State], State]]) -> State:
    """Execute a sequence of workflow steps with state threading.

    Each step receives the runner and current state, processes it, and returns
    an updated state that is passed to the next step. All steps are logged.

    Args:
        runner: The Runner instance executing the workflow.
        state: The initial state dictionary.
        steps: A list of callables that each accept (runner, state) and return
               the updated state.

    Returns:
        The final state after all steps have been executed.
    """
    runner.logger.info(f"run_workflow started with {len(steps)} steps: {[getattr(s, '__name__', repr(s)) for s in steps]}")
    for step in steps:
        step_name = getattr(step, "__name__", repr(step))
        runner.logger.info(f"Executing step: {step_name}")
        state = step(runner, state)
        runner._persist_state(state)
        runner.logger.debug(f"Step completed: {step_name}, state keys: {list(state.keys())}")
    runner.logger.info("run_workflow completed")
    return state
