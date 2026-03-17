"""CLI parsing and integration tests.

Tests command-line argument parsing, state pair parsing, and end-to-end
CLI workflow execution with dynamic handler loading.
"""

import argparse
import io
import json
import os
import subprocess
import tempfile
import textwrap
from unittest.mock import Mock, patch

import pytest

from antkeeper.cli import build_issues_prompt, fetch_gh_issue, main, parse_state_pairs


class TestParseStatePairs:
    """Test suite for parse_state_pairs function."""

    def test_parse_empty_pairs(self):
        """Test parsing state pairs with no initial state provided."""
        assert parse_state_pairs([]) == {}

    def test_parse_run_with_state_pairs(self):
        """Test parsing key=value pairs into initial state dictionary."""
        pairs = ["key=val", "k2=v2"]
        assert parse_state_pairs(pairs) == {"key": "val", "k2": "v2"}

    def test_invalid_state_pair_exits(self):
        """Test that malformed state pairs cause the parser to exit."""
        with pytest.raises(SystemExit):
            parse_state_pairs(["no_equals_sign"])


class TestArgParsing:
    """Test suite for command-line argument parsing."""

    def _build_parser(self):
        """Build and configure argument parser for testing.

        Returns:
            argparse.ArgumentParser: Configured parser with run subcommand.
        """
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        common = argparse.ArgumentParser(add_help=False)
        common.add_argument("--agents-file", default="handlers.py")
        common.add_argument("--initial-state", action="append", default=[])
        common.add_argument("--model", default=None)
        common.add_argument("workflow_name")
        run_p = sub.add_parser("run", parents=[common])
        run_p.add_argument("prompt_files", nargs="*")
        return parser

    def test_parse_run_with_workflow_name(self):
        """Test that workflow_name positional argument is parsed."""
        args = self._build_parser().parse_args(["run", "my_handler"])
        assert args.workflow_name == "my_handler"

    def test_parse_run_with_model_flag(self):
        """Test that --model flag is parsed."""
        args = self._build_parser().parse_args(["run", "--model", "opus", "my_handler"])
        assert args.model == "opus"

    def test_parse_run_with_agents_file(self):
        """Test that custom agents file path is correctly parsed."""
        args = self._build_parser().parse_args(["run", "--agents-file", "custom.py", "my_handler"])
        assert args.agents_file == "custom.py"

    def test_parse_run_with_prompt_files(self):
        """Test that positional file args are captured in args.prompt_files."""
        args = self._build_parser().parse_args(["run", "my_handler", "file1.md", "file2.md"])
        assert args.prompt_files == ["file1.md", "file2.md"]

    def test_parse_run_missing_workflow_name_exits(self):
        """Test that missing workflow name argument causes parser to exit."""
        with pytest.raises(SystemExit):
            self._build_parser().parse_args(["run"])


class TestInitArgParsing:
    """Test suite for init subcommand argument parsing."""

    def _build_parser(self):
        """Build and configure argument parser for init subcommand testing.

        Returns:
            argparse.ArgumentParser: Configured parser with init subcommand.
        """
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        init_p = sub.add_parser("init")
        init_p.add_argument("path", nargs="?", default=".")
        return parser

    def test_parse_init_defaults_path_to_dot(self):
        """Test that init command defaults path to current directory."""
        args = self._build_parser().parse_args(["init"])
        assert args.command == "init"
        assert args.path == "."

    def test_parse_init_with_explicit_path(self):
        """Test that init command accepts explicit path argument."""
        args = self._build_parser().parse_args(["init", "my_project"])
        assert args.path == "my_project"


class TestInitIntegration:
    """Integration tests for the init subcommand."""

    def test_init_creates_handlers_file(self, monkeypatch, capsys):
        """Test that init command creates handlers.py file with boilerplate."""
        tmpdir = tempfile.mkdtemp()
        try:
            monkeypatch.setattr("sys.argv", ["antkeeper", "init", tmpdir])
            main()
            target = os.path.join(tmpdir, "handlers.py")
            assert os.path.exists(target)
            content = open(target).read()
            assert "app = App()" in content
            assert "def healthcheck" in content
        finally:
            handlers = os.path.join(tmpdir, "handlers.py")
            if os.path.exists(handlers):
                os.unlink(handlers)
            os.rmdir(tmpdir)

    def test_init_prints_env_info(self, monkeypatch, capsys):
        """Test that init command prints environment variable information."""
        tmpdir = tempfile.mkdtemp()
        try:
            monkeypatch.setattr("sys.argv", ["antkeeper", "init", tmpdir])
            main()
            captured = capsys.readouterr()
            assert "Created handlers.py" in captured.out
            assert "ANTKEEPER_HANDLERS_FILE" in captured.out
        finally:
            handlers = os.path.join(tmpdir, "handlers.py")
            if os.path.exists(handlers):
                os.unlink(handlers)
            os.rmdir(tmpdir)

    def test_init_errors_if_handlers_exists(self, monkeypatch, capsys):
        """Test that init command exits with error if handlers.py already exists."""
        tmpdir = tempfile.mkdtemp()
        handlers = os.path.join(tmpdir, "handlers.py")
        try:
            with open(handlers, "w") as f:
                f.write("# existing\n")
            monkeypatch.setattr("sys.argv", ["antkeeper", "init", tmpdir])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "already exists" in captured.err
        finally:
            if os.path.exists(handlers):
                os.unlink(handlers)
            os.rmdir(tmpdir)

    def test_init_default_path_uses_cwd(self, monkeypatch, capsys):
        """Test that init command without path argument uses current working directory."""
        tmpdir = tempfile.mkdtemp()
        try:
            monkeypatch.chdir(tmpdir)
            monkeypatch.setattr("sys.argv", ["antkeeper", "init"])
            main()
            target = os.path.join(tmpdir, "handlers.py")
            assert os.path.exists(target)
        finally:
            handlers = os.path.join(tmpdir, "handlers.py")
            if os.path.exists(handlers):
                os.unlink(handlers)
            os.rmdir(tmpdir)

    def test_init_errors_if_directory_missing(self, monkeypatch, capsys):
        """Test that init command exits with error if target directory doesn't exist."""
        tmpdir = tempfile.mkdtemp()
        os.rmdir(tmpdir)
        monkeypatch.setattr("sys.argv", ["antkeeper", "init", tmpdir])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err


class TestCliIntegration:
    """Integration tests for end-to-end CLI workflow execution."""

    def test_cli_loads_agents_file_and_runs(self, monkeypatch, capsys):
        """Test end-to-end CLI execution with dynamic handler loading from file."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def add_1(runner, state: State) -> State:
                return {{**state, "result": int(state["result"]) + 1}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            monkeypatch.setattr("sys.stdin.isatty", lambda: True)
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "run",
                "--agents-file", agents_path,
                "--initial-state", "result=10",
                "add_1",
            ])
            main()
            captured = capsys.readouterr()
            assert "11" in captured.out
        finally:
            os.unlink(agents_path)

    def test_prompt_file_loaded_into_state(self, monkeypatch, capsys):
        """Test that a positional file arg reads contents into state['prompt']."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def echo(runner, state: State) -> State:
                return {{**state, "result": f"prompt={{state['prompt']}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        prompt_content = "hello from file"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as pf:
            pf.write(prompt_content)
            pf.flush()
            prompt_path = pf.name

        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "run",
                "--agents-file", agents_path,
                "echo", prompt_path,
            ])
            main()
            captured = capsys.readouterr()
            assert "prompt=hello from file" in captured.out
        finally:
            os.unlink(agents_path)
            os.unlink(prompt_path)

    def test_prompt_file_not_found_exits(self, monkeypatch, capsys):
        """Test that a nonexistent positional file path prints error and exits 1."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def echo(runner, state: State) -> State:
                return state
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "run",
                "--agents-file", agents_path,
                "echo", "/nonexistent/path.md",
            ])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "file not found" in captured.err.lower()
        finally:
            os.unlink(agents_path)

    def test_prompt_and_model_merged_into_state(self, monkeypatch, capsys):
        """Test that positional file and --model flag are merged into handler state."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def echo(runner, state: State) -> State:
                return {{**state, "result": f"prompt={{state['prompt']}},model={{state['model']}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        prompt_content = "hello world"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as pf:
            pf.write(prompt_content)
            pf.flush()
            prompt_path = pf.name

        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "run",
                "--agents-file", agents_path,
                "--model", "opus",
                "echo", prompt_path,
            ])
            main()
            captured = capsys.readouterr()
            assert "prompt=hello world" in captured.out
            assert "model=opus" in captured.out
        finally:
            os.unlink(agents_path)
            os.unlink(prompt_path)

    def test_multiple_files_concatenated(self, monkeypatch, capsys):
        """Test that multiple positional files are concatenated into state['prompt']."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def echo(runner, state: State) -> State:
                return {{**state, "result": f"prompt={{state['prompt']}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f1:
            f1.write("hello\n")
            f1.flush()
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f2:
            f2.write("world\n")
            f2.flush()
            path2 = f2.name

        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "run",
                "--agents-file", agents_path,
                "echo", path1, path2,
            ])
            main()
            captured = capsys.readouterr()
            assert "prompt=hello\\nworld\\n" in captured.out
        finally:
            os.unlink(agents_path)
            os.unlink(path1)
            os.unlink(path2)

    def test_stdin_read_as_prompt(self, monkeypatch, capsys):
        """Test that piped stdin content becomes state['prompt'] when no files provided."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def echo(runner, state: State) -> State:
                return {{**state, "result": f"prompt={{state['prompt']}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
            monkeypatch.setattr("sys.stdin.isatty", lambda: False)
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "run",
                "--agents-file", agents_path,
                "echo",
            ])
            main()
            captured = capsys.readouterr()
            assert "prompt=from stdin" in captured.out
        finally:
            os.unlink(agents_path)

    def test_run_command_catches_workflow_failed_error(self, monkeypatch, capsys):
        """Test that CLI run catches WorkflowFailedError, prints to stderr, exits 1."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def blow_up(runner, state: State) -> State:
                runner.fail("something went wrong")
                return state
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            monkeypatch.setattr("sys.stdin.isatty", lambda: True)
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "run",
                "--agents-file", agents_path,
                "blow_up",
            ])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "something went wrong" in captured.err
        finally:
            os.unlink(agents_path)


class TestFetchGhIssue:
    """Test suite for fetch_gh_issue function."""

    def test_fetch_gh_issue_returns_parsed_json(self):
        """Test that fetch_gh_issue parses and returns JSON from gh CLI."""
        mock_response = {"number": 42, "title": "bug"}
        with patch("antkeeper.cli.subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=json.dumps(mock_response))
            result = fetch_gh_issue(42)
            assert result == mock_response
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert kwargs["check"] is True

    def test_fetch_gh_issue_raises_on_nonzero_returncode(self):
        """Test that fetch_gh_issue propagates CalledProcessError."""
        with patch("antkeeper.cli.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
            with pytest.raises(subprocess.CalledProcessError):
                fetch_gh_issue(42)

    def test_fetch_gh_issue_raises_on_gh_not_found(self):
        """Test that fetch_gh_issue propagates FileNotFoundError."""
        with patch("antkeeper.cli.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with pytest.raises(FileNotFoundError):
                fetch_gh_issue(42)

    def test_fetch_gh_issue_raises_on_invalid_json(self):
        """Test that fetch_gh_issue propagates JSONDecodeError."""
        with patch("antkeeper.cli.subprocess.run") as mock_run:
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


class TestFixGhIssuesArgParsing:
    """Test suite for fix-gh-issues subcommand argument parsing."""

    def _build_parser(self):
        """Build and configure argument parser for fix-gh-issues subcommand testing.

        Returns:
            argparse.ArgumentParser: Configured parser with fix-gh-issues subcommand.
        """
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        common = argparse.ArgumentParser(add_help=False)
        common.add_argument("--agents-file", default="handlers.py")
        common.add_argument("--initial-state", action="append", default=[])
        common.add_argument("--model", default=None)
        common.add_argument("workflow_name")
        fgi_p = sub.add_parser("fix-gh-issues", parents=[common])
        fgi_p.add_argument("issue_numbers", nargs="+", type=int)
        return parser

    def test_parse_fix_gh_issues_with_single_issue(self):
        """Test parsing fix-gh-issues with single issue number."""
        args = self._build_parser().parse_args(["fix-gh-issues", "specify", "42"])
        assert args.workflow_name == "specify"
        assert args.issue_numbers == [42]

    def test_parse_fix_gh_issues_with_multiple_issues(self):
        """Test parsing fix-gh-issues with multiple issue numbers."""
        args = self._build_parser().parse_args(["fix-gh-issues", "specify", "42", "99"])
        assert args.issue_numbers == [42, 99]

    def test_parse_fix_gh_issues_missing_issue_numbers_exits(self):
        """Test that missing issue numbers causes parser to exit."""
        with pytest.raises(SystemExit):
            self._build_parser().parse_args(["fix-gh-issues", "specify"])

    def test_parse_fix_gh_issues_with_model_flag(self):
        """Test that --model flag is parsed."""
        args = self._build_parser().parse_args([
            "fix-gh-issues", "--model", "opus", "specify", "42"
        ])
        assert args.model == "opus"

    def test_parse_fix_gh_issues_with_agents_file(self):
        """Test that custom agents file path is correctly parsed."""
        args = self._build_parser().parse_args([
            "fix-gh-issues", "--agents-file", "custom.py", "specify", "42"
        ])
        assert args.agents_file == "custom.py"


class TestFixGhIssuesIntegration:
    """Integration tests for fix-gh-issues subcommand."""

    def test_fix_gh_issues_fetches_and_runs(self, monkeypatch, capsys):
        """Test fix-gh-issues fetches issue and runs workflow."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def specify(runner, state: State) -> State:
                return {{**state, "result": f"issues={{state['issue_numbers']}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            mock_issue = {"number": 42, "title": "test issue", "body": "description"}
            with patch("antkeeper.cli.subprocess.run") as mock_run:
                mock_run.return_value = Mock(stdout=json.dumps(mock_issue))
                monkeypatch.setattr("sys.argv", [
                    "antkeeper", "fix-gh-issues",
                    "--agents-file", agents_path,
                    "specify", "42",
                ])
                main()
                captured = capsys.readouterr()
                assert "issues=[42]" in captured.out
        finally:
            os.unlink(agents_path)

    def test_fix_gh_issues_multiple_issues(self, monkeypatch, capsys):
        """Test fix-gh-issues fetches and merges multiple issues."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def specify(runner, state: State) -> State:
                return {{**state, "result": f"issues={{state['issue_numbers']}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            issue1 = {"number": 42, "title": "bug1"}
            issue2 = {"number": 99, "title": "bug2"}
            with patch("antkeeper.cli.subprocess.run") as mock_run:
                mock_run.side_effect = [
                    Mock(stdout=json.dumps(issue1)),
                    Mock(stdout=json.dumps(issue2)),
                ]
                monkeypatch.setattr("sys.argv", [
                    "antkeeper", "fix-gh-issues",
                    "--agents-file", agents_path,
                    "specify", "42", "99",
                ])
                main()
                captured = capsys.readouterr()
                assert "issues=[42, 99]" in captured.out
        finally:
            os.unlink(agents_path)

    def test_fix_gh_issues_gh_failure_exits(self, monkeypatch, capsys):
        """Test fix-gh-issues exits with error on gh failure."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            app = App(log_dir="{log_dir}")
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            with patch("antkeeper.cli.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.CalledProcessError(
                    1, "gh", stderr="not found"
                )
                monkeypatch.setattr("sys.argv", [
                    "antkeeper", "fix-gh-issues",
                    "--agents-file", agents_path,
                    "specify", "42",
                ])
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
                captured = capsys.readouterr()
                assert "Failed to fetch issue" in captured.err
        finally:
            os.unlink(agents_path)

    def test_fix_gh_issues_gh_not_found_exits(self, monkeypatch, capsys):
        """Test fix-gh-issues exits with error if gh not installed."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            app = App(log_dir="{log_dir}")
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            with patch("antkeeper.cli.subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError()
                monkeypatch.setattr("sys.argv", [
                    "antkeeper", "fix-gh-issues",
                    "--agents-file", agents_path,
                    "specify", "42",
                ])
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
                captured = capsys.readouterr()
                assert "`gh` CLI not found" in captured.err
        finally:
            os.unlink(agents_path)

    def test_fix_gh_issues_model_merged(self, monkeypatch, capsys):
        """Test fix-gh-issues merges --model into state."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def specify(runner, state: State) -> State:
                return {{**state, "result": f"model={{state.get('model')}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            mock_issue = {"number": 42, "title": "test"}
            with patch("antkeeper.cli.subprocess.run") as mock_run:
                mock_run.return_value = Mock(stdout=json.dumps(mock_issue))
                monkeypatch.setattr("sys.argv", [
                    "antkeeper", "fix-gh-issues",
                    "--agents-file", agents_path,
                    "--model", "opus",
                    "specify", "42",
                ])
                main()
                captured = capsys.readouterr()
                assert "model=opus" in captured.out
        finally:
            os.unlink(agents_path)

    def test_fix_gh_issues_initial_state_merged(self, monkeypatch, capsys):
        """Test fix-gh-issues merges --initial-state into state."""
        log_dir = tempfile.mkdtemp()
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}")

            @app.handler
            def specify(runner, state: State) -> State:
                return {{**state, "result": f"custom={{state.get('custom_key')}}"}}
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(agents_code)
            f.flush()
            agents_path = f.name

        try:
            mock_issue = {"number": 42, "title": "test"}
            with patch("antkeeper.cli.subprocess.run") as mock_run:
                mock_run.return_value = Mock(stdout=json.dumps(mock_issue))
                monkeypatch.setattr("sys.argv", [
                    "antkeeper", "fix-gh-issues",
                    "--agents-file", agents_path,
                    "--initial-state", "custom_key=custom_value",
                    "specify", "42",
                ])
                main()
                captured = capsys.readouterr()
                assert "custom=custom_value" in captured.out
        finally:
            os.unlink(agents_path)


class TestResumeArgParsing:
    """Test suite for resume subcommand argument parsing."""

    def _build_parser(self):
        """Build and configure argument parser for resume subcommand testing.

        Returns:
            argparse.ArgumentParser: Configured parser with resume subcommand.
        """
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        resume_p = sub.add_parser("resume")
        resume_p.add_argument("--agents-file", default="handlers.py")
        resume_p.add_argument("run_id")
        return parser

    def test_parse_resume_with_run_id(self):
        """Test that resume command parses the positional run_id argument."""
        args = self._build_parser().parse_args(["resume", "abcd1234"])
        assert args.run_id == "abcd1234"
        assert args.command == "resume"

    def test_parse_resume_missing_run_id_exits(self):
        """Test that resume command without run_id causes the parser to exit."""
        with pytest.raises(SystemExit):
            self._build_parser().parse_args(["resume"])

    def test_parse_resume_with_agents_file(self):
        """Test that resume command accepts a custom --agents-file path."""
        args = self._build_parser().parse_args(["resume", "--agents-file", "custom.py", "abcd1234"])
        assert args.agents_file == "custom.py"


class TestResumeIntegration:
    """Integration tests for resume subcommand."""

    def _write_agents_file(self, log_dir, state_dir):
        """Write a temp agents file with a 2-step workflow handler."""
        agents_code = textwrap.dedent(f"""\
            from antkeeper.core.app import App, run_workflow
            from antkeeper.core.domain import State

            app = App(log_dir="{log_dir}", state_dir="{state_dir}")

            def step_one(runner, state: State) -> State:
                return {{**state, "steps": state.get("steps", []) + ["one"]}}

            def step_two(runner, state: State) -> State:
                return {{**state, "steps": state.get("steps", []) + ["two"]}}

            @app.handler
            def my_workflow(runner, state: State) -> State:
                return run_workflow(runner, state, [step_one, step_two])
        """)
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        f.write(agents_code)
        f.flush()
        f.close()
        return f.name

    def test_resume_loads_state_and_runs(self, monkeypatch, capsys):
        """Resume loads state, skips completed step, runs remaining."""
        log_dir = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        run_id = "aabb1122"
        state = {
            "workflow_name": "my_workflow",
            "run_id": run_id,
            "_progress": {"total": 2, "completed": 1},
        }
        state_path = os.path.join(state_dir, f"20260316-{run_id}.json")
        with open(state_path, "w") as f:
            json.dump(state, f)

        agents_path = self._write_agents_file(log_dir, state_dir)
        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "resume",
                "--agents-file", agents_path,
                run_id,
            ])
            main()
            captured = capsys.readouterr()
            assert "two" in captured.out
        finally:
            os.unlink(agents_path)

    def test_resume_run_id_not_found_exits(self, monkeypatch, capsys):
        """No matching state file exits with error."""
        log_dir = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        agents_path = self._write_agents_file(log_dir, state_dir)
        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "resume",
                "--agents-file", agents_path,
                "deadbeef",
            ])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "no state found for run_id: deadbeef" in captured.err
        finally:
            os.unlink(agents_path)

    def test_resume_already_completed_exits(self, monkeypatch, capsys):
        """State with completed == total exits with error."""
        log_dir = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        run_id = "ccdd3344"
        state = {
            "workflow_name": "my_workflow",
            "run_id": run_id,
            "_progress": {"total": 2, "completed": 2},
        }
        state_path = os.path.join(state_dir, f"20260316-{run_id}.json")
        with open(state_path, "w") as f:
            json.dump(state, f)

        agents_path = self._write_agents_file(log_dir, state_dir)
        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "resume",
                "--agents-file", agents_path,
                run_id,
            ])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "already completed" in captured.err
        finally:
            os.unlink(agents_path)

    def test_resume_no_progress_exits(self, monkeypatch, capsys):
        """State without _progress exits with error."""
        log_dir = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        run_id = "eeff5566"
        state = {"workflow_name": "my_workflow", "run_id": run_id}
        state_path = os.path.join(state_dir, f"20260316-{run_id}.json")
        with open(state_path, "w") as f:
            json.dump(state, f)

        agents_path = self._write_agents_file(log_dir, state_dir)
        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "resume",
                "--agents-file", agents_path,
                run_id,
            ])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "no progress to resume from" in captured.err
        finally:
            os.unlink(agents_path)

    def test_resume_no_workflow_name_exits(self, monkeypatch, capsys):
        """State without workflow_name exits with error."""
        log_dir = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        run_id = "aabb7788"
        state = {"run_id": run_id, "_progress": {"total": 2, "completed": 1}}
        state_path = os.path.join(state_dir, f"20260316-{run_id}.json")
        with open(state_path, "w") as f:
            json.dump(state, f)

        agents_path = self._write_agents_file(log_dir, state_dir)
        try:
            monkeypatch.setattr("sys.argv", [
                "antkeeper", "resume",
                "--agents-file", agents_path,
                run_id,
            ])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "no workflow_name" in captured.err
        finally:
            os.unlink(agents_path)
