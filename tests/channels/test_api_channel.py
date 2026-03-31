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
        """Progress events are printed to stdout as plain text."""
        channel = ApiChannel("my_wf")
        channel.report("abc123", StreamEvent(type="progress", content="step done"))
        captured = capsys.readouterr()
        assert captured.out == "[my_wf, abc123] step done\n"

    def test_report_error_event(self, capsys):
        """Error events are printed to stderr as plain text."""
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

    def test_verbose_false_suppresses_non_progress_non_error(self, capsys):
        """Non-verbose mode suppresses assistant, tool, and result events."""
        channel = ApiChannel("my_wf")
        for event_type in ("assistant", "tool", "result"):
            channel.report("abc123", StreamEvent(type=event_type, content="data"))
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_verbose_true_shows_all_events_as_json(self, capsys):
        """Verbose mode shows all event types with content as JSON."""
        channel = ApiChannel("my_wf", verbose=True)
        event = StreamEvent(type="assistant", content="thinking")
        channel.report("abc123", event)
        captured = capsys.readouterr()
        assert event.to_json() in captured.out

    def test_empty_content_suppressed(self, capsys):
        """Events with empty content produce no output regardless of verbose."""
        for verbose in (True, False):
            channel = ApiChannel("my_wf", verbose=verbose)
            channel.report("abc123", StreamEvent(type="progress", content=""))
            captured = capsys.readouterr()
            assert captured.out == ""
            assert captured.err == ""

    def test_verbose_defaults_to_false(self):
        """Constructor defaults verbose to False."""
        channel = ApiChannel("my_wf")
        assert channel.verbose is False
