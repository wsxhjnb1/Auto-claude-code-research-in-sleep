---
name: paper-illustration
description: "Generate publication-quality AI illustrations for academic papers using a PaperBanana-derived multi-stage pipeline. Use when user says \"生成图表\", \"画架构图\", \"AI绘图\", \"paper illustration\", \"generate diagram\", or needs hero/method/architecture figures for papers."
argument-hint: [description-or-method-file]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, mcp__codex__codex, mcp__codex__codex-reply, WebSearch
---

# Paper Illustration: PaperBanana-Derived AI Figure Pipeline

Generate publication-quality academic illustrations for: **$ARGUMENTS**

## Research Workspace

Resolve the active research workspace before rendering:

```bash
RESEARCH_ROOT="$(python3 tools/aris_research_workspace.py ensure --stage paper-illustration --arguments "$ARGUMENTS" --print-path)"
echo "Using research workspace: $RESEARCH_ROOT"
PROJECT_CLAUDE="$(python3 tools/aris_claude_file.py ensure --workspace-root "$RESEARCH_ROOT" --print-path)"
echo "Using project CLAUDE.md: $PROJECT_CLAUDE"
```

Treat `PAPER_PLAN.md`, `NARRATIVE_REPORT.md`, `AUTO_REVIEW.md`, `figures/`, and `paper/` as relative to `$RESEARCH_ROOT` unless the user explicitly supplies an absolute path or a `research/...` path.

This skill is now backed by real runtime code:

```bash
python3 tools/paper_illustration_cli.py "$ARGUMENTS"
```

The implementation lives in:

- `tools/paper_illustration_cli.py`
- `third_party/paperbanana/`

The vendored runtime is a **selective import** of the PaperBanana illustration chain plus a browser-backed Gemini web renderer:

- Retriever — optional reference-driven few-shot prompting
- Browser backend — submit prompts through a dedicated Gemini web profile, then download/save the image
- Planner / Stylist / Visualizer / Critic — retained as the explicit API fallback path

## Constants

- **ILLUSTRATION = `ai`** — User-facing illustration mode. Use `ai`, `mermaid`, or `false`.
- **ILLUSTRATION_BACKEND = `browser`** — Runtime backend. `browser` is default; `api` is explicit fallback.
- **PAPER_AUTO_INSTALL = true** — Auto-bootstrap Workflow 3 dependencies on first run.
- **PAPER_VENV_DIR = `.venv`** — Project-local Python environment for paper tooling.
- **PAPER_SYSTEM_INSTALL = `auto`** — Auto-install supported system packages via `apt-get` or `brew`.
- **MAX_CRITIC_ROUNDS = 3** — Maximum critic feedback loops before accepting the latest render or surfacing a blocker.
- **TARGET_SCORE = 9** — Target critic score for the final image.
- **RETRIEVAL_SETTING = `auto`** — `auto` uses local reference assets when available, `none` skips retrieval.
- **GEMINI_BROWSER_PROFILE_MODE = `dedicated`** — Keep Gemini automation isolated from your daily browser profile.
- **GEMINI_BROWSER_PROFILE_DIR** — Dedicated persistent profile reused by both the CLI and the MCP server.
- **GEMINI_BROWSER_HEADLESS = `false`** — Headed browser by default; helps reduce login/session friction.
- **GEMINI_BROWSER_AUTO_INTERACTIVE = `true`** — Automatically open or reuse an interactive Gemini browser window when sign-in is required.
- **GEMINI_BROWSER_AUTO_INTERACTIVE_WAIT_SEC = `300`** — How long `status` / `render_image` wait for login or human verification before returning `needs_login` or `needs_human_verification`.
- **GEMINI_BROWSER_AUTO_WAIT_FOR_HUMAN_VERIFICATION = `true`** — Keep the same auto-interactive recovery path active when Gemini/Google shows “I’m not a robot” or unusual-traffic verification.
- **GEMINI_BROWSER_AUTO_UPDATE = `true`** — Automatically refresh the Playwright-managed Chromium when the required revision changes.
- **GEMINI_BROWSER_UPDATE_SCOPE = `playwright_chromium`** — Only auto-update Playwright-managed Chromium, not external browsers.
- **GEMINI_BROWSER_CLOSE_INTERACTIVE_AFTER_READY = `true`** — Close the interactive login window after readiness and continue in the background.
- **GEMINI_BROWSER_PRUNE_EXTRA_PAGES = `true`** — Automatically prune extra dedicated-profile windows/tabs and keep the Gemini automation session on a strict single visible page.
- **GEMINI_BROWSER_MAX_INTERACTIVE_PAGES = `1`** — Maximum number of dedicated-profile interactive pages kept alive at once.
- **GEMINI_BROWSER_RENDER_SESSION_MODE = `temporary`** — Reset each render into a temporary chat, with `new_chat` as fallback if needed.
- **GEMINI_BROWSER_RENDER_RETRY_ON_CONTEXT_LEAK = `true`** — Retry automatically if Gemini appears to reuse stale chat context.
- **GEMINI_BROWSER_RENDER_MAX_RETRIES = `2`** — Maximum automatic retries after a context-leak detection.
- **GEMINI_BROWSER_MODE_POLICY = `prefer_thinking_fallback_fast`** — Prefer Thinking/Pro mode before Fast/Flash.
- **GEMINI_BROWSER_REMOTE_DEBUG_PORT = `9223`** — Preferred CDP port for the detached interactive browser session.
- **GEMINI_BROWSER_EXECUTABLE_PATH** — Optional explicit browser executable override for the interactive session.
- **PAPER_ILLUSTRATION_API_KEY** — Optional API fallback key. Only needed when `ILLUSTRATION_BACKEND=api`.

> Override: `/paper-illustration "overview figure" — retrieval setting: none`

## Inputs

The CLI reads as much context as exists:

1. **`PAPER_PLAN.md`** — especially the Figure Plan table and hero figure description
2. **`NARRATIVE_REPORT.md`** — story framing and figure requirements
3. **`AUTO_REVIEW.md`** — especially `## Method Description`
4. **Optional reference assets** — local examples passed through `--reference-dir`
5. **Direct request text** — if no plan exists, the argument itself becomes the figure spec

## Workflow

### Step 1: Gather Illustration Context

Read the relevant figure spec from `PAPER_PLAN.md` if it exists. Prefer figures whose type or description indicates:

- hero figure
- architecture
- method diagram
- pipeline
- workflow
- overview

Use `$RESEARCH_ROOT/AUTO_REVIEW.md`'s `## Method Description` as the primary method-summary input when available.

### Step 2: Run the PaperBanana-Derived CLI

Bootstrap the illustration runtime first:

```bash
python3 tools/ensure_paper_runtime.py --phase illustration
```

```bash
python3 tools/paper_illustration_cli.py \
  --workspace-root "$RESEARCH_ROOT" \
  --paper-plan PAPER_PLAN.md \
  --narrative-report NARRATIVE_REPORT.md \
  --auto-review AUTO_REVIEW.md \
  --manifest figures/illustration_manifest.json \
  --latex-includes figures/latex_includes.tex
```

The CLI will:

1. classify candidate figures from the figure plan
2. mark screenshots / qualitative grids / real photos as `manual_blocker`
3. default to the browser-backed Gemini web flow with a dedicated automation profile
4. reset each render into a fresh temporary chat, explicitly enable Gemini's image tool, prefer Thinking/Pro mode with Fast/Flash fallback, wrap the browser prompt in an image-only instruction, and auto-retry if stale chat context leaks in
5. if temporary-chat retries still surface stale artifacts or no reliable image path, escalate that retry to `new_chat` while preserving the dedicated profile
6. fall back to the Retriever → Planner → Stylist → Visualizer → Critic loop only when `ILLUSTRATION_BACKEND=api`
7. write final images to `$RESEARCH_ROOT/figures/ai_generated/`
8. write `$RESEARCH_ROOT/figures/illustration_manifest.json`
9. append/update the illustration snippets inside `$RESEARCH_ROOT/figures/latex_includes.tex`

If you want plugin-style access inside Claude Code, the shared browser backend is also exposed through:

- `mcp-servers/gemini-browser/server.py`

Manual fallback only if automatic bootstrap is disabled or fails:

```bash
python3 -m pip install -r mcp-servers/gemini-browser/requirements.txt
python3 -m playwright install chromium
claude mcp add gemini-browser -s user -- \
  python3 /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/gemini-browser/server.py
```

First use:

1. call `status`
2. if sign-in or human verification is missing, `status` automatically opens or reuses a dedicated interactive Gemini browser window
3. finish Gemini login and any “I’m not a robot” or unusual-traffic verification manually in that window
4. while waiting, the backend automatically prunes duplicate Gemini/login/verification/blank pages so the dedicated profile stays at a single visible page
5. `status` waits for recovery and returns `ready` if it succeeds before timeout; on success it closes the interactive window and rebinds the dedicated profile in the background; otherwise it returns `needs_login` or `needs_human_verification` and leaves only the required recovery page open
6. call `login` only when you want to explicitly reopen or keep waiting on the same dedicated session

### Step 3: Inspect the Manifest

The manifest is the canonical status file for AI illustrations:

```json
{
  "entries": [
    {
      "figure_id": "Fig 1",
      "kind": "illustration",
      "status": "auto_illustrated",
      "source": "paper-illustration",
      "latex_label": "fig:fig_1",
      "output_path": "figures/ai_generated/fig_1_final.png"
    }
  ]
}
```

Status values:

- `auto_illustrated` — generated by this skill
- `manual_blocker` — still needs user-supplied external assets
- `needs_login` — Gemini web automation opened or reused the dedicated interactive session, but sign-in still has not completed
- `needs_human_verification` — Gemini or Google requires a manual “I’m not a robot” / unusual-traffic verification step before the run can continue
- `backend_blocker` — browser/API runtime failure such as missing login, DOM drift, download failure, or rate limiting
- `auto_generated` — reserved for data/table figures handled by `/paper-figure`

### Step 4: Handle Blockers Correctly

Do **not** silently treat all non-data figures as manual. Only surface a manual blocker when the figure truly depends on external assets such as:

- qualitative sample grids
- screenshots
- real photographs
- user-provided images

If the browser backend reports `needs_login` or `needs_human_verification`, preserve that status and note that the dedicated interactive Gemini window has already been opened or reused. Use `backend_blocker` for other runtime failures such as missing GUI access, DOM drift, unavailable image generation, or download errors. In all cases, point to `refine-logs/PAPER_RUNTIME_STATE.json` or a rerun of `python3 tools/ensure_paper_runtime.py --phase illustration`. Only point to `PAPER_ILLUSTRATION_API_KEY` when they explicitly choose `ILLUSTRATION_BACKEND=api`.

The dedicated Gemini profile is now treated as an automation-owned surface. It should not accumulate windows: duplicate blank tabs, stale Gemini pages, duplicate login pages, and duplicate verification pages are pruned automatically, and a successful recovery leaves no visible automation window behind.

## Outputs

- `$RESEARCH_ROOT/figures/ai_generated/*.png` — rendered AI illustrations
- `$RESEARCH_ROOT/figures/illustration_manifest.json` — parseable illustration status
- `$RESEARCH_ROOT/figures/latex_includes.tex` — illustration snippets merged with the standard figure include file

## Key Rules

- **Use the real runtime.** Do not handwave the figure-generation process inside the skill body.
- **Keep the public interface model-agnostic.** User-facing docs and commands should say `illustration: ai`, not provider/model names.
- **Default to browser-first.** Gemini web automation is the primary path; API is explicit fallback.
- **Bootstrap before rendering.** The first step is `python3 tools/ensure_paper_runtime.py --phase illustration`.
- **Preserve provenance.** Vendored code stays under `third_party/paperbanana/` with Apache-2.0 attribution.
- **Prefer `$RESEARCH_ROOT/AUTO_REVIEW.md` over ad hoc summaries.** That file is the canonical review artifact for Workflow 2.
- **Do not mark architecture diagrams as manual by default.** Try the AI illustration pipeline first.
