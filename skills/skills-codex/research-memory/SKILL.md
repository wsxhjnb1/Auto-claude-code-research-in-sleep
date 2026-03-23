---
name: "research-memory"
description: "Summarize stage outcomes into repo-local research memory. Use when user says \"update memory\", \"record lessons\", \"reflect on results\", \"总结经验\", or when a workflow needs to persist reusable research heuristics, failed directions, or experiment lessons."
argument-hint: [ideation|experiment|review context]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob
---

# Research Memory

Write repo-local research memory for: **$ARGUMENTS**

## Purpose

This skill turns one stage's outcomes into reusable project memory. It does not dump raw logs. It extracts:

- what worked
- what failed
- what should not be repeated
- what should be tried first next time

The memory scope is **repo-local only**. Files live under `memory/`.

## Research Workspace Context

`memory/` stays repo-level and shared across all research workspaces. The source artifacts you summarize should normally come from the active research workspace:

```bash
RESEARCH_ROOT="$(python3 tools/aris_research_workspace.py status --print-path 2>/dev/null || true)"
```

If `RESEARCH_ROOT` is set, treat artifact paths below as relative to that workspace. If there is no active workspace, use explicit paths supplied by the current workflow or user.

## Inputs

Read the smallest relevant set of artifacts for the current context:

- Workflow 1:
  - `$RESEARCH_ROOT/IDEA_REPORT.md`
  - `$RESEARCH_ROOT/refine-logs/FINAL_PROPOSAL.md`
  - `$RESEARCH_ROOT/refine-logs/EXPERIMENT_PLAN.md`
- Workflow 1.5:
  - `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RESULTS.md`
  - `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json`
  - `$RESEARCH_ROOT/refine-logs/EXPERIMENT_DEBATE_LOG.md`
  - `$RESEARCH_ROOT/refine-logs/EXPERIMENT_TRACKER.md`
- Workflow 2:
  - `$RESEARCH_ROOT/AUTO_REVIEW.md`
  - recent figures / metrics / runtime artifacts when needed

If `memory/ideation-memory.md` or `memory/experiment-memory.md` is missing, create it using the default structure.

## Reflection Contract

Before updating memory, write a short reflection in your working notes that answers:

1. What did this stage teach us?
2. Which direction, experiment, or fix should not be repeated?
3. Which strategy should be reused first next time?
4. Does the next-stage plan need to change?

Then update the memory files.

## Output Rules

### `memory/ideation-memory.md`

Only record reusable Workflow 1 knowledge:

- promising directions
- failed directions
- reviewer objections
- selection heuristics

Do **not** append raw paper lists or long transcripts.

### `memory/experiment-memory.md`

Only record reusable Workflow 1.5 / 2 knowledge:

- proven strategies
- bad experiment patterns
- resume / runtime pitfalls
- useful baselines / metrics lessons

When the user asks to redesign experiments, read this file first and explicitly avoid repeating recorded bad patterns unless new evidence justifies revisiting them.

## Format

Append concise bullets under the relevant section headers. Each bullet should be self-contained and actionable.

Good:

- `Mixture-of-experts routing improved perplexity only after we froze the tokenizer and widened the router warmup; rerunning without warmup repeated the same instability.`

Bad:

- `We did a lot of runs and some were unstable.`

## Key Rules

- Keep memory **project-local**.
- Prefer reusable lessons over narrative recap.
- Update only the relevant sections; do not rewrite unrelated memory.
- If a lesson is superseded by stronger evidence, replace the old bullet rather than keeping contradictory clutter.
