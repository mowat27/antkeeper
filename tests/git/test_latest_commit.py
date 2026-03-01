"""Tests for the latest_commit function."""

import re

from antkeeper.git.core import latest_commit


def test_latest_commit_returns_sha_and_message(git_repo):
    result = latest_commit()
    assert "sha" in result
    assert "message" in result
    assert re.match(r"^[0-9a-f]{40}$", result["sha"])
    assert result["message"] == "init"


def test_latest_commit_importable_from_git_package():
    from antkeeper.git import latest_commit as lc
    assert callable(lc)
