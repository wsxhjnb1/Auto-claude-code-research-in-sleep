#!/usr/bin/env python3
"""Resolve and manage repo-local ARIS research workspaces."""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO_ROOT = Path(
    os.environ.get(
        "ARIS_RESEARCH_REPO_ROOT",
        str(Path(__file__).resolve().parents[1]),
    )
).resolve()
RESEARCH_DIR = DEFAULT_REPO_ROOT / "research"
ACTIVE_RESEARCH_PATH = RESEARCH_DIR / "ACTIVE_RESEARCH.json"
WORKSPACE_META_NAME = "WORKSPACE.json"
MAIN_ENTRY_STAGES = {
    "research-pipeline",
    "idea-discovery",
    "research-refine-pipeline",
    "research-refine",
    "experiment-plan",
}
INLINE_OVERRIDE_RE = re.compile(
    r"(?:^|--|—|,)\s*research name\s*:\s*(.+?)(?=\s*(?:--|—|,)\s*[A-Za-z][A-Za-z0-9 _-]{0,40}\s*:|$)",
    re.IGNORECASE,
)
WORKSPACE_PATH_RE = re.compile(
    r"(?P<path>(?:\./)?research/(?P<slug>[A-Za-z0-9][A-Za-z0-9._-]*)(?:/[^\s\"']*)?)"
)


class WorkspaceError(RuntimeError):
    """Workspace resolution failed."""


@dataclass
class ResearchWorkspace:
    name: str
    slug: str
    path: Path
    repo_root: Path

    @property
    def relative_path(self) -> str:
        return str(self.path.relative_to(self.repo_root))

    @property
    def metadata_path(self) -> Path:
        return self.path / WORKSPACE_META_NAME

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slug": self.slug,
            "path": self.relative_path,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify_research_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "research"


def _workspace_from_slug(repo_root: Path, slug: str, *, name: str | None = None) -> ResearchWorkspace:
    path = repo_root / "research" / slug
    if name is None:
        metadata = _read_json(path / WORKSPACE_META_NAME)
        name = str(metadata.get("name") or slug)
    return ResearchWorkspace(name=name, slug=slug, path=path, repo_root=repo_root)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_research_name_override(arguments: str) -> str | None:
    if not arguments:
        return None
    match = INLINE_OVERRIDE_RE.search(arguments)
    if not match:
        return None
    value = match.group(1).strip().strip('"').strip("'")
    return value or None


def extract_workspace_reference(arguments: str, *, repo_root: Path = DEFAULT_REPO_ROOT) -> ResearchWorkspace | None:
    if not arguments:
        return None
    match = WORKSPACE_PATH_RE.search(arguments)
    if not match:
        return None
    slug = match.group("slug")
    candidate = _workspace_from_slug(repo_root, slug)
    if candidate.path.exists():
        return candidate
    return None


def _primary_argument(arguments: str) -> str:
    text = (arguments or "").strip()
    if not text:
        return ""
    for marker in (" — ", " -- "):
        if marker in text:
            return text.split(marker, 1)[0].strip()
    return text


def ensure_workspace(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    research_name: str,
) -> ResearchWorkspace:
    research_name = research_name.strip()
    if not research_name:
        raise WorkspaceError("Research name is empty.")
    slug = slugify_research_name(research_name)
    workspace = _workspace_from_slug(repo_root, slug, name=research_name)
    workspace.path.mkdir(parents=True, exist_ok=True)
    (workspace.path / "refine-logs").mkdir(parents=True, exist_ok=True)

    metadata = _read_json(workspace.metadata_path)
    created_at = metadata.get("created_at") or utc_now()
    payload = {
        "name": research_name,
        "slug": slug,
        "path": workspace.relative_path,
        "created_at": created_at,
        "updated_at": utc_now(),
    }
    _write_json(workspace.metadata_path, payload)
    set_active_workspace(workspace)
    return workspace


def set_active_workspace(workspace: ResearchWorkspace) -> None:
    payload = workspace.to_dict()
    payload["updated_at"] = utc_now()
    _write_json(workspace.repo_root / "research" / "ACTIVE_RESEARCH.json", payload)


def get_active_workspace(*, repo_root: Path = DEFAULT_REPO_ROOT) -> ResearchWorkspace | None:
    data = _read_json(repo_root / "research" / "ACTIVE_RESEARCH.json")
    slug = str(data.get("slug") or "").strip()
    if not slug:
        return None
    workspace = _workspace_from_slug(repo_root, slug, name=str(data.get("name") or slug))
    if not workspace.path.exists():
        return None
    return workspace


def infer_workspace_from_cwd(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    cwd: Path | None = None,
) -> ResearchWorkspace | None:
    cwd = Path(cwd or Path.cwd()).resolve()
    research_root = repo_root / "research"
    try:
        relative = cwd.relative_to(research_root)
    except ValueError:
        return None
    parts = relative.parts
    if not parts:
        return None
    slug = parts[0]
    workspace = _workspace_from_slug(repo_root, slug)
    if workspace.path.exists():
        return workspace
    return None


def resolve_workspace_for_stage(
    *,
    stage: str,
    arguments: str = "",
    research_name: str | None = None,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> ResearchWorkspace:
    explicit_workspace = extract_workspace_reference(arguments, repo_root=repo_root)
    if explicit_workspace is not None:
        set_active_workspace(explicit_workspace)
        return explicit_workspace

    chosen_name = (research_name or "").strip() or extract_research_name_override(arguments)
    if chosen_name:
        return ensure_workspace(repo_root=repo_root, research_name=chosen_name)

    if stage in MAIN_ENTRY_STAGES:
        primary = _primary_argument(arguments)
        if not primary:
            raise WorkspaceError(
                f"No research name could be derived for stage {stage!r}. "
                "Provide a main argument or use `research name:`."
            )
        return ensure_workspace(repo_root=repo_root, research_name=primary)

    active = get_active_workspace(repo_root=repo_root)
    if active is not None:
        set_active_workspace(active)
        return active

    raise WorkspaceError(
        "No active research workspace. Start with `/research-pipeline` or `/idea-discovery`, "
        "or provide `research name:` explicitly."
    )


def default_workspace_root(
    *,
    explicit_workspace_root: str | None = None,
    repo_root: Path = DEFAULT_REPO_ROOT,
    cwd: Path | None = None,
) -> Path:
    cwd = Path(cwd or Path.cwd()).resolve()
    if explicit_workspace_root:
        return _normalize_workspace_root(explicit_workspace_root, repo_root=repo_root)

    env_workspace_root = os.environ.get("ARIS_RESEARCH_ROOT", "").strip()
    if env_workspace_root:
        return _normalize_workspace_root(env_workspace_root, repo_root=repo_root)

    inferred = infer_workspace_from_cwd(repo_root=repo_root, cwd=cwd)
    if inferred is not None:
        return inferred.path

    active = get_active_workspace(repo_root=repo_root)
    if active is not None:
        return active.path

    raise WorkspaceError(
        "No active research workspace. Start a research workflow first, "
        "pass a `research/...` path, or provide --workspace-root."
    )


def _normalize_workspace_root(raw: str, *, repo_root: Path = DEFAULT_REPO_ROOT) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def resolve_artifact_path(
    raw: str | Path,
    *,
    workspace_root: Path,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    normalized = path.as_posix()
    if normalized == "research" or normalized.startswith("research/"):
        return (repo_root / path).resolve()
    return (workspace_root / path).resolve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_p = subparsers.add_parser("ensure", help="Resolve, create, and activate a research workspace.")
    ensure_p.add_argument("--stage", required=True)
    ensure_p.add_argument("--arguments", default="")
    ensure_p.add_argument("--research-name")
    ensure_p.add_argument("--print-path", action="store_true")

    activate_p = subparsers.add_parser("activate", help="Activate a research workspace by name.")
    activate_p.add_argument("--research-name", required=True)
    activate_p.add_argument("--print-path", action="store_true")

    status_p = subparsers.add_parser("status", help="Show the current active research workspace.")
    status_p.add_argument("--print-path", action="store_true")
    return parser


def _emit_workspace(workspace: ResearchWorkspace, *, print_path: bool) -> int:
    if print_path:
        print(workspace.relative_path)
    else:
        print(json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.command == "ensure":
            workspace = resolve_workspace_for_stage(
                stage=args.stage,
                arguments=args.arguments,
                research_name=args.research_name,
            )
            return _emit_workspace(workspace, print_path=args.print_path)

        if args.command == "activate":
            workspace = ensure_workspace(research_name=args.research_name)
            return _emit_workspace(workspace, print_path=args.print_path)

        if args.command == "status":
            workspace = get_active_workspace()
            if workspace is None:
                raise WorkspaceError("No active research workspace.")
            return _emit_workspace(workspace, print_path=args.print_path)

    except WorkspaceError as exc:
        print(str(exc), file=os.sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
