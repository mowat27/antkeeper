"""Tests for the API channel implementation.

Tests the ApiChannel's type, state handling, and output reporting capabilities.
"""

import pytest

from antkeeper.channels.api import ApiChannel
from antkeeper.core.domain import StreamEvent


class TestApiChannel:
    """Test suite for ApiChannel class."""
    def test_api_channel_type(self):
        """Test that ApiChannel returns correct channel type."""
        channel = ApiChannel("wf")
        assert channel.type == "api"

    @pytest.mark.parametrize("initial_state,expected", [
        ({"k": "v"}, {"k": "v"}),
        (None, {}),
    ])
    def test_api_channel_initial_state(self, initial_state, expected):
        """Test that ApiChannel handles initial state correctly, defaulting to empty dict."""
        channel = ApiChannel("wf", initial_state)
        assert channel.initial_state == expected

    def test_report_progress_event(self, capsys):
        """Progress events are printed to stdout."""
        channel = ApiChannel("my_wf")
        channel.report("abc123", StreamEvent(type="progress", content="step done"))
        captured = capsys.readouterr()
        assert captured.out == "[my_wf, abc123] step done\n"

    def test_report_error_event(self, capsys):
        """Error events are printed to stderr."""
        channel = ApiChannel("my_wf")
        channel.report("abc123", StreamEvent(type="error", content="something broke"))
        captured = capsys.readouterr()
        assert captured.err == "[my_wf, abc123] something broke\n"

    def test_report_internal_event_suppressed(self, capsys):
        """Internal events are suppressed."""
        channel = ApiChannel("my_wf")
        channel.report("abc123", StreamEvent(type="result", content="internal", internal=True))
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
