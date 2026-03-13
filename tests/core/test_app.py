"""Tests for App constructor handlers param and add_handler method.

Verifies that App correctly stores handlers supplied at construction time,
supports dynamic handler registration via add_handler, and manages the
optional env parameter.
"""

from antkeeper.core.app import App


def _dummy_handler(runner, state):
    return state


def _another_handler(runner, state):
    return state


def test_app_constructor_with_handlers_dict():
    """Test that App stores a handlers dict passed at construction time."""
    app = App(handlers={"greet": _dummy_handler})
    assert app.handlers["greet"] is _dummy_handler


def test_app_constructor_default_no_handlers():
    """Test that App defaults to an empty handlers dict when none are provided."""
    app = App()
    assert app.handlers == {}


def test_add_handler_registers_function():
    """Test that add_handler registers a function using its __name__ as the key."""
    app = App()
    app.add_handler(_dummy_handler)
    assert app.handlers["_dummy_handler"] is _dummy_handler


def test_add_handler_overwrites_existing():
    """Test that add_handler silently overwrites an existing handler with the same name."""
    app = App()
    app.add_handler(_dummy_handler)
    app.add_handler(_dummy_handler)  # same name, no error
    # overwrite with a different function that has the same __name__
    first = _another_handler
    first.__name__ = "_dummy_handler"
    app.add_handler(first)
    assert app.handlers["_dummy_handler"] is first


def test_app_constructor_stores_env():
    """Test that App stores the env dict passed at construction time."""
    app = App(env={"FOO": "bar"})
    assert app.env == {"FOO": "bar"}


def test_app_constructor_default_env_is_none():
    """Test that App defaults env to None when not provided."""
    app = App()
    assert app.env is None
