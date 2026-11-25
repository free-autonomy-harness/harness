#!/usr/bin/env python3
"""Import: опционально создать issues из TASKS.md (не runtime).

Формат:
    ## [sandbox] Add README
    Details: ...
    Done when: ...
    Constraints: ...
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import GitHub, env, issue_labels  # noqa: E402


def parse_tasks(text: str) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    chunks = re.split(r"(?m)^##\s+", text)
    for chunk in chunks[1:]:
        lines = chunk.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        tasks.append({"title": title, "body": body})
    return tasks


def target_from_title(title: str, default: str) -> str:
    match = re.match(r"\[([a-z0-9_-]+)\]", title.strip(), re.IGNORECASE)
    return match.group(1) if match else default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="TASKS.md")
    parser.add_argument("--repo", default=env("GITHUB_REPOSITORY"))
    parser.add_argument("--target", default="sandbox")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return 1
    tasks = parse_tasks(path.read_text(encoding="utf-8"))
    if not tasks:
        print("no tasks found")
        return 0
    if args.dry_run:
        for task in tasks:
            print(f"- {task['title']} (target: {target_from_title(task['title'], args.target)})")
        return 0

    if not args.repo:
        print("error: --repo or GITHUB_REPOSITORY is required", file=sys.stderr)
        return 1
    api = GitHub()
    existing = {str(i.get("title")) for i in api.list_issues(args.repo, state="all")}
    created = 0
    for task in tasks:
        if task["title"] in existing:
            print(f"skip existing: {task['title']}")
            continue
        target = target_from_title(task["title"], args.target)
        issue = api.post(
            f"/repos/{args.repo}/issues",
            {
                "title": task["title"],
                "body": task["body"],
                "labels": ["harness:task", f"target:{target}"],
            },
        )
        print(f"created #{issue['number']}: {task['title']}")
        created += 1
    print(f"created {created} issue(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
