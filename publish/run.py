#!/usr/bin/env python3
"""publish/run: оркестрация publish pipeline.

prepare -> clone -> apply -> guard -> verify -> PR -> status -> merge ->
post-merge verify -> close issue. Любая ошибка: labels, comment, pause после двух.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guard.check import check as guard_check  # noqa: E402
from guard.check import load_rules  # noqa: E402
from publish.apply import (  # noqa: E402
    apply_patch,
    changed_files,
    clone_target,
    commit_all,
    head_sha,
    push_branch,
)
from publish.merge import merge_pr, post_merge_verify  # noqa: E402
from publish.pr import close_pr, create_pr, set_status, wait_for_checks  # noqa: E402
from publish.prepare import load_meta, load_patch, validate_meta  # noqa: E402
from publish.revert import revert_merge  # noqa: E402
from scripts.common import (  # noqa: E402
    GitHub,
    HarnessError,
    env,
    issue_labels,
    load_target,
    truncate,
    truthy,
    write_json,
)
from verify.run import verify  # noqa: E402

FAILURE_VAR = "HARNESS_FAILURES"
PAUSE_VAR = "HARNESS_PAUSED"


def log(message: str) -> None:
    print(f"[publish] {message}", flush=True)


def record_failure(
    core: GitHub,
    issue_repo: str,
    issue_number: int,
    reason: str,
    *,
    run_url: str | None = None,
    target_api: GitHub | None = None,
    target_repo: str | None = None,
    head: str | None = None,
    pr: dict[str, Any] | None = None,
    branch: str | None = None,
) -> int:
    if target_api and target_repo and head:
        try:
            set_status(target_api, target_repo, head, "failure", "harness publish failed", run_url)
        except HarnessError as exc:
            log(f"cannot set failure status: {exc}")
    if target_api and target_repo and pr:
        try:
            close_pr(target_api, target_repo, int(pr["number"]))
        except HarnessError as exc:
            log(f"cannot close PR: {exc}")
    if target_api and target_repo and branch:
        try:
            target_api.delete_branch(target_repo, branch)
        except HarnessError as exc:
            log(f"cannot delete branch: {exc}")

    body = "## Harness: ошибка\n\n"
    body += f"```\n{truncate(reason, 6000)}\n```\n"
    if run_url:
        body += f"\nRun: {run_url}\n"
    try:
        core.add_labels(issue_repo, issue_number, ["harness:failed"])
        for label in ("harness:active", "harness:task", "harness:dry-run"):
            core.remove_label(issue_repo, issue_number, label)
        core.comment(issue_repo, issue_number, body)
    except HarnessError as exc:
        log(f"cannot update issue: {exc}")

    try:
        current = int(core.get_variable(issue_repo, FAILURE_VAR) or "0")
        failures = current + 1
        core.set_variable(issue_repo, FAILURE_VAR, str(failures))
        if failures >= 2:
            core.add_labels(issue_repo, issue_number, ["harness:blocked"])
            core.set_variable(issue_repo, PAUSE_VAR, "true")
            core.comment(
                issue_repo,
                issue_number,
                "## Harness остановлен\n\n"
                f"Две ошибки подряд (счётчик: {failures}). "
                "Добавлен `harness:blocked` и `HARNESS_PAUSED=true`. "
                "Разберите лог и запустите `core / resume`.",
            )
    except HarnessError as exc:
        log(f"cannot update failure counter: {exc}")
    return 1


def record_success(
    core: GitHub,
    issue_repo: str,
    issue_number: int,
    *,
    pr: dict[str, Any],
    route: str | None,
    files: list[str],
    verify_report: dict[str, Any],
) -> None:
    checks = ", ".join(
        f"{c['name']}={'ok' if c['ok'] else 'fail'}" for c in verify_report.get("checks", [])
    )
    body = (
        "## Harness: готово\n\n"
        f"- PR: {pr.get('html_url')}\n"
        f"- Маршрут: `{route or 'unknown'}`\n"
        f"- Файлы: {', '.join(files) or '—'}\n"
        f"- Verify: {checks or '—'}\n"
    )
    try:
        core.add_labels(issue_repo, issue_number, ["harness:done"])
        for label in (
            "harness:active",
            "harness:failed",
            "harness:blocked",
            "harness:needs-approval",
            "harness:dry-run",
            "harness:task",
        ):
            core.remove_label(issue_repo, issue_number, label)
        core.comment(issue_repo, issue_number, body)
        core.close_issue(issue_repo, issue_number)
    except HarnessError as exc:
        log(f"cannot finalize issue: {exc}")
    try:
        core.set_variable(issue_repo, FAILURE_VAR, "0")
    except HarnessError as exc:
        log(f"cannot reset failure counter: {exc}")


def record_approval(
    core: GitHub,
    issue_repo: str,
    issue_number: int,
    *,
    pr: dict[str, Any],
    approval_paths: list[str],
    run_url: str | None,
) -> None:
    body = (
        "## Harness: нужен approve\n\n"
        f"PR: {pr.get('html_url')}\n\n"
        "Патч затрагивает kernel-пути core:\n"
        + "\n".join(f"- `{p}`" for p in approval_paths)
        + "\n\nMerge только вручную. После merge закрой issue."
    )
    if run_url:
        body += f"\n\nRun: {run_url}"
    try:
        core.add_labels(issue_repo, issue_number, ["harness:needs-approval"])
        for label in ("harness:active", "harness:task", "harness:dry-run"):
            core.remove_label(issue_repo, issue_number, label)
        core.comment(issue_repo, issue_number, body)
    except HarnessError as exc:
        log(f"cannot update approval issue: {exc}")
    try:
        core.set_variable(issue_repo, FAILURE_VAR, "0")
    except HarnessError as exc:
        log(f"cannot reset failure counter: {exc}")


def verify_in_copy(target_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    workdir = Path(tempfile.mkdtemp(prefix="harness-verify-copy-"))
    copy = workdir / "target"
    try:
        # Копируем вместе с .git: тестам может понадобиться git-контекст.
        # Копия одноразовая, поэтому мусор тестов не попадёт в патч.
        shutil.copytree(target_dir, copy)
        return verify(copy, manifest)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def publish(args: argparse.Namespace) -> int:
    issue_repo = env("ISSUE_REPO", required=True)
    target_repo = env("TARGET_REPO", required=True)
    target_token = env("TARGET_TOKEN", required=True)
    core_token = env("CORE_TOKEN", required=True)
    run_url = env("WORK_RUN_URL") or None
    publish_url = env("PUBLISH_RUN_URL") or run_url

    core = GitHub(core_token)
    target_api = GitHub(target_token)
    manifest = load_target(args.target)
    if manifest["repo"] != target_repo:
        raise HarnessError(f"target repo mismatch: manifest={manifest['repo']} input={target_repo}")
    branch_name = manifest["branch"]

    issue = core.get_issue(issue_repo, args.issue)
    labels = set(issue_labels(issue))
    title = str(issue.get("title") or f"issue {args.issue}")

    artifact_dir = Path(args.artifact_dir).resolve()
    meta = load_meta(artifact_dir)
    try:
        validate_meta(meta, target=args.target, issue=args.issue)
        patch = load_patch(artifact_dir)
    except HarnessError as exc:
        return record_failure(
            core,
            issue_repo,
            args.issue,
            str(exc),
            run_url=run_url,
            target_api=target_api,
            target_repo=target_repo,
        )

    base_sha = str(meta["base_sha"])
    route = meta.get("route")
    log(f"issue #{args.issue} target={args.target} base={base_sha[:12]} route={route}")

    workdir = Path(tempfile.mkdtemp(prefix="harness-publish-"))
    target_dir = workdir / "target"
    branch = f"harness/issue-{args.issue}-{args.run_id}"
    pr: dict[str, Any] | None = None
    head: str | None = None
    try:
        clone_target(target_repo, base_sha, target_dir, target_token)
        apply_patch(target_dir, patch)

        # Перечитываем labels: пользователь мог добавить allow-tests/allow-deps
        # уже после dispatch.
        labels = set(issue_labels(core.get_issue(issue_repo, args.issue)))
        rules = load_rules(ROOT / "guard" / "rules.yml")
        guard_report = guard_check(
            target_dir,
            target=args.target,
            labels=labels,
            rules=rules,
            patch_bytes=patch.stat().st_size,
            kernel_paths=list(manifest.get("kernel_paths", [])),
            use_gitleaks=True,
        )
        write_json(workdir / "guard.json", guard_report)
        if not guard_report["ok"]:
            raise HarnessError("guard failed:\n" + "\n".join(guard_report["violations"]))

        verify_report = verify_in_copy(target_dir, manifest)
        write_json(workdir / "verify.json", verify_report)
        if not verify_report["ok"]:
            failed = [c for c in verify_report.get("checks", []) if not c["ok"]]
            details = "\n".join(
                f"- {c['name']}: exit={c.get('exit_code')} timeout={c.get('timed_out')}\n"
                f"  stderr: {truncate(c.get('stderr') or '', 2000)}"
                for c in failed
            )
            raise HarnessError("verify failed:\n" + details)

        message = f"harness: {title} (#{args.issue})"
        commit_all(target_dir, message)
        head = head_sha(target_dir)
        push_branch(target_dir, branch, target_token)

        pr = create_pr(
            target_api,
            target_repo,
            title=message,
            head=branch,
            base=branch_name,
            body=(
                f"Closes #{args.issue}\n\n"
                f"Target: `{args.target}`\n"
                f"Route: `{route or 'unknown'}`\n"
                f"Base SHA: `{base_sha}`\n\n"
                "Generated by harness. Guard and verify passed before PR creation."
            ),
        )
        set_status(target_api, target_repo, head, "success", "guard + verify passed", publish_url)

        dry_run = truthy(env("HARNESS_DRY_RUN")) or truthy(
            core.get_variable(issue_repo, "HARNESS_DRY_RUN")
        )
        if dry_run:
            core.add_labels(issue_repo, args.issue, ["harness:dry-run"])
            core.remove_label(issue_repo, args.issue, "harness:active")
            core.comment(
                issue_repo,
                args.issue,
                f"## Dry-run\n\nPR создан без merge: {pr.get('html_url')}\n\n"
                "Снимите `HARNESS_DRY_RUN`, чтобы разрешить merge.",
            )
            return 0

        if guard_report.get("requires_approval"):
            record_approval(
                core,
                issue_repo,
                args.issue,
                pr=pr,
                approval_paths=list(guard_report.get("approval_paths", [])),
                run_url=publish_url,
            )
            return 0

        ok, message_checks = wait_for_checks(
            target_api,
            target_repo,
            head,
            require_native_ci=bool(manifest.get("require_native_ci", True)),
            timeout=int(env("VERIFY_WAIT_SECONDS", "600")),
        )
        if not ok:
            raise HarnessError(f"checks failed: {message_checks}")

        merge_result = merge_pr(
            target_api,
            target_repo,
            int(pr["number"]),
            head,
            title=message,
            message=f"Harness issue #{args.issue}, route {route or 'unknown'}",
        )
        merge_sha = str(merge_result.get("sha") or "")
        time.sleep(3)

        post = post_merge_verify(target_repo, branch_name, manifest, target_token)
        write_json(workdir / "post-merge-verify.json", post)
        if not post["ok"]:
            failed = [c["name"] for c in post.get("checks", []) if not c["ok"]]
            reason = f"post-merge verify failed: {', '.join(failed)}"
            try:
                revert_merge(
                    target_api,
                    target_repo,
                    merge_sha,
                    branch_name,
                    target_token,
                    manifest,
                    reason,
                    publish_url,
                )
                reason += "\nRevert PR создан и смержен."
            except HarnessError as exc:
                reason += f"\nRevert не удался: {exc}"
                try:
                    core.set_variable(issue_repo, PAUSE_VAR, "true")
                except HarnessError:
                    pass
            return record_failure(
                core,
                issue_repo,
                args.issue,
                reason,
                run_url=run_url,
                target_api=target_api,
                target_repo=target_repo,
                head=head,
                pr=pr,
                branch=branch,
            )

        record_success(
            core,
            issue_repo,
            args.issue,
            pr=pr,
            route=route,
            files=changed_files(target_dir, base_sha),
            verify_report=verify_report,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return record_failure(
            core,
            issue_repo,
            args.issue,
            f"{type(exc).__name__}: {exc}",
            run_url=run_url,
            target_api=target_api,
            target_repo=target_repo,
            head=head,
            pr=pr,
            branch=branch,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", default="artifact")
    parser.add_argument("--target", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        return publish(args)
    except Exception as exc:  # noqa: BLE001
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
