"""CLI click-based tests.

Tests click subcommands, state pair parsing, and end-to-end
CLI workflow execution with dynamic handler loading.
"""

import os
import tempfile
import textwrap

import pytest
from click.testing import CliRunner

from antkeeper.cli import cli, parse_state_pairs


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


class TestRunCommand:
    """Click CliRunner tests for the run subcommand."""

    def test_cli_loads_agents_file_and_runs(self):
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "--initial-state", "result=10",
                "add_1",
            ])
            assert result.exit_code == 0
            assert "11" in result.output
        finally:
            os.unlink(agents_path)

    def test_prompt_file_loaded_into_state(self):
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "echo", prompt_path,
            ])
            assert result.exit_code == 0
            assert "prompt=hello from file" in result.output
        finally:
            os.unlink(agents_path)
            os.unlink(prompt_path)

    def test_prompt_file_not_found_exits(self):
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "echo", "/nonexistent/path.md",
            ])
            assert result.exit_code == 1
            assert "file not found" in result.stderr.lower()
        finally:
            os.unlink(agents_path)

    def test_prompt_and_model_merged_into_state(self):
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "--model", "opus",
                "echo", prompt_path,
            ])
            assert result.exit_code == 0
            assert "prompt=hello world" in result.output
            assert "model=opus" in result.output
        finally:
            os.unlink(agents_path)
            os.unlink(prompt_path)

    def test_multiple_files_concatenated(self):
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "echo", path1, path2,
            ])
            assert result.exit_code == 0
            assert "prompt=hello\\nworld\\n" in result.output
        finally:
            os.unlink(agents_path)
            os.unlink(path1)
            os.unlink(path2)

    def test_stdin_read_as_prompt(self):
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "echo",
            ], input="from stdin")
            assert result.exit_code == 0
            assert "prompt=from stdin" in result.output
        finally:
            os.unlink(agents_path)

    def test_run_command_catches_workflow_failed_error(self):
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "blow_up",
            ])
            assert result.exit_code == 1
            assert "something went wrong" in result.stderr
        finally:
            os.unlink(agents_path)

    def test_run_missing_workflow_name_shows_usage(self):
        """Test that run with no workflow_name shows usage error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run"])
        assert result.exit_code != 0

    def test_agents_file_not_found_exits(self):
        """Test that --agents-file pointing to nonexistent file produces clear error."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "run",
            "--agents-file", "/nonexistent/handlers.py",
            "my_workflow",
        ])
        assert result.exit_code == 1
        assert "agents file not found" in result.stderr.lower()


class TestInitCommand:
    """Click CliRunner tests for the init subcommand."""

    def test_init_creates_handlers_file(self):
        """Test that init command creates handlers.py file with boilerplate."""
        tmpdir = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["init", tmpdir])
            assert result.exit_code == 0
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

    def test_init_prints_env_info(self):
        """Test that init command prints environment variable information."""
        tmpdir = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["init", tmpdir])
            assert "Created handlers.py" in result.output
            assert "ANTKEEPER_HANDLERS_FILE" in result.output
        finally:
            handlers = os.path.join(tmpdir, "handlers.py")
            if os.path.exists(handlers):
                os.unlink(handlers)
            os.rmdir(tmpdir)

    def test_init_errors_if_handlers_exists(self):
        """Test that init command exits with error if handlers.py already exists."""
        tmpdir = tempfile.mkdtemp()
        handlers = os.path.join(tmpdir, "handlers.py")
        try:
            with open(handlers, "w") as f:
                f.write("# existing\n")
            runner = CliRunner()
            result = runner.invoke(cli, ["init", tmpdir])
            assert result.exit_code == 1
            assert "already exists" in result.stderr
        finally:
            if os.path.exists(handlers):
                os.unlink(handlers)
            os.rmdir(tmpdir)

    def test_init_default_path_uses_cwd(self, monkeypatch):
        """Test that init command without path argument uses current working directory."""
        tmpdir = tempfile.mkdtemp()
        try:
            monkeypatch.chdir(tmpdir)
            runner = CliRunner()
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
            target = os.path.join(tmpdir, "handlers.py")
            assert os.path.exists(target)
        finally:
            handlers = os.path.join(tmpdir, "handlers.py")
            if os.path.exists(handlers):
                os.unlink(handlers)
            os.rmdir(tmpdir)

    def test_init_errors_if_directory_missing(self):
        """Test that init command exits with error if target directory doesn't exist."""
        tmpdir = tempfile.mkdtemp()
        os.rmdir(tmpdir)
        runner = CliRunner()
        result = runner.invoke(cli, ["init", tmpdir])
        assert result.exit_code == 1
        assert "does not exist" in result.stderr


class TestVerboseFlag:
    """Tests for --verbose flag on run and resume commands."""

    def test_run_verbose_flag_accepted(self):
        """Test that --verbose flag is accepted by the run command."""
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
            runner = CliRunner()
            result = runner.invoke(cli, [
                "run",
                "--agents-file", agents_path,
                "--initial-state", "result=10",
                "--verbose",
                "add_1",
            ])
            assert result.exit_code == 0
            assert "11" in result.output
        finally:
            os.unlink(agents_path)

class TestNoSubcommand:
    """Test CLI with no subcommand shows help."""

    def test_no_subcommand_shows_help(self):
        """Test that running with no subcommand shows help text."""
        runner = CliRunner()
        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        assert "Usage" in result.output
