---
name: paper-writing
description: "Workflow 3: Full paper writing pipeline. Orchestrates narrative synthesis → paper-plan → paper-figure → paper-illustration → paper-write → paper-compile → auto-paper-improvement-loop to go from research artifacts to a polished, submission-ready PDF."
argument-hint: [narrative-report-path-or-topic]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, Skill, mcp__codex__codex, mcp__codex__codex-reply
---

# Workflow 3: Paper Writing Pipeline

Orchestrate a complete paper writing workflow for: **$ARGUMENTS**

## Repo-Root Requirement

Run this workflow from the root of a checked-out ARIS repo or fork. It depends on repo-local `tools/`, `memory/`, `vendor-skills/`, `refine-logs/`, and `paper/`.

## Claude Project Entry

When Claude Code is started from the ARIS repo root, the project-level wrapper at `.claude/skills/paper-writing/SKILL.md` exposes `/paper-writing`. The canonical implementation remains this file.

## Overview

This workflow is now a true artifact-driven pipeline:

```
narrative synthesis → /paper-plan → /paper-figure → /paper-illustration → /paper-write → /paper-compile → /auto-paper-improvement-loop
```

The key change is that `NARRATIVE_REPORT.md` is no longer treated as a purely manual prerequisite. If it does not exist, but Workflow 1.5 / 2 artifacts do exist, synthesize it first.

## Constants

- **VENUE = `ICLR`** — Target venue. Options: `ICLR`, `NeurIPS`, `ICML`, `CVPR`, `ACL`, `AAAI`, `ACM`.
- **ILLUSTRATION = `ai`** — Figure mode for non-data visuals. Options: `ai`, `mermaid`, `false`.
- **PAPER_AUTO_INSTALL = true** — Auto-bootstrap Workflow 3 dependencies on first run.
- **PAPER_VENV_DIR = `.venv`** — Project-local Python environment for paper tooling.
- **PAPER_SYSTEM_INSTALL = `auto`** — Auto-install supported system packages via `apt-get` or `brew`.
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

This workflow can start from any of:

1. **`NARRATIVE_REPORT.md`** — best direct input
2. **Workflow 2 artifacts** — `AUTO_REVIEW.md`, `refine-logs/EXPERIMENT_RESULTS.md`, `refine-logs/EXPERIMENT_PLAN.md`, `refine-logs/FINAL_PROPOSAL.md`
3. **Existing `PAPER_PLAN.md`** — skip directly to figure generation and writing

## Pipeline

### Phase -2: Main-Branch Sync

Before Workflow 3 starts, try:

```bash
python3 tools/aris_upstream_sync.py sync
```

Continue on success, "no updates", or a temporary fetch / network failure. If the sync reports tracked worktree changes, local `main` vs `origin/main` divergence, a migration blocker, or an unresolved sync conflict, stop and fix the repo state first. The sync flow is origin-first and should leave the repo on `main`.

### Phase -1: Runtime Bootstrap

Before any Workflow 3 step, run:

```bash
python3 tools/ensure_paper_runtime.py --phase workflow3
```

This creates/reuses `.venv`, installs the Python packages for plotting and browser rendering, installs Chromium for Playwright, auto-installs supported system packages such as `latexmk` / `pdfinfo` / `pdftotext`, and writes `refine-logs/PAPER_RUNTIME_STATE.json`.

### Phase 0: Narrative Synthesis

If `NARRATIVE_REPORT.md` is missing, synthesize a draft from the existing research artifacts:

```bash
python3 tools/synthesize_narrative_report.py \
  --proposal refine-logs/FINAL_PROPOSAL.md \
  --plan refine-logs/EXPERIMENT_PLAN.md \
  --results refine-logs/EXPERIMENT_RESULTS.md \
  --runtime refine-logs/EXPERIMENT_RUNTIME.json \
  --review AUTO_REVIEW.md \
  --output NARRATIVE_REPORT.md
```

This draft is the canonical Workflow 2 → Workflow 3 handoff. It should capture:

- the core story
- the supported claims
- experiment setup and main results
- known weaknesses
- figure requirements

If neither a narrative report nor the upstream artifacts exist, stop and ask for more context.

### Phase 1: Paper Plan

Invoke `/paper-plan`:

```text
/paper-plan "$ARGUMENTS"
```

Expected output:

- `PAPER_PLAN.md`

The plan must include a detailed Figure Plan table and explicit hero-figure requirements.

### Phase 2: Data Figures and Tables

Invoke `/paper-figure`:

```text
/paper-figure "PAPER_PLAN.md"
```

This phase owns:

- data-driven plots
- comparison tables
- multi-panel quantitative figures

Expected outputs:

- `figures/latex_includes.tex`
- plot/table assets under `figures/`

### Phase 2b: AI Illustration Generation

If `ILLUSTRATION = ai`, run the PaperBanana-derived illustration runtime for:

- hero figures
- architecture diagrams
- method diagrams
- workflow / overview figures

```bash
python3 tools/paper_illustration_cli.py \
  --paper-plan PAPER_PLAN.md \
  --narrative-report NARRATIVE_REPORT.md \
  --auto-review AUTO_REVIEW.md \
  --manifest figures/illustration_manifest.json \
  --latex-includes figures/latex_includes.tex
```

Default backend behavior:

- `ILLUSTRATION_BACKEND=browser` is the default. It reuses the dedicated Gemini web profile and writes browser debug bundles under `refine-logs/gemini-browser-debug/` when automation fails.
- `ILLUSTRATION_BACKEND=api` is explicit fallback when you want the old API-backed PaperBanana agent chain.
- First run is auto-bootstrapped through `tools/ensure_paper_runtime.py`; the only remaining manual step is the dedicated Gemini login.

If `ILLUSTRATION = mermaid`, use `/mermaid-diagram` for simple diagram needs.

If `ILLUSTRATION = false`, skip AI illustration entirely.

The AI illustration phase must produce:

- `figures/ai_generated/*.png`
- `figures/illustration_manifest.json`
- updated `figures/latex_includes.tex`

Only classify a figure as `manual_blocker` when it truly depends on external assets such as:

- qualitative sample grids
- screenshots
- real photographs
- user-provided media

Treat browser/API runtime failures as `backend_blocker`, not `manual_blocker`.

### Phase 3: LaTeX Writing

Invoke `/paper-write`:

```text
/paper-write "PAPER_PLAN.md"
```

This phase should consume:

- `NARRATIVE_REPORT.md`
- `PAPER_PLAN.md`
- `figures/latex_includes.tex`
- `figures/illustration_manifest.json` when it exists

Expected output:

- `paper/`

### Phase 4: Compilation

Invoke `/paper-compile`:

```text
/paper-compile "paper/"
```

Expected output:

- `paper/main.pdf`

### Phase 5: Auto Improvement Loop

Invoke `/auto-paper-improvement-loop`:

```text
/auto-paper-improvement-loop "paper/"
```

Expected output:

- `paper/PAPER_IMPROVEMENT_LOG.md`
- round-by-round PDFs

## Final Report

At the end, report:

- whether the narrative was synthesized or reused
- whether figures came from `/paper-figure`, `/paper-illustration`, or manual assets
- whether any `manual_blocker` or `backend_blocker` entries remain
- whether `paper/main.pdf` compiled successfully

## Key Rules

- **`AUTO_REVIEW.md` is canonical.** Do not use model-specific review artifact names.
- **Keep the public interface model-agnostic.** User-facing docs should say `illustration: ai`, not a specific model name.
- **Default to browser-first.** The dedicated Gemini web profile is the primary illustration path.
- **Bootstrap Workflow 3 first.** Run `python3 tools/ensure_paper_runtime.py --phase workflow3` before substeps or rely on the runtime scripts that now self-bootstrap.
- **Try AI illustration before manual fallback.** Hero figures and architecture diagrams are not manual by default anymore.
- **Use the runtime scripts.** `tools/synthesize_narrative_report.py` and `tools/paper_illustration_cli.py` are now part of the workflow contract.
- **Only external assets block the flow.** Screenshots and qualitative grids may still need user input; method diagrams should not.
