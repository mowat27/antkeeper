"""Tests for the latest_commit function.

Verifies that latest_commit() returns a dict with valid sha and message fields,
and that it is importable from the top-level antkeeper.git package.
"""

import re

from antkeeper.git.core import latest_commit


def test_latest_commit_returns_sha_and_message(git_repo):
    """Test that latest_commit() returns a dict containing a valid sha and commit message.

    Args:
        git_repo: Pytest fixture providing a temporary Git repository.
    """
    result = latest_commit()
    assert "sha" in result
    assert "message" in result
    assert re.match(r"^[0-9a-f]{40}$", result["sha"])
    assert result["message"] == "init"


def test_latest_commit_importable_from_git_package():
    """Test that latest_commit is importable from the antkeeper.git package."""
    from antkeeper.git import latest_commit as lc
    assert callable(lc)
