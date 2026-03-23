---
name: "research-pipeline"
description: "Full research pipeline: Workflow 1 → 1.5 → 2 → 3. Goes from a broad research direction all the way to a compiled paper and submission-ready artifacts."
argument-hint: [research-direction]
disable-model-invocation: true
---

# Project-local Claude entrypoint for `/research-pipeline`

This wrapper exists so Claude Code can expose the main ARIS workflows as project-level slash commands when Claude is started from the ARIS repo root.

## Instructions

1. Read `skills/research-pipeline/SKILL.md` from this repo and treat it as the canonical implementation for `/research-pipeline`.
2. Pass through the user-supplied arguments exactly as `$ARGUMENTS`.
3. Stay inside this checked-out ARIS repo or fork. Use the repo-local `tools/`, `memory/`, `vendor-skills/`, `refine-logs/`, and other files referenced by the canonical skill.
4. If the canonical skill refers to another ARIS slash command like `/paper-plan` or `/run-experiment`, resolve it by reading the matching repo-local file at `skills/<skill-name>/SKILL.md` and following that file. Do not assume a separate project-level slash wrapper exists for internal sub-skills.
5. If this wrapper and the canonical skill ever disagree, the canonical skill wins.
