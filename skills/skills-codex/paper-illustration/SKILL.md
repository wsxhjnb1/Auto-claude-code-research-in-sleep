---
name: "paper-illustration"
description: "Generate publication-quality AI illustrations for academic papers using a PaperBanana-derived multi-stage pipeline. Use when user says \"生成图表\", \"画架构图\", \"AI绘图\", \"paper illustration\", \"generate diagram\", or needs hero/method/architecture figures for papers."
---

# Paper Illustration: PaperBanana-Derived AI Figure Pipeline

Generate publication-quality academic illustrations for: **$ARGUMENTS**

This skill is backed by real runtime code:

```bash
python3 tools/paper_illustration_cli.py "$ARGUMENTS"
```

The implementation lives in:

- `tools/paper_illustration_cli.py`
- `third_party/paperbanana/`

The vendored runtime is a selective PaperBanana import plus a browser-backed Gemini web renderer:

- Retriever — optional reference-driven prompting
- Browser backend — submits prompts through a dedicated Gemini web profile and saves the result
- Planner / Stylist / Visualizer / Critic — explicit API fallback path

## Constants

- **ILLUSTRATION = `ai`** — User-facing illustration mode. Use `ai`, `mermaid`, or `false`.
- **ILLUSTRATION_BACKEND = `browser`** — Default backend. `api` is explicit fallback.
- **PAPER_AUTO_INSTALL = true**
- **PAPER_VENV_DIR = `.venv`**
- **PAPER_SYSTEM_INSTALL = `auto`**
- **MAX_CRITIC_ROUNDS = 3**
- **TARGET_SCORE = 9**
- **RETRIEVAL_SETTING = `auto`**
- **GEMINI_BROWSER_PROFILE_MODE = `dedicated`**
- **GEMINI_BROWSER_PROFILE_DIR** — Dedicated persistent profile
- **GEMINI_BROWSER_HEADLESS = `false`**
- **GEMINI_BROWSER_AUTO_INTERACTIVE = `true`**
- **GEMINI_BROWSER_AUTO_INTERACTIVE_WAIT_SEC = `300`**
- **GEMINI_BROWSER_AUTO_WAIT_FOR_HUMAN_VERIFICATION = `true`**
- **GEMINI_BROWSER_AUTO_UPDATE = `true`**
- **GEMINI_BROWSER_UPDATE_SCOPE = `playwright_chromium`**
- **GEMINI_BROWSER_CLOSE_INTERACTIVE_AFTER_READY = `true`**
- **GEMINI_BROWSER_PRUNE_EXTRA_PAGES = `true`**
- **GEMINI_BROWSER_MAX_INTERACTIVE_PAGES = `1`**
- **GEMINI_BROWSER_RENDER_SESSION_MODE = `temporary`**
- **GEMINI_BROWSER_RENDER_RETRY_ON_CONTEXT_LEAK = `true`**
- **GEMINI_BROWSER_RENDER_MAX_RETRIES = `2`**
- **GEMINI_BROWSER_MODE_POLICY = `prefer_thinking_fallback_fast`**
- **GEMINI_BROWSER_REMOTE_DEBUG_PORT = `9223`**
- **GEMINI_BROWSER_EXECUTABLE_PATH** — Optional explicit browser executable override
- **PAPER_ILLUSTRATION_API_KEY** — Optional API fallback key

## Inputs

The CLI reads as much context as exists:

1. `PAPER_PLAN.md`
2. `NARRATIVE_REPORT.md`
3. `AUTO_REVIEW.md`
4. optional local reference assets via `--reference-dir`
5. direct request text when no paper plan exists

## Workflow

### Step 1: Gather Illustration Context

Read the relevant figure spec from `PAPER_PLAN.md` when present. Prefer figures whose type or description indicates:

- hero figure
- architecture
- method diagram
- pipeline
- workflow
- overview

Use `AUTO_REVIEW.md`'s `## Method Description` as the primary method-summary input when available.

### Step 2: Run the CLI

Bootstrap first:

```bash
python3 tools/ensure_paper_runtime.py --phase illustration
```

```bash
python3 tools/paper_illustration_cli.py \
  --paper-plan PAPER_PLAN.md \
  --narrative-report NARRATIVE_REPORT.md \
  --auto-review AUTO_REVIEW.md \
  --manifest figures/illustration_manifest.json \
  --latex-includes figures/latex_includes.tex
```

The CLI will:

1. classify candidate figures from the figure plan
2. mark screenshots / qualitative grids / real photos as `manual_blocker`
3. default to the browser-backed Gemini web flow
4. reset each render into a fresh temporary chat, explicitly enable Gemini's image tool, wrap the browser prompt in an image-only instruction, and auto-retry if stale chat context leaks in
5. if temporary-chat retries still surface stale artifacts or no reliable image path, escalate that retry to `new_chat` while preserving the dedicated profile
6. use the Retriever → Planner → Stylist → Visualizer → Critic loop only when `ILLUSTRATION_BACKEND=api`
7. write final images to `figures/ai_generated/`
8. write `figures/illustration_manifest.json`
9. append/update the illustration snippets inside `figures/latex_includes.tex`

Shared MCP bridge:

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
3. while waiting, the backend prunes duplicate Gemini/login/verification/blank pages so the dedicated profile stays at a single visible page
4. finish Gemini login and any “I’m not a robot” or unusual-traffic verification manually in that window
5. `status` waits for recovery and returns `ready` if it succeeds before timeout; otherwise it returns `needs_login` or `needs_human_verification` and leaves only the required recovery page open
5. call `login` only when you want to explicitly reopen or keep waiting on the same dedicated session

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

- `auto_illustrated`
- `manual_blocker`
- `needs_login`
- `needs_human_verification`
- `backend_blocker`
- `auto_generated`

### Step 4: Handle Blockers Correctly

Only mark a figure as manual when it truly depends on external assets such as:

- qualitative sample grids
- screenshots
- real photographs
- user-provided images

If the browser backend reports `needs_login` or `needs_human_verification`, preserve that status and note that the dedicated interactive Gemini window has already been opened or reused. Use `backend_blocker` for other runtime failures such as missing GUI access, DOM drift, unavailable image generation, or download errors. In all cases, point to `refine-logs/PAPER_RUNTIME_STATE.json` or a rerun of `python3 tools/ensure_paper_runtime.py --phase illustration`. Only point to `PAPER_ILLUSTRATION_API_KEY` when `ILLUSTRATION_BACKEND=api`.

The dedicated Gemini profile is automation-owned: duplicate blank tabs, stale Gemini pages, duplicate login pages, and duplicate verification pages are pruned automatically, and a successful recovery leaves no visible automation window behind.

## Outputs

- `figures/ai_generated/*.png`
- `figures/illustration_manifest.json`
- `figures/latex_includes.tex`

## Key Rules

- Use the real runtime, not a skill-body pseudo-implementation.
- Keep the public interface model-agnostic: `illustration: ai`.
- Default to the browser-backed path. API is explicit fallback.
- Bootstrap illustration dependencies before rendering.
- Preserve Apache-2.0 attribution for vendored PaperBanana code.
- Prefer `AUTO_REVIEW.md` over ad hoc summaries.
- Do not mark architecture diagrams as manual by default.
