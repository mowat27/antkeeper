"""Tests for the loader module."""

import os
import tempfile

import pytest

from antkeeper.loader import load_app


class TestLoadApp:
    """Test suite for load_app function."""

    def test_load_app_returns_app_object(self):
        """Load a temp file with valid app and verify it returns the app."""
        code = """\
from antkeeper.core.app import App
app = App()
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            path = f.name

        try:
            app = load_app(path)
            assert app is not None
            assert hasattr(app, "handler")
        finally:
            os.unlink(path)

    def test_load_app_file_not_found(self):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_app("/nonexistent/path/handlers.py")

    def test_load_app_missing_app_attribute(self):
        """Valid Python without app raises AttributeError."""
        code = "x = 42\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            path = f.name

        try:
            with pytest.raises(AttributeError):
                load_app(path)
        finally:
            os.unlink(path)
