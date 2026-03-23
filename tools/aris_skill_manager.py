#!/usr/bin/env python3
"""Manage repo-local vendor skills for ARIS.

This tool stages third-party skills inside ``vendor-skills/`` and keeps them
workspace-local. ARIS no longer supports publishing vendor skills into global
skill directories as an official workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENDOR_DIR = REPO_ROOT / "vendor-skills"
DEFAULT_MANIFEST = DEFAULT_VENDOR_DIR / "INSTALLED_SKILLS.json"
VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def ensure_vendor_dir(vendor_dir: Path) -> None:
    vendor_dir.mkdir(parents=True, exist_ok=True)
    manifest = vendor_dir / "INSTALLED_SKILLS.json"
    if not manifest.exists():
        manifest.write_text("[]\n", encoding="utf-8")


def load_manifest(vendor_dir: Path) -> list[dict]:
    ensure_vendor_dir(vendor_dir)
    manifest = vendor_dir / "INSTALLED_SKILLS.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid manifest JSON: {manifest}: {exc}") from exc
    if not isinstance(data, list):
        raise SystemExit(f"Invalid manifest structure: {manifest}")
    return data


def save_manifest(vendor_dir: Path, rows: list[dict]) -> None:
    ensure_vendor_dir(vendor_dir)
    manifest = vendor_dir / "INSTALLED_SKILLS.json"
    manifest.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_frontmatter_value(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", frontmatter, re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_skill_info(skill_dir: Path) -> dict:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SystemExit(f"Not a skill directory: {skill_dir} (missing SKILL.md)")

    name = skill_dir.name
    description = "(no description)"
    content = skill_md.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(content)
    if match:
        frontmatter = match.group(1)
        maybe_name = extract_frontmatter_value(frontmatter, "name")
        maybe_description = extract_frontmatter_value(frontmatter, "description")
        if maybe_name:
            name = maybe_name
        if maybe_description:
            description = maybe_description
    if not VALID_NAME_RE.match(name):
        raise SystemExit(f"Invalid skill name in {skill_md}: {name!r}")
    return {
        "name": name,
        "description": description,
    }


def parse_github_source(source: str) -> tuple[str, str | None, str | None]:
    if "@" in source and "://" not in source:
        repo, path = source.split("@", 1)
        if "/" not in repo:
            raise SystemExit(f"Invalid GitHub shorthand: {source}")
        return repo.strip(), "main", path.strip()

    cleaned = re.sub(r"^https?://github\.com/", "", source).rstrip("/")
    match = re.match(r"^([^/]+/[^/]+)/tree/([^/]+)(?:/(.+))?$", cleaned)
    if match:
        return match.group(1), match.group(2), match.group(3)
    match = re.match(r"^([^/]+/[^/]+)$", cleaned)
    if match:
        return match.group(1), "main", None
    raise SystemExit(f"Unsupported GitHub source: {source}")


def is_github_source(source: str) -> bool:
    return "github.com" in source.lower() or ("@" in source and "/" in source.split("@", 1)[0])


def clone_repo(repo: str, ref: str | None, dest: Path) -> None:
    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [f"https://github.com/{repo}.git", str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit(f"git clone failed for {repo}: {result.stderr.strip()}")


def validate_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / "SKILL.md").is_file()


def scan_skill_dirs(root: Path) -> list[Path]:
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if validate_skill_dir(child):
            found.append(child)
            continue
        for grandchild in sorted(child.iterdir()):
            if validate_skill_dir(grandchild):
                found.append(grandchild)
    return found


def resolve_local_skill(source: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    if validate_skill_dir(source_path):
        return source_path
    if source_path.is_dir():
        found = scan_skill_dirs(source_path)
        if len(found) == 1:
            return found[0]
        if found:
            joined = ", ".join(path.name for path in found)
            raise SystemExit(f"Ambiguous local source {source_path}. Found multiple skills: {joined}")
    raise SystemExit(f"Local skill source not found or invalid: {source}")


def find_skill_by_name(root: Path, name: str) -> Path | None:
    preferred = [
        root / "skills" / name,
        root / name,
        root / "skills-codex" / name,
        root / "skills-codex-claude-review" / name,
    ]
    for candidate in preferred:
        if validate_skill_dir(candidate):
            return candidate

    matches: list[Path] = []
    for skill_md in root.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        if not validate_skill_dir(skill_dir):
            continue
        try:
            info = parse_skill_info(skill_dir)
        except SystemExit:
            continue
        if skill_dir.name == name or info["name"] == name:
            matches.append(skill_dir)

    if not matches:
        return None
    matches.sort(key=lambda item: (len(item.relative_to(root).parts), str(item.relative_to(root))))
    return matches[0]


def resolve_github_skill(source: str) -> tuple[Path, dict, Path]:
    repo, ref, path = parse_github_source(source)
    temp_root = Path(tempfile.mkdtemp(prefix="aris-skill-"))
    clone_dir = temp_root / "repo"
    clone_repo(repo, ref, clone_dir)

    candidate = clone_dir / path if path else clone_dir
    if validate_skill_dir(candidate):
        return candidate, {"repo": repo, "ref": ref, "path": path}, temp_root

    if candidate.is_dir():
        found = scan_skill_dirs(candidate)
        if len(found) == 1:
            return found[0], {"repo": repo, "ref": ref, "path": str(found[0].relative_to(clone_dir))}, temp_root
        if found:
            names = ", ".join(path.name for path in found)
            shutil.rmtree(temp_root, ignore_errors=True)
            raise SystemExit(f"Ambiguous GitHub source {source}. Found multiple skills: {names}")

    if path:
        named = find_skill_by_name(clone_dir, path)
        if named is not None:
            return named, {"repo": repo, "ref": ref, "path": str(named.relative_to(clone_dir))}, temp_root

    shutil.rmtree(temp_root, ignore_errors=True)
    raise SystemExit(f"Could not resolve a skill directory from GitHub source: {source}")


def install_skill(source: str, vendor_dir: Path) -> dict:
    ensure_vendor_dir(vendor_dir)
    cleanup_dir: Path | None = None
    if is_github_source(source):
        resolved, source_meta, cleanup_dir = resolve_github_skill(source)
        source_type = "github"
    else:
        resolved = resolve_local_skill(source)
        source_meta = {"path": str(resolved)}
        source_type = "local"

    try:
        skill_info = parse_skill_info(resolved)
        target_dir = vendor_dir / skill_info["name"]
        if target_dir.exists():
            raise SystemExit(f"Skill already installed in vendor dir: {target_dir}")
        shutil.copytree(resolved, target_dir)

        manifest = load_manifest(vendor_dir)
        row = {
            "name": skill_info["name"],
            "description": skill_info["description"],
            "installed_at": utc_now(),
            "source": source,
            "source_type": source_type,
            "source_meta": source_meta,
            "vendor_path": display_path(target_dir),
            "synced_targets": [],
        }
        manifest = [item for item in manifest if item.get("name") != skill_info["name"]]
        manifest.append(row)
        manifest.sort(key=lambda item: item.get("name", ""))
        save_manifest(vendor_dir, manifest)
        return row
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def list_skills(vendor_dir: Path) -> list[dict]:
    manifest = load_manifest(vendor_dir)
    rows_by_name = {row.get("name"): row for row in manifest}
    results: list[dict] = []
    for entry in sorted(vendor_dir.iterdir()):
        if not entry.is_dir() or not validate_skill_dir(entry):
            continue
        info = parse_skill_info(entry)
        row = rows_by_name.get(info["name"], {})
        results.append(
            {
                "name": info["name"],
                "description": info["description"],
                "vendor_path": display_path(entry),
                "source": row.get("source", ""),
                "installed_at": row.get("installed_at", ""),
                "synced_targets": row.get("synced_targets", []),
            }
        )
    return results


def get_skill_info(name: str, vendor_dir: Path) -> dict:
    for item in list_skills(vendor_dir):
        if item["name"] == name:
            return item
    raise SystemExit(f"Vendor skill not found: {name}")


def uninstall_skill(name: str, vendor_dir: Path) -> None:
    skill_dir = vendor_dir / name
    if not validate_skill_dir(skill_dir):
        raise SystemExit(f"Vendor skill not found: {name}")
    shutil.rmtree(skill_dir)
    manifest = [row for row in load_manifest(vendor_dir) if row.get("name") != name]
    save_manifest(vendor_dir, manifest)


def sync_global_removed() -> None:
    raise SystemExit(
        "sync-global has been removed. ARIS now supports only repo workspace mode. "
        "Keep vendor skills inside this repo's vendor-skills/ directory."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage repo-local vendor skills for ARIS.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_p = subparsers.add_parser("install", help="Install a skill into vendor-skills/")
    install_p.add_argument("--source", required=True, help="Local skill path or GitHub source.")
    install_p.add_argument("--vendor-dir", default=str(DEFAULT_VENDOR_DIR), help=argparse.SUPPRESS)

    list_p = subparsers.add_parser("list", help="List installed vendor skills.")
    list_p.add_argument("--vendor-dir", default=str(DEFAULT_VENDOR_DIR), help=argparse.SUPPRESS)

    info_p = subparsers.add_parser("info", help="Show detailed info for one vendor skill.")
    info_p.add_argument("--name", required=True)
    info_p.add_argument("--vendor-dir", default=str(DEFAULT_VENDOR_DIR), help=argparse.SUPPRESS)

    uninstall_p = subparsers.add_parser("uninstall", help="Remove one vendor skill.")
    uninstall_p.add_argument("--name", required=True)
    uninstall_p.add_argument("--vendor-dir", default=str(DEFAULT_VENDOR_DIR), help=argparse.SUPPRESS)

    sync_p = subparsers.add_parser(
        "sync-global",
        help="Removed. ARIS vendor skills stay repo-local.",
    )
    sync_p.add_argument("--target", default="auto", choices=["auto", "codex", "claude"], help=argparse.SUPPRESS)
    sync_p.add_argument("--name", action="append", default=[], help=argparse.SUPPRESS)
    sync_p.add_argument("--vendor-dir", default=str(DEFAULT_VENDOR_DIR), help=argparse.SUPPRESS)
    sync_p.add_argument("--global-dir", default="", help=argparse.SUPPRESS)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    vendor_dir = Path(getattr(args, "vendor_dir", str(DEFAULT_VENDOR_DIR))).expanduser().resolve()

    if args.command == "install":
        result = install_skill(args.source, vendor_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "list":
        print(json.dumps(list_skills(vendor_dir), indent=2, ensure_ascii=False))
        return 0
    if args.command == "info":
        print(json.dumps(get_skill_info(args.name, vendor_dir), indent=2, ensure_ascii=False))
        return 0
    if args.command == "uninstall":
        uninstall_skill(args.name, vendor_dir)
        print(json.dumps({"removed": args.name}, indent=2, ensure_ascii=False))
        return 0
    if args.command == "sync-global":
        sync_global_removed()

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
