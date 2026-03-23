#!/usr/bin/env python3
"""Generate repo-local Claude Code wrapper skills for ARIS entry workflows."""

from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = REPO_ROOT / "skills"
CLAUDE_ROOT = REPO_ROOT / ".claude" / "skills"

ENTRY_SKILLS = [
    "idea-discovery",
    "experiment-bridge",
    "auto-review-loop",
    "paper-writing",
    "research-pipeline",
]

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def extract_field(frontmatter: str, field: str) -> str:
    pattern = re.compile(rf"^{re.escape(field)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(frontmatter)
    if not match:
        return ""
    value = match.group(1).strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        try:
            value = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            value = value[1:-1]
    return value


def build_frontmatter(name: str, description: str, argument_hint: str) -> str:
    safe_description = description.replace('"', '\\"')
    lines = [
        "---",
        f'name: "{name}"',
        f'description: "{safe_description}"',
    ]
    if argument_hint:
        lines.append(f"argument-hint: {argument_hint}")
    lines.append("disable-model-invocation: true")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def build_body(skill_name: str) -> str:
    canonical_path = f"skills/{skill_name}/SKILL.md"
    return (
        f"# Project-local Claude entrypoint for `/{skill_name}`\n\n"
        "This wrapper exists so Claude Code can expose the main ARIS workflows as "
        "project-level slash commands when Claude is started from the ARIS repo root.\n\n"
        "## Instructions\n\n"
        f"1. Read `{canonical_path}` from this repo and treat it as the canonical implementation for `/{skill_name}`.\n"
        "2. Pass through the user-supplied arguments exactly as `$ARGUMENTS`.\n"
        "3. Stay inside this checked-out ARIS repo or fork. Use the repo-local "
        "`tools/`, `memory/`, `vendor-skills/`, `refine-logs/`, and other files "
        "referenced by the canonical skill.\n"
        "4. If the canonical skill refers to another ARIS slash command like "
        "`/paper-plan` or `/run-experiment`, resolve it by reading the matching "
        "repo-local file at `skills/<skill-name>/SKILL.md` and following that file. "
        "Do not assume a separate project-level slash wrapper exists for internal "
        "sub-skills.\n"
        "5. If this wrapper and the canonical skill ever disagree, the canonical "
        "skill wins.\n"
    )


def generate_one(skill_name: str) -> None:
    canonical_path = CANONICAL_ROOT / skill_name / "SKILL.md"
    content = canonical_path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(f"Missing frontmatter: {canonical_path}")

    frontmatter = match.group(1)
    name = extract_field(frontmatter, "name") or skill_name
    description = extract_field(frontmatter, "description") or f"Project-local entrypoint for /{skill_name}."
    argument_hint = extract_field(frontmatter, "argument-hint")

    target_dir = CLAUDE_ROOT / skill_name
    target_dir.mkdir(parents=True, exist_ok=True)
    output = build_frontmatter(name, description, argument_hint)
    output += build_body(skill_name)
    (target_dir / "SKILL.md").write_text(output, encoding="utf-8")


def main() -> None:
    CLAUDE_ROOT.mkdir(parents=True, exist_ok=True)
    for skill_name in ENTRY_SKILLS:
        generate_one(skill_name)


if __name__ == "__main__":
    main()
