---
name: "paper-writing"
description: "Workflow 3: Full paper writing pipeline. Orchestrates narrative synthesis → paper-plan → paper-figure → paper-illustration → paper-write → paper-compile → auto-paper-improvement-loop to go from research artifacts to a polished, submission-ready PDF."
argument-hint: [narrative-report-path-or-topic]
disable-model-invocation: true
---

# Project-local Claude entrypoint for `/paper-writing`

This wrapper exists so Claude Code can expose the main ARIS workflows as project-level slash commands when Claude is started from the ARIS repo root.

## Instructions

1. Read `skills/paper-writing/SKILL.md` from this repo and treat it as the canonical implementation for `/paper-writing`.
2. Pass through the user-supplied arguments exactly as `$ARGUMENTS`.
3. Stay inside this checked-out ARIS repo or fork. Use the repo-local `tools/`, `memory/`, `vendor-skills/`, `refine-logs/`, and other files referenced by the canonical skill.
4. If the canonical skill refers to another ARIS slash command like `/paper-plan` or `/run-experiment`, resolve it by reading the matching repo-local file at `skills/<skill-name>/SKILL.md` and following that file. Do not assume a separate project-level slash wrapper exists for internal sub-skills.
5. If this wrapper and the canonical skill ever disagree, the canonical skill wins.
