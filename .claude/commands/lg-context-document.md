---
description: Update codebase documentation with full codebase access
model: opus
argument-hint: [focus]
allowed-tools: Read, Write, Edit, Bash(*), Glob, Grep, Skill, Task
---

# Purpose

Update all documentation to accurately reflect the current codebase. Leverages the large context window to load source, tests, and existing docs upfront — then updates everything in a single pass.

## Variables

FOCUS: $ARGUMENTS
- Git commit(s), files, directories, experts, or a description of recent changes
- Default to the whole system when empty

## Instructions

You are a documentarian with full codebase access. Your job is to make the documentation truthful — it should describe what the code actually does, not what it used to do or what someone hopes it will do.

### Principles

- **Accuracy over completeness.** A short correct doc beats a long stale one.
- **Don't duplicate.** Each fact lives in one place. If `instrumentation.md` covers logging, `README.md` should not repeat the details — just point there.
- **Match the code.** If a doc describes a function signature, config option, or env var, verify it still exists and works that way. Remove or update anything that doesn't.
- **Preserve voice.** Each doc has an established style. Match it. Don't rewrite working prose.
- **Don't pad.** No filler, no "this document describes...", no tables of contents within small files.

### What NOT to do

- Do not add docstrings or comments to Python source files — this command updates documentation files only
- Do not change code behaviour
- Do not create new documentation files unless there is a clear gap (a whole subsystem with zero docs)

## Workflow

### Phase 0: Load Context

Read everything upfront so you have the full picture before making any changes.

1. **Source code** — `Glob("src/**/*.py")` then read all files
2. **Tests** — `Glob("tests/**/*.py")` then read all files
3. **Existing docs** — read every file in `app_docs/`, plus `README.md` and `CLAUDE.md`
4. **Specs** — if FOCUS names a branch, read the matching spec from `specs/`. Otherwise read any uncommitted specs.
5. **Recent changes** — if FOCUS names commits or a branch, run `git log` and `git diff` to understand what changed

After loading, note any discrepancies between code and docs before proceeding.

### Phase 1: App Docs

Update the following files in `app_docs/` to reflect the current codebase. For each file, compare what the doc says against what the code actually does. Fix discrepancies. Add coverage for new features. Remove coverage for removed features.

- **releasing.md** — packaging, dependencies, release process
- **testing_policy.md** — test approach, fixtures, patterns (not individual test cases)
- **instrumentation.md** — progress reporting, logging, state persistence, tracing
- **http_server.md** — HTTP endpoints, configuration, design
- **slack.md** — Slack integration, configuration, runtime behaviour
- **standards.md** — engineering standards and design philosophy
- **reference.md** — project structure, core concepts, handler patterns, data flow

After updating the individual files, update **app_docs/README.md** to accurately index what each file covers.

### Phase 2: Experts

Ask each expert to self-improve by invoking their skill:

- `design-expert` — invoke with "self-improve"
- `otel-expert` — invoke with "self-improve"
- `channels-expert` — invoke with "self-improve"

These run in parallel as blocking skill invocations so the experts can read the (now-current) codebase.

### Phase 3: README

Update `README.md` last, after all other docs and experts are current. The README is the entry point — it should orient developers quickly and point them to `app_docs/` for depth.

Check:
- Core concepts still accurate
- Quickstart still works
- Design principles still reflect reality
- Links to app_docs/ files are correct
- No overlap with detailed content that belongs in app_docs/

## Report

- Files updated (each with a one-line summary of what changed)
- Files unchanged (confirmed accurate)
- Expert self-improve results
- Any gaps found that could not be resolved (e.g. ambiguous code, missing context)
