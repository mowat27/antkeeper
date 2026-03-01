"""LLM-backed workflow handlers for the Antkeeper framework.

Each handler runs a slash command via ClaudeCodeAgent, extracts structured
data from the response, and threads it through state for downstream steps.
"""

from datetime import datetime

from antkeeper.core.runner import Runner
from antkeeper.core.domain import State
from antkeeper.core.app import App, run_workflow
from antkeeper.git.worktrees import Worktree, git_worktree
from antkeeper.helpers.json import extract_json
from antkeeper.llm.claude_code import ClaudeCodeAgent

app = App()


# --- Steps ---


@app.handler
def healthcheck(runner: Runner, state: State) -> State:
    """Verify the agent pipeline is working by asking Claude to write a short poem.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary.

    Returns:
        Updated state with "poem" key containing the generated poem.
    """
    runner.report_progress("Running healthcheck")
    agent = ClaudeCodeAgent(model=state.get("model"))
    response = agent.prompt("Write a short poem about agentic coding")
    runner.logger.info(f"healthcheck response: {response}")
    runner.report_progress("Healthcheck complete")
    runner.report_progress(response)
    return {**state, "poem": response}


@app.handler
def specify(runner: Runner, state: State) -> State:
    """Generate a specification and extract spec_file and slug from the response.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "prompt" key.

    Returns:
        Updated state with "spec_file" and "slug" keys extracted from the agent response.
    """
    runner.report_progress("Running /specify")
    agent = ClaudeCodeAgent(model=state.get("model"))
    prompt = (
        f'/specify {state["prompt"]}\n\n'
        "After running the command, return ONLY a JSON object with the spec file path "
        'and slug: {"spec_file": "<path>", "slug": "<slug>"}'
    )
    runner.logger.info(f"specify prompt: {prompt}")
    response = agent.prompt(prompt)
    runner.logger.info(f"specify response: {response}")
    parsed = extract_json(response)
    runner.report_progress("/specify complete")
    return {**state, "spec_file": parsed["spec_file"], "slug": parsed["slug"]}


@app.handler
def branch(runner: Runner, state: State) -> State:
    """Create a feature branch and extract the branch name from the response.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "spec_file" key.

    Returns:
        Updated state with "branch_name" key extracted from the agent response.
    """
    runner.report_progress("Running /branch")
    agent = ClaudeCodeAgent(model=state.get("model"))
    prompt = (
        f'/sdlc:branch {state["spec_file"]}\n\n'
        "After running the command, return ONLY a JSON object with the branch name: "
        '{"branch_name": "<branch>"}'
    )
    runner.logger.info(f"branch prompt: {prompt}")
    response = agent.prompt(prompt)
    runner.logger.info(f"branch response: {response}")
    parsed = extract_json(response)
    runner.report_progress("/branch complete")
    return {**state, "branch_name": parsed["branch_name"]}


@app.handler
def implement(runner: Runner, state: State) -> State:
    """Implement a feature from a spec/plan.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "spec_file" key.

    Returns:
        Updated state with "implement_status" set to "complete".
    """
    runner.report_progress("Running /implement")
    agent = ClaudeCodeAgent(model=state.get("model"))
    prompt = f'/sdlc:implement {state["spec_file"]}'
    runner.logger.info(f"implement prompt: {prompt}")
    response = agent.prompt(prompt)
    runner.logger.info(f"implement response length: {len(response)} chars")
    runner.report_progress("/implement complete")
    return {**state, "implement_status": "complete"}


@app.handler
def document(runner: Runner, state: State) -> State:
    """Update documentation for completed work on the current branch.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary.

    Returns:
        Updated state with "document_status" set to "complete".
    """
    runner.report_progress("Running /document")
    agent = ClaudeCodeAgent(model=state.get("model"))
    prompt = "/document Update documentation for the changes on this branch."
    runner.logger.info(f"document prompt: {prompt}")
    response = agent.prompt(prompt)
    runner.logger.info(f"document response length: {len(response)} chars")
    runner.report_progress("/document complete")
    return {**state, "document_status": "complete"}


@app.handler
def derive_feature(runner: Runner, state: State) -> State:
    """Derive feature type and slug from a prompt via LLM.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "prompt" key.

    Returns:
        Updated state with "feature_type" and "slug" keys extracted from the agent response.
    """
    runner.report_progress("Deriving feature metadata")
    agent = ClaudeCodeAgent(model=state.get("model"))
    prompt = (
        f'/sdlc:derive_feature {state["prompt"]}\n\n'
        "After running the command, return ONLY a JSON object: "
        '{"feature_type": "<type>", "slug": "<slug>"}'
    )
    runner.logger.info(f"derive_feature prompt: {prompt}")
    response = agent.prompt(prompt)
    runner.logger.info(f"derive_feature response: {response}")
    parsed = extract_json(response)

    feature_type = parsed["feature_type"]
    slug = parsed["slug"]
    runner.report_progress(
        f"Derived: feature_type={feature_type}, slug={slug}")
    return {**state, "feature_type": feature_type, "slug": slug}


# --- Shared workflow constants ---


SDLC_STEPS = [specify, branch, implement, document]
"""List of handler functions that make up the standard SDLC workflow."""


# --- Workflows ---


@app.handler
def specify_implement(runner: Runner, state: State) -> State:
    """Run partial SDLC workflow: specify -> implement.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "prompt" key.

    Returns:
        State after specify and implement steps have been executed.
    """
    return run_workflow(runner, state, [specify, implement])


@app.handler
def sdlc(runner: Runner, state: State) -> State:
    """Run the full SDLC workflow: specify -> branch -> implement -> document.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "prompt" key.

    Returns:
        Final state after all SDLC steps have been executed.
    """
    return run_workflow(runner, state, SDLC_STEPS)


@app.handler
def specify_and_branch(runner: Runner, state: State) -> State:
    """Run partial SDLC workflow: specify -> branch.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "prompt" key.

    Returns:
        State after specify and branch steps have been executed.
    """
    return run_workflow(runner, state, SDLC_STEPS[0:2])


@app.handler
def sdlc_iso(runner: Runner, state: State) -> State:
    """Run SDLC workflow inside an isolated git worktree.

    Creates a git worktree with a feature branch based on derived metadata,
    then executes the SDLC workflow (specify -> implement -> document) within
    that isolated environment. The worktree is not automatically removed.

    Args:
        runner: The Runner instance executing the workflow.
        state: Current workflow state dictionary. Must contain "prompt" key.

    Returns:
        Final state with additional "worktree_path" and "branch_name" keys.
    """
    state = derive_feature(runner, state)
    worktree_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{runner.id}"
    branch_name = f"{state['feature_type']}/{state['slug']}"
    wt = Worktree(base_dir=runner.app.worktree_dir, name=worktree_name)
    with git_worktree(wt, create=True, branch=branch_name, remove=False):
        state = run_workflow(runner, state, [specify, implement, document])
    return {**state, "worktree_path": wt.path, "branch_name": branch_name}
