# Design: OpenRig-native step communication for generated rigs

Status: agreed with orch-lead@pw-website (22:13Z); sections 1 and 2 are built, section 3 is deferred

## Review outcome

- Section 1 agreed. The note is one JSON object, `{"summary", "state"}`, with
  `summary` first.
- Change 1: the resume state comes from the orchestrator. It finds the failed
  step's input state using the trail lookup in its own role, corrects the state
  if needed, and passes it in `rig workflow resume --decision` as
  `{"summary", "state"}`. A step reads its state from the single JSON object in
  its packet: `Root objective`, `Prior step note` or the resume `decision`. If a
  resume carries no state, the step fails again rather than guessing.
- Change 2: seats always read packets with `rig queue show <id> --full`. The
  default view truncates bodies and would cut the JSON short.
- Section 2 agreed.
- Section 3 deferred. It is not communication, and `sdlc_iso` worktrees did not
  work before this change either. If it is built later, a dedicated seat owns
  glue steps, not the orchestrator, whose role forbids step work.
- Section 4: items 6 and 7 are out of scope. The `--permission-policy` default is
  Adrian's decision, so the flag lands as a separate commit.
Base: commit 2086ae2 (`fix/generate-rig-run-id`)
Branch: `feat/generate-rig-native-state`
Researched against: OpenRig 0.6.5 (CLI help and daemon source)

## Goal

Generated rigs stop using `.antkeeper/state/<instance-id>.json`. Steps and the
orchestrator exchange antkeeper state through OpenRig's workflow runtime, and
every `handlers.py` data flow still works. Done means Adrian's `/sdlc` test
passes on a regenerated pw-website.

## What OpenRig offers

| Primitive | What it carries | Verdict |
|---|---|---|
| `rig workflow project --result-note` | Free text. Stored on the instance as `lastContinuationDecision.resultNote` (`rig workflow show --json`) and copied verbatim into the next packet's body as `Prior step note: …`. Only the immediately prior note travels. | **Carrier for state** |
| Packet bodies | Entry: `Root objective` and `Step objective`. Handoff: `Objective` and the prior note. The objective comes from the current spec, and the daemon re-caches a spec whose content changed. Resume packets carry neither, only the resumer's `--decision` and a pointer to `rig workflow trace`. | **Carrier for instructions** |
| `rig workflow trace --json` | Each step's closure: step, actor, exit, `priorQitemId` (the packet the step closed) and `nextQitemId`. No notes. | Index for recovery |
| `rig workflow instantiate --root-objective` | The only input channel. There is no instance key/value store and no typed inputs. | Seed input |
| `--evidence-ref`, `--acceptance-*` | References to artefacts and acceptance verdicts, not data. | Not needed |
| Context packs, stream, chatroom | An operator-authored library, an intake feed, and chat. None is scoped to one workflow run. | Rejected |

## Proposal

### 1. State travels in result notes

The state file goes away. Each step closes its packet with a result note that
holds the whole state so far:

```text
--result-note '{"summary": "specify done: set spec_file, slug", "state": {"prompt": "…", "run_id": "…", "workflow_name": "sdlc", "spec_file": "specs/x.md", "slug": "x"}}'
```

A step reads its input state from the packet that brought it:

| Packet | Where the state is |
|---|---|
| Entry (first step) | `Root objective`. A JSON object is the initial state (antkeeper's `--initial-state`); anything else becomes `{"prompt": …}`. The step adds `run_id` (the instance id) and `workflow_name` (the workflow id). |
| Handoff | The `state` object in `Prior step note`. |
| Resume | Not in the packet. Take the trail entry for this step with exit `failed`; its `priorQitemId` is the packet the step failed on, and that packet's body holds the state the step received. Run `rig workflow trace <id> --json`, then `rig queue show <qitem> --full`. |

A failed step's note is plain text giving the reason. State recovery on resume
does not depend on it.

What this fixes from the brief:

- **Observation 1, state invisible to the runtime:** the latest state is in
  `rig workflow show <id> --json` (`lastContinuationDecision.resultNote`).
  Every step's output is in the body of the packet it handed to the next step.
  The close packet carries the final state, so the orchestrator no longer
  reads files.
- **Observation 2, run identity:** `run_id` and `workflow_name` come from the
  packet header, which the runtime writes, and then travel in state so that
  `$run_id` resolves as it does in antkeeper.
- **Observation 3, seeding:** there is no native input channel other than the
  root objective, so the JSON-object root objective stays as the convention.
  The orchestrator's role documents it.

Risks:

- The JSON must be single-quoted in the shell. Seats already handle
  `'\''` escaping for root objectives.
- The prompt is repeated in every note. I found no length limit in the 0.6.5
  source, and antkeeper prompts are small.

### 2. Step instructions reach running seats (observation 4)

Each step's spec objective says: *"Antkeeper step `X`. Read
`.openrig/agents/X/guidance/role.md` before acting; it is the current
instruction."* Handoff and entry packets carry the current spec's objective, so
a regenerated role reaches a running seat on its next packet without a
relaunch. Resume packets carry no objective, so the role itself also says to
re-read the role file on every packet. The first regeneration after adopting
this still needs one re-read, because the seats are running the old role.

### 3. Workflow glue, including sdlc_iso's worktree

A composite handler's statements between step calls become orchestrator
steps at that point in the spec. For `sdlc_iso`:

```text
derive_feature → sdlc_iso-setup (orchestrator) → specify → implement → document → close
```

`sdlc_iso-setup` performs the handler code between `derive_feature` and
`run_workflow`: it creates the worktree and branch as the source does, and
adds `worktree_path` and `branch_name` to state. Steps called inside
`with git_worktree(...)` get "work in `$worktree_path`" in their objective.
Glue after the last step merges into `close`. Segmentation is generic: any
non-step statements become glue. The only antkeeper-specific knowledge is that
`git_worktree` changes the working directory.

### 4. Flagged, not built

| Observation | Call |
|---|---|
| 5. Permission stalls | Partly in scope: add `--permission-policy <policy>` to `generate-rig`, written to `rig.yaml` `permission_policy`. The default stays the floor, so Adrian chooses. While building I'll check which built-in matches the auto mode he uses now. The generator can't know what each step's skills need, so I won't widen the allowlist fragment beyond `rig`. |
| 6. No human seat | Out of scope. Registering a human is operator setup (`rig gateway human …`). The orchestrator's role keeps "ask the user in the terminal" as the fallback. |
| 7. Seats keep context between runs | Out of scope for the generator. For a clean test, relaunch the rig fresh between runs. Adrian has to do that, because the orchestrator would stop itself. |

## Changes to generated artefacts

- **Step roles:** the packet protocol in section 1, plus "re-read this role on
  every packet". All mention of `.antkeeper/state` is removed.
- **Orchestrator role and skills:** close reads the final state from the close
  packet's prior note; JSON seeding is documented; the resume guidance is
  unchanged; glue steps are part of the role.
- **`CULTURE.md`:** the "Workflow state" section is rewritten for notes.
- **Workflow specs:** objectives point at the role file; glue steps and
  worktree hints are added.

## Test plan

1. Unit tests: glue segmentation (`sdlc_iso`), spec shape, and role text.
2. Scratch rig, live: a seeded key, `$run_id`, a failure and resume with state
   recovered from the trail, and a glue step that creates a worktree.
3. Adrian's test: orch-lead@pw-website regenerates and re-runs `/sdlc` (up to 3
   runs).

## Questions for the reviewer

1. Note format: `{"summary", "state"}` JSON, or a plain summary line followed by
   the JSON?
2. Glue steps: should the orchestrator own them, or a dedicated seat per
   workflow?
3. Should `--permission-policy` default to the floor, or to the policy that
   matches Adrian's current auto mode?
