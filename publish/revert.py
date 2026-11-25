#!/usr/bin/env python3
"""publish/revert: откат merge commit отдельным PR."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from publish.apply import clone_target, head_sha, push_branch  # noqa: E402
from publish.merge import merge_pr  # noqa: E402
from publish.pr import set_status, wait_for_checks  # noqa: E402
from scripts.common import GitHub, HarnessError, env, git  # noqa: E402


def revert_merge(
    api: GitHub,
    repo: str,
    merge_sha: str,
    branch: str,
    token: str,
    manifest: dict[str, Any],
    reason: str,
    run_url: str | None = None,
) -> dict[str, Any]:
    workdir = Path(tempfile.mkdtemp(prefix="harness-revert-"))
    target = workdir / "target"
    try:
        clone_target(repo, branch, target, token, depth=0)
        proc = git(target, "revert", "--no-edit", merge_sha, check=False)
        if proc.returncode != 0:
            git(target, "revert", "--abort", check=False)
            proc = git(target, "revert", "-m", "1", "--no-edit", merge_sha, check=False)
        if proc.returncode != 0:
            raise HarnessError(f"git revert failed: {proc.stderr[-4000:]}")

        sha = head_sha(target)
        revert_branch = f"harness/revert-{merge_sha[:12]}"
        push_branch(target, revert_branch, token)
        pr = api.create_pull(
            repo,
            f"Revert harness merge {merge_sha[:12]}",
            revert_branch,
            branch,
            f"Автоматический revert.\n\nПричина: {reason}\n\nИсходный merge: {merge_sha}",
        )
        set_status(api, repo, sha, "success", "revert to last known good", run_url)
        ok, message = wait_for_checks(
            api,
            repo,
            sha,
            require_native_ci=bool(manifest.get("require_native_ci", True)),
            timeout=int(env("REVERT_WAIT_SECONDS", "600")),
        )
        if not ok:
            raise HarnessError(f"revert PR checks failed: {message}")
        result = merge_pr(
            api,
            repo,
            int(pr["number"]),
            sha,
            title=f"Revert harness merge {merge_sha[:12]}",
            message=reason,
        )
        return {"pull": pr, "merge": result, "sha": sha}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
