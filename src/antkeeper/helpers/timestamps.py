"""Timestamp and log-directory utilities for handler code."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from antkeeper.core.runner import Runner


def make_timestamp() -> str:
    """Return the current time as a 14-character YYYYMMDDHHmmss string."""
    return datetime.now().strftime("%Y%m%d%H%M%S")


def make_log_dir(base_dir: str) -> Callable[[Runner], str]:
    """Return a callable that produces a log directory path for a runner.

    The returned callable is compatible with ``App(log_dir=...)``.

    Args:
        base_dir: Root directory under which log directories are created.

    Returns:
        A callable ``(runner) -> str`` producing
        ``"{base_dir}/{timestamp}-{runner.id}/"``.
    """

    def _log_dir(runner: Runner) -> str:
        """Return a timestamped log directory path for the given runner."""
        return f"{base_dir}/{make_timestamp()}-{runner.id}/"

    return _log_dir
