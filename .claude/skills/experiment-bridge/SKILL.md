---
name: "experiment-bridge"
description: "Workflow 1.5: Bridge between idea discovery and auto review. Reads EXPERIMENT_PLAN.md, implements experiment code, runs a dual-AI debate loop, deploys to GPU, and collects initial results. Use when user says \"实现实验\", \"implement experiments\", \"bridge\", \"从计划到跑实验\", \"deploy the plan\", or has an experiment plan ready to execute."
argument-hint: [experiment-plan-path-or-topic]
disable-model-invocation: true
---

# Project-local Claude entrypoint for `/experiment-bridge`

This wrapper exists so Claude Code can expose the main ARIS workflows as project-level slash commands when Claude is started from the ARIS repo root.

## Instructions

1. Read `skills/experiment-bridge/SKILL.md` from this repo and treat it as the canonical implementation for `/experiment-bridge`.
2. Pass through the user-supplied arguments exactly as `$ARGUMENTS`.
3. Stay inside this checked-out ARIS repo or fork. Use the repo-local `tools/`, `memory/`, `vendor-skills/`, `refine-logs/`, and other files referenced by the canonical skill.
4. If the canonical skill refers to another ARIS slash command like `/paper-plan` or `/run-experiment`, resolve it by reading the matching repo-local file at `skills/<skill-name>/SKILL.md` and following that file. Do not assume a separate project-level slash wrapper exists for internal sub-skills.
5. If this wrapper and the canonical skill ever disagree, the canonical skill wins.
