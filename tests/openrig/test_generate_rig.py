"""Tests for generating an OpenRig rig from an antkeeper handlers file."""

import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from antkeeper.cli import cli
from antkeeper.loader import load_module
from antkeeper.openrig import GenerationError, generate_rig
from antkeeper.openrig import generator
from antkeeper.openrig.introspect import introspect

HANDLERS = textwrap.dedent('''\
    from antkeeper.core.app import App, run_workflow
    from antkeeper.handlers.claude_code.factories import cc_handler
    from antkeeper.handlers.ralph import ralph, ValidationResult

    specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"], model="opus")
    implement = cc_handler("/implement $spec_file")
    count_words = cc_handler("Count the words in $poem", state_updates=["word_count"], label="count words")

    app = App()

    @app.handler
    def branch(runner, state):
        """Create a branch named after the slug."""
        return {**state, "branch_name": state["slug"]}

    def _ok(state):
        return ValidationResult(success=True, feedback="")

    checked = ralph(implement, validator=_ok, max_retries=2)

    STEPS = [specify, branch, implement]

    @app.handler
    def sdlc(runner, state):
        """Specify, branch and implement."""
        return run_workflow(runner, state, STEPS)

    @app.handler
    def partial(runner, state):
        return run_workflow(runner, state, STEPS[0:2])

    @app.handler
    def outer(runner, state):
        """Count words, then the whole sdlc."""
        state = count_words(runner, state)
        state = {**state, "extra": True}
        return run_workflow(runner, state, [sdlc, checked])
''')


def _write(directory: Path, source: str = HANDLERS) -> Path:
    path = directory / "handlers.py"
    path.write_text(source)
    return path


def _shared(directory: Path) -> Path:
    shared = directory / "openrig-shared"
    shared.mkdir()
    (shared / "agent.yaml").write_text("name: shared\nversion: '1.0'\n")
    return shared


def _load(path: Path):
    return yaml.safe_load(path.read_text())


class TestIntrospect:
    """Translating a handlers module into steps and workflows."""

    def test_resolves_workflow_steps(self, tmp_path):
        spec = introspect(load_module(str(_write(tmp_path))))

        workflows = {name: wf.steps for name, wf in spec.workflows.items()}
        assert workflows == {
            "branch": ("branch",),
            "sdlc": ("specify", "branch", "implement"),
            "partial": ("specify", "branch"),
            "outer": ("count_words", "specify", "branch", "implement", "checked"),
        }
        assert spec.workflows["sdlc"].composite and not spec.workflows["branch"].composite
        assert spec.workflows["sdlc"].glue_source is None
        assert "extra" in (spec.workflows["outer"].glue_source or "")

    def test_describes_each_kind_of_step(self, tmp_path):
        spec = introspect(load_module(str(_write(tmp_path))))

        specify = spec.steps["specify"]
        assert specify.model == "opus" and specify.command == "/specify"
        assert "/specify $prompt" in specify.instructions and "`spec_file`, `slug`" in specify.instructions
        assert "def branch" in spec.steps["branch"].instructions
        checked = spec.steps["checked"].instructions
        assert "at most 3 attempts" in checked and "def _ok" in checked and "/implement $spec_file" in checked

    def test_skips_workflows_with_unresolvable_steps(self, tmp_path):
        source = HANDLERS + textwrap.dedent('''
            @app.handler
            def dynamic(runner, state):
                return run_workflow(runner, state, list(reversed(STEPS)))
        ''')
        spec = introspect(load_module(str(_write(tmp_path, source))))

        assert "dynamic" not in spec.workflows and "sdlc" in spec.workflows
        assert "cannot statically resolve" in spec.skipped["dynamic"]

    def test_raises_when_no_workflow_resolves(self, tmp_path):
        source = textwrap.dedent('''
            from antkeeper.core.app import App, run_workflow

            app = App()

            @app.handler
            def dynamic(runner, state):
                return run_workflow(runner, state, state["steps"])
        ''')
        with pytest.raises(GenerationError, match="no workflow could be translated"):
            introspect(load_module(str(_write(tmp_path, source))))

    def test_reserved_step_name_raises(self, tmp_path):
        source = HANDLERS.replace("def branch(", "def close(").replace("STEPS = [specify, branch,", "STEPS = [specify, close,")
        with pytest.raises(GenerationError, match="reserved"):
            introspect(load_module(str(_write(tmp_path, source))))


class TestGenerateRig:
    """Writing the rig, agents, skills and workflow specs."""

    def test_writes_rig(self, tmp_path):
        handlers = _write(tmp_path)
        result = generate_rig(str(handlers), str(tmp_path), rig_name="My Rig", shared_source=_shared(tmp_path))

        assert result.rig_name == "my-rig" and result.lead_session == "orch-lead@my-rig"
        rig = _load(tmp_path / "rig.yaml")
        orch, steps = rig["pods"]
        assert orch["members"][0]["agent_ref"] == "local:.openrig/agents/orchestrator"
        assert [m["id"] for m in steps["members"]] == ["branch", "specify", "implement", "count_words", "checked"]
        assert steps["members"][1]["model"] == "opus"
        assert {"kind": "delegates_to", "from": "orch.lead", "to": "steps.count_words"} in rig["edges"]

        workflow = _load(tmp_path / ".openrig/workflows/sdlc.yaml")["workflow"]
        assert [s["id"] for s in workflow["steps"]] == ["specify", "branch", "implement", "close"]
        assert "next_hop" not in workflow["steps"][0]  # a failure stays on its step, so resume re-runs it
        assert workflow["exception_routing"]["orchestrator_role"] == "orchestrator"
        assert workflow["roles"]["specify"]["preferred_targets"] == ["steps-specify@my-rig"]
        assert workflow["roles"]["orchestrator"]["preferred_targets"] == ["orch-lead@my-rig"]

        orchestrator = _load(tmp_path / ".openrig/agents/orchestrator/agent.yaml")
        assert "sdlc" in orchestrator["profiles"]["default"]["uses"]["skills"]
        assert "rig-permissions" in orchestrator["profiles"]["default"]["uses"]["runtime_resources"]
        skill = (tmp_path / ".openrig/agents/orchestrator/skills/sdlc/SKILL.md").read_text()
        assert skill.startswith("---\nname: sdlc\n") and "rig workflow instantiate \"$PWD/.openrig/workflows/sdlc.yaml\"" in skill
        role = (tmp_path / ".openrig/agents/count_words/guidance/role.md").read_text()
        assert "`run_id` to the workflow instance id" in role and "`workflow_name`" in role
        assert (tmp_path / "CULTURE.md").is_file()
        assert (tmp_path / ".openrig/shared/agent.yaml").is_file() and result.shared_copied

    def test_skips_skills_that_shadow_slash_commands(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "partial.md").write_text("project command")
        result = generate_rig(str(_write(tmp_path)), str(tmp_path), shared_source=_shared(tmp_path))

        assert "partial" not in result.launchers and result.launchers["sdlc"] == "sdlc"
        assert any("'partial'" in warning for warning in result.warnings)

    def test_refuses_to_overwrite_without_force(self, tmp_path):
        handlers, shared = _write(tmp_path), _shared(tmp_path)
        generate_rig(str(handlers), str(tmp_path), shared_source=shared)

        with pytest.raises(GenerationError, match="refusing to overwrite"):
            generate_rig(str(handlers), str(tmp_path), shared_source=shared)
        generate_rig(str(handlers), str(tmp_path), force=True)

    def test_requires_openrig_shared_pool(self, tmp_path, monkeypatch):
        monkeypatch.setattr(generator, "find_openrig_shared", lambda: None)
        with pytest.raises(GenerationError, match="OpenRig CLI"):
            generate_rig(str(_write(tmp_path)), str(tmp_path))


class TestGenerateRigCommand:
    """The ``antkeeper generate-rig`` CLI command."""

    def test_defaults_to_handlers_py(self, tmp_path, monkeypatch):
        _write(tmp_path)
        shared = _shared(tmp_path)
        monkeypatch.setattr(generator, "find_openrig_shared", lambda: shared)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["generate-rig", "--name", "demo"])

        assert result.exit_code == 0, result.output
        assert "/sdlc <prompt>" in result.output and "orch-lead@demo" in result.output
        assert (tmp_path / "rig.yaml").is_file()

    def test_reports_missing_handlers_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(cli, ["generate-rig", "missing.py"])
        assert result.exit_code == 1
        assert "handlers file not found" in result.output
