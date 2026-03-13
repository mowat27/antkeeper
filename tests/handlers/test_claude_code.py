"""Tests for the claude_code handlers package."""

from antkeeper.handlers.claude_code import cc_handler


def test_cc_handler_importable_from_package():
    """Verify cc_handler is importable and callable."""
    assert callable(cc_handler)
