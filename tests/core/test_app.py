"""Tests for App constructor handlers param and add_handler method."""

from antkeeper.core.app import App


def _dummy_handler(runner, state):
    return state


def _another_handler(runner, state):
    return state


def test_app_constructor_with_handlers_dict():
    app = App(handlers={"greet": _dummy_handler})
    assert app.handlers["greet"] is _dummy_handler


def test_app_constructor_default_no_handlers():
    app = App()
    assert app.handlers == {}


def test_add_handler_registers_function():
    app = App()
    app.add_handler(_dummy_handler)
    assert app.handlers["_dummy_handler"] is _dummy_handler


def test_add_handler_overwrites_existing():
    app = App()
    app.add_handler(_dummy_handler)
    app.add_handler(_dummy_handler)  # same name, no error
    # overwrite with a different function that has the same __name__
    first = _another_handler
    first.__name__ = "_dummy_handler"
    app.add_handler(first)
    assert app.handlers["_dummy_handler"] is first


def test_app_constructor_stores_env():
    app = App(env={"FOO": "bar"})
    assert app.env == {"FOO": "bar"}


def test_app_constructor_default_env_is_none():
    app = App()
    assert app.env is None
