"""Shared app-loading utility, used by CLI and server."""

import importlib.util


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
    spec = importlib.util.spec_from_file_location("agents", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app
