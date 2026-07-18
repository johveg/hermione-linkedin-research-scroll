#!/usr/bin/env python3
"""Publish one completed LinkedIn intake to the public research scroll.

This is intentionally a post-intake action. It refuses to publish an activity
unless its canonical archive contains the basic public artifacts plus an
intake research summary. It then regenerates the static page, stages only the
public-site outputs, scans those outputs, commits, pushes, and verifies the
remote branch.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("/home/hermoine/agent-research-linkedin-source/data/posts")
PUBLIC_PATHS = ("index.html", "manifest.json", "assets/posts")
FORBIDDEN_PUBLIC_MARKERS = (
    "source.html",
    "comments.json",
    "authenticated-visible",
    "persistent logged-in Chromium",
    "/home/hermoine/",
)
SECRET_PATTERN = re.compile(
    r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|"
    r"(?:api[_-]?key|token|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_./-]{24,})",
    re.IGNORECASE,
)


class PublishError(RuntimeError):
    pass


def run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=SITE_ROOT, text=True, check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def find_archive(source: Path, activity_id: str) -> Path:
    matches: list[Path] = []
    for metadata_path in source.glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(metadata.get("activity_id") or "") == activity_id:
            matches.append(metadata_path.parent)
    if len(matches) != 1:
        raise PublishError(f"expected exactly one archive for activity {activity_id}; found {len(matches)}")
    return matches[0]


def verify_intake_ready(source: Path, activity_id: str) -> Path:
    archive = find_archive(source, activity_id)
    required = ("metadata.json", "post.txt", "intake-summary.md")
    missing = [name for name in required if not (archive / name).is_file()]
    if missing:
        raise PublishError(
            "refusing publication before intake is complete: "
            f"{archive} is missing {', '.join(missing)}"
        )
    return archive


def ensure_public_worktree_clean() -> None:
    completed = run("git", "status", "--porcelain", "--", *PUBLIC_PATHS, capture=True)
    if completed.stdout.strip():
        raise PublishError("public site worktree is not clean; refusing to absorb unrelated changes")


def staged_names() -> list[str]:
    completed = run("git", "diff", "--cached", "--name-only", "-z", capture=True)
    return [name for name in completed.stdout.split("\0") if name]


def scan_staged_public_files() -> None:
    run("git", "diff", "--cached", "--check")
    names = staged_names()
    for name in names:
        path = SITE_ROOT / name
        if not path.is_file():
            continue
        if path.stat().st_size > 100 * 1024 * 1024:
            raise PublishError(f"refusing oversized public asset: {name}")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if SECRET_PATTERN.search(text):
            raise PublishError(f"refusing apparent secret in staged public file: {name}")

    page = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    for marker in FORBIDDEN_PUBLIC_MARKERS:
        if marker in page:
            raise PublishError(f"refusing forbidden private/raw marker in public page: {marker}")


def remote_branch_sha() -> str:
    completed = run("git", "ls-remote", "origin", "refs/heads/main", capture=True)
    fields = completed.stdout.strip().split()
    if not fields:
        raise PublishError("origin/main is not reachable")
    return fields[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--activity-id", required=True, help="canonical LinkedIn activity ID")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dry-run", action="store_true", help="validate and rebuild but do not commit/push")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        raise PublishError(f"invalid LinkedIn source archive: {source}")

    archive = verify_intake_ready(source, args.activity_id)
    ensure_public_worktree_clean()
    if not args.dry_run:
        run("git", "pull", "--ff-only", "origin", "main")

    run(sys.executable, "scripts/build_site.py", "--source", str(source))
    run("git", "add", "--", *PUBLIC_PATHS)
    scan_staged_public_files()

    names = staged_names()
    result = {
        "activity_id": args.activity_id,
        "archive": str(archive),
        "public_url": "https://johveg.github.io/hermione-linkedin-research-scroll/",
        "staged_files": names,
    }
    if args.dry_run:
        # The clean-worktree gate above makes this restoration safe and keeps dry-runs idempotent.
        run("git", "restore", "--source=HEAD", "--staged", "--worktree", "--", *PUBLIC_PATHS)
        result["status"] = "dry-run-validated"
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if not names:
        local = run("git", "rev-parse", "HEAD", capture=True).stdout.strip()
        remote = remote_branch_sha()
        if local != remote:
            raise PublishError("no generated diff, but local main differs from origin/main")
        result.update(status="already-current", commit=local)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    run("git", "commit", "-m", f"feat: publish LinkedIn filing {args.activity_id}")
    run("git", "push", "origin", "main")
    local = run("git", "rev-parse", "HEAD", capture=True).stdout.strip()
    remote = remote_branch_sha()
    if local != remote:
        raise PublishError(f"push verification failed: local {local} != remote {remote}")
    result.update(status="published", commit=local)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PublishError, subprocess.CalledProcessError) as exc:
        print(f"publish failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
