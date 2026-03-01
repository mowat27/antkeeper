"""Git integration for the Antkeeper framework.

This module provides git utilities including worktree management, command execution,
and branch operations.

Exports:
    Worktree: Class representing a git worktree on disk.
    WorktreeError: Exception raised when worktree operations fail.
    git_worktree: Context manager for creating, entering, and cleaning up worktrees.
    GitCommandError: Exception raised when a git command fails.
    execute: Execute an arbitrary git command and return stdout.
    current: Get the name of the current git branch.
"""

from antkeeper.git.branch import current
from antkeeper.git.core import GitCommandError, execute, latest_commit
from antkeeper.git.worktrees import Worktree, WorktreeError, git_worktree

__all__ = [
    "GitCommandError",
    "Worktree",
    "WorktreeError",
    "current",
    "execute",
    "git_worktree",
    "latest_commit",
]
