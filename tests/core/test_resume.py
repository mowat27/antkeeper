"""Tests for resume-specific behaviour: state loading, skip consumption, error paths."""

import json
import os
import tempfile

import pytest

from antkeeper.cli import _load_state_by_run_id


class TestLoadStateByRunId:
    """Tests for _load_state_by_run_id helper."""

    def test_finds_matching_file(self):
        """Write a state file and verify it loads correctly."""
        state = {"workflow_name": "my_wf", "_progress": {"total": 3, "completed": 1}}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "20260316-abcd1234.json")
            with open(path, "w") as f:
                json.dump(state, f)
            loaded, found_path = _load_state_by_run_id(d, "abcd1234")
            assert loaded == state
            assert found_path == path

    def test_not_found_raises(self):
        """Empty dir raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as d:
            with pytest.raises(FileNotFoundError):
                _load_state_by_run_id(d, "deadbeef")

    def test_multiple_files_finds_correct_one(self):
        """Multiple state files, finds the one matching the run_id."""
        target_state = {"workflow_name": "target", "_progress": {"total": 2, "completed": 1}}
        other_state = {"workflow_name": "other", "_progress": {"total": 2, "completed": 2}}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "20260316-aaaa1111.json"), "w") as f:
                json.dump(other_state, f)
            target_path = os.path.join(d, "20260316-bbbb2222.json")
            with open(target_path, "w") as f:
                json.dump(target_state, f)
            loaded, found_path = _load_state_by_run_id(d, "bbbb2222")
            assert loaded == target_state
            assert found_path == target_path
