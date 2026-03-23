---
name: research-pipeline
description: "Full research pipeline: Workflow 1 → 1.5 → 2 → 3. Goes from a broad research direction all the way to a compiled paper and submission-ready artifacts."
argument-hint: [research-direction]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, WebSearch, WebFetch, Agent, Skill, mcp__codex__codex, mcp__codex__codex-reply
---

# Full Research Pipeline: Idea → Experiments → Paper

End-to-end autonomous research workflow for: **$ARGUMENTS**

## Repo-Root Requirement

Run this workflow from the root of a checked-out ARIS repo or fork. It depends on repo-local `tools/`, `memory/`, `vendor-skills/`, and `refine-logs/`.

## Claude Project Entry

When Claude Code is started from the ARIS repo root, the project-level wrapper at `.claude/skills/research-pipeline/SKILL.md` exposes `/research-pipeline`. The canonical implementation remains this file.

## Research Workspace

Resolve the active research workspace before Stage 1:

```bash
RESEARCH_ROOT="$(python3 tools/aris_research_workspace.py ensure --stage research-pipeline --arguments "$ARGUMENTS" --print-path)"
echo "Using research workspace: $RESEARCH_ROOT"
```

Behavior:

- The first main-entry call creates a plain `research/<slug>/` and marks it active in `research/ACTIVE_RESEARCH.json`.
- Reusing the same research name reuses the same workspace, which keeps experiment resume state and paper artifacts together.
- Later stages default to the active research workspace. To switch, include `research name: <human-readable-name>` inline.
- Run `python3 tools/aris_research_workspace.py git-init --research-name "<name>"` when you want that workspace to become its own Git repo.
- Run `python3 tools/aris_research_workspace.py clone-repo --repo-url <github-url> [--research-name "<name>"]` when an existing repo should become the workspace root directly.
- Git-backed research workspaces keep their own Git history; the outer ARIS repo ignores `research/**`.
- Repo-level runtime stays at the repo root: `.venv/`, `.claude/`, `memory/`, `vendor-skills/`, and runtime/sync state under `refine-logs/`.

## Constants

- **AUTO_PROCEED = true**
- **ARXIV_DOWNLOAD = false**
- **HUMAN_CHECKPOINT = false**
- **ILLUSTRATION = `ai`** — `ai`, `mermaid`, or `false`
- **SYNC_LOCAL_REMOTE = `origin`**
- **SYNC_REMOTE = `upstream`**
- **SYNC_BRANCH = `main`**
- **SYNC_TARGET_BRANCH = `main`**
- **SYNC_ON_ENTRY = true**
- **SYNC_PUSH = true**
- **SYNC_BRANCH_MODE = `main_only`**
- **REPO_LOCAL_MEMORY = true** — Read repo-local `memory/` files before major stage transitions.
- **REPO_LOCAL_VENDOR_SKILLS = true** — Repo-local third-party skills live under `vendor-skills/` and stay local unless explicitly synced globally.

## Overview

This skill now orchestrates the full lifecycle:

```text
/idea-discovery → /experiment-bridge → /auto-review-loop → narrative synthesis → /paper-writing → submission-ready artifacts
```

### Stage -1: Main-Branch Sync

Before Workflow 1 starts, try:

```bash
python3 tools/aris_upstream_sync.py sync
```

Interpret the result like this:

- no update / sync success → continue
- temporary fetch or network failure → note it, then continue
- tracked worktree changes, local `main` vs `origin/main` divergence, unresolved sync conflict, or migration blocker → stop and fix the repo state first

The sync flow is origin-first: check `origin/main`, fast-forward local `main` when it is only behind, then inspect `upstream/main`. If it succeeds, the repo should remain on `main`.

If this repo still uses the old long-lived `update` branch, migrate it once from a clean worktree:

```bash
python3 tools/aris_upstream_sync.py migrate-to-main
```

### Stage 0: Repo-Local Context Intake

Before Workflow 1 starts, read these files if they exist:

- `memory/ideation-memory.md`
- `memory/experiment-memory.md`
- `vendor-skills/INSTALLED_SKILLS.json`

Use them to avoid repeating failed directions, reuse proven experiment strategies, and discover any repo-local vendor skills that may help this workspace. Keep vendor skills inside this repo's `vendor-skills/` directory.

## Pipeline

### Stage 1: Idea Discovery

```text
/idea-discovery "$ARGUMENTS"
```

Output:

- `$RESEARCH_ROOT/IDEA_REPORT.md`
- `$RESEARCH_ROOT/refine-logs/FINAL_PROPOSAL.md`
- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_PLAN.md`
- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_TRACKER.md`

After Workflow 1 converges, run a short reflection and refresh repo-local ideation memory:

```text
/research-memory "ideation"
```

### Stage 2: Experiment Bridge

```text
/experiment-bridge
```

Output:

- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RESULTS.md`
- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json`
- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_DEBATE_LOG.md`

If the user asks to redesign experiments midstream, re-read `memory/experiment-memory.md` before re-entering `/experiment-bridge`.

After Workflow 1.5 reaches a stable result snapshot or a design pivot, update repo-local experiment memory:

```text
/research-memory "experiment"
```

### Stage 3: Auto Review Loop

```text
/auto-review-loop "$ARGUMENTS"
```

Output:

- `$RESEARCH_ROOT/AUTO_REVIEW.md`

This is the canonical review artifact. Do not use model-specific review file names.

After each major review-loop convergence or reviewer-forced plan change, refresh repo-local memory:

```text
/research-memory "review"
```

### Stage 4: Narrative Synthesis

If `$RESEARCH_ROOT/NARRATIVE_REPORT.md` is missing, synthesize it from the Workflow 1.5 / 2 artifacts:

```bash
python3 tools/synthesize_narrative_report.py \
  --workspace-root "$RESEARCH_ROOT" \
  --proposal refine-logs/FINAL_PROPOSAL.md \
  --plan refine-logs/EXPERIMENT_PLAN.md \
  --results refine-logs/EXPERIMENT_RESULTS.md \
  --runtime refine-logs/EXPERIMENT_RUNTIME.json \
  --review AUTO_REVIEW.md \
  --output NARRATIVE_REPORT.md
```

### Stage 5: Paper Writing

```text
/paper-writing "NARRATIVE_REPORT.md"
```

Pass through `illustration: ai|mermaid|false` to control how Workflow 3 handles non-data figures.
Workflow 3 inherits the automatic bootstrap from `paper-writing`; it now creates `.venv`, installs Python deps, Playwright/Chromium, and supported system packages on first run.

Output:

- `$RESEARCH_ROOT/paper/main.pdf`
- `$RESEARCH_ROOT/paper/PAPER_IMPROVEMENT_LOG.md`
- `$RESEARCH_ROOT/figures/illustration_manifest.json` when AI illustrations are used

### Stage 6: Final Summary

Write a final report that includes:

- chosen idea
- experiment completion and reviewer score trajectory
- whether the narrative was synthesized or user-provided
- how figures were produced (`paper-figure`, `paper-illustration`, or manual blockers)
- whether `$RESEARCH_ROOT/paper/main.pdf` compiled successfully

## Key Rules

- Read repo-local memory before starting and before any experiment redesign.
- Before entering the main workflow, try `tools/aris_upstream_sync.py sync` and keep the repo on a single long-lived `main` branch.
- Resolve `RESEARCH_ROOT` first and keep research artifacts under `research/<slug>/`.
- Keep `vendor-skills/` repo-local.
- Treat reflection + memory update as part of the pipeline contract, not an optional note-taking step.
- Use `/experiment-bridge`, not an ad hoc implementation step.
- `$RESEARCH_ROOT/AUTO_REVIEW.md` is canonical.
- The pipeline is not done at Workflow 2 anymore; it must continue to Workflow 3 unless blocked.
- Keep public interfaces model-agnostic: `illustration: ai`, not provider/model-specific values.
- Only external media should block paper figures; architecture and hero figures should go through AI illustration first.
