#!/usr/bin/env python3
"""PaperBanana-derived CLI for academic method illustrations."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ensure_paper_runtime import maybe_reexec_for_phase

maybe_reexec_for_phase("illustration")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from third_party.paperbanana import (
    CriticAgent,
    GeminiBrowserBackend,
    IllustrationConfig,
    PlannerAgent,
    RetrieverAgent,
    StylistAgent,
    VisualizerAgent,
)


PLACEHOLDER_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnP7wAAAABJRU5ErkJggg=="
)

ILLUSTRATION_KEYWORDS = {
    "architecture",
    "diagram",
    "hero",
    "method",
    "overview",
    "pipeline",
    "workflow",
}
EXTERNAL_KEYWORDS = {
    "photo",
    "photograph",
    "qualitative",
    "sample grid",
    "screenshot",
    "user-provided",
}


@dataclass
class FigureSpec:
    figure_id: str
    figure_type: str
    description: str
    data_source: str
    priority: str

    @property
    def caption(self) -> str:
        return self.description.strip() or self.figure_id

    @property
    def normalized_id(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", self.figure_id.lower()).strip("_")
        return slug or "figure"

    @property
    def kind(self) -> str:
        haystack = " ".join(
            [
                self.figure_type.lower(),
                self.description.lower(),
                self.data_source.lower(),
            ]
        )
        if any(keyword in haystack for keyword in EXTERNAL_KEYWORDS):
            return "external"
        if any(keyword in haystack for keyword in ILLUSTRATION_KEYWORDS):
            return "illustration"
        if "table" in haystack:
            return "table"
        return "plot"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", default="", help="Optional free-form illustration request.")
    parser.add_argument("--paper-plan", default="PAPER_PLAN.md")
    parser.add_argument("--narrative-report", default="NARRATIVE_REPORT.md")
    parser.add_argument("--auto-review", default="AUTO_REVIEW.md")
    parser.add_argument("--output-dir", default="figures/ai_generated")
    parser.add_argument("--manifest", default="figures/illustration_manifest.json")
    parser.add_argument("--latex-includes", default="figures/latex_includes.tex")
    parser.add_argument("--reference-dir")
    parser.add_argument("--backend", choices=["browser", "api"])
    parser.add_argument("--figure-id", action="append", default=[])
    parser.add_argument("--retrieval-setting", choices=["auto", "none"], default="auto")
    parser.add_argument("--max-critic-rounds", type=int, default=3)
    parser.add_argument("--target-score", type=int, default=9)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paper_plan = _read_optional(Path(args.paper_plan))
    narrative_report = _read_optional(Path(args.narrative_report))
    auto_review = _read_optional(Path(args.auto_review))

    figure_specs = _select_figure_specs(
        paper_plan=paper_plan,
        request=args.request,
        requested_ids=args.figure_id,
    )
    if not figure_specs:
        print("No illustration candidates found. Nothing to do.", file=sys.stderr)
        return 1

    config_kwargs: dict[str, Any] = {
        "work_dir": work_dir,
        "output_dir": output_dir,
        "reference_dir": Path(args.reference_dir) if args.reference_dir else None,
        "retrieval_setting": args.retrieval_setting,
        "max_critic_rounds": args.max_critic_rounds,
        "target_score": args.target_score,
    }
    if args.backend:
        config_kwargs["backend"] = args.backend

    config = IllustrationConfig(
        **config_kwargs,
    )
    retriever = RetrieverAgent(config)
    browser_backend = GeminiBrowserBackend(config) if config.uses_browser_backend else None
    planner = PlannerAgent(config) if config.uses_api_backend else None
    stylist = StylistAgent(config) if config.uses_api_backend else None
    visualizer = VisualizerAgent(config) if config.uses_api_backend else None
    critic = CriticAgent(config) if config.uses_api_backend else None

    manifest_entries: list[dict[str, Any]] = []
    blocked = False
    for spec in figure_specs:
        entry = _build_manifest_entry(
            spec=spec,
            config=config,
            output_dir=output_dir,
            narrative_report=narrative_report,
            auto_review=auto_review,
            paper_plan=paper_plan,
            retriever=retriever,
            browser_backend=browser_backend,
            planner=planner,
            stylist=stylist,
            visualizer=visualizer,
            critic=critic,
            dry_run=args.dry_run,
        )
        manifest_entries.append(entry)
        if entry["status"] in {"manual_blocker", "backend_blocker"}:
            blocked = True

    _write_manifest(Path(args.manifest), manifest_entries, backend=config.normalized_backend)
    _update_latex_includes(Path(args.latex_includes), manifest_entries)

    if blocked and not args.dry_run:
        return 2
    return 0


def _build_manifest_entry(
    *,
    spec: FigureSpec,
    config: IllustrationConfig,
    output_dir: Path,
    narrative_report: str,
    auto_review: str,
    paper_plan: str,
    retriever: RetrieverAgent,
    browser_backend: GeminiBrowserBackend | None,
    planner: PlannerAgent | None,
    stylist: StylistAgent | None,
    visualizer: VisualizerAgent | None,
    critic: CriticAgent | None,
    dry_run: bool,
) -> dict[str, Any]:
    figure_path = output_dir / f"{spec.normalized_id}_final.png"
    latex_label = f"fig:{spec.normalized_id}"
    base_entry = {
        "figure_id": spec.figure_id,
        "kind": spec.kind,
        "source": "paper-illustration" if spec.kind == "illustration" else "user",
        "backend": config.normalized_backend if spec.kind == "illustration" else None,
        "inputs": {
            "paper_plan": "PAPER_PLAN.md" if paper_plan else None,
            "narrative_report": "NARRATIVE_REPORT.md" if narrative_report else None,
            "auto_review": "AUTO_REVIEW.md" if auto_review else None,
        },
        "latex_label": latex_label,
        "output_path": str(figure_path),
        "caption": spec.caption,
    }

    if spec.kind == "external":
        return dict(
            base_entry,
            status="manual_blocker",
            notes="This figure depends on external qualitative assets or user-provided media.",
        )

    if spec.kind != "illustration":
        return dict(
            base_entry,
            source="paper-figure",
            status="auto_generated",
            notes="Generated by /paper-figure or another data-driven figure step.",
        )

    method_context = _compose_method_context(
        narrative_report=narrative_report,
        auto_review=auto_review,
        paper_plan=paper_plan,
        spec=spec,
    )
    if dry_run:
        figure_path.write_bytes(base64.b64decode(PLACEHOLDER_PNG_BASE64))
        return dict(
            base_entry,
            status="auto_illustrated",
            notes=(
                "Dry-run placeholder output written without calling the "
                f"{config.normalized_backend} backend."
            ),
            review_score=None,
        )

    references = retriever.process(query_text=f"{spec.caption}\n{method_context}", top_k=3)
    base_entry["reference_count"] = len(references)

    if config.uses_browser_backend:
        if browser_backend is None:
            return dict(
                base_entry,
                status="backend_blocker",
                notes="Browser backend was selected but not initialized.",
            )
        render_result = browser_backend.render_image(
            prompt=browser_backend.build_prompt(
                method_context=method_context,
                figure_id=spec.figure_id,
                figure_type=spec.figure_type,
                figure_caption=spec.caption,
                figure_description=spec.description,
                references=references,
                aspect_ratio=_aspect_ratio_for(spec),
            ),
            output_path=figure_path,
            aspect_ratio=_aspect_ratio_for(spec),
        )
        if render_result.status == "auto_illustrated":
            return dict(
                base_entry,
                status="auto_illustrated",
                output_path=render_result.output_path or str(figure_path),
                notes=(
                    "Generated through the browser-backed Gemini web workflow using "
                    "the dedicated automation profile."
                ),
                artifact_method=render_result.artifact_method,
                debug_bundle_path=render_result.debug_bundle_path,
                selector_report=render_result.selector_report,
                review_score=None,
            )
        return dict(
            base_entry,
            status="backend_blocker",
            notes=render_result.message,
            debug_bundle_path=render_result.debug_bundle_path,
            selector_report=render_result.selector_report,
            backend_status=render_result.status,
        )

    if not config.has_backend_credentials:
        return dict(
            base_entry,
            status="backend_blocker",
            notes=(
                "API illustration backend is not configured. Set ILLUSTRATION_BACKEND=browser "
                "to use the Gemini web flow, or configure PAPER_ILLUSTRATION_API_KEY "
                "(or PAPER_ILLUSTRATION_API_KEY_ENV / GEMINI_API_KEY) for API fallback."
            ),
        )
    if any(agent is None for agent in (planner, stylist, visualizer, critic)):
        return dict(
            base_entry,
            status="backend_blocker",
            notes="API backend was selected but the PaperBanana agent chain is incomplete.",
        )

    planned = planner.process(
        method_context=method_context,
        figure_id=spec.figure_id,
        figure_type=spec.figure_type,
        figure_caption=spec.caption,
        figure_description=spec.description,
        references=references,
    )
    styled = stylist.process(
        detailed_description=planned,
        method_context=method_context,
        figure_caption=spec.caption,
    )
    review_score = None
    current_description = styled
    image_bytes, image_mime = visualizer.process(
        styled_description=current_description,
        aspect_ratio=_aspect_ratio_for(spec),
    )
    for _ in range(config.max_critic_rounds):
        review = critic.process(
            image_bytes=image_bytes,
            image_mime_type=image_mime,
            detailed_description=current_description,
            method_context=method_context,
            figure_caption=spec.caption,
        )
        review_score = review["score"]
        revised = review["revised_description"].strip()
        if review_score >= config.target_score or revised == current_description.strip():
            break
        current_description = revised
        image_bytes, image_mime = visualizer.process(
            styled_description=current_description,
            aspect_ratio=_aspect_ratio_for(spec),
        )
    figure_path.write_bytes(image_bytes)
    return dict(
        base_entry,
        status="auto_illustrated",
        notes=(
            "Generated through the API-backed PaperBanana planner/stylist/visualizer/"
            "critic loop."
        ),
        review_score=review_score,
    )


def _compose_method_context(
    *,
    narrative_report: str,
    auto_review: str,
    paper_plan: str,
    spec: FigureSpec,
) -> str:
    parts = []
    method_description = _extract_section(auto_review, "Method Description")
    if method_description:
        parts.append("Method Description:\n" + method_description.strip())
    core_story = _extract_section(narrative_report, "Core Story")
    if core_story:
        parts.append("Core Story:\n" + core_story.strip())
    figure_plan = _extract_section(paper_plan, "Figure Plan")
    if figure_plan:
        parts.append("Figure Plan:\n" + figure_plan.strip())
    parts.append(
        "\n".join(
            [
                f"Target Figure ID: {spec.figure_id}",
                f"Target Figure Type: {spec.figure_type}",
                f"Target Figure Description: {spec.description}",
            ]
        )
    )
    return "\n\n".join(part for part in parts if part.strip())


def _aspect_ratio_for(spec: FigureSpec) -> str:
    haystack = f"{spec.figure_type} {spec.description}".lower()
    if "overview" in haystack or "pipeline" in haystack:
        return "16:9"
    if "architecture" in haystack:
        return "4:3"
    return "1:1"


def _select_figure_specs(*, paper_plan: str, request: str, requested_ids: list[str]) -> list[FigureSpec]:
    specs = _parse_figure_plan(paper_plan)
    if requested_ids:
        wanted = {item.lower() for item in requested_ids}
        specs = [spec for spec in specs if spec.figure_id.lower() in wanted]
    if not specs and request.strip():
        specs = [
            FigureSpec(
                figure_id="Fig_custom",
                figure_type="Method Diagram",
                description=request.strip(),
                data_source="paper-illustration",
                priority="HIGH",
            )
        ]
    return specs


def _parse_figure_plan(markdown_text: str) -> list[FigureSpec]:
    specs: list[FigureSpec] = []
    lines = markdown_text.splitlines()
    for index, line in enumerate(lines):
        if "| ID | Type | Description | Data Source | Priority |" not in line:
            continue
        for row in lines[index + 2 :]:
            if not row.strip().startswith("|"):
                break
            columns = [column.strip() for column in row.strip().strip("|").split("|")]
            if len(columns) < 5:
                continue
            spec = FigureSpec(
                figure_id=columns[0],
                figure_type=columns[1],
                description=columns[2],
                data_source=columns[3],
                priority=columns[4],
            )
            if spec.kind in {"illustration", "external"}:
                specs.append(spec)
        break
    return specs


def _extract_section(markdown_text: str, heading: str) -> str:
    if not markdown_text.strip():
        return ""
    pattern = re.compile(
        rf"(?ms)^##+\s+{re.escape(heading)}\s*$\n(.*?)(?=^##+\s+|\Z)"
    )
    match = pattern.search(markdown_text)
    return match.group(1).strip() if match else ""


def _read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_manifest(path: Path, entries: list[dict[str, Any]], *, backend: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _update_latex_includes(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    for entry in entries:
        if entry["kind"] != "illustration":
            continue
        marker = re.sub(r"[^a-z0-9_]+", "_", entry["figure_id"].lower())
        block_re = re.compile(
            rf"(?ms)^% BEGIN ILLUSTRATION {re.escape(marker)}\n.*?^% END ILLUSTRATION {re.escape(marker)}\n?"
        )
        if block_re.search(existing):
            existing = block_re.sub("", existing)
        if entry["status"] != "auto_illustrated":
            continue
        rel_path = Path(entry["output_path"]).as_posix()
        snippet = "\n".join(
            [
                f"% BEGIN ILLUSTRATION {marker}",
                r"\begin{figure}[t]",
                r"    \centering",
                f"    \\includegraphics[width=0.95\\textwidth]{{{rel_path}}}",
                f"    \\caption{{{_escape_latex(entry['caption'])}}}",
                f"    \\label{{{entry['latex_label']}}}",
                r"\end{figure}",
                f"% END ILLUSTRATION {marker}",
            ]
        )
        if existing and not existing.endswith("\n"):
            existing += "\n"
        existing += snippet + "\n"
    path.write_text(existing, encoding="utf-8")


def _escape_latex(text: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


if __name__ == "__main__":
    raise SystemExit(main())
