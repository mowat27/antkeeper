"""Tests for timestamp and log-directory helpers."""

from datetime import datetime
from unittest.mock import Mock, patch

from antkeeper.core.runner import Runner
from antkeeper.helpers.timestamps import make_log_dir, make_timestamp

FIXED_DT = datetime(2026, 3, 14, 9, 5, 7)


def test_make_timestamp_format():
    """Test that make_timestamp returns YYYYMMDDHHmmss for a known datetime."""
    with patch("antkeeper.helpers.timestamps.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DT
        assert make_timestamp() == "20260314090507"


def test_make_log_dir_returns_callable():
    """Test that make_log_dir returns a callable."""
    result = make_log_dir("logs")
    assert callable(result)


def test_make_log_dir_produces_correct_path():
    """Test that the callable produces the expected path with timestamp and runner id."""
    with patch("antkeeper.helpers.timestamps.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DT
        mock_runner = Mock(spec=Runner, id="abc123")
        log_dir_fn = make_log_dir("/var/logs")
        assert log_dir_fn(mock_runner) == "/var/logs/20260314090507-abc123/"


def test_make_log_dir_uses_timestamp_at_call_time():
    """Test that the timestamp is captured at invocation time, not factory time."""
    log_dir_fn = make_log_dir("out")
    with patch("antkeeper.helpers.timestamps.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2099, 12, 31, 23, 59, 59)
        mock_runner = Mock(spec=Runner, id="run1")
        assert log_dir_fn(mock_runner) == "out/20991231235959-run1/"
