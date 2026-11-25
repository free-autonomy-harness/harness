#!/usr/bin/env python3
"""publish/merge: squash merge и post-merge verify."""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from publish.apply import clone_target  # noqa: E402
from scripts.common import GitHub, HarnessError  # noqa: E402
from verify.run import verify  # noqa: E402


def merge_pr(
    api: GitHub,
    repo: str,
    number: int,
    sha: str,
    *,
    title: str | None = None,
    message: str | None = None,
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            result = api.merge_pull(repo, number, sha, method="squash", title=title, message=message)
            if result.get("merged"):
                return result
            last_error = HarnessError(f"merge not completed: {result}")
        except HarnessError as exc:
            last_error = exc
        time.sleep(5 * attempt)
    raise HarnessError(f"merge failed after {retries} attempts: {last_error}")


def verify_ref(
    repo: str,
    ref: str,
    manifest: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    workdir = Path(tempfile.mkdtemp(prefix="harness-verify-"))
    target = workdir / "target"
    try:
        clone_target(repo, ref, target, token)
        return verify(target, manifest)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def post_merge_verify(
    repo: str,
    branch: str,
    manifest: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    return verify_ref(repo, branch, manifest, token)
