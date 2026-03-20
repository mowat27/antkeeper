---
description: Implement a spec with full codebase access
model: opus
argument-hint: [spec-file]
allowed-tools: Read, Write, Edit, Bash(*), Glob, Grep, Task, TodoWrite
---

# Purpose

Implement a spec by reading the codebase directly, identifying affected files, writing tests, and validating the result to zero errors.

## Variables

SPEC_FILE: $1
ARGUMENTS: $ARGUMENTS

- If SPEC_FILE is empty, unset, or literally `$1`, search for the most recent uncommitted spec in `specs/`
- If no spec can be found, stop and ask the user for the path

## Instructions

You are a builder with full codebase access. The spec tells you WHAT to build and the architectural decisions behind it. You determine HOW to implement it.

### Your Responsibilities

1. **Understand the spec** — read it fully. Understand the interface changes, acceptance criteria, and any architectural constraints called out in Notes.
2. **Find the relevant files yourself** — use Glob and Grep. Do not wait to be told what to read.
3. **Validate architectural fit before writing code** — check your approach against the existing patterns. Use the design-expert skill when uncertain. It is better to pause and check than to implement something that breaks the architecture.
4. **Write tests** — follow `app_docs/testing_policy.md` exactly. Tests exercise framework behaviour, not app logic.
5. **Reach zero** — all validation checks must pass with zero errors and zero warnings before you are done. Investigate and fix failures; do not explain them away.

### Non-Negotiable Rules

- Do not change the core design unless the spec explicitly requires it
- The core must remain generic; channel-specific concerns stay in channels
- State is a plain dict; handlers are pure functions `(runner, state) -> state`; no mutation
- Exceptions propagate by default; only catch at edges where a stack trace adds no value
- No backwards-compatibility shims, unused variables, or re-exports for removed code
- Do not add features, refactoring, or improvements outside the spec scope — implement exactly what is specified, nothing more

### When to Use design-expert

Invoke the design-expert skill before writing code if you are unsure about:
- Where a new concept belongs in the layer structure
- Whether something belongs in core vs channels vs handlers
- How a new type or function should be named and structured
- Whether an error should be caught or propagated

## Workflow

1. Read the spec file completely
2. Read the documentation and consult the experts listed in the spec's `## Resources` section
3. Use Glob and Grep to find all source files relevant to the spec's schema changes and acceptance criteria
4. Read those files
5. Implement all changes
6. Update Python docstrings on any source files you changed (module, class, and function level). Do not update docstrings in test files.
7. Write tests
8. Run validation commands — fix all failures before proceeding
9. Report

## Relevant Files

Specified in the `## Resources` section of the spec.

## Report

- Files changed (each file with a one-line description of what changed)
- Tests added (count per file)
- Output of `git diff --stat`
- Validation results: ruff, ty, pytest (pass/fail with counts)
