# skills-codex-claude-review

This package is a **thin override layer** for users who want:

- **Codex** as the main executor
- **Claude Code** as the reviewer
- the local `claude-review` MCP bridge instead of a second Codex reviewer

It is designed to sit on top of the repo-local Codex-native package at `skills/skills-codex/`.

## What this package contains

- Only the review-heavy skill overrides that need a different reviewer backend
- No duplicate templates or resource directories
- No replacement for the base `skills/skills-codex/` installation

Current overrides:

- `research-review`
- `novelty-check`
- `research-refine`
- `experiment-bridge`
- `auto-review-loop`
- `paper-plan`
- `paper-figure`
- `paper-write`
- `auto-paper-improvement-loop`

## Workspace Setup

1. Keep the base Codex-native skill tree in this repo:

`skills/skills-codex/`

2. Layer this Claude-review override tree on top of it:

`skills/skills-codex-claude-review/`

3. Register the local reviewer bridge:

```bash
codex mcp add claude-review -- python3 /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/claude-review/server.py
```

If your Claude setup depends on a shell helper such as `claude-aws`, use the wrapper instead:

```bash
chmod +x mcp-servers/claude-review/run_with_claude_aws.sh
codex mcp add claude-review -- /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/claude-review/run_with_claude_aws.sh
```

## Why this exists

The upstream `skills/skills-codex/` path already supports Codex-native execution with a second Codex reviewer via `spawn_agent`.

This package adds a different split:

- executor: Codex
- reviewer: Claude Code CLI
- transport: `claude-review` MCP

For long paper and review prompts, the reviewer path uses:

- `review_start`
- `review_reply_start`
- `review_status`

This avoids the observed Codex-hosted timeout issue when Claude is invoked synchronously through a local bridge.
