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
4. use the Retriever → Planner → Stylist → Visualizer → Critic loop only when `ILLUSTRATION_BACKEND=api`
5. write final images to `figures/ai_generated/`
6. write `figures/illustration_manifest.json`
7. append/update the illustration snippets inside `figures/latex_includes.tex`

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
2. if it returns `needs_login`, call `login`
3. finish Gemini login manually in the dedicated browser window
4. rerun `status` until it returns `ready`

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
- `backend_blocker`
- `auto_generated`

### Step 4: Handle Blockers Correctly

Only mark a figure as manual when it truly depends on external assets such as:

- qualitative sample grids
- screenshots
- real photographs
- user-provided images

If the browser backend is not ready, report `backend_blocker` and point to `refine-logs/PAPER_RUNTIME_STATE.json`, a rerun of `python3 tools/ensure_paper_runtime.py --phase illustration`, or the dedicated-profile login flow. Only point to `PAPER_ILLUSTRATION_API_KEY` when `ILLUSTRATION_BACKEND=api`.

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
