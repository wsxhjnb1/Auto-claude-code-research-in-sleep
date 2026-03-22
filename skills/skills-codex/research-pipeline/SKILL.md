---
name: "research-pipeline"
description: "Full research pipeline: Workflow 1 → 1.5 → 2 → 3. Goes from a broad research direction all the way to a compiled paper and submission-ready artifacts."
---

# Full Research Pipeline: Idea → Experiments → Paper

End-to-end autonomous research workflow for: **$ARGUMENTS**

## Constants

- **AUTO_PROCEED = true**
- **ARXIV_DOWNLOAD = false**
- **HUMAN_CHECKPOINT = false**
- **ILLUSTRATION = `ai`**

## Overview

This skill now orchestrates the full lifecycle:

```text
/idea-discovery → /experiment-bridge → /auto-review-loop → narrative synthesis → /paper-writing → submission-ready artifacts
```

## Pipeline

### Stage 1: Idea Discovery

```text
/idea-discovery "$ARGUMENTS"
```

Output:

- `IDEA_REPORT.md`
- `refine-logs/FINAL_PROPOSAL.md`
- `refine-logs/EXPERIMENT_PLAN.md`
- `refine-logs/EXPERIMENT_TRACKER.md`

### Stage 2: Experiment Bridge

```text
/experiment-bridge
```

Output:

- `refine-logs/EXPERIMENT_RESULTS.md`
- `refine-logs/EXPERIMENT_RUNTIME.json`
- `refine-logs/EXPERIMENT_DEBATE_LOG.md`

### Stage 3: Auto Review Loop

```text
/auto-review-loop "$ARGUMENTS"
```

Output:

- `AUTO_REVIEW.md`

### Stage 4: Narrative Synthesis

If `NARRATIVE_REPORT.md` is missing:

```bash
python3 tools/synthesize_narrative_report.py \
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

- `paper/main.pdf`
- `paper/PAPER_IMPROVEMENT_LOG.md`
- `figures/illustration_manifest.json` when AI illustrations are used

## Key Rules

- Use `/experiment-bridge`, not a free-form implementation step.
- `AUTO_REVIEW.md` is canonical.
- The pipeline continues through Workflow 3 unless blocked.
- Keep public interfaces model-agnostic: `illustration: ai`.
- Only external media should block paper figures.
