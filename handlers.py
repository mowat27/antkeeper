"""LLM-backed workflow handlers for the Antkeeper framework.

Each handler runs a slash command via ClaudeCodeAgent, extracts structured
data from the response, and threads it through state for downstream steps.
"""

from datetime import datetime

from antkeeper import git
from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.core.app import App, run_workflow
from antkeeper.git.worktrees import Worktree, git_worktree
from antkeeper.handlers.claude_code.factories import cc_handler
from antkeeper.llm.claude_code import run_prompt


# --- Steps (factory-built) ---

specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
implement = cc_handler("/sdlc:implement $spec_file")
document = cc_handler("/document this branch.")
derive_feature = cc_handler(
    "/sdlc:derive_feature $prompt",
    state_updates=["feature_type", "slug"],
)
commit_push_raise_pr = cc_handler(
    "/commit_push_raise_pr", state_updates=["pr_url"])

# --- App ---

app = App(handlers={
    "commit_push_raise_pr": commit_push_raise_pr
})

# --- Steps (hand-written) ---


@app.handler
def branch(runner: Runner, state: State) -> State:
    """Create a git branch for the current work item.

    If ``slug`` is already present in state (e.g. set by a prior ``specify``
    step), reports progress and checks out a new branch named after the slug.
    Otherwise, delegates to a Claude Code handler that derives a branch name
    from the spec file and stores it in state as ``branch_name``.

    Args:
        runner: The active workflow runner, used for progress reporting.
        state: Current workflow state. Reads ``slug`` and ``spec_file``.

    Returns:
        Updated state with ``branch_name`` set to the checked-out branch name.
    """
    slug = state.get('slug')
    if slug:
        runner.report_progress(f"Using branch {slug}")
        git.execute(['checkout', '-b', slug])
        return {**state, "branch_name": slug}

    fallback = cc_handler("/sdlc:branch $spec_file",
                          state_updates=["branch_name"],
                          label="branch")
    return fallback(runner, state)


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


# --- Shared workflow constants ---


SDLC_STEPS = [specify, branch, implement, document]
"""List of handler functions that make up the standard SDLC workflow."""


# --- Workflows ---


@app.handler
def specify_implement(runner: Runner, state: State) -> State:
    """Run partial SDLC workflow: specify -> implement."""
    return run_workflow(runner, state, [specify, implement])


@app.handler
def sdlc(runner: Runner, state: State) -> State:
    """Run the full SDLC workflow: specify -> branch -> implement -> document."""
    return run_workflow(runner, state, SDLC_STEPS)


@app.handler
def specify_and_branch(runner: Runner, state: State) -> State:
    """Run partial SDLC workflow: specify -> branch."""
    return run_workflow(runner, state, SDLC_STEPS[0:2])


@app.handler
def sdlc_iso(runner: Runner, state: State) -> State:
    """Run SDLC workflow inside an isolated git worktree.

    Creates a git worktree with a feature branch based on derived metadata,
    then executes the SDLC workflow (specify -> implement -> document) within
    that isolated environment. The worktree is not automatically removed.
    """
    state = derive_feature(runner, state)
    worktree_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{runner.id}"
    branch_name = f"{state['feature_type']}/{state['slug']}"
    wt = Worktree(base_dir=runner.app.worktree_dir, name=worktree_name)
    with git_worktree(wt, create=True, branch=branch_name, remove=False):
        state = run_workflow(runner, state, [specify, implement, document])
    return {**state, "worktree_path": wt.path, "branch_name": branch_name}
