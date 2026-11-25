#!/usr/bin/env python3
"""Resume: снять HARNESS_PAUSED, сбросить failures, вернуть blocked -> task."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import GitHub, HarnessError, env, issue_labels  # noqa: E402


def main() -> int:
    repo = env("GITHUB_REPOSITORY", required=True)
    api = GitHub()
    api.set_variable(repo, "HARNESS_PAUSED", "false")
    api.set_variable(repo, "HARNESS_FAILURES", "0")
    print("[resume] pause=false failures=0")

    for issue in api.list_issues(repo, labels="harness:blocked"):
        number = int(issue["number"])
        labels = issue_labels(issue)
        api.remove_label(repo, number, "harness:blocked")
        api.remove_label(repo, number, "harness:failed")
        api.add_labels(repo, number, ["harness:task"])
        api.comment(
            repo,
            number,
            "`core / resume`: блокировка снята, задача возвращена в очередь (`harness:task`).",
        )
        print(f"[resume] unblocked #{number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
