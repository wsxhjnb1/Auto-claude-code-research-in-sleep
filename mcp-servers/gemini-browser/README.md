# Gemini Browser MCP Server

Browser-backed Gemini image generation for ARIS `paper-illustration`.

## Install

```bash
# Default: first server start bootstraps this automatically
python3 tools/ensure_paper_runtime.py --phase illustration
```

## Add To Claude Code

```bash
claude mcp add gemini-browser -s user -- \
  python3 /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/gemini-browser/server.py
```

Optional environment variables:

- `PAPER_AUTO_INSTALL=true`
- `PAPER_VENV_DIR=.venv`
- `PAPER_SYSTEM_INSTALL=auto`
- `GEMINI_BROWSER_WORK_DIR` — defaults to the current working directory
- `GEMINI_BROWSER_PROFILE_DIR` — dedicated persistent profile directory
- `GEMINI_BROWSER_HEADLESS=false` — headed by default
- `GEMINI_BROWSER_TIMEOUT_SEC=240`
- `ILLUSTRATION_BACKEND=browser|api`

## First Login

1. Call `status`.
2. If it returns `needs_login`, call `login`.
3. Finish Gemini login manually in the opened dedicated browser window.
4. Call `status` again until it returns `ready`.

Manual fallback if bootstrap is disabled or fails:

```bash
python3 -m pip install -r mcp-servers/gemini-browser/requirements.txt
python3 -m playwright install chromium
```

## Tools

- `status`
- `login`
- `render_image`

`render_image` takes a fully prepared prompt and an output path. The shared implementation is in `third_party/paperbanana/browser_backend.py`, which is also used by `tools/paper_illustration_cli.py`.
