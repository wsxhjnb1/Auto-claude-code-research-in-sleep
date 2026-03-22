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
- `GEMINI_BROWSER_AUTO_INTERACTIVE=true` — auto-open a dedicated interactive Gemini window when sign-in is required
- `GEMINI_BROWSER_AUTO_INTERACTIVE_WAIT_SEC=300` — how long `status` / `render_image` wait for login or human verification before returning `needs_login` or `needs_human_verification`
- `GEMINI_BROWSER_AUTO_WAIT_FOR_HUMAN_VERIFICATION=true` — keep the same recovery flow active when Google shows “I’m not a robot” / unusual-traffic verification
- `GEMINI_BROWSER_AUTO_UPDATE=true` — auto-refresh Playwright-managed Chromium when the required revision changes
- `GEMINI_BROWSER_UPDATE_SCOPE=playwright_chromium` — only auto-update the managed Playwright browser
- `GEMINI_BROWSER_CLOSE_INTERACTIVE_AFTER_READY=true` — close the interactive login window after readiness and continue in the background
- `GEMINI_BROWSER_PRUNE_EXTRA_PAGES=true` — automatically close extra dedicated-profile windows/tabs and keep the session at a strict single-page budget
- `GEMINI_BROWSER_MAX_INTERACTIVE_PAGES=1` — maximum number of dedicated-profile interactive pages to keep alive
- `GEMINI_BROWSER_RENDER_SESSION_MODE=temporary` — reset each render into `temporary`, `new_chat`, or `reuse`
- `GEMINI_BROWSER_RENDER_RETRY_ON_CONTEXT_LEAK=true` — retry automatically if Gemini appears to inherit stale conversation context
- `GEMINI_BROWSER_RENDER_MAX_RETRIES=2` — maximum automatic render retries after a context leak
- `GEMINI_BROWSER_MODE_POLICY=prefer_thinking_fallback_fast` — prefer Thinking/Pro mode before Fast/Flash
- `GEMINI_BROWSER_REMOTE_DEBUG_PORT=9223` — preferred CDP port for the detached interactive browser session
- `GEMINI_BROWSER_EXECUTABLE_PATH` — optional explicit browser executable override
- `GEMINI_BROWSER_TIMEOUT_SEC=240`
- `ILLUSTRATION_BACKEND=browser|api`

## First Login

1. Call `status`.
2. If the dedicated profile still needs sign-in or human verification, `status` now opens or reuses a dedicated interactive Gemini browser window automatically and prunes the dedicated profile back down to a single live page.
3. Finish Gemini login and any “I’m not a robot” / unusual-traffic verification manually in that window.
4. `status` waits for recovery to complete and returns `ready` if it succeeds before timeout; on success the backend closes the interactive window and continues with the same dedicated profile in the background. If recovery does not finish in time, it returns `needs_login` or `needs_human_verification` and leaves only the single required visible page open.
5. `login` remains available as an explicit "open/reuse the window and wait again" tool.

Manual fallback if bootstrap is disabled or fails:

```bash
python3 -m pip install -r mcp-servers/gemini-browser/requirements.txt
python3 -m playwright install chromium
```

On Linux hosts without non-interactive `sudo`, the bootstrap automatically falls back to the direct `playwright install chromium` path instead of using `--with-deps`.

## Tools

- `status` — now has auto-recovery side effects when sign-in is missing
- `login`
- `render_image`

`render_image` takes a fully prepared prompt and an output path. It also accepts optional `loginTimeoutSec`, which controls how long the automatic interactive recovery wait lasts before returning `needs_login` or `needs_human_verification`.

Before each render, the shared backend resets Gemini into a fresh temporary chat by default, explicitly turns on the image tool, prefers Thinking/Pro mode and falls back to Fast/Flash only when needed, wraps the prompt in an image-only instruction so Gemini returns an image rather than prose, and retries automatically if the page appears to reuse stale conversation context.

If the temporary-chat surface keeps leaking stale artifacts or does not expose a reliable image path, the retry escalates to `new_chat` automatically while keeping the same dedicated browser profile.

The dedicated profile now enforces a strict single-window budget. Extra blank tabs, duplicate Gemini tabs, duplicate login/verification tabs, and stale old-session pages are closed automatically; after recovery succeeds, no visible Gemini automation window is left behind.

The shared implementation is in `third_party/paperbanana/browser_backend.py`, which is also used by `tools/paper_illustration_cli.py`.
