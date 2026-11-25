#!/usr/bin/env python3
"""Dispatch: watchdog, выбор старейшего issue с harness:task, запуск work/agent."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import (  # noqa: E402
    GitHub,
    GitHubError,
    HarnessError,
    env,
    issue_labels,
    load_target,
    target_alias,
    truthy,
)


def log(message: str) -> None:
    print(f"[dispatch] {message}", flush=True)


def age_minutes(issue: dict) -> float:
    raw = str(issue.get("updated_at") or "")
    if not raw:
        return 0.0
    try:
        then = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (datetime.now(timezone.utc) - then).total_seconds() / 60.0


def watchdog(api: GitHub, repo: str, active: list[dict]) -> bool:
    """Снять застрявший active, если прогон не завершился за отведённое время."""
    limit = float(env("WATCHDOG_MINUTES", "90"))
    issue = active[0]
    minutes = age_minutes(issue)
    if minutes < limit:
        return False
    number = int(issue["number"])
    api.remove_label(repo, number, "harness:active")
    api.add_labels(repo, number, ["harness:task", "harness:failed"])
    api.comment(
        repo,
        number,
        f"## Watchdog\n\n`harness:active` висел {minutes:.0f} мин (лимит {limit:.0f}). "
        "Задача возвращена в очередь с `harness:failed`. Проверьте `work / agent`.",
    )
    log(f"watchdog: reset stale active #{number} ({minutes:.0f}m)")
    return True


def main() -> int:
    core_repo = env("GITHUB_REPOSITORY", required=True)
    owner = core_repo.split("/", 1)[0]
    work_repo = env("WORK_REPO") or f"{owner}/harness-work"
    api = GitHub()

    if truthy(api.get_variable(core_repo, "HARNESS_PAUSED")):
        log("HARNESS_PAUSED=true, skip")
        return 0

    active = api.list_issues(core_repo, labels="harness:active")
    if active:
        if watchdog(api, core_repo, active):
            active = []
        else:
            log(f"already active: #{active[0]['number']}, skip")
            return 0

    issues = api.list_issues(core_repo, labels="harness:task")
    if not issues:
        log("no harness:task issues")
        return 0

    work_ref = api.default_branch(work_repo)
    for issue in issues:
        number = int(issue["number"])
        labels = issue_labels(issue)
        if "harness:blocked" in labels:
            continue
        target = target_alias(labels)
        if not target:
            match = re.match(r"\s*\[([a-z0-9_-]+)\]", str(issue.get("title") or ""), re.IGNORECASE)
            if match:
                target = match.group(1)
                api.add_labels(core_repo, number, [f"target:{target}"])
        if not target:
            api.add_labels(core_repo, number, ["harness:failed"])
            api.remove_label(core_repo, number, "harness:task")
            api.comment(core_repo, number, "Нет label `target:<alias>` и префикса `[alias]` в title.")
            continue

        try:
            manifest = load_target(target)
        except HarnessError as exc:
            api.add_labels(core_repo, number, ["harness:failed"])
            api.remove_label(core_repo, number, "harness:task")
            api.comment(core_repo, number, f"Неизвестный target: {exc}")
            continue

        target_repo = manifest["repo"]
        base_sha = api.branch_sha(target_repo, manifest["branch"])
        api.add_labels(core_repo, number, ["harness:active"])
        api.remove_label(core_repo, number, "harness:task")

        try:
            api.dispatch_workflow(
                work_repo,
                "agent.yml",
                work_ref,
                {
                    "target": target,
                    "issue": number,
                    "base_sha": base_sha,
                    "issue_repo": core_repo,
                    "target_repo": target_repo,
                    "target_branch": manifest["branch"],
                },
            )
        except (GitHubError, HarnessError) as exc:
            api.remove_label(core_repo, number, "harness:active")
            api.add_labels(core_repo, number, ["harness:task", "harness:failed"])
            api.comment(core_repo, number, f"Не удалось запустить `work/agent`: {exc}")
            return 1

        log(f"dispatched #{number} target={target} base={base_sha[:12]} -> {work_repo}")
        return 0

    log("no runnable issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
