---
name: "research-pipeline"
description: "Full research pipeline: Workflow 1 → 1.5 → 2 → 3. Goes from a broad research direction all the way to a compiled paper and submission-ready artifacts."
---

# Full Research Pipeline: Idea → Experiments → Paper

End-to-end autonomous research workflow for: **$ARGUMENTS**

## Repo-Root Requirement

Run this workflow from the root of a checked-out ARIS repo or fork. It depends on repo-local `tools/`, `memory/`, `vendor-skills/`, and `refine-logs/`.

## Research Workspace

Resolve and activate the research workspace first:

```bash
RESEARCH_NAME="<existing workspace identifier or short English research name>"
RESEARCH_ROOT="$(python3 tools/aris_research_workspace.py ensure --stage research-pipeline --arguments "$ARGUMENTS" --research-name "$RESEARCH_NAME" --print-path)"
echo "Original topic: $ARGUMENTS"
echo "Resolved research name: $RESEARCH_NAME"
echo "Using research workspace: $RESEARCH_ROOT"
```

If `$ARGUMENTS` already matches an existing workspace `research/<slug>` path, slug, saved research title, or saved original topic, reuse that workspace directly. Otherwise, first compress the long topic into a short English research name (2-5 words, ASCII-friendly, directory-safe), then pass that short name via `--research-name`. The first main-entry call creates a plain `research/<slug>/` and records it in `research/ACTIVE_RESEARCH.json`. New workspaces store both the short research `name` and the original long `topic`. If two unrelated topics collapse to the same short slug, the resolver assigns `-2`, `-3`, ... suffixes instead of merging them. Later stages reuse the active research workspace by default. To switch, include `research name: <human-readable-name>` inline. Use `python3 tools/aris_research_workspace.py git-init --research-name "<name>"` when that workspace should become its own Git repo, or `clone-repo --repo-url <github-url>` when an existing repo should become the workspace root directly. Git-backed workspaces keep their own Git history; the outer ARIS repo ignores `research/**`.

## Constants

- **AUTO_PROCEED = true**
- **ARXIV_DOWNLOAD = false**
- **HUMAN_CHECKPOINT = false**
- **ILLUSTRATION = `ai`**
- **SYNC_LOCAL_REMOTE = `origin`**
- **SYNC_REMOTE = `upstream`**
- **SYNC_BRANCH = `main`**
- **SYNC_TARGET_BRANCH = `main`**
- **SYNC_ON_ENTRY = true**
- **SYNC_PUSH = true**
- **SYNC_BRANCH_MODE = `main_only`**
- **REPO_LOCAL_MEMORY = true**
- **REPO_LOCAL_VENDOR_SKILLS = true**

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

Continue on success, "no updates", or a temporary fetch / network failure. If the sync reports tracked worktree changes, local `main` vs `origin/main` divergence, a migration blocker, or an unresolved sync conflict, stop and fix the repo state first. The sync flow is origin-first and should leave the repo on `main`.

If this repo still uses the old long-lived `update` branch, migrate it once from a clean worktree:

```bash
python3 tools/aris_upstream_sync.py migrate-to-main
```

### Stage 0: Repo-Local Context Intake

Before Workflow 1 starts, read these files if they exist:

- `memory/ideation-memory.md`
- `memory/experiment-memory.md`
- `vendor-skills/INSTALLED_SKILLS.json`

Use them to avoid repeating failed directions, reuse proven experiment strategies, and discover any repo-local vendor skills that may be relevant. Keep vendor skills inside this repo's `vendor-skills/` directory.

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

After Workflow 1 converges, run a short reflection and update repo-local ideation memory:

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

After each major review-loop convergence or reviewer-forced plan change, refresh repo-local memory:

```text
/research-memory "review"
```

### Stage 4: Narrative Synthesis

If `$RESEARCH_ROOT/NARRATIVE_REPORT.md` is missing:

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

Pass through `illustration: ai|mermaid|false` to control non-data figure generation.
Workflow 3 inherits the automatic bootstrap from `paper-writing`; first run creates `.venv`, installs Python deps, Playwright/Chromium, and supported system packages.

Output:

- `$RESEARCH_ROOT/paper/main.pdf`
- `$RESEARCH_ROOT/paper/PAPER_IMPROVEMENT_LOG.md`
- `$RESEARCH_ROOT/figures/illustration_manifest.json` when AI illustrations are used

## Key Rules

- Read repo-local memory before starting and before any experiment redesign.
- Before entering the main workflow, try `tools/aris_upstream_sync.py sync` and keep the repo on a single long-lived `main` branch.
- Keep `vendor-skills/` repo-local. Do not publish or copy vendor skills into external global skill directories.
- Treat reflection + memory update as part of the pipeline contract, not an optional note-taking step.
- Use `/experiment-bridge`, not a free-form implementation step.
- `$RESEARCH_ROOT/AUTO_REVIEW.md` is canonical.
- The pipeline continues through Workflow 3 unless blocked.
- Keep public interfaces model-agnostic: `illustration: ai`.
- Only external media should block paper figures.
