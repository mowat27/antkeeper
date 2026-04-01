"""Channel implementations for Antkeeper workflow framework.

This package provides channel adapters that connect workflows to different
execution environments. Each channel implements a common protocol with
report_progress() and report_error() methods, allowing workflows to run
in various contexts:

- CliChannel: Command-line interface environments (stdout/stderr)
- ApiChannel: Web servers and HTTP APIs (server logs)
- SlackChannel: Slack workspace threads (via Slack Web API)
- ProgrammaticChannel: In-process execution with callback-based event delivery

Channels encapsulate I/O and state initialization, keeping workflow handlers
environment-agnostic.
"""
