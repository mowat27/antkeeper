"""Tests for the built-in claude_code handlers package."""

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
    assert isinstance(app, App)


def test_app_has_expected_handlers():
    assert len(app.handlers) == 11
    assert set(app.handlers.keys()) == EXPECTED_HANDLERS
