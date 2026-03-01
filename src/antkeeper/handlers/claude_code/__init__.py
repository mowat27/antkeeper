"""Pre-registered SDLC handlers using Claude Code as the LLM backend.

Provides a module-level ``app`` instance with 11 handlers registered.
Consumers import the handlers dict into their own App::

    from antkeeper.handlers.claude_code import app as claude_code_app
    app = App(handlers=claude_code_app.handlers)
"""

from datetime import datetime

from antkeeper.core.app import App, run_workflow
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.git import Worktree, git_worktree, latest_commit
from antkeeper.helpers.json import extract_json, json_prompt
from antkeeper.llm.claude_code import run_prompt

app = App()


# --- Steps ---


@app.handler
def healthcheck(runner: Runner, state: State) -> State:
    """Verify the agent pipeline is working by asking Claude to write a short poem."""
    runner.report_progress("Running healthcheck")
    response = run_prompt(
        "Write a short poem about agentic coding",
        runner.logger,
        model=state.get("model"),
    )
    runner.logger.info(f"healthcheck response: {response}")
    runner.report_progress("Healthcheck complete")
    runner.report_progress(response)
    return {**state, "poem": response}


@app.handler
def derive_feature(runner: Runner, state: State) -> State:
    """Derive feature type and slug from a prompt via LLM."""
    runner.report_progress("Deriving feature metadata")
    prompt = json_prompt(
        f'/derive_feature {state["prompt"]}',
        required_fields=["feature_type", "slug"],
    )
    runner.logger.info(f"derive_feature prompt: {prompt}")
    response = run_prompt(prompt, runner.logger, model=state.get("model"))
    runner.logger.info(f"derive_feature response: {response}")
    parsed = extract_json(response)
    feature_type = parsed["feature_type"]
    slug = parsed["slug"]
    runner.report_progress(f"Derived: feature_type={feature_type}, slug={slug}")
    return {**state, "feature_type": feature_type, "slug": slug}


@app.handler
def specify(runner: Runner, state: State) -> State:
    """Generate a specification and extract spec_file and slug from the response."""
    runner.report_progress("Running /specify")
    prompt = json_prompt(
        f'/specify {state["prompt"]}',
        required_fields=["spec_file", "slug"],
    )
    runner.logger.info(f"specify prompt: {prompt}")
    response = run_prompt(prompt, runner.logger, model=state.get("model"))
    runner.logger.info(f"specify response: {response}")
    parsed = extract_json(response)
    runner.report_progress("/specify complete")
    return {**state, "spec_file": parsed["spec_file"], "slug": parsed["slug"]}


@app.handler
def commit(runner: Runner, state: State) -> State:
    """Commit current changes with an auto-generated message."""
    runner.report_progress("Running /commit")
    response = run_prompt("/commit", runner.logger, model=state.get("model"))
    runner.logger.info(f"commit response length: {len(response)} chars")
    lc = latest_commit()
    runner.report_progress(f"/commit complete: {lc['sha'][:8]}")
    return {**state, "last_commit": lc}


@app.handler
def branch_if_on_main(runner: Runner, state: State) -> State:
    """Create a feature branch if currently on main."""
    runner.report_progress("Running /branch")
    prompt = json_prompt(
        f'/branch {state["spec_file"]}',
        required_fields=["branch_name"],
    )
    runner.logger.info(f"branch prompt: {prompt}")
    response = run_prompt(prompt, runner.logger, model=state.get("model"))
    runner.logger.info(f"branch response: {response}")
    parsed = extract_json(response)
    runner.report_progress("/branch complete")
    return {**state, "branch_name": parsed["branch_name"]}


@app.handler
def implement(runner: Runner, state: State) -> State:
    """Implement a feature from a spec/plan."""
    runner.report_progress("Running /implement")
    prompt = f'/implement {state["spec_file"]}'
    runner.logger.info(f"implement prompt: {prompt}")
    response = run_prompt(prompt, runner.logger, model=state.get("model"))
    runner.logger.info(f"implement response length: {len(response)} chars")
    runner.report_progress("/implement complete")
    return {**state, "implement_status": "complete"}


@app.handler
def push(runner: Runner, state: State) -> State:
    """Push the current branch to the remote."""
    runner.report_progress("Running git push")
    response = run_prompt(
        "Push the current branch to the remote origin.",
        runner.logger,
        model=state.get("model"),
    )
    runner.logger.info(f"push response length: {len(response)} chars")
    runner.report_progress("Push complete")
    return {**state, "push_status": "complete"}


@app.handler
def raise_a_pr(runner: Runner, state: State) -> State:
    """Raise a pull request for the current branch."""
    runner.report_progress("Raising PR")
    response = run_prompt(
        "Create a pull request for the current branch using gh pr create.",
        runner.logger,
        model=state.get("model"),
    )
    runner.logger.info(f"raise_a_pr response length: {len(response)} chars")
    runner.report_progress("PR raised")
    return {**state, "pr_status": "complete"}


# --- Workflows ---


@app.handler
def specify_implement(runner: Runner, state: State) -> State:
    """Run partial SDLC workflow: specify -> implement."""
    return run_workflow(runner, state, [specify, implement])


@app.handler
def sdlc(runner: Runner, state: State) -> State:
    """Run the full SDLC workflow without document step."""
    return run_workflow(
        runner,
        state,
        [specify, branch_if_on_main, commit, implement, commit, push, raise_a_pr],
    )


@app.handler
def sdlc_iso(runner: Runner, state: State) -> State:
    """Run SDLC workflow inside an isolated git worktree."""
    state = derive_feature(runner, state)
    worktree_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{runner.id}"
    branch_name = f"{state['feature_type']}/{state['slug']}"
    wt = Worktree(base_dir=runner.app.worktree_dir, name=worktree_name)
    with git_worktree(wt, create=True, branch=branch_name, remove=False):
        state = run_workflow(
            runner,
            state,
            [specify, commit, implement, commit, push, raise_a_pr],
        )
    return {**state, "worktree_path": wt.path, "branch_name": branch_name}
