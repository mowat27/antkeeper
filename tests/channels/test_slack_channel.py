"""Tests for the Slack channel implementation.

Verifies SlackChannel's HTTP-based messaging capabilities, error handling,
and integration with the Slack API.
"""
from unittest.mock import patch, MagicMock

import httpx
import pytest

from antkeeper.channels.slack import SlackChannel
from antkeeper.core.domain import StreamEvent


class TestSlackChannel:
    """Test suite for SlackChannel class."""

    def _make_channel(self, **overrides):
        """Helper factory to create SlackChannel instances with test defaults."""
        defaults: dict = {
            "workflow_name": "wf",
            "slack_token": "xoxb-test-token",
            "channel_id": "C123",
            "thread_ts": "1234567890.123456",
        }
        defaults.update(overrides)
        wf: str = defaults.pop("workflow_name")
        state: dict | None = defaults.pop("initial_state", None)
        return SlackChannel(wf, state, **defaults)

    def test_slack_channel_type(self):
        """Test that SlackChannel returns correct channel type."""
        channel = self._make_channel()
        assert channel.type == "slack"

    @pytest.mark.parametrize("initial_state,expected", [
        ({"k": "v"}, {"k": "v"}),
        (None, {}),
    ])
    def test_slack_channel_initial_state(self, initial_state, expected):
        """Test that SlackChannel handles initial state correctly, defaulting to empty dict."""
        channel = self._make_channel(initial_state=initial_state)
        assert channel.initial_state == expected

    @patch("antkeeper.channels.slack.httpx.Client")
    def test_report_progress_event(self, mock_client_cls):
        """Progress events are posted to Slack thread via API."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        channel = self._make_channel()
        channel.report("run1", StreamEvent(type="progress", content="step done"))

        mock_client.post.assert_called_once_with(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": "Bearer xoxb-test-token"},
            json={
                "channel": "C123",
                "thread_ts": "1234567890.123456",
                "text": "[wf, run1] step done",
            },
        )

    @patch("antkeeper.channels.slack.httpx.Client")
    def test_report_error_event(self, mock_client_cls):
        """Error events are posted with ERROR prefix formatting."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        channel = self._make_channel()
        channel.report("run1", StreamEvent(type="error", content="something broke"))

        call_args = mock_client.post.call_args
        assert "[ERROR]" in call_args.kwargs["json"]["text"]

    @patch("antkeeper.channels.slack.httpx.Client")
    def test_report_internal_event_suppressed(self, mock_client_cls):
        """Internal events are suppressed — no Slack API call."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        channel = self._make_channel()
        channel.report("run1", StreamEvent(type="result", content="internal", internal=True))

        mock_client.post.assert_not_called()

    @patch("antkeeper.channels.slack.httpx.Client")
    def test_report_survives_http_failure(self, mock_client_cls):
        """HTTP failures during reporting are handled gracefully."""
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.HTTPError("connection failed")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        channel = self._make_channel()
        channel.report("run1", StreamEvent(type="progress", content="step done"))  # should not raise

    @patch("antkeeper.channels.slack.httpx.Client")
    def test_verbose_false_suppresses_non_progress_non_error(self, mock_client_cls):
        """Non-verbose mode suppresses assistant, tool, and result events."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        channel = self._make_channel()
        for event_type in ("assistant", "tool", "result"):
            channel.report("run1", StreamEvent(type=event_type, content="data"))
        mock_client.post.assert_not_called()

    @patch("antkeeper.channels.slack.httpx.Client")
    def test_verbose_true_shows_all_events_as_plain_text(self, mock_client_cls):
        """Verbose mode posts all event types as plain text (event.content)."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        channel = self._make_channel(verbose=True)
        channel.report("run1", StreamEvent(type="assistant", content="thinking"))
        call_args = mock_client.post.call_args
        assert "thinking" in call_args.kwargs["json"]["text"]

    @patch("antkeeper.channels.slack.httpx.Client")
    def test_empty_content_suppressed(self, mock_client_cls):
        """No Slack API call for events with empty content."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        channel = self._make_channel()
        channel.report("run1", StreamEvent(type="progress", content=""))
        mock_client.post.assert_not_called()

    def test_verbose_defaults_to_false(self):
        """Constructor defaults verbose to False."""
        channel = self._make_channel()
        assert channel.verbose is False
