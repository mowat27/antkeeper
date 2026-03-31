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
from antkeeper.handlers.ralph import ralph, ValidationResult
from antkeeper.llm.claude_code import run_prompt


# --- Steps (factory-built) ---

specify = cc_handler("/specify $prompt", state_updates=["spec_file", "slug"])
"""Handler that runs the ``/specify`` slash command and stores ``spec_file`` and ``slug`` in state."""

implement = cc_handler("/sdlc:implement $spec_file")
"""Handler that runs the ``/sdlc:implement`` slash command against the current ``spec_file``."""

document = cc_handler("/document this branch.")
"""Handler that runs the ``/document`` slash command to document the current branch."""

derive_feature = cc_handler(
    "/sdlc:derive_feature $prompt",
    state_updates=["feature_type", "slug"],
)
"""Handler that derives ``feature_type`` and ``slug`` from a prompt using the ``/sdlc:derive_feature`` command."""

commit_push_raise_pr = cc_handler(
    "/commit_push_raise_pr", state_updates=["pr_url"])
"""Handler that commits, pushes, and raises a PR, storing the resulting ``pr_url`` in state."""

count_words = cc_handler(
    "Count the number of words in this poem: $poem",
    state_updates=["word_count"],
    label="count words",
    opts=["--max-turns", "1"],
)
"""Handler that counts the words in ``poem`` (from state) and stores the result as ``word_count``."""

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
    """Verify the agent pipeline is working by asking Claude to write a short poem.

    Runs a simple LLM prompt and logs the response. Useful as a smoke-test to
    confirm that the LLM backend is reachable and returning output.

    Args:
        runner: The active workflow runner, used for progress reporting and logging.
        state: Current workflow state. Reads ``model`` if present.

    Returns:
        Updated state with ``poem`` set to the LLM's response text.
    """
    runner.report_progress("Running healthcheck")
    stream = run_prompt(
        "Write a short poem about agentic coding",
        runner.logger,
        model=state.get("model"),
    )
    result_text = ""
    for event in stream:
        runner.channel.report(runner.id, event)
        if event.type == "result" and not event.internal:
            result_text = event.content
    runner.logger.info(f"healthcheck response: {result_text}")
    runner.report_progress("Healthcheck complete")
    return {**state, "poem": result_text}


# --- Shared workflow constants ---


SDLC_STEPS = [specify, branch, implement, document]
"""List of handler functions that make up the standard SDLC workflow."""


# --- Workflows ---


@app.handler
def test_workflow(runner: Runner, state: State) -> State:
    """Run a two-step test workflow: healthcheck -> count_words.

    Asks Claude to write a poem (healthcheck), then counts the words in the
    poem and stores the result in state. Useful for verifying that the full
    pipeline — including factory-built handlers and state extraction — is
    working end-to-end.

    Args:
        runner: The active workflow runner.
        state: Current workflow state.

    Returns:
        Updated state with ``poem`` and ``word_count`` set.
    """
    return run_workflow(runner, state, [healthcheck, count_words])


@app.handler
def specify_implement(runner: Runner, state: State) -> State:
    """Run partial SDLC workflow: specify -> implement.

    Args:
        runner: The active workflow runner.
        state: Current workflow state, typically containing ``prompt``.

    Returns:
        Updated state after the specify and implement steps complete.
    """
    return run_workflow(runner, state, [specify, implement])


@app.handler
def sdlc(runner: Runner, state: State) -> State:
    """Run the full SDLC workflow: specify -> branch -> implement -> document.

    Args:
        runner: The active workflow runner.
        state: Current workflow state, typically containing ``prompt``.

    Returns:
        Updated state after all four SDLC steps complete.
    """
    return run_workflow(runner, state, SDLC_STEPS)


@app.handler
def specify_and_branch(runner: Runner, state: State) -> State:
    """Run partial SDLC workflow: specify -> branch.

    Args:
        runner: The active workflow runner.
        state: Current workflow state, typically containing ``prompt``.

    Returns:
        Updated state with ``spec_file``, ``slug``, and ``branch_name`` set.
    """
    return run_workflow(runner, state, SDLC_STEPS[0:2])


def _increment(runner: Runner, state: State) -> State:
    """Increment ``attempt_count`` in state by 1.

    Args:
        runner: The active workflow runner (unused).
        state: Current workflow state. Reads ``attempt_count`` (defaults to 0).

    Returns:
        Updated state with ``attempt_count`` incremented by 1.
    """
    count = state.get("attempt_count", 0) + 1
    return {**state, "attempt_count": count}


def _needs_four(state: State) -> ValidationResult:
    """Validate that ``attempt_count`` has reached 4.

    Used as the validator for ``_ralph_increment`` in the ``test_ralph`` workflow.

    Args:
        state: Current workflow state. Reads ``attempt_count`` (defaults to 0).

    Returns:
        A passing ``ValidationResult`` when ``attempt_count >= 4``, otherwise a
        failing result with descriptive feedback.
    """
    count = state.get("attempt_count", 0)
    if count >= 4:
        return ValidationResult(success=True, feedback="")
    return ValidationResult(success=False, feedback=f"attempt_count is {count}, need 4")


_ralph_increment = ralph(_increment, validator=_needs_four, max_retries=3, label="test-ralph")
"""Ralph-wrapped ``_increment`` handler that retries until ``attempt_count`` reaches 4."""


@app.handler
def test_ralph(runner: Runner, state: State) -> State:
    """Deterministic test workflow for the ralph retry wrapper.

    Increments ``attempt_count`` on each attempt; passes on the 4th attempt.
    Runnable with ``antkeeper run test_ralph``.

    Args:
        runner: The active workflow runner.
        state: Current workflow state.

    Returns:
        Updated state with ``attempt_count`` equal to 4 on success.
    """
    return _ralph_increment(runner, state)


@app.handler
def sdlc_iso(runner: Runner, state: State) -> State:
    """Run SDLC workflow inside an isolated git worktree.

    Creates a git worktree with a feature branch based on derived metadata,
    then executes the SDLC workflow (specify -> implement -> document) within
    that isolated environment. The worktree is not automatically removed.

    Args:
        runner: The active workflow runner.
        state: Current workflow state, typically containing ``prompt``.

    Returns:
        Updated state after the workflow completes, with ``worktree_path`` set
        to the worktree's filesystem path and ``branch_name`` set to the
        ``feature_type/slug`` branch that was created.
    """
    state = derive_feature(runner, state)
    worktree_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{runner.id}"
    branch_name = f"{state['feature_type']}/{state['slug']}"
    wt = Worktree(base_dir=runner.app.worktree_dir, name=worktree_name)
    with git_worktree(wt, create=True, branch=branch_name, remove=False):
        state = run_workflow(runner, state, [specify, implement, document])
    return {**state, "worktree_path": wt.path, "branch_name": branch_name}
