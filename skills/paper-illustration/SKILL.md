---
name: paper-illustration
description: "Generate publication-quality AI illustrations for academic papers using a PaperBanana-derived multi-stage pipeline. Use when user says \"生成图表\", \"画架构图\", \"AI绘图\", \"paper illustration\", \"generate diagram\", or needs hero/method/architecture figures for papers."
argument-hint: [description-or-method-file]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, mcp__codex__codex, mcp__codex__codex-reply, WebSearch
---

# Paper Illustration: PaperBanana-Derived AI Figure Pipeline

Generate publication-quality academic illustrations for: **$ARGUMENTS**

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

Use `AUTO_REVIEW.md`'s `## Method Description` as the primary method-summary input when available.

### Step 2: Run the PaperBanana-Derived CLI

Bootstrap the illustration runtime first:

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
3. default to the browser-backed Gemini web flow with a dedicated automation profile
4. fall back to the Retriever → Planner → Stylist → Visualizer → Critic loop only when `ILLUSTRATION_BACKEND=api`
5. write final images to `figures/ai_generated/`
6. write `figures/illustration_manifest.json`
7. append/update the illustration snippets inside `figures/latex_includes.tex`

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
2. if it returns `needs_login`, call `login`
3. finish Gemini login manually in the opened dedicated browser window
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

- `auto_illustrated` — generated by this skill
- `manual_blocker` — still needs user-supplied external assets
- `backend_blocker` — browser/API runtime failure such as missing login, DOM drift, download failure, or rate limiting
- `auto_generated` — reserved for data/table figures handled by `/paper-figure`

### Step 4: Handle Blockers Correctly

Do **not** silently treat all non-data figures as manual. Only surface a manual blocker when the figure truly depends on external assets such as:

- qualitative sample grids
- screenshots
- real photographs
- user-provided images

If the browser backend is not ready, report that explicitly as `backend_blocker` and point the user to `refine-logs/PAPER_RUNTIME_STATE.json`, the dedicated-profile login flow, or a rerun of `python3 tools/ensure_paper_runtime.py --phase illustration`. Only point to `PAPER_ILLUSTRATION_API_KEY` when they explicitly choose `ILLUSTRATION_BACKEND=api`.

## Outputs

- `figures/ai_generated/*.png` — rendered AI illustrations
- `figures/illustration_manifest.json` — parseable illustration status
- `figures/latex_includes.tex` — illustration snippets merged with the standard figure include file

## Key Rules

- **Use the real runtime.** Do not handwave the figure-generation process inside the skill body.
- **Keep the public interface model-agnostic.** User-facing docs and commands should say `illustration: ai`, not provider/model names.
- **Default to browser-first.** Gemini web automation is the primary path; API is explicit fallback.
- **Bootstrap before rendering.** The first step is `python3 tools/ensure_paper_runtime.py --phase illustration`.
- **Preserve provenance.** Vendored code stays under `third_party/paperbanana/` with Apache-2.0 attribution.
- **Prefer `AUTO_REVIEW.md` over ad hoc summaries.** That file is the canonical review artifact for Workflow 2.
- **Do not mark architecture diagrams as manual by default.** Try the AI illustration pipeline first.
