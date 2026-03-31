"""Tests for the CLI channel implementation.

Verifies that CliChannel correctly handles initial state, workflow
configuration, and event reporting for command-line workflows.
"""

import pytest

from antkeeper.channels.cli import CliChannel
from antkeeper.core.domain import StreamEvent


class TestCliChannel:
    """Test suite for CliChannel class."""

    @pytest.mark.parametrize("initial_state,expected", [
        ({"k": "v"}, {"k": "v"}),
        (None, {}),
    ])
    def test_cli_channel_initial_state(self, initial_state, expected):
        """Test that CliChannel correctly handles initial state, defaulting to empty dict."""
        channel = CliChannel("wf", initial_state)
        assert channel.initial_state == expected

    def test_cli_channel_workflow_name(self):
        """Test that CliChannel stores workflow name and identifies as cli type."""
        channel = CliChannel("my_workflow")
        assert channel.workflow_name == "my_workflow"
        assert channel.type == "cli"

    def test_report_progress_event(self, capsys):
        """Progress events are printed to stdout."""
        channel = CliChannel("my_wf")
        channel.report("abc123", StreamEvent(type="progress", content="step done"))
        captured = capsys.readouterr()
        assert captured.out == "[my_wf, abc123] step done\n"

    def test_report_error_event(self, capsys):
        """Error events are printed to stderr."""
        channel = CliChannel("my_wf")
        channel.report("abc123", StreamEvent(type="error", content="something broke"))
        captured = capsys.readouterr()
        assert captured.err == "[my_wf, abc123] something broke\n"

    def test_report_internal_event_suppressed(self, capsys):
        """Internal events are suppressed."""
        channel = CliChannel("my_wf")
        channel.report("abc123", StreamEvent(type="result", content="internal", internal=True))
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
