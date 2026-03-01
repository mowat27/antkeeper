# Application Documentation Index

This directory contains policy and pattern documentation for the Antkeeper workflow framework.

## Files

- **releasing.md** - Packaging, dependency management, and PyPI release process. Covers the split dependency model (core vs optional dependencies), public API exports, entry points (CLI script and Python module), environment variables (`ANTKEEPER_HANDLERS_FILE`), package metadata, build system (uv_build), release checklist, publishing to PyPI, post-release verification, and version numbering strategy. Documents how Slack functionality (httpx) is a core dependency, while server features (FastAPI, uvicorn) are optional extras.

- **testing_policy.md** - Testing approach, fixture management, test structure rules, and test organization. Covers how to write tests for the framework core, including the `app` fixture for log, worktree, and state isolation, the `git_repo` fixture for all git tests (command execution, branch operations, worktrees), patterns for testing git command execution (`execute()` with stdout/stderr/empty output), branch operations (`current()` with default/switched/detached branches), git worktrees, and state persistence, CLI testing patterns (argument parsing vs integration tests with positional file arguments), API channel testing patterns (ApiChannel unit tests with FastAPI TestClient), SlackChannel testing patterns (mocking httpx), Slack server testing patterns (AsyncMock, env patching, deterministic timers, and the `slack_client_no_env` fixture pattern for testing without environment variables by popping vars after `create_app()` to handle dotenv loading), and App environment variable testing patterns (`TestAppEnvironment` class: env var setting, str conversion, restoration after success/failure, existing-var preservation, no-op for None/empty, invalid conversion propagation, and visibility to `run_workflow()` steps).

- **instrumentation.md** - Progress reporting, error handling (including `WorkflowFailedError`), run identification, logging patterns, automatic state persistence, and git integration. Explains the Channel interface for I/O (CliChannel, ApiChannel, SlackChannel), how handlers communicate status, per-run file-based logging, automatic JSON state persistence with correlation to log files, error handling differences between CLI and API execution, the `ClaudeCodeAgent` class for LLM integration (including model selection, yolo mode, and arbitrary CLI options), git command execution via `execute()`, branch operations via `current()`, `GitCommandError` exception handling, the `Worktree` class for git worktree operations, the `git_worktree` context manager for cwd restoration guarantees, and worktree naming conventions.

- **http_server.md** - HTTP server architecture and endpoint design. Covers the standard FastAPI pattern in `server.py` (routes defined with `@api.post()` decorators), the `http/__init__.py` module exporting `run_workflow_background()` to break circular imports, `webhook.py` exporting `handle_webhook()` function, `slack_events.py` exporting `SlackEventProcessor` class with explicit state management, background task execution patterns, the factory pattern in `create_app()`, and POST `/slack_event` environment variable validation (HTTP 422 when `SLACK_BOT_TOKEN` or `SLACK_BOT_USER_ID` missing, with `url_verification` exception).

- **slack.md** - Slack integration: app configuration (bot token, user ID), event handling via POST `/slack_event`, required environment variables (`SLACK_BOT_TOKEN`, `SLACK_BOT_USER_ID`) with validation behavior (HTTP 422 for missing vars, `url_verification` bypass), the `SlackEventProcessor` class managing debounce state, debounce logic for rapid @mentions (`SLACK_COOLDOWN_SECONDS`), `PendingMessage` dataclass, event routing order (thread replies, edits, deletes, mentions), `SlackChannel` for thread-based replies, timer reset behavior, and environment variable setup (`.env` support).

## Usage

These docs describe **how the framework works** and **policies for extending it**, not how to use it as a library. For usage documentation, see the main [README.md](../README.md).

If you're writing framework code (in `src/antkeeper/core/`, `src/antkeeper/channels/`, `src/antkeeper/http/`, or `src/antkeeper/llm/`), read these docs.

If you're writing application handlers, see the "Writing Handlers" section in the main README.
