#!/usr/bin/env python3
"""Resolve and manage repo-local ARIS research workspaces."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
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
WORKSPACE_MODE_PLAIN = "plain"
WORKSPACE_MODE_GIT = "git"
SOURCE_KIND_NEW = "new"
SOURCE_KIND_GIT_INIT = "git_init"
SOURCE_KIND_GIT_CLONE = "git_clone"
GIT_INIT_COMMIT_MESSAGE = "chore: initialize ARIS research workspace"
WORKSPACE_GITIGNORE = """# Local development noise
__pycache__/
*.pyc
*.pyo
.DS_Store
.venv/
.pytest_cache/
.mypy_cache/
"""


class WorkspaceError(RuntimeError):
    """Workspace resolution failed."""


@dataclass
class ResearchWorkspace:
    name: str
    slug: str
    path: Path
    repo_root: Path
    topic: str | None = None
    workspace_mode: str = WORKSPACE_MODE_PLAIN
    source_kind: str = SOURCE_KIND_NEW
    git_origin_url: str | None = None
    git_default_branch: str | None = None

    @property
    def relative_path(self) -> str:
        return str(self.path.relative_to(self.repo_root))

    @property
    def metadata_path(self) -> Path:
        return self.path / WORKSPACE_META_NAME

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "slug": self.slug,
            "path": self.relative_path,
            "workspace_mode": self.workspace_mode,
            "source_kind": self.source_kind,
        }
        if self.topic:
            payload["topic"] = self.topic
        if self.git_origin_url:
            payload["git_origin_url"] = self.git_origin_url
        if self.git_default_branch:
            payload["git_default_branch"] = self.git_default_branch
        return payload


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify_research_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "research"


def _workspace_from_slug(repo_root: Path, slug: str, *, name: str | None = None) -> ResearchWorkspace:
    path = repo_root / "research" / slug
    metadata = _read_json(path / WORKSPACE_META_NAME)
    if name is None:
        name = str(metadata.get("name") or slug)
    workspace_mode = _detect_workspace_mode(path, metadata)
    return ResearchWorkspace(
        name=name,
        slug=slug,
        path=path,
        repo_root=repo_root,
        topic=str(metadata.get("topic") or "").strip() or None,
        workspace_mode=workspace_mode,
        source_kind=str(
            metadata.get("source_kind")
            or (
                SOURCE_KIND_GIT_CLONE
                if workspace_mode == WORKSPACE_MODE_GIT
                else SOURCE_KIND_NEW
            )
        ),
        git_origin_url=str(metadata.get("git_origin_url") or "") or None,
        git_default_branch=str(metadata.get("git_default_branch") or "") or None,
    )


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


def _detect_workspace_mode(path: Path, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    if _is_git_workspace(path):
        return WORKSPACE_MODE_GIT
    return str(metadata.get("workspace_mode") or WORKSPACE_MODE_PLAIN)


def _is_git_workspace(path: Path) -> bool:
    return (path / ".git").exists()


def _normalize_match_value(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _iter_existing_workspaces(repo_root: Path) -> list[ResearchWorkspace]:
    research_root = repo_root / "research"
    if not research_root.exists():
        return []
    workspaces: list[ResearchWorkspace] = []
    for child in sorted(research_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        workspaces.append(_workspace_from_slug(repo_root, child.name))
    return workspaces


def _find_existing_workspace(repo_root: Path, query: str) -> ResearchWorkspace | None:
    normalized_query = _normalize_match_value(query)
    if not normalized_query:
        return None

    tiers: list[tuple[str, list[ResearchWorkspace]]] = []
    workspaces = _iter_existing_workspaces(repo_root)
    tiers.append(
        (
            "slug",
            [workspace for workspace in workspaces if _normalize_match_value(workspace.slug) == normalized_query],
        )
    )
    tiers.append(
        (
            "name",
            [workspace for workspace in workspaces if _normalize_match_value(workspace.name) == normalized_query],
        )
    )
    tiers.append(
        (
            "topic",
            [workspace for workspace in workspaces if _normalize_match_value(workspace.topic) == normalized_query],
        )
    )

    for label, matches in tiers:
        if not matches:
            continue
        if len(matches) == 1:
            return matches[0]
        options = ", ".join(f"research/{workspace.slug}" for workspace in matches)
        raise WorkspaceError(
            f"Multiple research workspaces match {query!r} by {label}: {options}. "
            "Use an explicit `research/<slug>` path."
        )
    return None


def _next_available_slug(repo_root: Path, base_slug: str) -> str:
    candidate = base_slug
    counter = 2
    while (repo_root / "research" / candidate).exists():
        candidate = f"{base_slug}-{counter}"
        counter += 1
    return candidate


def _run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise WorkspaceError(f"`git {' '.join(args)}` failed in {cwd}: {stderr}")
    return result.stdout.strip()


def _maybe_run_git(args: list[str], *, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _git_info(path: Path) -> dict[str, str | None]:
    if not _is_git_workspace(path):
        return {"origin_url": None, "default_branch": None}
    origin_url = _maybe_run_git(["remote", "get-url", "origin"], cwd=path)
    default_branch = _maybe_run_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd=path)
    if default_branch and "/" in default_branch:
        default_branch = default_branch.split("/", 1)[1]
    if not default_branch:
        head_branch = _maybe_run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
        if head_branch and head_branch != "HEAD":
            default_branch = head_branch
    return {
        "origin_url": origin_url,
        "default_branch": default_branch,
    }


def _workspace_name_from_repo_url(repo_url: str) -> str:
    cleaned = repo_url.rstrip("/").rsplit("/", 1)[-1]
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    return cleaned or "research"


def _is_empty_scaffold(path: Path) -> bool:
    if not path.exists():
        return True
    allowed = {WORKSPACE_META_NAME}
    for child in path.iterdir():
        if child.name in allowed and child.is_file():
            continue
        if child.name == "refine-logs" and child.is_dir() and not any(child.iterdir()):
            continue
        return False
    return True


def _remove_empty_scaffold(path: Path) -> None:
    if not path.exists():
        return
    if not _is_empty_scaffold(path):
        raise WorkspaceError(
            f"Cannot reuse {path}: the research workspace already has substantive contents."
        )
    if (path / WORKSPACE_META_NAME).exists():
        (path / WORKSPACE_META_NAME).unlink()
    refine_logs = path / "refine-logs"
    if refine_logs.exists() and refine_logs.is_dir():
        refine_logs.rmdir()
    if path.exists():
        path.rmdir()


def _workspace_readme(workspace: ResearchWorkspace) -> str:
    return (
        f"# {workspace.name}\n\n"
        "This research workspace is managed by ARIS.\n\n"
        f"- Slug: `{workspace.slug}`\n"
        "- Layout: code, reports, paper, figures, results, and refine-logs live in this directory.\n"
    )


def _refresh_workspace_metadata(
    workspace: ResearchWorkspace,
    *,
    source_kind: str | None = None,
) -> ResearchWorkspace:
    workspace.path.mkdir(parents=True, exist_ok=True)
    (workspace.path / "refine-logs").mkdir(parents=True, exist_ok=True)

    existing = _read_json(workspace.metadata_path)
    workspace_mode = _detect_workspace_mode(workspace.path, existing)
    git_info = _git_info(workspace.path) if workspace_mode == WORKSPACE_MODE_GIT else {}
    created_at = str(existing.get("created_at") or utc_now())
    resolved_source_kind = (
        source_kind
        or str(existing.get("source_kind") or "").strip()
        or (
            SOURCE_KIND_GIT_CLONE
            if workspace_mode == WORKSPACE_MODE_GIT and git_info.get("origin_url")
            else SOURCE_KIND_GIT_INIT
            if workspace_mode == WORKSPACE_MODE_GIT
            else SOURCE_KIND_NEW
        )
    )

    payload = {
        "name": workspace.name,
        "slug": workspace.slug,
        "path": workspace.relative_path,
        "topic": str(existing.get("topic") or workspace.topic or "").strip() or None,
        "workspace_mode": workspace_mode,
        "source_kind": resolved_source_kind,
        "created_at": created_at,
        "updated_at": utc_now(),
    }
    if workspace_mode == WORKSPACE_MODE_GIT:
        payload["git_origin_url"] = git_info.get("origin_url")
        payload["git_default_branch"] = git_info.get("default_branch")

    _write_json(workspace.metadata_path, payload)
    return ResearchWorkspace(
        name=workspace.name,
        slug=workspace.slug,
        path=workspace.path,
        repo_root=workspace.repo_root,
        topic=str(payload.get("topic") or "") or None,
        workspace_mode=workspace_mode,
        source_kind=resolved_source_kind,
        git_origin_url=str(payload.get("git_origin_url") or "") or None,
        git_default_branch=str(payload.get("git_default_branch") or "") or None,
    )


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
    topic: str | None = None,
) -> ResearchWorkspace:
    research_name = research_name.strip()
    if not research_name:
        raise WorkspaceError("Research name is empty.")
    topic = (topic or "").strip() or None

    if topic:
        existing_by_topic = _find_existing_workspace(repo_root, topic)
        if existing_by_topic is not None:
            existing_by_topic = _refresh_workspace_metadata(existing_by_topic)
            set_active_workspace(existing_by_topic)
            return existing_by_topic

    existing = _find_existing_workspace(repo_root, research_name)
    if existing is not None:
        if not topic or not existing.topic or _normalize_match_value(existing.topic) == _normalize_match_value(topic):
            existing = _refresh_workspace_metadata(
                ResearchWorkspace(
                    name=existing.name,
                    slug=existing.slug,
                    path=existing.path,
                    repo_root=existing.repo_root,
                    topic=existing.topic or topic,
                    workspace_mode=existing.workspace_mode,
                    source_kind=existing.source_kind,
                    git_origin_url=existing.git_origin_url,
                    git_default_branch=existing.git_default_branch,
                )
            )
            set_active_workspace(existing)
            return existing

    base_slug = slugify_research_name(research_name)
    slug = _next_available_slug(repo_root, base_slug)
    workspace = _workspace_from_slug(repo_root, slug, name=research_name)
    workspace.topic = topic
    workspace = _refresh_workspace_metadata(workspace)
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
    workspace = _refresh_workspace_metadata(workspace)
    set_active_workspace(workspace)
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
        explicit_workspace = _refresh_workspace_metadata(explicit_workspace)
        set_active_workspace(explicit_workspace)
        return explicit_workspace

    chosen_name = (research_name or "").strip() or extract_research_name_override(arguments)
    if chosen_name:
        primary = _primary_argument(arguments)
        topic = primary if primary and _normalize_match_value(primary) != _normalize_match_value(chosen_name) else None
        return ensure_workspace(repo_root=repo_root, research_name=chosen_name, topic=topic)

    if stage in MAIN_ENTRY_STAGES:
        primary = _primary_argument(arguments)
        if not primary:
            raise WorkspaceError(
                f"No research name could be derived for stage {stage!r}. "
                "Provide a main argument or use `research name:`."
            )
        existing = _find_existing_workspace(repo_root, primary)
        if existing is not None:
            existing = _refresh_workspace_metadata(existing)
            set_active_workspace(existing)
            return existing
        return ensure_workspace(repo_root=repo_root, research_name=primary, topic=primary)

    active = get_active_workspace(repo_root=repo_root)
    if active is not None:
        set_active_workspace(active)
        return active

    raise WorkspaceError(
        "No active research workspace. Start with `/research-pipeline` or `/idea-discovery`, "
        "or provide `research name:` explicitly."
    )


def git_init_workspace(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    research_name: str | None = None,
) -> ResearchWorkspace:
    workspace = (
        ensure_workspace(repo_root=repo_root, research_name=research_name)
        if research_name
        else get_active_workspace(repo_root=repo_root)
    )
    if workspace is None:
        raise WorkspaceError("No active research workspace to initialize.")

    if _is_git_workspace(workspace.path):
        workspace = _refresh_workspace_metadata(workspace)
        set_active_workspace(workspace)
        return workspace

    _run_git(["init", "-b", "main"], cwd=workspace.path)

    gitignore_path = workspace.path / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(WORKSPACE_GITIGNORE, encoding="utf-8")

    readme_path = workspace.path / "README.md"
    if not readme_path.exists():
        readme_path.write_text(_workspace_readme(workspace), encoding="utf-8")

    workspace = _refresh_workspace_metadata(workspace, source_kind=SOURCE_KIND_GIT_INIT)
    set_active_workspace(workspace)

    _run_git(["add", "."], cwd=workspace.path)
    result = subprocess.run(
        ["git", "commit", "-m", GIT_INIT_COMMIT_MESSAGE],
        cwd=str(workspace.path),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise WorkspaceError(
            f"Failed to create the initial workspace commit in {workspace.path}: {stderr}"
        )
    return workspace


def clone_repo_into_workspace(
    *,
    repo_url: str,
    research_name: str | None = None,
    ref: str | None = None,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> ResearchWorkspace:
    if not repo_url.strip():
        raise WorkspaceError("Repository URL is empty.")

    resolved_name = (research_name or "").strip() or _workspace_name_from_repo_url(repo_url)
    slug = slugify_research_name(resolved_name)
    destination = repo_root / "research" / slug

    if destination.exists():
        _remove_empty_scaffold(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    clone_cmd = ["git", "clone"]
    if ref:
        clone_cmd.extend(["--branch", ref])
    clone_cmd.extend([repo_url, str(destination)])
    result = subprocess.run(clone_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise WorkspaceError(f"Failed to clone {repo_url} into {destination}: {stderr}")

    workspace = _workspace_from_slug(repo_root, slug, name=resolved_name)
    workspace = _refresh_workspace_metadata(workspace, source_kind=SOURCE_KIND_GIT_CLONE)
    set_active_workspace(workspace)
    return workspace


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

    git_init_p = subparsers.add_parser("git-init", help="Initialize the active research workspace as a Git repo.")
    git_init_p.add_argument("--research-name")
    git_init_p.add_argument("--print-path", action="store_true")

    clone_p = subparsers.add_parser("clone-repo", help="Clone an external repo directly into research/<slug>.")
    clone_p.add_argument("--repo-url", required=True)
    clone_p.add_argument("--research-name")
    clone_p.add_argument("--ref")
    clone_p.add_argument("--print-path", action="store_true")
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

        if args.command == "git-init":
            workspace = git_init_workspace(research_name=args.research_name)
            return _emit_workspace(workspace, print_path=args.print_path)

        if args.command == "clone-repo":
            workspace = clone_repo_into_workspace(
                repo_url=args.repo_url,
                research_name=args.research_name,
                ref=args.ref,
            )
            return _emit_workspace(workspace, print_path=args.print_path)

    except WorkspaceError as exc:
        print(str(exc), file=os.sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
