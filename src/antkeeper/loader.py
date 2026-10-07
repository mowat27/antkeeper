"""Shared app-loading utility, used by CLI and server."""

import importlib.util
from types import ModuleType


def load_module(path: str) -> ModuleType:
    """Dynamically import a handlers file as a module.

    Args:
        path: File path to the Python module.

    Returns:
        The executed module.

    Raises:
        FileNotFoundError: If the file cannot be found or the module spec
            cannot be created.
    """
    spec = importlib.util.spec_from_file_location("agents", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_app(path: str):
    """Dynamically load an Antkeeper app from a Python file.

    Uses importlib to dynamically import a Python module and extract its
    'app' attribute, which should be an instance of antkeeper.core.app.App.

    Args:
        path: File path to the Python module containing the app.

    Returns:
        App: The app object from the loaded module.

    Raises:
        FileNotFoundError: If the file cannot be found or the module spec
            cannot be created.
        AttributeError: If the loaded module does not have an 'app' attribute.
    """
    return load_module(path).app
