---
name: "experiment-bridge"
description: "Workflow 1.5: Bridge between idea discovery and auto review. Reads EXPERIMENT_PLAN.md, implements experiment code, runs a bounded debate using a secondary Codex agent, deploys to GPU, and collects initial results."
---

# Workflow 1.5: Experiment Bridge

Implement, debate, and deploy experiments from plan: **$ARGUMENTS**

## Overview

This skill bridges Workflow 1 (idea discovery + method refinement) and Workflow 2 (auto review loop). It takes the experiment plan and turns it into running experiments with initial results.

```
Workflow 1 output:                    This skill:                                                         Workflow 2 input:
refine-logs/EXPERIMENT_PLAN.md   →   implement → debate → sanity/runtime review → deploy → collect   →   initial results ready
refine-logs/EXPERIMENT_TRACKER.md     code        (secondary Codex agent)   (/run-experiment)            for /auto-review-loop
refine-logs/FINAL_PROPOSAL.md
```

The debate loop is default-enabled in v1. It is framework-agnostic at the core, but it may recommend faster frameworks, runtimes, or kernel work when runtime evidence clearly justifies it.

## Constants

- **CODE_REVIEW = true** — Keeps the experiment review gate enabled. Set `false` to preserve the legacy direct implementation → sanity → deploy path.
- **CODE_REVIEW_MODE = `debate`** — Review mode. `single` = one reviewer pass. `debate` = bounded multi-round executor vs. reviewer loop.
- **MAX_DEBATE_ROUNDS = 3** — Maximum pre-run debate rounds before auto-deploy is blocked on unresolved critical issues.
- **RUNTIME_REVIEW = true** — Re-enter review after sanity failures or blocker-level runtime anomalies.
- **OPTIMIZATION_REVIEW = true** — Ask the reviewer to look for framework, backend, memory, throughput, and kernel opportunities in a second pass.
- **OPTIMIZATION_AUTHORITY = `recommend`** — Recommendation-only in v1. The skill may argue for a change, but must not silently switch frameworks or write Triton/CUDA just because the reviewer suggested it.
- **WORKLOAD_PROFILE = `mixed`** — Expected workload shape. Options: `mixed`, `training`, `inference`.
- **LIGHT_PROFILE = true** — Request a short hotspot / memory sample during sanity runs when the stack exposes a clean profiler. Fall back to coarse timing and memory evidence otherwise.
- **LONG_RUN_RESUME = `required`** — Any experiment that is multi-step or likely to run for 10+ minutes must be resumable. Missing resumeability is a deployment blocker.
- **LONG_RUN_THRESHOLD = `10min_or_multi_step`** — Classify a run as "long" if it is clearly iterative (training / finetuning / search / long batched generation or evaluation) or likely to exceed roughly 10 minutes.
- **SYNC_LOCAL_REMOTE = `origin`**
- **SYNC_REMOTE = `upstream`**
- **SYNC_BRANCH = `main`**
- **SYNC_TARGET_BRANCH = `main`**
- **SYNC_ON_ENTRY = true**
- **SYNC_PUSH = true**
- **SYNC_BRANCH_MODE = `main_only`**
- **REPO_LOCAL_MEMORY = true** — Read repo-local experiment memory before redesigning runs or repeating failed runtime fixes.
- **REPO_LOCAL_VENDOR_SKILLS = true** — Repo-local vendor skills live under `vendor-skills/` and can be reused locally without publishing them globally.
- **AUTO_DEPLOY = true** — Automatically deploy experiments after implementation + review. Set `false` to manually inspect code before deploying.
- **SANITY_FIRST = true** — Run the sanity-stage experiment first (smallest, fastest) before launching the rest. Catches setup bugs early.
- **MAX_PARALLEL_RUNS = 4** — Maximum number of experiments to deploy in parallel (limited by available GPUs).
- **BASE_REPO = false** — GitHub repo URL to use as base codebase. When set, clone the repo first and implement experiments on top of it. When `false` (default), write code from scratch or reuse existing project files.
- **REVIEWER_MODEL = `gpt-5.4`** — Model used via a secondary Codex agent. Must be an OpenAI model (for example `gpt-5.4`, `o3`, `gpt-4o`).

> Override: `/experiment-bridge "EXPERIMENT_PLAN.md" — code review mode: single, workload profile: inference, light profile: false`

## Prerequisites

- Use `spawn_agent` and `send_input` when the user has explicitly allowed delegation or subagents.
- If delegation is not allowed, run the same debate loop locally and preserve the same deliverable structure.

## Inputs

This skill expects one or more of:

1. **`refine-logs/EXPERIMENT_PLAN.md`** (best) — claim-driven experiment roadmap from `/experiment-plan`
2. **`refine-logs/EXPERIMENT_TRACKER.md`** — run-by-run execution table
3. **`refine-logs/FINAL_PROPOSAL.md`** — method description for implementation context
4. **`IDEA_REPORT.md`** — fallback if refine-logs don't exist
5. **`memory/experiment-memory.md`** (optional, recommended) — reusable lessons about bad experiment patterns, proven strategies, resume pitfalls, and metrics lessons
6. **`vendor-skills/INSTALLED_SKILLS.json`** (optional) — repo-local third-party skills staged for this repo

If none exist, ask the user what experiments to implement.

Before Phase 1, try:

```bash
python3 tools/aris_upstream_sync.py sync
```

Continue on success, "no updates", or a temporary fetch / network failure. If the sync reports tracked worktree changes, local `main` vs `origin/main` divergence, a migration blocker, or an unresolved sync conflict, stop and fix the repo state before implementing experiments. The sync flow is origin-first and should leave the repo on `main`.

## State Persistence (Compact Recovery)

Persist state to `refine-logs/EXPERIMENT_DEBATE_STATE.json` after each review round and runtime-review checkpoint:

```json
{
  "current_phase": "pre_run_review",
  "review_mode": "debate",
  "round": 2,
  "agent_id": "019d0abc-...",
  "last_runtime_artifact": "refine-logs/EXPERIMENT_RUNTIME.json",
  "open_blockers": ["R1-F2", "runtime-oom-1"],
  "status": "in_progress",
  "timestamp": "2026-03-22T21:00:00"
}
```

**On startup**:
- if the state file does not exist → fresh start
- if `status` is `"completed"` → fresh start
- if `status` is `"in_progress"` and `timestamp` is within 24 hours → resume from the saved phase / round
- if `status` is `"in_progress"` and older than 24 hours → treat as stale, document it, and start fresh

## Outputs

- `refine-logs/EXPERIMENT_DEBATE_LOG.md` — round-by-round findings with `ACCEPTED`, `DEFERRED`, or `REJECTED` decisions and one-line rationales
- `refine-logs/EXPERIMENT_DEBATE_STATE.json` — compact recovery state
- `refine-logs/EXPERIMENT_RUNTIME.json` — parseable runtime evidence from sanity and deployed runs
- `results/*/RUN_STATE.json` — per-run progress + latest-checkpoint state for long resumable runs
- `refine-logs/EXPERIMENT_TRACKER.md` — run-by-run execution table with status notes
- `refine-logs/EXPERIMENT_RESULTS.md` — initial results summary

## Workflow

### Phase 1: Parse the Experiment Plan

Read `EXPERIMENT_PLAN.md` and extract:

1. **Run order and milestones** — which experiments run first (sanity → baseline → main → ablation → polish)
2. **For each experiment block:**
   - dataset / split / task
   - compared systems and variants
   - metrics to compute
   - setup details (backbone, hyperparameters, seeds)
   - success criterion
   - priority (`MUST-RUN` vs `NICE-TO-HAVE`)
3. **Compute budget** — total estimated GPU-hours
4. **Method details** from `FINAL_PROPOSAL.md` — what exactly to implement
5. **Workload hints** — whether the plan looks training-heavy, evaluation-heavy, or mixed. Use `WORKLOAD_PROFILE` as the default if nothing more specific is available.
6. **Repo-local experiment memory** — prior failures, runtime anomalies, and proven fixes from `memory/experiment-memory.md`
7. **Repo-local vendor skills** — any staged third-party skill under `vendor-skills/` that may help with this repo's implementation or evaluation workflow

Present a brief summary:

```
Experiment plan loaded:
- Milestones: [N] (sanity → baseline → main → ablation)
- Must-run experiments: [N]
- Nice-to-have: [N]
- Estimated GPU-hours: [X]
- Workload profile: [mixed / training / inference]
- Review mode: [single / debate]
```

### Phase 2: Implement Experiment Code

**If `BASE_REPO` is set** — clone the repo first:

```bash
git clone <BASE_REPO> base_repo/
# Read the repo's README, understand its structure, find entry points
# Implement experiments by modifying/extending this codebase
```

For each milestone (in order), write the experiment scripts:

1. **Check existing code** — scan the project (or cloned `base_repo/`) for existing experiment scripts, model code, data loaders. Reuse as much as possible.
   - Also inspect any relevant repo-local vendor skill staged under `vendor-skills/`. Reuse it locally if it fits, but do not auto-sync it into a global skill directory.
2. **Implement missing pieces:**
   - training scripts with proper argparse (all hyperparameters configurable)
   - evaluation scripts computing the specified metrics
   - data loading / preprocessing if needed
   - baseline implementations if not already present
   - fixed random seeds for reproducibility
   - stable output roots for each run, preferably `results/<run_name>/` when writing new code from scratch
   - periodic checkpoints for every long run, stored under a canonical checkpoint directory (default: `<output_dir>/checkpoints/`)
   - a parseable per-run state file (default: `<output_dir>/RUN_STATE.json`) recording latest checkpoint + last completed progress unit
   - enough persisted state to resume correctly: model, optimizer, scheduler, RNG/progress counters, and output locations
   - auto-resume behavior: relaunching the same run should discover the latest valid checkpoint and continue without a manually edited command
   - results saved to JSON / CSV for later analysis
   - proper logging (wandb if configured in `AGENTS.md`)
   - metric and runtime hooks needed for `refine-logs/EXPERIMENT_RUNTIME.json`
3. **Follow the plan's run order** — implement sanity-stage experiments first, then baselines, then main method, then ablations.
4. **Self-review before external review:**
   - are all hyperparameters from `EXPERIMENT_PLAN.md` reflected in argparse?
   - is the random seed fixed and controllable?
   - are results saved in a parseable format (JSON / CSV)?
   - does the code match `FINAL_PROPOSAL.md`'s method description?
   - does the run path expose enough runtime evidence for `/run-experiment` to write `EXPERIMENT_RUNTIME.json`?
   - for every long run, do `output_dir`, `checkpoint_dir`, and `RUN_STATE.json` exist as stable locations?
   - for every long run, can the same launch path auto-resume from the latest valid checkpoint after interruption?

### Phase 2.5: Debate Review (when CODE_REVIEW = true)

**Skip this phase entirely if `CODE_REVIEW` is `false`.**

This phase has two explicit passes inside the same lifecycle:

1. **Pass A: Correctness and experimental integrity**
2. **Pass B: Performance and stability optimization**

Round 1 prompt:

```
spawn_agent:
  reasoning_effort: xhigh
  message: |
    Review the following experiment implementation through TWO PASSES.

    ## Experiment Plan
    [paste key sections from EXPERIMENT_PLAN.md]

    ## Method Description
    [paste key sections from FINAL_PROPOSAL.md]

    ## Workload Profile
    [mixed / training / inference]

    ## Optimization Authority
    recommend-only. Do NOT assume we are allowed to auto-switch frameworks or write Triton/CUDA in this round.

    ## Implementation
    [paste the experiment scripts]

    ## Pass A: Correctness and Experimental Integrity
    Check:
    1. Does the code correctly implement the proposal?
    2. Are all planned hyperparameters reflected in the code?
    3. Are there logic bugs (wrong loss, wrong split, missing eval, stale cache assumptions)?
    4. Is the evaluation metric computed correctly?
    5. CRITICAL: Does evaluation use the dataset's actual ground truth labels?
    6. Any likely runtime blockers (OOM, NaN/Inf risk, missing seeds, malformed outputs)?
    7. For any long run, does the code checkpoint often enough and auto-resume correctly from the latest valid checkpoint?
    8. Does the persisted state include optimizer / scheduler / RNG / progress counters instead of model weights only?

    ## Pass B: Performance and Stability Optimization
    Check:
    1. Are there framework/backend/runtime changes worth recommending while preserving semantics?
    2. Do memory or throughput risks justify a simpler runtime switch before any kernel work?
    3. Is there any evidence that Triton or custom CUDA would be justified, or is that premature?
    4. If you suggest kernel-level work, include a fallback path and an expected gain statement.

    For EVERY finding, return:
    - Finding ID
    - Pass (A or B)
    - Severity (CRITICAL / MAJOR / MINOR)
    - Recommendation
    - Evidence required to accept or reject it
```

#### If `CODE_REVIEW_MODE = single`

1. Run one reviewer pass.
2. Implement fixes or rebut them with evidence.
3. Record each reviewer suggestion in `refine-logs/EXPERIMENT_DEBATE_LOG.md` with:
   - `ACCEPTED`
   - `DEFERRED`
   - `REJECTED`
4. **Do not auto-deploy** if any `Pass A / CRITICAL` findings remain unresolved after the single pass.

#### If `CODE_REVIEW_MODE = debate`

Run a capped executor-vs-reviewer loop:

1. **Round 1** — reviewer returns findings for both passes.
2. **Executor turn** — implement accepted fixes, gather evidence, and answer every reviewer suggestion.
3. **Rounds 2..N** — continue the same dialogue and focus only on unresolved findings:

```
send_input:
  id: [saved from round 1]
  reasoning_effort: xhigh
  message: |
    Debate round [N/MAX_DEBATE_ROUNDS].

    Since your last review, we resolved each finding as follows:
    - [Finding ID]: ACCEPTED — [fix or evidence]
    - [Finding ID]: DEFERRED — [why it is postponed]
    - [Finding ID]: REJECTED — [why it does not preserve semantics / is not justified]

    Reassess ONLY unresolved items.
    Stop flagging an item once it has enough evidence or a valid rejection.
    Call out any remaining Pass A / CRITICAL blockers explicitly.
```

4. Stop when one of the following is true:
   - no unresolved `Pass A / CRITICAL` findings remain
   - the reviewer confirms the remaining items are optimization-only or non-blocking
   - `MAX_DEBATE_ROUNDS` is reached
5. If `MAX_DEBATE_ROUNDS` is reached and unresolved `Pass A / CRITICAL` findings remain:
   - set `AUTO_DEPLOY = false` for this run
   - present the blockers to the user
   - do not blindly deploy

#### Decision Logging

Record every finding in `refine-logs/EXPERIMENT_DEBATE_LOG.md`:

```markdown
| Finding ID | Pass | Severity | Disposition | Rationale |
|------------|------|----------|-------------|-----------|
| R1-F1 | A | CRITICAL | ACCEPTED | Fixed dataset split leakage in eval.py |
| R1-F2 | B | MAJOR | DEFERRED | Worth revisiting after sanity because no hotspot evidence yet |
| R2-F1 | B | MINOR | REJECTED | Suggested inference-only backend, but this milestone is training-only |
```

### Phase 3: Sanity Check (if SANITY_FIRST = true)

Before deploying the full experiment suite, run the sanity-stage experiment:

```
/run-experiment [sanity experiment command]
```

The sanity run must refresh `refine-logs/EXPERIMENT_RUNTIME.json`.

Verify:
- the training loop runs without errors
- metrics are computed and saved correctly
- `EXPERIMENT_RUNTIME.json` contains command, environment, exit code, wall time, GPU memory, throughput if available, failure signatures, and long-run resume metadata when applicable
- the runtime evidence does not show blocker-level anomalies

For any sanity-stage run that is long or multi-step, do a resume smoke test before full deployment:
- let the run produce at least one valid checkpoint
- interrupt it once
- relaunch through the same run path
- verify it resumes from the latest checkpoint instead of restarting from step 0

If sanity fails or evidence is malformed → go to Phase 3.5. Do not proceed to full deployment with broken code.

### Phase 3.5: Runtime Review (when RUNTIME_REVIEW = true)

**Skip this phase if `RUNTIME_REVIEW = false`.**

Re-enter review after sanity or deployment if `EXPERIMENT_RUNTIME.json` shows any of:
- non-zero exit code
- `CUDA out of memory`, OOM killer, or repeated allocator failures
- `nan`, `inf`, or divergence-like numerical signatures
- missing metrics file or malformed JSON / CSV outputs
- interrupted run with missing / invalid checkpoint metadata or no reconstructable resume path
- severe slowdown (for example, throughput far below a comparable baseline / hardware expectation, or a short profile showing the GPU mostly idle)

If the runtime review indicates the experimental design itself is flawed, re-read `memory/experiment-memory.md` before revising the plan. Explicitly avoid repeating a previously recorded bad pattern unless new evidence justifies revisiting it.

Use the existing reviewer agent when available; otherwise spawn a new one. Provide:
- the relevant experiment-plan block
- the method description
- the latest `EXPERIMENT_RUNTIME.json`
- the most relevant log excerpt
- what was already accepted / deferred / rejected in the debate log

Ask the reviewer to classify each issue as:
- correctness bug
- environment / config issue
- numerical stability issue
- performance bottleneck
- evidence gap

For each runtime finding, require:
- severity
- minimal fix
- whether it blocks continued deployment
- whether it is a recommendation-only optimization
- if kernel work is suggested, fallback path + expected gain statement

After runtime review:
1. implement accepted blocker fixes
2. update `EXPERIMENT_DEBATE_LOG.md`
3. rerun sanity
4. continue only when blocker-level runtime issues are cleared

### Phase 4: Deploy Full Experiments

Deploy experiments following the plan's milestone order:

```
/run-experiment [experiment commands]
```

For each milestone:
1. deploy experiments in parallel (up to `MAX_PARALLEL_RUNS`)
2. use `/monitor-experiment` to track progress
3. parse result files plus `refine-logs/EXPERIMENT_RUNTIME.json`
4. if any run hits a blocker-level runtime issue, pause that milestone and re-enter Phase 3.5 before continuing
5. if a run only surfaces optimization opportunities, log them as `DEFERRED` unless they are required to make the experiment feasible

### Phase 5: Collect Initial Results

As experiments complete:

1. **Parse output files** (JSON / CSV / logs) for key metrics
2. **Parse `refine-logs/EXPERIMENT_RUNTIME.json`** for wall time, exit code, GPU memory, throughput, and failure signatures
3. **Update `refine-logs/EXPERIMENT_TRACKER.md`** — fill in Status and Notes columns
4. **Check success criteria** from `EXPERIMENT_PLAN.md` — did each experiment meet its bar?
5. **Write initial results summary** with debate and runtime notes

### Phase 6: Handoff

Before the final handoff, write a short reflection that answers:

1. What actually worked in implementation or deployment?
2. Which experiment design or runtime pattern should not be repeated?
3. Which fix or baseline should be reused first next time?
4. Does the next-stage review plan need to change?

Then update repo-local experiment memory:

```text
/research-memory "experiment"
```

Present final status:

```
Experiment bridge complete:
- Implemented: [N] experiment scripts
- Debate rounds: [N]
- Accepted fixes: [N]
- Deferred optimizations: [N]
- Deployed: [N] experiments on [M] GPUs
- Completed: [X/Y] must-run, [A/B] nice-to-have
- Main result: [one sentence]

Debate log: refine-logs/EXPERIMENT_DEBATE_LOG.md
Runtime evidence: refine-logs/EXPERIMENT_RUNTIME.json
Results: refine-logs/EXPERIMENT_RESULTS.md
Tracker: refine-logs/EXPERIMENT_TRACKER.md

Ready for Workflow 2:
-> /auto-review-loop "[topic]"
```

## Decision Rules for Optimization Review

- **Recommendation-only authority** — optimization suggestions may change what to try next, but v1 must not silently rewrite the experiment around a new runtime or custom kernel.
- **Framework / backend recommendations must preserve semantics**:
  - generation-heavy inference / eval may justify a specialized inference runtime such as `vllm`
  - training milestones should prefer training-oriented optimizations, not inference-only runtimes
  - if a simpler library / runtime switch gives comparable upside, prefer it over kernel work
- **Kernel escalation is the last step**:
  - only recommend Triton / custom CUDA when light profiling or runtime evidence shows a dominant hotspot or memory bottleneck
  - any kernel-level recommendation must include a fallback path and an expected gain statement before it can be marked `ACCEPTED`
- **Optimization-only findings are non-blocking by default** unless they are required to make the run feasible within the plan's compute budget

## Key Rules

- ALWAYS use `reasoning_effort: xhigh` for reviews
- **CRITICAL — Evaluation must use dataset ground truth.** NEVER compare against another model's outputs as the source of truth.
- **CRITICAL — Long runs must be resumable.** Any multi-step or 10+ minute run must checkpoint periodically and auto-resume from the latest valid checkpoint.
- **Follow the plan.** Do not invent experiments not in `EXPERIMENT_PLAN.md`.
- **Sanity first.** Never deploy a full suite without verifying the sanity stage passes and `EXPERIMENT_RUNTIME.json` is usable.
- **Keep the fork on `main`.** Migrate old `update`-branch layouts with `tools/aris_upstream_sync.py migrate-to-main`, then keep future origin-first sync on `main`.
- **Reuse existing code.** Extend, do not duplicate.
- **Save everything as JSON / CSV.** The downstream loops need parseable results, not just terminal output.
- **Prefer stable run roots.** New experiment code should default to `results/<run_name>/`, with `checkpoints/` and `RUN_STATE.json` underneath unless the project already has a stronger native convention.
- **Do not auto-switch frameworks.** A suggestion to use a different backend belongs in the debate log until explicitly accepted for a future change.
- **Do not recommend Triton / CUDA casually.** Require hotspot evidence, a fallback path, and an expected gain statement.
- **Read `memory/experiment-memory.md` before redesigning experiments or repeating a runtime fix.**
- **Treat repo-local vendor skills as workspace-only by default.** Only explicit `tools/aris_skill_manager.py sync-global` should publish them to `~/.codex/skills/` or `~/.claude/skills/`.
- **Reflection + memory update is part of the Workflow 1.5 contract** after major result snapshots, runtime anomalies, or design pivots.
- **Document the reviewer agent id** for future resumption.
- **Budget awareness.** Track GPU-hours against the plan's budget and warn when approaching the limit.
