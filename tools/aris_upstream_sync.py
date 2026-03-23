#!/usr/bin/env python3
"""Synchronize this fork against upstream/main and keep a single main branch."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO_ROOT = Path(
    os.environ.get(
        "ARIS_SYNC_REPO_ROOT",
        str(Path(__file__).resolve().parents[1]),
    )
).resolve()
STATE_PATH = DEFAULT_REPO_ROOT / "refine-logs" / "UPSTREAM_SYNC_STATE.json"
LOG_PATH = DEFAULT_REPO_ROOT / "refine-logs" / "UPSTREAM_SYNC_LOG.md"

SYNC_LOCAL_REMOTE = os.environ.get("SYNC_LOCAL_REMOTE", "origin").strip() or "origin"
SYNC_REMOTE = os.environ.get("SYNC_REMOTE", "upstream").strip() or "upstream"
SYNC_BRANCH = os.environ.get("SYNC_BRANCH", "main").strip() or "main"
SYNC_TARGET_BRANCH = os.environ.get("SYNC_TARGET_BRANCH", "main").strip() or "main"
SYNC_ON_ENTRY = os.environ.get("SYNC_ON_ENTRY", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
SYNC_PUSH = os.environ.get("SYNC_PUSH", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
SYNC_BRANCH_MODE = os.environ.get("SYNC_BRANCH_MODE", "main_only").strip() or "main_only"

RESOLVER_BIN = os.environ.get("ARIS_SYNC_RESOLVER_BIN", "").strip()
RESOLVER_MODEL = os.environ.get("ARIS_SYNC_RESOLVER_MODEL", "").strip()
RESOLVER_TIMEOUT_SEC = int(os.environ.get("ARIS_SYNC_RESOLVER_TIMEOUT_SEC", "600"))

EXIT_OK = 0
EXIT_DIRTY = 10
EXIT_FETCH_FAILED = 11
EXIT_CONFLICT_FAILED = 12
EXIT_VALIDATION_FAILED = 13
EXIT_PUSH_FAILED = 14
EXIT_MIGRATION_BLOCKED = 15
EXIT_ORIGIN_BLOCKED = 16

CONFLICT_REPORT_PATH = DEFAULT_REPO_ROOT / "refine-logs" / "UPSTREAM_SYNC_CONFLICT_REPORT.md"
CLAUDE_JSON_RE = re.compile(r"\{[\s\S]*\}\s*$")


class SyncError(RuntimeError):
    """Base class for sync failures."""


class GitCommandError(SyncError):
    """git command failed."""


class ConflictResolutionError(SyncError):
    """AI conflict resolution failed."""


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_state_dir(repo_root: Path) -> None:
    (repo_root / "refine-logs").mkdir(parents=True, exist_ok=True)


def load_state(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "refine-logs" / "UPSTREAM_SYNC_STATE.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(repo_root: Path, state: dict[str, Any]) -> None:
    ensure_state_dir(repo_root)
    path = repo_root / "refine-logs" / "UPSTREAM_SYNC_STATE.json"
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_log(repo_root: Path, title: str, lines: list[str]) -> None:
    ensure_state_dir(repo_root)
    path = repo_root / "refine-logs" / "UPSTREAM_SYNC_LOG.md"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"## {utc_now()} — {title}\n\n")
        for line in lines:
            fh.write(f"- {line}\n")
        fh.write("\n")


def run_command(
    cmd: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    timeout: int | None = None,
    check: bool = False,
) -> CommandResult:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    result = CommandResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if check and result.code != 0:
        joined = " ".join(cmd)
        raise GitCommandError(
            f"Command failed ({joined}): {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def git(repo_root: Path, *args: str, check: bool = False) -> CommandResult:
    return run_command(["git", *args], cwd=repo_root, check=check)


def git_stdout(repo_root: Path, *args: str, default: str = "") -> str:
    result = git(repo_root, *args)
    if result.code != 0:
        return default
    return result.stdout.strip()


def current_branch(repo_root: Path) -> str:
    return git_stdout(repo_root, "branch", "--show-current")


def tracked_dirty_entries(repo_root: Path) -> list[str]:
    out = git_stdout(repo_root, "status", "--porcelain", "--untracked-files=no")
    return [line.rstrip() for line in out.splitlines() if line.strip()]


def rev_parse(repo_root: Path, ref: str) -> str:
    result = git(repo_root, "rev-parse", ref)
    if result.code != 0:
        raise GitCommandError(f"Could not resolve ref {ref}: {result.stderr.strip()}")
    return result.stdout.strip()


def ref_exists(repo_root: Path, ref: str) -> bool:
    return git(repo_root, "rev-parse", "--verify", ref).code == 0


def ensure_branch_exists(repo_root: Path, branch: str) -> None:
    if ref_exists(repo_root, branch):
        return
    remote_ref = f"origin/{branch}"
    if ref_exists(repo_root, remote_ref):
        git(repo_root, "branch", branch, remote_ref, check=True)
        return
    raise GitCommandError(f"Branch {branch!r} does not exist locally or at origin/{branch}.")


def create_backup_ref(repo_root: Path, name: str, ref: str = "HEAD") -> str:
    backup_ref = f"refs/aris/backups/{name}"
    commit = rev_parse(repo_root, ref)
    git(repo_root, "update-ref", backup_ref, commit, check=True)
    return backup_ref


def create_backup_tag(repo_root: Path, name: str, ref: str = "HEAD") -> None:
    git(repo_root, "tag", "-f", name, ref, check=True)


def merge_base_is_ancestor(repo_root: Path, older: str, newer: str) -> bool:
    return git(repo_root, "merge-base", "--is-ancestor", older, newer).code == 0


def list_conflicted_files(repo_root: Path) -> list[str]:
    result = git(repo_root, "diff", "--name-only", "--diff-filter=U")
    if result.code != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def remote_branch_ref(remote: str, branch: str) -> str:
    return f"{remote}/{branch}"


def fetch_remote_branch(repo_root: Path, remote: str, branch: str) -> CommandResult:
    return git(repo_root, "fetch", remote, branch)


def checkout_branch(repo_root: Path, branch: str) -> None:
    git(repo_root, "checkout", branch, check=True)


def push_branch(repo_root: Path, remote: str, branch: str) -> None:
    git(repo_root, "push", remote, branch, check=True)


def delete_branch(repo_root: Path, branch: str) -> None:
    if ref_exists(repo_root, branch):
        git(repo_root, "branch", "-D", branch, check=True)


def delete_remote_branch(repo_root: Path, remote: str, branch: str) -> None:
    result = git(repo_root, "push", remote, "--delete", branch)
    if result.code != 0 and "remote ref does not exist" not in result.stderr.lower():
        raise GitCommandError(result.stderr.strip() or f"Could not delete {remote}/{branch}")


def companion_context(repo_root: Path, relative_path: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if relative_path == "README.md":
        mate = repo_root / "README_CN.md"
        if mate.exists():
            pairs.append(("README_CN.md", mate.read_text(encoding="utf-8")))
    elif relative_path == "README_CN.md":
        mate = repo_root / "README.md"
        if mate.exists():
            pairs.append(("README.md", mate.read_text(encoding="utf-8")))
    return pairs


def decode_stage_blob(repo_root: Path, stage: int, path: str) -> str:
    result = git(repo_root, "show", f":{stage}:{path}")
    if result.code != 0:
        raise ConflictResolutionError(f"Could not read merge stage {stage} for {path}")
    return result.stdout


def choose_resolver_bin() -> str:
    if RESOLVER_BIN:
        return RESOLVER_BIN
    for candidate in ("claude",):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise ConflictResolutionError("No supported AI resolver CLI found. Expected `claude`.")


def run_resolver_prompt(prompt: str) -> str:
    resolver = choose_resolver_bin()
    cmd = [resolver, "-p", prompt, "--output-format", "json", "--tools", ""]
    if RESOLVER_MODEL:
        cmd.extend(["--model", RESOLVER_MODEL])
    result = run_command(cmd, cwd=DEFAULT_REPO_ROOT, timeout=RESOLVER_TIMEOUT_SEC)
    if result.code != 0:
        raise ConflictResolutionError(result.stderr.strip() or "AI resolver command failed.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConflictResolutionError(
            f"AI resolver did not return valid JSON wrapper: {result.stdout[:400]}"
        ) from exc
    response = str(payload.get("result", "")).strip()
    if not response:
        raise ConflictResolutionError("AI resolver returned an empty result.")
    return response


def parse_merged_content(response: str) -> tuple[str, str]:
    text = response.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = CLAUDE_JSON_RE.search(text)
        if not match:
            raise ConflictResolutionError("AI resolver did not return the expected JSON payload.")
        payload = json.loads(match.group(0))
    merged_b64 = payload.get("merged_content_b64", "")
    summary = str(payload.get("summary", "")).strip()
    if not merged_b64:
        raise ConflictResolutionError("AI resolver payload is missing merged_content_b64.")
    try:
        merged = base64.b64decode(merged_b64.encode("utf-8")).decode("utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        raise ConflictResolutionError("Could not decode merged_content_b64 from AI output.") from exc
    return merged, summary


def build_conflict_prompt(
    *,
    path: str,
    base: str,
    ours: str,
    theirs: str,
    repo_root: Path,
) -> str:
    companion_blocks = []
    for companion_path, content in companion_context(repo_root, path):
        companion_blocks.append(
            f"<COMPANION path=\"{companion_path}\">\n{content}\n</COMPANION>"
        )
    companion_text = "\n\n".join(companion_blocks)
    return f"""You are resolving a git merge conflict for one file in a customized ARIS fork.

Return ONLY a JSON object with this schema:
{{
  "merged_content_b64": "<base64-encoded UTF-8 full file content>",
  "summary": "<one-line explanation>"
}}

Hard rules:
- Output the full final file content, not a diff.
- Do not include markdown fences or commentary outside the JSON object.
- Preserve local ARIS customizations unless upstream provides a clear compatibility or bug-fix improvement.
- If upstream changed an interface, adapt the local customization to the new interface instead of dropping one side.
- Keep English/Chinese paired docs semantically aligned when relevant.
- Do not leave conflict markers.

Repository root: {repo_root}
File path: {path}

{companion_text}

<BASE>
{base}
</BASE>

<OURS>
{ours}
</OURS>

<THEIRS>
{theirs}
</THEIRS>
"""


def classify_ref_relation(repo_root: Path, local_ref: str, other_ref: str) -> dict[str, str | None]:
    local_head: str | None = None
    other_head: str | None = None
    try:
        local_head = rev_parse(repo_root, local_ref)
    except GitCommandError:
        return {
            "status": "missing_local",
            "local_head": None,
            "other_head": None,
        }
    try:
        other_head = rev_parse(repo_root, other_ref)
    except GitCommandError:
        return {
            "status": "missing_remote",
            "local_head": local_head,
            "other_head": None,
        }
    if local_head == other_head:
        status = "up_to_date"
    elif merge_base_is_ancestor(repo_root, local_ref, other_ref):
        status = "behind"
    elif merge_base_is_ancestor(repo_root, other_ref, local_ref):
        status = "ahead_local"
    else:
        status = "diverged"
    return {
        "status": status,
        "local_head": local_head,
        "other_head": other_head,
    }


def resolve_overlay_conflict(repo_root: Path, path: str) -> str:
    git(repo_root, "checkout", "--ours", "--", path, check=True)
    git(repo_root, "add", "--", path, check=True)
    return "Kept local overlay version; generator will reconcile it after the merge."


def resolve_conflict_file(repo_root: Path, path: str) -> str:
    if path.startswith("skills/skills-codex-claude-review/"):
        return resolve_overlay_conflict(repo_root, path)
    base = decode_stage_blob(repo_root, 1, path)
    ours = decode_stage_blob(repo_root, 2, path)
    theirs = decode_stage_blob(repo_root, 3, path)
    prompt = build_conflict_prompt(
        path=path,
        base=base,
        ours=ours,
        theirs=theirs,
        repo_root=repo_root,
    )
    response = run_resolver_prompt(prompt)
    merged, summary = parse_merged_content(response)
    target = repo_root / path
    target.write_text(merged, encoding="utf-8")
    git(repo_root, "add", "--", path, check=True)
    return summary or "Resolved with AI merge."


def write_conflict_report(
    repo_root: Path,
    *,
    conflicted_files: list[str],
    resolutions: dict[str, str],
    failure: str,
) -> None:
    ensure_state_dir(repo_root)
    path = repo_root / "refine-logs" / "UPSTREAM_SYNC_CONFLICT_REPORT.md"
    lines = [
        "# Upstream Sync Conflict Report",
        "",
        f"Generated at: {utc_now()}",
        "",
        f"Failure: {failure}",
        "",
        "## Files",
    ]
    for file_path in conflicted_files:
        lines.append(f"- `{file_path}` — {resolutions.get(file_path, 'unresolved')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_repo(repo_root: Path) -> None:
    compile_cmd = [
        "python3",
        "-c",
        (
            "import pathlib, py_compile; "
            "paths = sorted(p for root in ['tools','mcp-servers','third_party'] "
            "for p in pathlib.Path(root).rglob('*.py')); "
            "[py_compile.compile(str(p), doraise=True) for p in paths]"
        ),
    ]
    run_command(compile_cmd, cwd=repo_root, check=True)
    git(repo_root, "diff", "--check", check=True)
    run_command(["python3", "tools/generate_codex_claude_review_overrides.py"], cwd=repo_root, check=True)
    run_command(["python3", "tools/aris_skill_manager.py", "--help"], cwd=repo_root, check=True)
    run_command(["python3", "tools/ensure_paper_runtime.py", "--help"], cwd=repo_root, check=True)


def sync_status(repo_root: Path, *, fetch: bool = True) -> dict[str, Any]:
    ensure_state_dir(repo_root)
    state = load_state(repo_root)
    result: dict[str, Any] = {
        "generated_at": utc_now(),
        "repo_root": str(repo_root),
        "local_remote": SYNC_LOCAL_REMOTE,
        "sync_remote": SYNC_REMOTE,
        "sync_branch": SYNC_BRANCH,
        "sync_target_branch": SYNC_TARGET_BRANCH,
        "sync_on_entry": SYNC_ON_ENTRY,
        "sync_push": SYNC_PUSH,
        "sync_branch_mode": SYNC_BRANCH_MODE,
        "current_branch": current_branch(repo_root),
        "dirty_tracked_entries": tracked_dirty_entries(repo_root),
        "last_sync_state": state,
    }
    local_remote_ref = remote_branch_ref(SYNC_LOCAL_REMOTE, SYNC_TARGET_BRANCH)
    upstream_remote_ref = remote_branch_ref(SYNC_REMOTE, SYNC_BRANCH)
    if fetch:
        origin_fetch = fetch_remote_branch(repo_root, SYNC_LOCAL_REMOTE, SYNC_TARGET_BRANCH)
        upstream_fetch = fetch_remote_branch(repo_root, SYNC_REMOTE, SYNC_BRANCH)
        result["origin_fetch_code"] = origin_fetch.code
        result["origin_fetch_stderr"] = origin_fetch.stderr.strip()
        result["upstream_fetch_code"] = upstream_fetch.code
        result["upstream_fetch_stderr"] = upstream_fetch.stderr.strip()
    try:
        result["target_head"] = rev_parse(repo_root, SYNC_TARGET_BRANCH)
    except GitCommandError:
        result["target_head"] = None
    try:
        result["origin_head"] = rev_parse(repo_root, local_remote_ref)
    except GitCommandError:
        result["origin_head"] = None
    try:
        result["upstream_head"] = rev_parse(repo_root, upstream_remote_ref)
    except GitCommandError:
        result["upstream_head"] = None
    origin_status = "fetch_failed" if fetch and result.get("origin_fetch_code") not in (None, 0) else None
    upstream_status = "fetch_failed" if fetch and result.get("upstream_fetch_code") not in (None, 0) else None
    if origin_status is None:
        origin_relation = classify_ref_relation(repo_root, SYNC_TARGET_BRANCH, local_remote_ref)
        origin_status = str(origin_relation["status"])
        result["origin_relation"] = origin_status
        result["origin_sync_action"] = {
            "up_to_date": "none",
            "behind": f"would_fast_forward_to_{local_remote_ref}",
            "ahead_local": f"would_keep_local_{SYNC_TARGET_BRANCH}",
            "diverged": "would_block_on_origin_divergence",
            "missing_remote": f"missing_{local_remote_ref}",
            "missing_local": f"missing_local_{SYNC_TARGET_BRANCH}",
        }.get(origin_status, "unknown")
    else:
        result["origin_sync_action"] = "fetch_failed"
    if upstream_status is None:
        upstream_relation = classify_ref_relation(repo_root, SYNC_TARGET_BRANCH, upstream_remote_ref)
        upstream_status = str(upstream_relation["status"])
        result["upstream_relation"] = upstream_status
        result["upstream_sync_action"] = {
            "up_to_date": "none",
            "behind": f"would_merge_{upstream_remote_ref}",
            "ahead_local": f"already_contains_{upstream_remote_ref}",
            "diverged": f"would_merge_{upstream_remote_ref}",
            "missing_remote": f"missing_{upstream_remote_ref}",
            "missing_local": f"missing_local_{SYNC_TARGET_BRANCH}",
        }.get(upstream_status, "unknown")
    else:
        result["upstream_sync_action"] = "fetch_failed"
    result["origin_sync_status"] = origin_status
    result["upstream_sync_status"] = upstream_status
    return result


def rollback_to_backup(repo_root: Path, backup_ref: str) -> None:
    git(repo_root, "reset", "--hard", backup_ref, check=True)


def perform_sync(repo_root: Path) -> int:
    ensure_state_dir(repo_root)
    tracked_dirty = tracked_dirty_entries(repo_root)
    state = load_state(repo_root)
    local_remote_ref = remote_branch_ref(SYNC_LOCAL_REMOTE, SYNC_TARGET_BRANCH)
    upstream_ref = remote_branch_ref(SYNC_REMOTE, SYNC_BRANCH)
    if tracked_dirty:
        state.update(
            {
                "generated_at": utc_now(),
                "status": "dirty_blocked",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "dirty_tracked_entries": tracked_dirty,
                "origin_sync_status": "skipped_due_to_dirty",
                "upstream_sync_status": "skipped_due_to_dirty",
            }
        )
        save_state(repo_root, state)
        append_log(
            repo_root,
            "Sync blocked by tracked worktree changes",
            tracked_dirty,
        )
        return EXIT_DIRTY

    origin_fetch = fetch_remote_branch(repo_root, SYNC_LOCAL_REMOTE, SYNC_TARGET_BRANCH)
    upstream_fetch = fetch_remote_branch(repo_root, SYNC_REMOTE, SYNC_BRANCH)
    if origin_fetch.code != 0:
        state.update(
            {
                "generated_at": utc_now(),
                "status": "fetch_failed",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_sync_status": "fetch_failed",
                "origin_sync_action": "fetch_failed",
                "upstream_sync_status": "skipped_due_to_origin_block",
                "fetch_error": origin_fetch.stderr.strip() or origin_fetch.stdout.strip(),
            }
        )
        save_state(repo_root, state)
        append_log(
            repo_root,
            "Origin fetch failed",
            [state["fetch_error"] or "unknown fetch error"],
        )
        return EXIT_FETCH_FAILED
    ensure_branch_exists(repo_root, SYNC_TARGET_BRANCH)
    if upstream_fetch.code != 0:
        origin_relation = classify_ref_relation(repo_root, SYNC_TARGET_BRANCH, local_remote_ref)
        origin_status = str(origin_relation["status"])
        state.update(
            {
                "generated_at": utc_now(),
                "status": "fetch_failed",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_head": origin_relation["other_head"],
                "origin_sync_status": origin_status,
                "origin_sync_action": {
                    "up_to_date": "none",
                    "behind": f"would_fast_forward_to_{local_remote_ref}",
                    "ahead_local": f"kept_local_{SYNC_TARGET_BRANCH}",
                    "diverged": "blocked_on_origin_divergence",
                    "missing_remote": f"missing_{local_remote_ref}",
                    "missing_local": f"missing_local_{SYNC_TARGET_BRANCH}",
                }.get(origin_status, "unknown"),
                "upstream_sync_status": "fetch_failed",
                "upstream_sync_action": "fetch_failed",
                "fetch_error": upstream_fetch.stderr.strip() or upstream_fetch.stdout.strip(),
            }
        )
        save_state(repo_root, state)
        append_log(
            repo_root,
            "Upstream fetch failed",
            [state["fetch_error"] or "unknown fetch error"],
        )
        return EXIT_FETCH_FAILED
    if current_branch(repo_root) != SYNC_TARGET_BRANCH:
        checkout_branch(repo_root, SYNC_TARGET_BRANCH)

    origin_relation = classify_ref_relation(repo_root, SYNC_TARGET_BRANCH, local_remote_ref)
    origin_head = str(origin_relation["other_head"] or "")
    upstream_head = rev_parse(repo_root, upstream_ref)
    backup_ref: str | None = None
    merge_commit: str | None = None
    ai_used = False
    resolutions: dict[str, str] = {}
    origin_sync_status = "up_to_date"
    origin_sync_action = "none"
    upstream_sync_status = "up_to_date"
    upstream_sync_action = "none"

    def ensure_backup() -> str:
        nonlocal backup_ref
        if backup_ref is None:
            backup_name = f"pre-sync-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            backup_ref = create_backup_ref(repo_root, backup_name)
        return backup_ref

    if origin_relation["status"] == "missing_remote":
        state.update(
            {
                "generated_at": utc_now(),
                "status": "fetch_failed",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_head": None,
                "origin_sync_status": "fetch_failed",
                "origin_sync_action": f"missing_{local_remote_ref}",
                "upstream_head": upstream_head,
                "upstream_sync_status": "skipped_due_to_origin_block",
                "upstream_sync_action": "skipped_due_to_origin_block",
                "error": f"Missing {local_remote_ref}.",
            }
        )
        save_state(repo_root, state)
        append_log(repo_root, "Origin sync failed", [f"Missing `{local_remote_ref}`."])
        return EXIT_FETCH_FAILED
    if origin_relation["status"] == "diverged":
        state.update(
            {
                "generated_at": utc_now(),
                "status": "origin_diverged_blocked",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_head": origin_head,
                "origin_sync_status": "diverged_blocked",
                "origin_sync_action": "blocked_on_origin_divergence",
                "upstream_head": upstream_head,
                "upstream_sync_status": "skipped_due_to_origin_block",
                "upstream_sync_action": "skipped_due_to_origin_block",
                "last_checked_at": utc_now(),
            }
        )
        save_state(repo_root, state)
        append_log(
            repo_root,
            "Origin sync blocked",
            [
                f"`{SYNC_TARGET_BRANCH}` diverged from `{local_remote_ref}`.",
                "Resolve the divergence manually, then rerun sync.",
            ],
        )
        return EXIT_ORIGIN_BLOCKED

    try:
        if origin_relation["status"] == "behind":
            ensure_backup()
            git(repo_root, "merge", "--ff-only", local_remote_ref, check=True)
            origin_sync_status = "fast_forwarded"
            origin_sync_action = f"fast_forwarded_to_{local_remote_ref}"
        elif origin_relation["status"] == "ahead_local":
            origin_sync_status = "ahead_local"
            origin_sync_action = f"kept_local_{SYNC_TARGET_BRANCH}"

        upstream_relation = classify_ref_relation(repo_root, SYNC_TARGET_BRANCH, upstream_ref)
        if upstream_relation["status"] == "missing_remote":
            raise GitCommandError(f"Missing {upstream_ref}.")

        if upstream_relation["status"] not in {"up_to_date", "ahead_local"}:
            ensure_backup()
            merge_result = git(
                repo_root,
                "merge",
                "--no-ff",
                upstream_ref,
                "-m",
                f"chore(sync): merge {upstream_ref} into {SYNC_TARGET_BRANCH}",
            )
            if merge_result.code != 0:
                conflicted = list_conflicted_files(repo_root)
                if not conflicted:
                    raise GitCommandError(merge_result.stderr.strip() or "git merge failed without conflict list.")
                ai_used = True
                for file_path in conflicted:
                    resolutions[file_path] = resolve_conflict_file(repo_root, file_path)
                if list_conflicted_files(repo_root):
                    raise ConflictResolutionError("Some conflicts remain unresolved after AI merge.")
                commit_result = git(
                    repo_root,
                    "commit",
                    "-m",
                    f"chore(sync): merge {upstream_ref} into {SYNC_TARGET_BRANCH}",
                )
                if commit_result.code != 0:
                    raise GitCommandError(commit_result.stderr.strip() or "git commit failed after AI resolution.")
                upstream_sync_status = "conflict_resolved"
                upstream_sync_action = f"merged_{upstream_ref}_with_ai"
            else:
                upstream_sync_status = "merged"
                upstream_sync_action = f"merged_{upstream_ref}"

        final_head = rev_parse(repo_root, "HEAD")
        need_validation = (
            origin_sync_status == "fast_forwarded"
            or upstream_sync_status in {"merged", "conflict_resolved"}
            or (origin_sync_status == "ahead_local" and SYNC_PUSH and final_head != origin_head)
        )
        if need_validation:
            validate_repo(repo_root)
            merge_commit = rev_parse(repo_root, "HEAD")
        else:
            merge_commit = final_head

        push_result = "disabled" if SYNC_PUSH else "disabled"
        need_push = SYNC_PUSH and final_head != origin_head
        if need_push:
            push_cmd = git(repo_root, "push", SYNC_LOCAL_REMOTE, SYNC_TARGET_BRANCH)
            if push_cmd.code != 0:
                if backup_ref is not None:
                    create_backup_ref(
                        repo_root,
                        f"push-failed-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                        "HEAD",
                    )
                raise GitCommandError(push_cmd.stderr.strip() or "git push failed.")
            push_result = "success"
        elif not SYNC_PUSH:
            push_result = "disabled"
        else:
            push_result = "not_needed"

        overall_status = "up_to_date"
        if origin_sync_status != "up_to_date" or upstream_sync_status != "up_to_date":
            overall_status = "synced"
        state.update(
            {
                "generated_at": utc_now(),
                "status": overall_status,
                "local_remote": SYNC_LOCAL_REMOTE,
                "last_checked_at": utc_now(),
                "last_upstream_commit": upstream_head,
                "last_merge_commit": merge_commit,
                "ai_conflict_resolution": ai_used,
                "push_result": push_result,
                "backup_ref": backup_ref,
                "current_branch": current_branch(repo_root),
                "origin_head": origin_head,
                "origin_sync_status": origin_sync_status,
                "origin_sync_action": origin_sync_action,
                "upstream_head": upstream_head,
                "upstream_sync_status": upstream_sync_status,
                "upstream_sync_action": upstream_sync_action,
            }
        )
        save_state(repo_root, state)
        append_log(
            repo_root,
            "Repository sync completed",
            [
                f"origin phase: {origin_sync_status} ({origin_sync_action})",
                f"upstream phase: {upstream_sync_status} ({upstream_sync_action})",
                f"backup ref: `{backup_ref}`" if backup_ref else "backup ref: not needed",
                f"resulting head: `{merge_commit}`",
                f"push result: {push_result}",
            ]
            + ([f"{path}: {summary}" for path, summary in sorted(resolutions.items())] if ai_used else []),
        )
        return EXIT_OK
    except Exception as exc:
        write_conflict_report(
            repo_root,
            conflicted_files=list_conflicted_files(repo_root),
            resolutions=resolutions,
            failure=str(exc),
        )
        try:
            git(repo_root, "merge", "--abort")
            if backup_ref is not None:
                rollback_to_backup(repo_root, backup_ref)
        except Exception:
            pass
        state.update(
            {
                "generated_at": utc_now(),
                "status": "sync_failed",
                "local_remote": SYNC_LOCAL_REMOTE,
                "last_checked_at": utc_now(),
                "last_upstream_commit": upstream_head,
                "ai_conflict_resolution": ai_used,
                "push_result": "failed" if merge_commit is not None else "not_reached",
                "backup_ref": backup_ref,
                "current_branch": current_branch(repo_root),
                "origin_head": origin_head or None,
                "origin_sync_status": origin_sync_status,
                "origin_sync_action": origin_sync_action,
                "upstream_head": upstream_head,
                "upstream_sync_status": "failed",
                "upstream_sync_action": upstream_sync_action,
                "error": str(exc),
            }
        )
        save_state(repo_root, state)
        append_log(
            repo_root,
            "Repository sync failed",
            [
                f"error: {exc}",
                f"origin phase: {origin_sync_status} ({origin_sync_action})",
                f"upstream phase: failed ({upstream_sync_action})",
                f"backup ref: `{backup_ref}`" if backup_ref else "backup ref: not created",
                f"conflict report: `{CONFLICT_REPORT_PATH.relative_to(repo_root)}`",
            ],
        )
        if isinstance(exc, ConflictResolutionError):
            return EXIT_CONFLICT_FAILED
        if "push failed" in str(exc).lower():
            return EXIT_PUSH_FAILED
        return EXIT_VALIDATION_FAILED


def perform_migration(repo_root: Path) -> int:
    ensure_state_dir(repo_root)
    tracked_dirty = tracked_dirty_entries(repo_root)
    local_remote_ref = remote_branch_ref(SYNC_LOCAL_REMOTE, "main")
    upstream_ref = remote_branch_ref(SYNC_REMOTE, SYNC_BRANCH)
    if tracked_dirty:
        save_state(
            repo_root,
            {
                "generated_at": utc_now(),
                "status": "migration_blocked_dirty",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "dirty_tracked_entries": tracked_dirty,
            },
        )
        append_log(repo_root, "Main migration blocked by tracked worktree changes", tracked_dirty)
        return EXIT_MIGRATION_BLOCKED

    origin_fetch = fetch_remote_branch(repo_root, SYNC_LOCAL_REMOTE, "main")
    upstream_fetch = fetch_remote_branch(repo_root, SYNC_REMOTE, SYNC_BRANCH)
    if origin_fetch.code != 0:
        save_state(
            repo_root,
            {
                "generated_at": utc_now(),
                "status": "migration_fetch_failed",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_sync_status": "fetch_failed",
                "origin_sync_action": "fetch_failed",
                "fetch_error": origin_fetch.stderr.strip() or origin_fetch.stdout.strip(),
            },
        )
        append_log(repo_root, "Main migration blocked", ["Could not fetch origin/main."])
        return EXIT_FETCH_FAILED
    if upstream_fetch.code != 0:
        save_state(
            repo_root,
            {
                "generated_at": utc_now(),
                "status": "migration_fetch_failed",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "upstream_sync_status": "fetch_failed",
                "upstream_sync_action": "fetch_failed",
                "fetch_error": upstream_fetch.stderr.strip() or upstream_fetch.stdout.strip(),
            },
        )
        append_log(repo_root, "Main migration blocked", ["Could not fetch upstream/main."])
        return EXIT_FETCH_FAILED

    ensure_branch_exists(repo_root, "main")
    current = current_branch(repo_root)
    if current != "main":
        checkout_branch(repo_root, "main")
    origin_relation = classify_ref_relation(repo_root, "main", local_remote_ref)
    origin_head = str(origin_relation["other_head"] or "")
    upstream_head = rev_parse(repo_root, upstream_ref)
    if origin_relation["status"] == "missing_remote":
        save_state(
            repo_root,
            {
                "generated_at": utc_now(),
                "status": "migration_fetch_failed",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_sync_status": "fetch_failed",
                "origin_sync_action": f"missing_{local_remote_ref}",
                "error": f"Missing {local_remote_ref}.",
            },
        )
        append_log(repo_root, "Main migration blocked", [f"Missing `{local_remote_ref}`."])
        return EXIT_FETCH_FAILED
    if origin_relation["status"] == "diverged":
        save_state(
            repo_root,
            {
                "generated_at": utc_now(),
                "status": "migration_origin_diverged_blocked",
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_head": origin_head,
                "origin_sync_status": "diverged_blocked",
                "origin_sync_action": "blocked_on_origin_divergence",
                "upstream_head": upstream_head,
            },
        )
        append_log(
            repo_root,
            "Main migration blocked",
            [f"`main` diverged from `{local_remote_ref}`. Resolve that first."],
        )
        return EXIT_ORIGIN_BLOCKED

    backup_ref: str | None = None
    origin_sync_status = "up_to_date"
    origin_sync_action = "none"

    def ensure_backup() -> str:
        nonlocal backup_ref
        if backup_ref is None:
            backup_ref = create_backup_ref(repo_root, "pre-main-migration", "HEAD")
        return backup_ref

    try:
        if origin_relation["status"] == "behind":
            ensure_backup()
            git(repo_root, "merge", "--ff-only", local_remote_ref, check=True)
            origin_sync_status = "fast_forwarded"
            origin_sync_action = f"fast_forwarded_to_{local_remote_ref}"
        elif origin_relation["status"] == "ahead_local":
            origin_sync_status = "ahead_local"
            origin_sync_action = "kept_local_main"

        if not ref_exists(repo_root, "update"):
            final_head = rev_parse(repo_root, "main")
            need_push = SYNC_PUSH and final_head != origin_head
            if origin_sync_status == "fast_forwarded" or need_push:
                validate_repo(repo_root)
            push_result = "disabled" if not SYNC_PUSH else "not_needed"
            if need_push:
                push_branch(repo_root, SYNC_LOCAL_REMOTE, "main")
                push_result = "success"
            save_state(
                repo_root,
                {
                    "generated_at": utc_now(),
                    "status": "migration_not_needed",
                    "local_remote": SYNC_LOCAL_REMOTE,
                    "current_branch": current_branch(repo_root),
                    "origin_head": origin_head,
                    "origin_sync_status": origin_sync_status,
                    "origin_sync_action": origin_sync_action,
                    "upstream_head": upstream_head,
                    "push_result": push_result,
                    "message": "No local update branch exists.",
                },
            )
            append_log(
                repo_root,
                "Main migration skipped",
                [
                    "No local `update` branch exists.",
                    f"origin phase: {origin_sync_status} ({origin_sync_action})",
                    f"push result: {push_result}",
                ],
            )
            return EXIT_OK

        if not merge_base_is_ancestor(repo_root, "main", "update"):
            save_state(
                repo_root,
                {
                    "generated_at": utc_now(),
                    "status": "migration_blocked_non_linear",
                    "local_remote": SYNC_LOCAL_REMOTE,
                    "current_branch": current_branch(repo_root),
                    "origin_head": origin_head,
                    "origin_sync_status": origin_sync_status,
                    "origin_sync_action": origin_sync_action,
                    "upstream_head": upstream_head,
                    "message": "`update` is not a linear descendant of `main`.",
                    "backup_ref": backup_ref,
                },
            )
            append_log(
                repo_root,
                "Main migration blocked",
                [
                    f"origin phase: {origin_sync_status} ({origin_sync_action})",
                    "`update` is not a linear descendant of `main`.",
                ],
            )
            return EXIT_MIGRATION_BLOCKED

        ensure_backup()
        create_backup_tag(
            repo_root,
            f"aris-main-migration-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "update",
        )
        git(repo_root, "merge", "--ff-only", "update", check=True)
        validate_repo(repo_root)
        push_result = "disabled" if not SYNC_PUSH else "not_needed"
        final_head = rev_parse(repo_root, "main")
        if SYNC_PUSH and final_head != origin_head:
            push_branch(repo_root, SYNC_LOCAL_REMOTE, "main")
            push_result = "success"
        delete_branch(repo_root, "update")
        delete_remote_branch(repo_root, SYNC_LOCAL_REMOTE, "update")

        save_state(
            repo_root,
            {
                "generated_at": utc_now(),
                "status": "migrated_to_main",
                "backup_ref": backup_ref,
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "main_head": final_head,
                "origin_head": origin_head,
                "origin_sync_status": origin_sync_status,
                "origin_sync_action": origin_sync_action,
                "upstream_head": upstream_head,
                "push_result": push_result,
            },
        )
        append_log(
            repo_root,
            "Migrated update branch into main",
            [
                f"origin phase: {origin_sync_status} ({origin_sync_action})",
                f"backup ref: `{backup_ref}`",
                "Fast-forwarded `main` to `update`.",
                "Deleted local and remote `update` branches.",
                f"push result: {push_result}",
            ],
        )
        return EXIT_OK
    except Exception as exc:
        if backup_ref is not None:
            try:
                rollback_to_backup(repo_root, backup_ref)
            except Exception:
                pass
        save_state(
            repo_root,
            {
                "generated_at": utc_now(),
                "status": "migration_failed",
                "backup_ref": backup_ref,
                "local_remote": SYNC_LOCAL_REMOTE,
                "current_branch": current_branch(repo_root),
                "origin_head": origin_head,
                "origin_sync_status": origin_sync_status,
                "origin_sync_action": origin_sync_action,
                "upstream_head": upstream_head,
                "error": str(exc),
            },
        )
        append_log(
            repo_root,
            "Main migration failed",
            [
                f"origin phase: {origin_sync_status} ({origin_sync_action})",
                f"backup ref: `{backup_ref}`" if backup_ref else "backup ref: not created",
                f"error: {exc}",
            ],
        )
        if "push failed" in str(exc).lower():
            return EXIT_PUSH_FAILED
        return EXIT_VALIDATION_FAILED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize this fork against upstream/main and keep a single main branch."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_p = subparsers.add_parser("status", help="Show sync status.")
    status_p.add_argument("--no-fetch", action="store_true", help="Do not fetch upstream before reporting status.")

    subparsers.add_parser("sync", help="Fetch upstream and merge it into the target branch.")
    subparsers.add_parser(
        "migrate-to-main",
        help="Fast-forward main to update, push origin/main, and delete update.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = DEFAULT_REPO_ROOT

    if args.command == "status":
        print(
            json.dumps(
                sync_status(repo_root, fetch=not args.no_fetch),
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK
    if args.command == "sync":
        return perform_sync(repo_root)
    if args.command == "migrate-to-main":
        return perform_migration(repo_root)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
