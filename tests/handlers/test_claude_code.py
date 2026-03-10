"""Tests for the built-in claude_code handlers package.

Verifies that the claude_code handler package exposes a correctly configured
App instance with all expected workflow handlers registered.
"""

from antkeeper.core.app import App
from antkeeper.handlers.claude_code import app


EXPECTED_HANDLERS = {
    "healthcheck",
    "derive_feature",
    "specify",
    "commit",
    "branch_if_on_main",
    "implement",
    "push",
    "raise_a_pr",
    "specify_implement",
    "sdlc",
    "sdlc_iso",
}


def test_package_exposes_app_instance():
    """Test that the claude_code package exports an App instance."""
    assert isinstance(app, App)


def test_app_has_expected_handlers():
    """Test that the App instance has exactly the expected set of handlers registered."""
    assert len(app.handlers) == 11
    assert set(app.handlers.keys()) == EXPECTED_HANDLERS
