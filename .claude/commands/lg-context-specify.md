---
description: Generate a lightweight architectural spec for large-context implementation
model: opus
argument-hint: [feature-type] [descriptive-slug]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(*), WebFetch, WebSearch, Task
---

# Purpose

Generate an architecturally-compliant spec that defines what to build and why, leaving implementation details to the builder agent.

## Variables

FEATURE_TYPE: $1
SLUG: $2
ARGUMENTS: $ARGUMENTS

- Derive FEATURE_TYPE from $ARGUMENTS if $1 is not an obvious feature type (e.g. `feature`, `chore`, `patch`, `bugfix`, `refactor`)
- Derive SLUG from $ARGUMENTS if $2 is not an obvious slug (e.g. `add-slack`, `fix-login`)
- SLUG must be lowercase with `hyphens-for-spaces`

IMPORTANT: Never override a user-supplied FEATURE_TYPE.

## Instructions

CRITICAL REQUIREMENTS — You MUST follow these exactly:

1. **YOU ARE SPECIFYING, NOT IMPLEMENTING.** Your ONLY job is to produce a spec document. Do NOT write any code. Do NOT make any changes to source files, test files, or configuration. If you find yourself editing a `.py` file, stop immediately — you are doing the wrong job.
2. **RESEARCH FIRST.** Before writing anything, read the codebase and documentation thoroughly to understand existing patterns, architecture, and conventions.
3. **OUTPUT LOCATION.** Create the spec in `specs/` with filename: `{FEATURE_TYPE}-{SLUG}.md`.
4. **NO PLACEHOLDERS.** Replace every `<placeholder>` in the Spec Format with real, specific content. Vague or incomplete specs are unacceptable.
5. **AVOID OVER-SPECIFICATION.** Only include changes that are actually needed. Do not mention files that don't need to change, future features that may come later, or "just in case" additions.
6. **NO PLAN MODE.** Under no circumstances should you or any agent enter plan mode.

Your spec must answer three questions:

1. **What changes** — precise interface contracts and external behaviour
2. **Why it fits** — how the change aligns with the existing architecture
3. **What success looks like** — measurable acceptance criteria

Do NOT include: lists of files to change, step-by-step implementation workflows, or named test functions. The builder agent has full codebase access and will determine these itself.

### Design Philosophy

- The system is a generic, extensible framework supporting multiple channels (CLI, Slack, API) and LLM providers
- Outer layers (channels) own runtime type/value checks; the core must remain generic
- Reducer pattern: every handler receives `(Runner, State) -> State`; state is immutable and ephemeral per run
- Exceptions propagate by default; only handle at edges where a stack trace adds no value
- Composition over inheritance; no DAG schedulers, no base classes
- Convention over configuration; sensible defaults throughout

### Breaking Changes

If ARGUMENTS contain "BREAKING CHANGE" (or variant), explicitly instruct the builder to ignore backwards compatibility. This prevents unnecessary complexity when a design mistake is being corrected.

## Workflow

- IF FEATURE_TYPE is `patch` or `chore`: run `lightweight-process`
- ELSE: run `full-process`

### full-process

1. Research the codebase directly — read the relevant source files, docs, and existing patterns. You have full context capacity; there is no need to delegate research to a sub-agent.
2. Design the solution. Write a concise internal summary of what you propose to build.
3. Spawn these in parallel as blocking Tasks:
   - **Craig** (subagent_type: general-purpose) — assesses the proposed design for unnecessary complexity and over-engineering
   - **Eduard** (subagent_type: general-purpose) — assesses the proposed design for correctness and architectural consistency
4. Synthesize their feedback, resolve any conflicts, write the final spec.

Rules for spawning agents:
- Pass your design summary to Craig and Eduard — do not make them re-read the codebase
- Instruct each to return a concise report, not raw file contents
- Do NOT create a team. Do NOT use run_in_background. Plain blocking Task calls only.
- As overseer, ensure: the spec meets the goals, conforms to design philosophy, no scope creep, no pre-emptive abstractions, no "just in case" changes

### lightweight-process

1. Read the codebase as needed to understand the change
2. Design the solution
3. Write the spec

## Spec Format

```md
# <FEATURE_TYPE>: <description — 10 words max>

<3 bullets max summarising the goal. 25 words max each. Sacrifice grammar for concision.>

## Solution Design

### External Interface Change

<What new capabilities exist. Include usage examples for each affected channel (CLI, API, Slack). Omit channels that are unaffected.>

### Architectural Schema Changes

<YAML describing changed interfaces, types, and function signatures. Use the format below. Omit this section entirely if there are no interface changes.>

```yaml
types:
  Foo:
    kind: dataclass
    fields:
      - bar: str

functions:
  my_function:
    module: antkeeper.core.app
    params:
      - runner: Runner
      - state: State
      - new_param: "int = 0"  # NEW
    returns: State
```

### Breaking Changes

<Only present if explicitly requested in ARGUMENTS. Instructions to ignore backwards compatibility.>

## Acceptance Criteria

<Specific, measurable criteria. Each must be independently verifiable. Include any invariants the builder must preserve (e.g. "X key must never appear in persisted state").>

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run pytest tests/ -v
```

IMPORTANT: All checks must pass with zero errors and zero warnings. Investigate and fix any failures — do not explain them away.

## Resources

### Documentation

<List only the app_docs files the implementer actually needs for this change, and briefly state why each is relevant. Omit docs that are not relevant to this change.>

### Experts

<List which expert skills are available and describe the specific situations in this change where the implementer should invoke them. At minimum, include the design-expert skill and describe when it applies here.>

## Notes

<Optional. Architectural constraints, design decisions, or gotchas the builder must know. Omit if nothing material to add.>
```

## Relevant Files

- `app_docs/` — read everything in this directory before designing the solution
- `README.md` — framework overview and developer documentation

Use the design-expert skill proactively to validate architectural decisions before committing to them in the spec.

**Finding experts:** Experts are skills already loaded into your context. Identify them by scanning the skill descriptions you already have in context — a skill is an expert if its description explicitly says so (e.g. "Design expert skill"). Include the relevant ones in the spec's `## Resources → Experts` section so the implementer knows what to use and when.

## Report

Provide:

- Location of the spec file
- Overview of the design decision
- Observations from agents and how conflicts were resolved
- Trade-offs and assumptions made

IMPORTANT: Always write the spec. Never stop to ask for clarification or permission.
