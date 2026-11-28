#!/usr/bin/env python3
"""publish/apply: чистый clone target на base SHA, применение патча, commit, push."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import HarnessError, env, git, git_env, run  # noqa: E402


def clone_target(repo: str, base_sha: str, dest: Path, token: str, *, depth: int = 1) -> Path:
    """Создать чистый clone target и перейти на base SHA."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    server = env("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    url = f"{server}/{repo}.git"
    run(["git", "clone", "--no-checkout", url, str(dest)], env=git_env(token), check=True, timeout=300)
    fetch = ["fetch"]
    if depth > 0:
        fetch.append(f"--depth={depth}")
    fetch.extend(["origin", base_sha])
    git(dest, *fetch, token=token, timeout=300)
    # FETCH_HEAD работает и для SHA, и для имени ветки.
    git(dest, "checkout", "--detach", "FETCH_HEAD", token=token, timeout=120)
    git(dest, "config", "user.name", "free-autonomy-harness-bot[bot]")
    git(dest, "config", "user.email", "361107743+free-autonomy-harness-bot[bot]@users.noreply.github.com")
    return dest


def apply_patch(repo_dir: Path, patch_path: Path) -> None:
    if not patch_path.exists() or patch_path.stat().st_size == 0:
        raise HarnessError("patch is missing or empty")
    proc = git(repo_dir, "apply", "--index", "--binary", "--whitespace=nowarn", str(patch_path), check=False)
    if proc.returncode != 0:
        raise HarnessError(f"patch does not apply: {proc.stderr[-4000:]}")


def commit_all(repo_dir: Path, message: str) -> str:
    git(repo_dir, "add", "-A")
    status = git(repo_dir, "status", "--porcelain")
    if not status.stdout.strip():
        raise HarnessError("nothing to commit after applying patch")
    git(repo_dir, "commit", "-m", message)
    return git(repo_dir, "rev-parse", "HEAD").stdout.strip()


def head_sha(repo_dir: Path) -> str:
    return git(repo_dir, "rev-parse", "HEAD").stdout.strip()


def push_branch(repo_dir: Path, branch: str, token: str) -> None:
    proc = git(repo_dir, "push", "origin", f"HEAD:refs/heads/{branch}", token=token, check=False, timeout=300)
    if proc.returncode != 0:
        raise HarnessError(f"git push failed: {proc.stderr[-4000:]}")


def changed_files(repo_dir: Path, base_sha: str) -> list[str]:
    proc = git(repo_dir, "diff", "--name-only", base_sha, "HEAD")
    return [line for line in proc.stdout.splitlines() if line]
