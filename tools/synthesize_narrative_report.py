#!/usr/bin/env python3
"""Synthesize a draft NARRATIVE_REPORT.md from Workflow 1.5/2 artifacts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ensure_paper_runtime import maybe_reexec_for_phase

maybe_reexec_for_phase("write")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", default="refine-logs/FINAL_PROPOSAL.md")
    parser.add_argument("--plan", default="refine-logs/EXPERIMENT_PLAN.md")
    parser.add_argument("--results", default="refine-logs/EXPERIMENT_RESULTS.md")
    parser.add_argument("--runtime", default="refine-logs/EXPERIMENT_RUNTIME.json")
    parser.add_argument("--review", default="AUTO_REVIEW.md")
    parser.add_argument("--output", default="NARRATIVE_REPORT.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    proposal = _read_optional(Path(args.proposal))
    plan = _read_optional(Path(args.plan))
    results = _read_optional(Path(args.results))
    review = _read_optional(Path(args.review))
    runtime = _read_json_optional(Path(args.runtime))

    title = _extract_title(proposal) or _extract_title(results) or "Auto-Synthesized Research Narrative"
    method_description = _extract_section(review, "Method Description")
    core_story = _first_nonempty(
        _extract_section(proposal, "Final Method Thesis"),
        _extract_section(proposal, "Summary"),
        method_description,
        _extract_section(results, "Summary"),
    )
    claims = _extract_claims(plan, results)
    weaknesses = _extract_weaknesses(review, results)
    figures = _extract_figures(plan)
    experiment_setup = _extract_setup(plan, runtime)
    experiment_summary = _extract_experiment_summary(results, runtime)

    output = Path(args.output)
    output.write_text(
        "\n".join(
            [
                f"# Narrative Report: {title}",
                "",
                "> Auto-synthesized draft from Workflow 1.5/2 artifacts. Edit freely before `/paper-writing`.",
                "",
                "## Core Story",
                core_story or "Describe the problem, the approach, and the strongest result here.",
                "",
                "## Claims",
                *claims,
                "",
                "## Experiments",
                "",
                "### Setup",
                *experiment_setup,
                "",
                "### Summary",
                experiment_summary or "Summarize the main experiment outcomes here.",
                "",
                "## Figures",
                *figures,
                "",
                "## Known Weaknesses",
                *weaknesses,
                "",
                "## Proposed Title",
                title,
                "",
                "## Target Venue",
                _extract_target_venue(proposal, plan, review),
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def _read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json_optional(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    match = re.search(r"^\*\*Title\*\*:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_section(markdown_text: str, heading: str) -> str:
    pattern = re.compile(rf"(?ms)^##+\s+{re.escape(heading)}\s*$\n(.*?)(?=^##+\s+|\Z)")
    match = pattern.search(markdown_text)
    return match.group(1).strip() if match else ""


def _extract_claims(plan: str, results: str) -> list[str]:
    claims = []
    for source in (plan, results):
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- [Claim", "- **[Main claim", "1. **", "2. **")):
                claims.append(stripped if stripped.startswith("-") else f"- {stripped}")
        if claims:
            break
    if not claims:
        claims = [
            "- **Main claim**: Fill from the strongest supported experiment result.",
            "- **Supporting claim**: Fill from the strongest ablation or analysis result.",
        ]
    return claims


def _extract_weaknesses(review: str, results: str) -> list[str]:
    weaknesses = []
    for text in (review, results):
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("-") and any(
                keyword in stripped.lower()
                for keyword in ("limitation", "weakness", "risk", "blocker")
            ):
                weaknesses.append(stripped)
    return weaknesses or ["- Add remaining limitations or reviewer caveats here."]


def _extract_figures(plan: str) -> list[str]:
    figures = []
    in_table = False
    for line in plan.splitlines():
        if "| ID | Type | Description | Data Source | Priority |" in line:
            in_table = True
            continue
        if in_table:
            if not line.strip().startswith("|"):
                break
            cols = [col.strip() for col in line.strip().strip("|").split("|")]
            if len(cols) >= 3 and not all(set(col) <= {"-"} for col in cols[:3]):
                figures.append(f"- **{cols[0]}**: {cols[2]}")
    return figures or ["- Add figure/table requirements here."]


def _extract_setup(plan: str, runtime: dict) -> list[str]:
    setup = []
    if runtime:
        environment = runtime.get("environment") or runtime.get("environments")
        if environment:
            setup.append(f"- **Environment**: {environment}")
        commands = runtime.get("command") or runtime.get("commands")
        if commands:
            setup.append(f"- **Command**: {commands}")
    for line in plan.splitlines():
        stripped = line.strip()
        if stripped.startswith("-") and any(
            keyword in stripped.lower()
            for keyword in ("dataset", "metric", "baseline", "seed", "backbone")
        ):
            setup.append(stripped)
    return setup or ["- Fill models, datasets, baselines, hardware, and metrics here."]


def _extract_experiment_summary(results: str, runtime: dict) -> str:
    summary = _extract_section(results, "Summary")
    if summary:
        return summary
    if runtime:
        exit_code = runtime.get("exit_code")
        wall_time = runtime.get("wall_time") or runtime.get("wall_time_seconds")
        return f"Latest runtime evidence: exit_code={exit_code}, wall_time={wall_time}."
    return ""


def _extract_target_venue(*texts: str) -> str:
    for text in texts:
        match = re.search(r"(?i)\b(ICLR|NeurIPS|ICML|CVPR|ACL|AAAI|ACM|EMNLP|NAACL|ICCV|ECCV|SIGIR|KDD|CHI)\b", text)
        if match:
            return match.group(1)
    return "[Venue]"


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
