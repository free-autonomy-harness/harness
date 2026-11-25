#!/usr/bin/env python3
"""Notify/replay: вручную dispatch core/publish для готового artifact.

Обычно используется из work/notify; этот CLI нужен для повторного запуска.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import GitHub, env  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=env("GITHUB_REPOSITORY"))
    parser.add_argument("--target", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--work-repo", required=True)
    args = parser.parse_args(argv)
    if not args.repo:
        print("error: --repo or GITHUB_REPOSITORY is required", file=sys.stderr)
        return 1

    api = GitHub()
    ref = api.default_branch(args.repo)
    api.dispatch_workflow(
        args.repo,
        "publish.yml",
        ref,
        {
            "target": args.target,
            "issue": args.issue,
            "run_id": args.run_id,
            "work_repo": args.work_repo,
        },
    )
    print(f"dispatched publish for {args.target} #{args.issue} run {args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
