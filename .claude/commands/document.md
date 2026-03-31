---
description: Update codebase documentation
model: sonnet
argument-hint: [focus]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(*), WebFetch, WebSearch
---

# Document

Review and update the codebase's documentation

## Variables

FOCUS: Git commit(s), files, directories, experts etc. Default to whole system.

## Instructions

* Use standard python documentataion standards for python files
* Update experts by asking them to self-improve

## Workflow

* Find all python files in the focus area using the appropriate method (`git`, `ls` etc) but do not read them
* Spawn subagents to do the following (blocking Tasks, subagent_type: general-purpose)
  * **Python Documenter** agents (max: 5). Each reads a batch of files, updates the python docs and returns a concise summary. Do NOT spawn it in the background.
  * **Expert Updater** agent. Find all expert skills in context (name ends with `-expert`) and asks them to "self improve" simultaneously, in parallel.
  * **App Docs Updater** agent.  Follows `App Doc Update Workflow`

### App Doc Update Workflow

* Find commits related to the FOCUS
* Find the spec(s) related to the current FOCUS in `spec/`
  - **hint**: if the FOCUS is a branch then you must choose the spec that matches the branch name. Do not waste time searching them all.
* Look for changes to our policies
  - new ideas that were included in the spec
  - changes that were made after the main build (ie gaps in our specs)
  - anything else that indicated a gap in the spec or surrounding documentation
* Use the information to update the following files
  * **app_decs/releasing.md** - documents how we packaging and releasing
  * **app_decs/testing_policy.md** - documents how we do testing - e.g. test approach, fixture management etc - NOT the specifics of the test cases we run (those can be taken from the code)
  * **app_decs/instrumentation.md** - documents how we report progress at runtime. This includes logging and state persistance.
  * **app_decs/http_server.md** - documents the http server - endpoints, configuration, design etc at an abstract level but do not overlap with the slack docs below
  * **app_decs/slack.md** - documents the slack integration - configuration on the slack side, runtime behaviour etc
  * **README.md** - developer documentation - how to install and use.  Do not reference other files.  This is just enough for developers to get oriented not a complete instruction manual and they can ask an Agent if they need to learn more.
* Update `app_decs/README.md` with an index of the files in `app_docs/` and what is covered by each.

IMPORTANT: if any files are not present then create them from scratch by looking at the existing codebase, `README.md` and `CLAUDE.md`.  Move redundant information out of `README.md` and `CLAUDE.md` if it is covered by the new docs.


## Report

Bullet point summary of the changes made.  Include a list of all files changed including expertise documents owned by skills (`.claude/skills/*/expertise.yaml`)
