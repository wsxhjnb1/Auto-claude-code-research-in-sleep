---
name: "paper-writing"
description: "Workflow 3: Full paper writing pipeline. Orchestrates narrative synthesis → paper-plan → paper-figure → paper-illustration → paper-write → paper-compile → auto-paper-improvement-loop to go from research artifacts to a polished, submission-ready PDF."
---

# Workflow 3: Paper Writing Pipeline

Orchestrate a complete paper writing workflow for: **$ARGUMENTS**

## Repo-Root Requirement

Run this workflow from the root of a checked-out ARIS repo or fork. It depends on repo-local `tools/`, `memory/`, `vendor-skills/`, `refine-logs/`, and `paper/`.

## Research Workspace

Resolve the active research workspace first:

```bash
RESEARCH_ROOT="$(python3 tools/aris_research_workspace.py ensure --stage paper-writing --arguments "$ARGUMENTS" --print-path)"
echo "Using research workspace: $RESEARCH_ROOT"
```

Workflow 3 reads and writes research artifacts under `$RESEARCH_ROOT`. Repo-level `memory/`, `vendor-skills/`, `.venv/`, `.claude/`, and runtime/sync state remain at the repo root.

## Overview

This workflow is now an artifact-driven chain:

```
narrative synthesis → /paper-plan → /paper-figure → /paper-illustration → /paper-write → /paper-compile → /auto-paper-improvement-loop
```

If `$RESEARCH_ROOT/NARRATIVE_REPORT.md` is missing but Workflow 2 artifacts exist, synthesize it first instead of treating it as a purely manual prerequisite.

## Constants

- **VENUE = `ICLR`** — Target venue. Options: `ICLR`, `NeurIPS`, `ICML`, `CVPR`, `ACL`, `AAAI`, `ACM`.
- **ILLUSTRATION = `ai`** — `ai`, `mermaid`, or `false`
- **PAPER_AUTO_INSTALL = true**
- **PAPER_VENV_DIR = `.venv`**
- **PAPER_SYSTEM_INSTALL = `auto`**
- **SYNC_LOCAL_REMOTE = `origin`**
- **SYNC_REMOTE = `upstream`**
- **SYNC_BRANCH = `main`**
- **SYNC_TARGET_BRANCH = `main`**
- **SYNC_ON_ENTRY = true**
- **SYNC_PUSH = true**
- **SYNC_BRANCH_MODE = `main_only`**
- **MAX_IMPROVEMENT_ROUNDS = 2**
- **AUTO_PROCEED = true**
- **HUMAN_CHECKPOINT = false**

> Override inline: `/paper-writing "topic" — venue: NeurIPS, illustration: mermaid`

## Inputs

This workflow can start from:

1. `$RESEARCH_ROOT/NARRATIVE_REPORT.md`
2. Workflow 2 artifacts (`$RESEARCH_ROOT/AUTO_REVIEW.md`, experiment results, proposal, runtime evidence)
3. existing `$RESEARCH_ROOT/PAPER_PLAN.md`

## Pipeline

### Phase -2: Main-Branch Sync

Before Workflow 3 starts, try:

```bash
python3 tools/aris_upstream_sync.py sync
```

Continue on success, "no updates", or a temporary fetch / network failure. If the sync reports tracked worktree changes, local `main` vs `origin/main` divergence, a migration blocker, or an unresolved sync conflict, stop and fix the repo state first. The sync flow is origin-first and should leave the repo on `main`.

### Phase -1: Runtime Bootstrap

```bash
python3 tools/ensure_paper_runtime.py --phase workflow3
```

This creates/reuses `.venv`, installs Python deps, Playwright/Chromium, and supported system packages, then records the result in `refine-logs/PAPER_RUNTIME_STATE.json`.

### Phase 0: Narrative Synthesis

If `$RESEARCH_ROOT/NARRATIVE_REPORT.md` is missing, synthesize it:

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

### Phase 1: Paper Plan

```text
/paper-plan "$ARGUMENTS"
```

Output:

- `$RESEARCH_ROOT/PAPER_PLAN.md`

### Phase 2: Data Figures and Tables

```text
/paper-figure "PAPER_PLAN.md"
```

Output:

- data-driven figures/tables
- `figures/latex_includes.tex`

### Phase 2b: AI Illustration Generation

If `ILLUSTRATION = ai`, run:

```bash
python3 tools/paper_illustration_cli.py \
  --workspace-root "$RESEARCH_ROOT" \
  --paper-plan PAPER_PLAN.md \
  --narrative-report NARRATIVE_REPORT.md \
  --auto-review AUTO_REVIEW.md \
  --manifest figures/illustration_manifest.json \
  --latex-includes figures/latex_includes.tex
```

Default backend behavior:

- `ILLUSTRATION_BACKEND=browser` is primary and reuses the dedicated Gemini web profile.
- `ILLUSTRATION_BACKEND=api` is explicit fallback.
- Browser automation failures are reported through `backend_blocker`.
- First run is auto-bootstrapped; only the dedicated Gemini login stays manual.

If `ILLUSTRATION = mermaid`, use `/mermaid-diagram`.

If `ILLUSTRATION = false`, skip AI illustration.

Expected outputs:

- `$RESEARCH_ROOT/figures/ai_generated/*.png`
- `$RESEARCH_ROOT/figures/illustration_manifest.json`
- updated `$RESEARCH_ROOT/figures/latex_includes.tex`

Only mark a figure as `manual_blocker` when it depends on external qualitative assets, screenshots, real photos, or other user-provided media. Browser/API runtime failures stay `backend_blocker`.

### Phase 3: LaTeX Writing

```text
/paper-write "PAPER_PLAN.md"
```

Consume:

- `$RESEARCH_ROOT/NARRATIVE_REPORT.md`
- `$RESEARCH_ROOT/PAPER_PLAN.md`
- `$RESEARCH_ROOT/figures/latex_includes.tex`
- `$RESEARCH_ROOT/figures/illustration_manifest.json` when present

### Phase 4: Compilation

```text
/paper-compile "paper/"
```

Output:

- `$RESEARCH_ROOT/paper/main.pdf`

### Phase 5: Auto Improvement Loop

```text
/auto-paper-improvement-loop "paper/"
```

## Key Rules

- `$RESEARCH_ROOT/AUTO_REVIEW.md` is the canonical Workflow 2 review artifact.
- Keep the public interface model-agnostic: `illustration: ai`.
- Default to the browser-backed path and only use API when explicitly requested.
- Bootstrap Workflow 3 before substeps or rely on the self-bootstrapping runtime scripts.
- Use the real runtime scripts instead of pseudo-implementations inside skills.
- Try AI illustration before manual fallback for hero and architecture figures.
- Only external assets should block the flow.
