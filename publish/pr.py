#!/usr/bin/env python3
"""publish/pr: PR, commit status harness/verify, ожидание CI."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import GitHub, HarnessError  # noqa: E402

CONTEXT = "harness/verify"
FAIL_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required", "stale"}


def create_pr(
    api: GitHub,
    repo: str,
    *,
    title: str,
    head: str,
    base: str,
    body: str,
) -> dict[str, Any]:
    return api.create_pull(repo, title, head, base, body)


def set_status(
    api: GitHub,
    repo: str,
    sha: str,
    state: str,
    description: str,
    target_url: str | None = None,
) -> None:
    api.create_status(repo, sha, CONTEXT, state, description, target_url)


def wait_for_checks(
    api: GitHub,
    repo: str,
    sha: str,
    *,
    require_native_ci: bool,
    timeout: int = 600,
    poll: int = 15,
) -> tuple[bool, str]:
    """Дождаться harness/verify + нативного CI. Вернуть (ok, reason)."""
    deadline = time.monotonic() + timeout
    last = "no checks yet"
    while time.monotonic() < deadline:
        statuses = api.combined_status(repo, sha)
        our = next((s for s in statuses.get("statuses", []) if s.get("context") == CONTEXT), None)
        checks = api.check_runs(repo, sha)
        native = [c for c in checks if c.get("name") != CONTEXT]

        failing = [
            c.get("name")
            for c in native
            if c.get("status") == "completed" and c.get("conclusion") in FAIL_CONCLUSIONS
        ]
        if failing:
            return False, f"native CI failed: {', '.join(str(x) for x in failing)}"
        if our is None:
            last = f"{CONTEXT} status is missing"
        elif our.get("state") != "success":
            last = f"{CONTEXT} state is {our.get('state')}"
        elif require_native_ci:
            if not native:
                last = "native CI checks are missing"
            elif any(c.get("status") != "completed" for c in native):
                last = "native CI is still running"
            else:
                # skipped/neutral не считаем падением; failure уже отловлен выше.
                return True, "all checks passed"
        else:
            return True, "harness/verify passed"
        time.sleep(poll)
    return False, f"timeout after {timeout}s: {last}"


def close_pr(api: GitHub, repo: str, number: int) -> None:
    try:
        api.update_pull(repo, number, state="closed")
    except HarnessError:
        pass
