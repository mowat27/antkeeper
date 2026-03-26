"""Tests for GitHub CLI helpers."""

import json
import subprocess
from unittest.mock import Mock, patch

import pytest

from antkeeper.helpers.github import build_issues_prompt, fetch_gh_issue


class TestFetchGhIssue:
    """Test suite for fetch_gh_issue function."""

    def test_fetch_gh_issue_returns_parsed_json(self):
        """Test that fetch_gh_issue parses and returns JSON from gh CLI."""
        mock_response = {"number": 42, "title": "bug"}
        with patch("antkeeper.helpers.github.subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=json.dumps(mock_response))
            result = fetch_gh_issue(42)
            assert result == mock_response
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert kwargs["check"] is True

    def test_fetch_gh_issue_raises_on_nonzero_returncode(self):
        """Test that fetch_gh_issue propagates CalledProcessError."""
        with patch("antkeeper.helpers.github.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
            with pytest.raises(subprocess.CalledProcessError):
                fetch_gh_issue(42)

    def test_fetch_gh_issue_raises_on_gh_not_found(self):
        """Test that fetch_gh_issue propagates FileNotFoundError."""
        with patch("antkeeper.helpers.github.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with pytest.raises(FileNotFoundError):
                fetch_gh_issue(42)

    def test_fetch_gh_issue_raises_on_invalid_json(self):
        """Test that fetch_gh_issue propagates JSONDecodeError."""
        with patch("antkeeper.helpers.github.subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="not json")
            with pytest.raises(json.JSONDecodeError):
                fetch_gh_issue(42)


class TestBuildIssuesPrompt:
    """Test suite for build_issues_prompt function."""

    def test_single_issue_prompt(self):
        """Test prompt format for single issue."""
        issue = {"number": 42, "title": "bug", "body": "description"}
        prompt = build_issues_prompt([issue])
        assert "Fix the following GitHub issue(s)." in prompt
        assert "--- Issue #42 ---" in prompt
        assert json.dumps(issue, indent=2) in prompt

    def test_multiple_issues_prompt(self):
        """Test prompt format for multiple issues."""
        issues = [
            {"number": 42, "title": "bug1"},
            {"number": 99, "title": "bug2"},
        ]
        prompt = build_issues_prompt(issues)
        assert "--- Issue #42 ---" in prompt
        assert "--- Issue #99 ---" in prompt
