# Project Files Guide

[中文版](PROJECT_FILES_GUIDE_CN.md) | English

> How to organize project-level state files for ARIS research workflows — what each file does, when to write it, and how they relate to each other.

## The Problem

ARIS workflows generate a lot of information across multiple stages: ideas, experiment plans, results, review feedback, decisions. Without clear file conventions, this information gets scattered across chat sessions and lost on context compaction or new sessions.

This guide establishes a layered file system where each file has a clear purpose, update trigger, and relationship to other files.

## File Overview

```text
repo-root/
├── CLAUDE.md                          # Optional repo-level shared defaults for CLAUDE fields
├── memory/                            # Repo-level shared research memory
├── vendor-skills/                     # Repo-level staged extensions
├── research/
│   └── <slug>/
│       ├── CLAUDE.md                  # Canonical project file — Pipeline Status + per-research constraints
│       ├── IDEA_CANDIDATES.md         # Curated pool of viable ideas (post-review)
│       ├── findings.md                # Lightweight discovery log (experiments + debug)
│       ├── EXPERIMENT_LOG.md          # Complete record of all experiments run
│       ├── IDEA_REPORT.md             # Raw brainstorm output (from /idea-creator)
│       ├── AUTO_REVIEW.md             # Review loop log (from /auto-review-loop)
│       ├── docs/
│       │   └── research_contract.md   # Focused context for the active idea
│       └── refine-logs/
│           ├── EXPERIMENT_PLAN.md     # Experiment design (claims + blocks)
│           ├── EXPERIMENT_TRACKER.md  # Execution checklist (TODO → DONE)
│           └── REVIEW_STATE.json      # Review loop recovery state
```

Use the helper below to create or inspect the canonical project file for a workspace:

```bash
python3 tools/aris_claude_file.py ensure --workspace-root research/<slug> --print-path
python3 tools/aris_claude_file.py status --workspace-root research/<slug>
```

### Existing ARIS Files (unchanged)

| File | Created by | Purpose |
|------|-----------|---------|
| `research/<slug>/IDEA_REPORT.md` | `/idea-creator` | Raw brainstorm output: all 8-12 ideas + pilot results + eliminated ideas |
| `research/<slug>/refine-logs/EXPERIMENT_PLAN.md` | `/experiment-plan` | Experiment design: claim map, blocks, run order, compute budget |
| `research/<slug>/refine-logs/EXPERIMENT_TRACKER.md` | `/experiment-plan` | Execution checklist: run ID, status (TODO→DONE), one-line notes |
| `research/<slug>/AUTO_REVIEW.md` | `/auto-review-loop` | Cumulative review log: scores, reviewer responses, actions taken |
| `research/<slug>/refine-logs/REVIEW_STATE.json` | `/auto-review-loop` | Recovery state for context compaction |

### New Files (this guide)

| File | Purpose | Template |
|------|---------|----------|
| `research/<slug>/IDEA_CANDIDATES.md` | Curated pool of viable ideas that survived review — pick next idea from here when pivoting | [`IDEA_CANDIDATES_TEMPLATE.md`](../templates/IDEA_CANDIDATES_TEMPLATE.md) |
| `research/<slug>/findings.md` | Lightweight discovery log — anomalies, debug root causes, key decisions during experiments | [`FINDINGS_TEMPLATE.md`](../templates/FINDINGS_TEMPLATE.md) |
| `research/<slug>/EXPERIMENT_LOG.md` | Complete experiment record — full results, configs, reproduction commands | [`EXPERIMENT_LOG_TEMPLATE.md`](../templates/EXPERIMENT_LOG_TEMPLATE.md) |
| `research/<slug>/docs/research_contract.md` | Focused working document for the active idea (from [Session Recovery Guide](SESSION_RECOVERY_GUIDE.md)) | [`RESEARCH_CONTRACT_TEMPLATE.md`](../templates/RESEARCH_CONTRACT_TEMPLATE.md) |

## How They Relate

### Idea Flow

```
research/<slug>/IDEA_REPORT.md    (12 ideas, raw brainstorm)
  ↓ novelty-check + review
research/<slug>/IDEA_CANDIDATES.md (3-5 viable ideas, scored)
  ↓ select one
research/<slug>/docs/research_contract.md  (active idea, focused context)
  ↓ idea fails?
IDEA_CANDIDATES.md → pick next → update contract
```

**Why three files?** Context pollution. Loading 12 raw ideas into every session wastes the LLM's working memory. The candidate pool is lean (3-5 entries), and the contract is focused (one idea). On session recovery, the LLM reads only the contract — not the full report.

### Experiment Flow

```
research/<slug>/refine-logs/EXPERIMENT_PLAN.md    (what to run — design)
  ↓
research/<slug>/refine-logs/EXPERIMENT_TRACKER.md (execution status — TODO/RUNNING/DONE)
  ↓ experiment completes
research/<slug>/EXPERIMENT_LOG.md (what happened — full results + reproduction)
  ↓ discover something unexpected
research/<slug>/findings.md       (one-line entry — anomaly, root cause, decision)
```

**Why separate tracker and log?** Different audiences. The tracker is for execution management ("what's left to run?"). The log is for knowledge preservation ("what did we learn?"). The tracker can be reset between ideas; the log is permanent.

### When to Write Each File

| File | Write when... | Update frequency |
|------|--------------|-----------------|
| `research/<slug>/IDEA_CANDIDATES.md` | After `/idea-discovery` completes (initial creation); after idea kill/selection (update status) | Per idea transition |
| `research/<slug>/findings.md` | Discover something non-obvious during experiments, debugging, or analysis | As discoveries happen (append) |
| `research/<slug>/EXPERIMENT_LOG.md` | An experiment finishes (any experiment, successful or not) | After every experiment |
| `research/<slug>/docs/research_contract.md` | Select an idea to work on; baseline reproduced; major results obtained | Per stage milestone |

### Session Recovery Priority

On new session or post-compaction, read files in this order:

1. `research/<slug>/CLAUDE.md` → Pipeline Status (30 seconds: where am I?)
2. `research/<slug>/docs/research_contract.md` (active idea context)
3. `research/<slug>/findings.md` recent entries (what did I discover recently?)
4. `research/<slug>/EXPERIMENT_LOG.md` (if needed: what experiments have been run?)

Do NOT read `research/<slug>/IDEA_REPORT.md` or `research/<slug>/IDEA_CANDIDATES.md` unless switching ideas.

## Separation Principles

| Question | Answer |
|----------|--------|
| Where does a brainstorm idea go? | `research/<slug>/IDEA_REPORT.md` (raw) → `research/<slug>/IDEA_CANDIDATES.md` (curated) |
| Where does the current idea's full context go? | `research/<slug>/docs/research_contract.md` |
| Where does "experiment X is running" go? | `research/<slug>/refine-logs/EXPERIMENT_TRACKER.md` |
| Where does "experiment X got accuracy 95.2" go? | `research/<slug>/EXPERIMENT_LOG.md` |
| Where does "lr=1e-4 diverges on dataset-X" go? | `research/<slug>/findings.md` |
| Where does "reviewer says add ablation" go? | `research/<slug>/AUTO_REVIEW.md` |
| Where does "chose approach A over B because Z" go? | `research/<slug>/findings.md` |
| Where does "current stage is training" go? | `research/<slug>/CLAUDE.md` Pipeline Status |
