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
from antkeeper.llm.claude_code import run_prompt
from antkeeper.handlers.claude_code.factories import cc_handler

app = App()


# --- Steps (factory-built) ---

derive_feature = cc_handler("/derive_feature $prompt", state_updates=["feature_type", "slug"])
app.add_handler(derive_feature)

specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
app.add_handler(specify)

branch_if_on_main = cc_handler("/branch $spec_file", state_updates=["branch_name"], label="branch_if_on_main")
app.add_handler(branch_if_on_main)

implement = cc_handler("/implement $spec_file")
app.add_handler(implement)

push = cc_handler("Push the current branch to the remote origin.", label="push")
app.add_handler(push)

raise_a_pr = cc_handler("Create a pull request for the current branch using gh pr create.", label="raise_a_pr")
app.add_handler(raise_a_pr)


# --- Steps (hand-written) ---


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
def commit(runner: Runner, state: State) -> State:
    """Commit current changes with an auto-generated message."""
    runner.report_progress("Running /commit")
    response = run_prompt("/commit", runner.logger, model=state.get("model"))
    runner.logger.info(f"commit response length: {len(response)} chars")
    lc = latest_commit()
    runner.report_progress(f"/commit complete: {lc['sha'][:8]}")
    return {**state, "last_commit": lc}


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
    """Run the full SDLC workflow inside an isolated git worktree.

    Derives the feature type and slug from state, creates a timestamped
    worktree under ``runner.app.worktree_dir``, checks out a new branch
    named ``<feature_type>/<slug>``, then runs the full SDLC steps
    (specify -> commit -> implement -> commit -> push -> raise_a_pr) inside
    that worktree.  The worktree is intentionally left on disk after the
    workflow so the branch can be inspected or retried.

    Args:
        runner: The active workflow runner providing logging and progress
            reporting.
        state: Workflow state dict. Must contain a ``prompt`` key (and
            optionally ``model``) consumed by ``derive_feature``.

    Returns:
        Updated state dict with all SDLC fields merged in, plus:
            - ``worktree_path`` (str): Absolute path to the created worktree.
            - ``branch_name`` (str): Name of the new git branch.
    """
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
