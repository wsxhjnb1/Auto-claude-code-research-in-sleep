#!/usr/bin/env python3
"""Manage project-level CLAUDE.md files for ARIS research workspaces."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from aris_research_workspace import DEFAULT_REPO_ROOT, default_workspace_root


PROJECT_CLAUDE_NAME = "CLAUDE.md"
PIPELINE_STATUS_SECTION = "Pipeline Status"
SHARED_SECTIONS = (
    "Remote Server",
    "Local Environment",
    "Paper Library",
)
SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")
KEY_VALUE_RE = re.compile(r"^\s*(?:-\s*)?([A-Za-z0-9_. -]+?)\s*:\s*(.*?)\s*$")

PIPELINE_STATUS_TEMPLATE = """stage: unknown
idea: ""
contract:
current_branch:
baseline:
training_status:
active_tasks:
next:
"""

SECTION_TEMPLATES = {
    "Remote Server": """ssh_alias:
remote_workdir:
conda_env:
""",
    "Local Environment": """code_sync: rsync
wandb: false
wandb_project:
wandb_entity:
wandb_api_key:
""",
    "Paper Library": """paper_library:
""",
}


class ClaudeFileError(RuntimeError):
    """Raised when project CLAUDE.md resolution fails."""


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(DEFAULT_REPO_ROOT))
    except ValueError:
        return str(path)


def _claude_paths(workspace_root: Path) -> tuple[Path, Path]:
    workspace_root = workspace_root.resolve()
    project_path = workspace_root / PROJECT_CLAUDE_NAME
    repo_default_path = DEFAULT_REPO_ROOT / PROJECT_CLAUDE_NAME
    return project_path, repo_default_path


def _normalize_workspace_root(explicit_workspace_root: str | None) -> Path:
    return default_workspace_root(
        explicit_workspace_root=explicit_workspace_root,
        repo_root=DEFAULT_REPO_ROOT,
    )


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        match = SECTION_HEADER_RE.match(line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)

    return {
        name: "\n".join(lines).strip("\n")
        for name, lines in sections.items()
    }


def _parse_scalar_fields(section_body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in section_body.splitlines():
        match = KEY_VALUE_RE.match(line)
        if not match:
            continue
        key = _normalize_key(match.group(1))
        value = match.group(2).strip()
        if value:
            values[key] = value
    return values


def _normalize_key(key: str) -> str:
    normalized = re.sub(r"[\s-]+", "_", key.strip().casefold())
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _project_template(repo_default_sections: dict[str, str]) -> str:
    parts = [
        "# ARIS Research Project CLAUDE File",
        "",
        "This file stores project-level state and overrides for one research workspace.",
        "",
        f"## {PIPELINE_STATUS_SECTION}",
        PIPELINE_STATUS_TEMPLATE.strip(),
        "",
    ]

    for section_name in SHARED_SECTIONS:
        body = repo_default_sections.get(section_name) or SECTION_TEMPLATES[section_name]
        parts.extend([f"## {section_name}", body.strip(), ""])

    return "\n".join(parts).rstrip() + "\n"


def ensure_project_claude(
    *,
    workspace_root: Path,
) -> tuple[Path, bool]:
    project_path, repo_default_path = _claude_paths(workspace_root)
    if project_path.exists():
        return project_path, False

    project_path.parent.mkdir(parents=True, exist_ok=True)
    repo_default_sections = _parse_sections(_read_text(repo_default_path))
    project_path.write_text(
        _project_template(repo_default_sections),
        encoding="utf-8",
    )
    return project_path, True


def _resolve_sources(
    *,
    workspace_root: Path,
) -> tuple[Path, dict[str, str], Path, dict[str, str]]:
    project_path, repo_default_path = _claude_paths(workspace_root)
    project_sections = _parse_sections(_read_text(project_path))
    repo_sections = _parse_sections(_read_text(repo_default_path))
    return project_path, project_sections, repo_default_path, repo_sections


def _find_value(
    *,
    key: str,
    section: str | None,
    project_sections: dict[str, str],
    repo_sections: dict[str, str],
) -> tuple[str | None, str | None, str | None]:
    normalized_section = (section or "").strip()

    def lookup(
        sections: dict[str, str],
        *,
        scope: str,
        section_name: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        candidate_sections: list[tuple[str, str]]
        if section_name:
            if section_name not in sections:
                return None, None, None
            candidate_sections = [(section_name, sections[section_name])]
        else:
            candidate_sections = list(sections.items())

        for current_section, body in candidate_sections:
            parsed = _parse_scalar_fields(body)
            value = parsed.get(_normalize_key(key))
            if value:
                return value, scope, current_section
        return None, None, None

    if normalized_section:
        value, scope, source_section = lookup(
            project_sections,
            scope="project",
            section_name=normalized_section,
        )
        if value is not None:
            return value, scope, source_section
        if normalized_section != PIPELINE_STATUS_SECTION:
            return lookup(
                repo_sections,
                scope="repo_default",
                section_name=normalized_section,
            )
        return None, None, None

    value, scope, source_section = lookup(project_sections, scope="project")
    if value is not None:
        return value, scope, source_section
    value, scope, source_section = lookup(
        {
            name: body
            for name, body in repo_sections.items()
            if name != PIPELINE_STATUS_SECTION
        },
        scope="repo_default",
    )
    return value, scope, source_section


def status_payload(*, workspace_root: Path) -> dict[str, Any]:
    project_path, project_sections, repo_default_path, repo_sections = _resolve_sources(
        workspace_root=workspace_root
    )
    return {
        "workspace_root": _display_path(workspace_root),
        "project_claude_path": _display_path(project_path),
        "project_claude_exists": project_path.exists(),
        "repo_default_claude_path": _display_path(repo_default_path),
        "repo_default_claude_exists": repo_default_path.exists(),
        "project_sections": sorted(project_sections.keys()),
        "repo_default_sections": sorted(repo_sections.keys()),
    }


def resolve_value_payload(
    *,
    workspace_root: Path,
    key: str,
    section: str | None,
) -> dict[str, Any]:
    project_path, project_sections, repo_default_path, repo_sections = _resolve_sources(
        workspace_root=workspace_root
    )
    value, scope, source_section = _find_value(
        key=key,
        section=section,
        project_sections=project_sections,
        repo_sections=repo_sections,
    )
    source_path = None
    if scope == "project":
        source_path = _display_path(project_path)
    elif scope == "repo_default":
        source_path = _display_path(repo_default_path)

    return {
        "key": key,
        "section": section,
        "value": value,
        "source_scope": scope,
        "source_section": source_section,
        "source_path": source_path,
        "project_claude_path": _display_path(project_path),
        "repo_default_claude_path": _display_path(repo_default_path),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_p = subparsers.add_parser("ensure", help="Ensure research/<slug>/CLAUDE.md exists.")
    ensure_p.add_argument("--workspace-root")
    ensure_p.add_argument("--print-path", action="store_true")

    status_p = subparsers.add_parser("status", help="Show CLAUDE.md status for a workspace.")
    status_p.add_argument("--workspace-root")

    print_path_p = subparsers.add_parser("print-path", help="Print the canonical project CLAUDE.md path.")
    print_path_p.add_argument("--workspace-root")
    print_path_p.add_argument("--ensure", action="store_true")

    resolve_p = subparsers.add_parser("resolve-value", help="Resolve a config value with project->repo fallback.")
    resolve_p.add_argument("--workspace-root")
    resolve_p.add_argument("--key", required=True)
    resolve_p.add_argument("--section")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        workspace_root = _normalize_workspace_root(getattr(args, "workspace_root", None))
        if args.command == "ensure":
            project_path, created = ensure_project_claude(workspace_root=workspace_root)
            if args.print_path:
                print(_display_path(project_path))
            else:
                print(
                    json.dumps(
                        {
                            "workspace_root": _display_path(workspace_root),
                            "project_claude_path": _display_path(project_path),
                            "created": created,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 0

        if args.command == "status":
            print(json.dumps(status_payload(workspace_root=workspace_root), ensure_ascii=False, indent=2))
            return 0

        if args.command == "print-path":
            if args.ensure:
                project_path, _ = ensure_project_claude(workspace_root=workspace_root)
            else:
                project_path, _ = _claude_paths(workspace_root)
            print(_display_path(project_path))
            return 0

        if args.command == "resolve-value":
            print(
                json.dumps(
                    resolve_value_payload(
                        workspace_root=workspace_root,
                        key=args.key,
                        section=args.section,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

    except (ClaudeFileError, RuntimeError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
