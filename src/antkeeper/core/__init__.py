"""Antkeeper core framework components.

This module provides the core building blocks for creating workflow-based
applications with handlers, runners, and state management.

The core framework consists of:
- App: Handler registry and decorator-based workflow registration
- Runner: Workflow execution engine with logging and state persistence
- State: Type alias for workflow data (dict[str, Any])
- Channel: Protocol for I/O boundaries and workflow configuration
- WorkflowFailedError: Exception for signaling workflow failures

State conventions
-----------------
All handlers receive and return a ``State`` (``dict[str, Any]``).  State should
be treated as immutable — always return a new copy with updates rather than
modifying in place.

Several keys are reserved for framework use:

``run_id``
    Injected by ``Runner.run()`` before the first handler is called.  Uniquely
    identifies the current execution.

``workflow_name``
    Injected by ``Runner.run()`` alongside ``run_id``.

``_progress``
    Injected by ``run_workflow`` when a handler uses the step-sequencing helper.
    Shape: ``{"total": int, "completed": int}``.  Initialised once before the
    first step runs and written to the state file via ``Runner._persist_state``
    so that external observers can poll progress even while the first step is
    still executing.  Updated (and persisted again) after each step completes.

Typical usage::

    from antkeeper.core import App, Runner

    app = App()

    @app.handler
    def my_workflow(runner, state):
        runner.report_progress("Working...")
        return {**state, "result": "done"}

    channel = CliChannel(workflow_name="my_workflow", initial_state={})
    runner = Runner(app, channel)
    final_state = runner.run()
"""
