# Codex + Claude Reviewer Guide

Run ARIS with:

- **Codex** as the main executor
- **Claude Code CLI** as the reviewer
- the local `claude-review` MCP bridge as the transport layer

This guide is **repo-local** to the checked-out ARIS workspace. Use the checked-out repo directly for skills, overlays, and runtime scripts.

## Architecture

- Base skill set: `skills/skills-codex/`
- Reviewer override layer: `skills/skills-codex-claude-review/`
- Reviewer bridge: `mcp-servers/claude-review/`

The repo-local layering order matters:

1. use `skills/skills-codex/` as the base skill tree
2. use `skills/skills-codex-claude-review/` as the review override layer
3. register `claude-review` MCP from this repo

## Workspace Setup

```bash
git clone https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git
cd Auto-claude-code-research-in-sleep

codex mcp add claude-review -- python3 /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/claude-review/server.py
```

If your Claude login depends on a shell helper such as `claude-aws`, use the wrapper:

```bash
chmod +x mcp-servers/claude-review/run_with_claude_aws.sh
codex mcp add claude-review -- /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/claude-review/run_with_claude_aws.sh
```

Optional reviewer model override:

```bash
codex mcp remove claude-review
codex mcp add claude-review --env CLAUDE_REVIEW_MODEL=claude-opus-4-1 -- python3 /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/claude-review/server.py
```

## Verify

1. Check MCP registration:

```bash
codex mcp list
```

2. Check Claude CLI login:

```bash
claude -p "Reply with exactly READY" --output-format json --tools ""
```

3. Start Codex from the ARIS repo root or your ARIS fork root:

```bash
codex -C /path/to/Auto-claude-code-research-in-sleep
```

## What gets overridden

The overlay only replaces review-heavy skills:

- `research-review`
- `novelty-check`
- `research-refine`
- `experiment-bridge`
- `auto-review-loop`
- `paper-plan`
- `paper-figure`
- `paper-write`
- `auto-paper-improvement-loop`

Everything else still comes from the upstream `skills/skills-codex/` package.

## Async reviewer flow

For long paper or project reviews, use:

- `review_start`
- `review_reply_start`
- `review_status`

Why: in this host path, the review hop is:

`Codex -> claude-review MCP -> local Claude CLI -> Claude backend`

That extra local CLI hop is what makes long synchronous reviewer calls more likely to hit the observed Codex-hosted MCP timeout.

## Project config

No special project config file is required for this path.

- keep using your existing `CLAUDE.md`
- keep your current project layout
- keep the repo-local Codex skill trees and MCP registration in this workspace

## Maintenance

Regenerate the overlay package with:

```bash
python3 tools/generate_codex_claude_review_overrides.py
```
