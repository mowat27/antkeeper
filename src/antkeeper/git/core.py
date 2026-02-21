"""Core git command execution utilities.

This module provides low-level utilities for executing git commands via subprocess.
It handles command execution, output capture, and error handling for git operations.
"""

import logging
import subprocess

logger = logging.getLogger("antkeeper.git.core")


class GitCommandError(Exception):
    """Raised when a git command exits with non-zero status.

    This exception is raised when any git subprocess command fails,
    carrying the stderr output as the error message.
    """


def execute(cmd: list[str]) -> str:
    """Execute a git command and return its stdout.

    Automatically prepends "git" if not already present, so both
    ``execute(["status"])`` and ``execute(["git", "status"])`` work.

    Args:
        cmd (list[str]): The command to execute. The "git" prefix is optional
            and will be auto-prepended if missing (e.g., ["status"] or ["git", "status"]).

    Returns:
        str: The stripped stdout output from the command.

    Raises:
        GitCommandError: If the command exits with a non-zero return code.
    """
    if cmd[0] != "git":
        cmd = ["git"] + cmd
    logger.debug(f"Executing: {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitCommandError(result.stderr.strip())
    return result.stdout.strip()


def latest_commit() -> dict:
    """Return the SHA and message of the most recent commit.

    Uses a unit-separator delimiter to safely parse commit messages that
    may contain quotes or special characters.

    Returns:
        A dict with "sha" and "message" keys.
    """
    output = execute(["log", "-1", "--pretty=format:%H\x1f%s"])
    sha, _, message = output.partition("\x1f")
    return {"sha": sha, "message": message}
