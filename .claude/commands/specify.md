---
description: Generates a spec for a change
model: Opus
argument-hint: [feature-type] [descriptive-slug]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(*), WebFetch, WebSearch
---

# Specify Change

Specify a change to the system

## Variables

FEATURE_TYPE: $1
SLUG: $2
ARGUMENTS: $ARGUMENTS

* Derive FEATURE_TYPE from $ARGUMENTS if, and only if,  $1 is not an obvious feature type - e.g. `feature`, `chore`, `patch`, `refactor`, `bugfix` etc.
* Derive SLUG from $ARGUMENTS if $2 is not an obvious slug type - e.g. `add-slack`, `improve-test-coverage` etc
* SLUG must be all lowercase with `hyphens-for-spaces`

IMPORTANT: it is essential that you never override the user's FEATURE_TYPE if one is provided becuase some feature types use the lightweight workflow below.

## Instructions

CRITICAL REQUIREMENTS - You MUST follow these exactly:

1. **YOU ARE SPECIFYING, NOT IMPLEMENTING.** Your ONLY job is to produce a detailed spec document. Do NOT write any code.
2. **RESEARCH FIRST.** Before writing anything, thoroughly research the codebase and documentation to understand existing patterns, architecture, and conventions.
3. **OUTPUT LOCATION.** Create the spec in `specs/` with filename: `{FEATURE_TYPE}-{SLUG}.md` (e.g., `feature-add-auth.md`, `chore-update-deps.md`, `bugfix-login-crash.md`).
4. **NO PLACEHOLDERS.** Replace EVERY `<placeholder>` in the `Spec Format` with real, specific content. Vague or incomplete specs are unacceptable.
5. **PRECISION MATTERS.** Be thorough and precise. There will be NO second round of changes - the spec must be complete and actionable on first delivery.
6. **USE THE FORMAT EXACTLY.** Follow the `Spec Format` section precisely. Do not skip sections or invent new structure.
7. **FOLLOW THE RULES.** Use the `Rules` to define specific sections.
8. **NO PLAN MODE** Under no circumstances should you or any agent enter plan mode.
9. **AVOID OVER SPECIFICATION** Only include changes that are actually needed.  Avoid mentioning anything unecessary that could bloat the context of a builder agent such as files that do not need to change or future features that may come later.

### Rules

#### Design Philosophy

When designing the solution, remember:

* The system is a generic and extensible framework that can work with a range of 3rd party channels (CLI, Slack, GitHub Issues etc) and LLM Providers/Platforms (Claude Code, Gemini API, LangChain)
* Users are developers
* Use built in Python packages by default except for common exceptions like `pytest`, `pandas` etc
* The outer layers (channels etc) are responsible runtime type and value checks to prevent bad data getting into the core.
* Exceptions are often allowed to propogate up to handlers:
  - Handler errors like missing keys in state must propogate
  - Runtime issues like failed connections must propogate
  - Coding errors like naming mistakes must propogate
  - Failed validations at the edges of the system like checking for parameters can be handled and reported to users by the framework but only when the stack trace would provide no value
* Specifics must be isolated in the outer layers of the system and the core must be truly generic.  For example, a GitHub issue number or Jira Issue ID must not ever appear in the core
* Outer layers (e.g. Channels) must depend on inner layers like `core`
* The core of the system is a reducer pattern that allows client code to define steps in workflows.  Every step gets a context object and a `State` object and returns a new `State` that is passed to the next step.  The result of the reduction is the final state.  The state is ephemeral and never shared between workflows - this ensures thread safety in a server environment (one `App` can be used for multiple workflows) and makes it easy to reason about.
* It is ESSENTIAL that you do not change the core design unless explicitly asked.

#### Design Changes

The solution design section must include the following when relevant:

**External Interface Change**: Description of what new capabilities the `channels` will have available to them with examples.  Include examples for all the channels of what will be possible when the specced change has been built.

**Architectural Schema Changes**: A YAML document that describes the changed interfaces in the system using the yaml format below

```yaml
types:
    AgentContext:
      kind: dataclass
      fields:
        - mission_id: str
        - name: str
        - executor: AgentExecutor | None # Support for None added
        - workdir: str
        - branch_name: str
        - mission_source: MissionSource | None  # New field
        - logger: Logger | None
```

**REST Changes**: Use bullet points for all changes to REST endpoints using standard notation like `POST /foo/:id?arg=value` and a short description of what changed.

**Database Changes**: Use bullet points for all changes to database object like tables, indexes and constraints.

#### Breaking Changes

If `ARGUMENTS` contain "BREAKING CHANGE" or similar ("BREAKING_CHANGE", "breaking-change" etc) then specifically include instructions in the spec to ignore backwards compatability.  This is essential to prevent over complication in the codebase when a mistake or discovery is discovered in the design.

#### Testing

- **Test the framework, not the app.** Import from the library (`antkeeper.core.*`). If a test needs handlers, define them in the test suite — they exist to exercise the core machinery, not to replicate production logic.
- **Each test owns its setup.** Build the `App`, register handlers, and wire the `Mission` inside the test. No shared global state. This makes it obvious what each test is actually exercising.
- **Replace I/O at the boundary.** Swap sources/sinks that do I/O (print, stderr) with capturing doubles that collect into lists. Match the interface via duck typing.
- **One test per code path.** If two tests traverse the same core path with different data, they're the same test. A single-handler workflow is one path regardless of what the handler computes.
- Refer to `app_docs/testing_policy.md` as well

## Workflow

* IF the FEATURE_TYPE is `patch` or `chore` run the `lightweight-process`
* ELSE run the `full-process`

<full-process>
  The overseer (you) coordinates the spec by spawning agents via **blocking Task calls** — not background teammates. This keeps each
  agent's research out of your context window while giving you simple sequential/parallel control.

  **Execution pipeline:**

  1. Spawn a **Designer** agent (blocking Task, subagent_type: general-purpose). It researches the codebase, designs the solution, and returns a concise summary. Do NOT spawn it in the background.
  2. Once the Designer returns, spawn these **in parallel** as blocking Task calls:
      - **Tester** (subagent_type: general-purpose) — designs test cases based on the Designer's output
      - **Craig** (subagent_type: craig) — assesses the Designer's output for simplicity
      - **Eduard** (subagent_type: eduard) — assesses the Designer's output for correctness and consistency
  3. Synthesize all inputs, resolve conflicts, and write the final spec file. Only you write the spec.
  4. Populate the template in the `Spec Format` and write the spec to `specs/` with filename: `{FEATURE_TYPE}-{SLUG}.md`

  **Rules for spawning agents:**
  - Pass the Designer's summary into each reviewer's prompt — do not make them re-read the codebase.
  - Instruct each agent to return a concise report (not raw file contents).
  - Do NOT create a team. Do NOT use run_in_background. Plain blocking Task calls are sufficient.
  - The `overseer` has a pivotal role in ensuring that the other agents stay on track and do not diverge.  As such it must ULTRA THINK and make sure that:
    - The spec meets the goals of the change
    - The spec conforms to the `Design Philosophy`
    - The solution is simple and does not add any non-essential complexity
    - The work of the other agents does not conflict - either logically or structurally - with one another
    - Scope does not creep
      - do not allow additional changes outside of the scope of this change to be included in the spec
      - do not allow "just in case" or "useful for later" changes (pre-emptive abstraction etc)
      - THINK HARD about whether an error should be handled or allowed to propogate up the handler.
      - do not allow over zealous value and type checking
</full-process>


<lightweight-process>
  1. Read all `Relevant Files`
  2. Design the solution and tests
  3. Populate the `Spec Format` template and write it to `specs/` with filename: `{FEATURE_TYPE}-{SLUG}.md`.
</lightweight-process>

## Spec Format

```md
# <FEATURE_TYPE>: <feature description - 10 words max>

<Write bullet points - 3 at most - to summarise of the goal of the feature.  Each bullet must be 25 words at the most.  Sacrifice grammar for the sake of concison.>

## Solution Design

<Add an h3 for each of the relevant design changes in the `Rules` above>

## Relevant Files

Use these files to fix the bug:

<find and list the files that are relevant to the feature describe why they are relevant in bullet points. If there are new files that need to be created to implement the feature, list them in an h3 `### New Files` section.>

## Workflow

<list step by step tasks as h3 headers plus bullet points. use as many h3 headers as needed to fix the bug. Order matters, start with the foundational shared changes required to fix the buh then move on to the specific changes required to fix the bug. Your last step should be running the `Validation Commands` to validate the bug is fixed with zero regressions.>

## Testing Strategy

### Unit Tests
<describe unit tests needed for to replicate and fix the bug.  >

### Integration
<describe integration tests needed for to replicate and fix the bug - omit if none requested>

### Edge Cases
<list edge cases that need to be tested>

## Acceptance Criteria
<list specific, measurable criteria that must be met for the bug to be considered fixed>

### Validation Commands

<List explicit, actionable, runnable criteria that must be met for the bug to be considered fixed.  At a bare minimum, this must include running ALL the tests, typechecks and other standard checks described in the application documentation.  In addtion to the standard checks you should also include bespoke checks that validate the bug has been fixed and the system remain stable>

IMPORTANT: If any of the checks above fail you must investigate and fix the error.  It is not accepatable to simply explain away the problem.  You must reach zero errors, zero warnings before you move on.  This includes pre-exsiting issues and other issues that you don't think are related to this bugfix.

## Notes
<optionally list any additional notes or context that are relevant to the chore that will be helpful to the developer>

## Report

<Describe what the spec should report.  Minimum: files changed, tests added, validations added.  Include anything else that might be useful. Max length: 200 words>
```

## Relevant Files

* `app_docs/README.md` - provides an index into the application documentation files.  You MUST read this and use the resources provided to ensure you are building to existing standards
* `README.md` - contains developer documentation and how to use the framework.  Use this as additional context.

The design expert skill will answer questions about how the system is designed.  Use it proactively as needed.

## Report

Provide:

* **IMPORTANT**: Location of spec file
* Overview of design
* Observations from agents and decisions made
* Trade offs and assumptions made

IMPORTANT: Always write the spec document.  Never stop and ask for clarification or permission.

