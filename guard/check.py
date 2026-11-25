#!/usr/bin/env python3
"""Guard: статическая проверка патча до PR.

Запускается после `git apply --index` в чистом clone на base SHA.
Проверяет пути, режимы файлов, размеры, labels и kernel-пути.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import (  # noqa: E402
    HarnessError,
    git,
    is_kernel_path,
    matches_any,
    read_json,
    split_csv,
    write_json,
)


def load_rules(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise HarnessError("PyYAML is required") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise HarnessError(f"guard rules must be a mapping: {path}")
    return data


def changed_paths(repo: Path) -> list[str]:
    proc = git(repo, "diff", "--cached", "--name-only", "-z")
    return [p for p in proc.stdout.split("\0") if p]


def file_mode(repo: Path, path: str) -> str | None:
    proc = git(repo, "ls-files", "-s", "--", path, check=False)
    line = proc.stdout.strip()
    if not line:
        return None
    return line.split()[0]


def rename_paths(path: str) -> list[str]:
    """Развернуть git-нотацию rename (`old => new`, `d/{a => b}/f`) в пути."""
    if " => " not in path:
        return [path]
    if "{" in path and "}" in path:
        prefix, rest = path.split("{", 1)
        inside, suffix = rest.split("}", 1)
        old, new = inside.split(" => ", 1)
        return [prefix + old + suffix, prefix + new + suffix]
    old, new = path.split(" => ", 1)
    return [old, new]


def numstat(repo: Path) -> tuple[dict[str, tuple[int | None, int | None]], int]:
    """Вернуть map path -> (added, deleted) и суммарное число строк."""
    proc = git(repo, "diff", "--cached", "--numstat")
    stats: dict[str, tuple[int | None, int | None]] = {}
    total = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], "\t".join(parts[2:])
        a = int(added) if added.isdigit() else None
        d = int(deleted) if deleted.isdigit() else None
        for candidate in rename_paths(path):
            stats[candidate] = (a, d)
        if a is not None:
            total += a
        if d is not None:
            total += d
    return stats, total


def gitleaks(repo: Path) -> list[str]:
    if not shutil.which("gitleaks"):
        return []
    # gitleaks v8: detect --source <dir> --no-git
    proc = subprocess.run(
        ["gitleaks", "detect", "--source", str(repo), "--no-git", "--redact", "--exit-code", "1"],
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        return []
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return [f"gitleaks: {output[-4000:]}"] if output else ["gitleaks: secret detected"]


def check(
    repo: Path,
    *,
    target: str,
    labels: set[str],
    rules: dict[str, Any],
    patch_bytes: int,
    kernel_paths: list[str],
    use_gitleaks: bool = True,
) -> dict[str, Any]:
    violations: list[str] = []
    approval_paths: list[str] = []
    paths = changed_paths(repo)
    stats, total_lines = numstat(repo)

    deny_paths = list(rules.get("deny_paths", []))
    protected_tests = list(rules.get("protected_tests", []))
    dependency_files = list(rules.get("dependency_files", []))
    limits = rules.get("limits", {}) or {}

    if not paths:
        violations.append("patch is empty")

    if len(paths) > int(limits.get("max_files", 300)):
        violations.append(f"too many files: {len(paths)} > {limits.get('max_files')}")
    if patch_bytes > int(limits.get("max_patch_bytes", 2 * 1024 * 1024)):
        violations.append(f"patch too large: {patch_bytes} bytes > {limits.get('max_patch_bytes')}")
    if total_lines > int(limits.get("max_lines", 20000)):
        violations.append(f"too many changed lines: {total_lines} > {limits.get('max_lines')}")

    for path in paths:
        # .github/workflows в target запрещены; в core это kernel-путь.
        if target != "core" and matches_any(path, deny_paths):
            violations.append(f"denied path: {path}")
        elif target == "core" and matches_any(path, [".github/workflows/**"]):
            approval_paths.append(path)
        elif matches_any(path, [p for p in deny_paths if p != ".github/workflows/**"]):
            violations.append(f"denied path: {path}")

        if matches_any(path, protected_tests) and "allow-tests" not in labels and target != "core":
            violations.append(f"test file requires label allow-tests: {path}")
        if matches_any(path, dependency_files) and "allow-deps" not in labels:
            violations.append(f"dependency file requires label allow-deps: {path}")

        mode = file_mode(repo, path)
        if mode == "120000" and rules.get("deny_symlinks", True):
            violations.append(f"symlink denied: {path}")
        if mode == "160000" and rules.get("deny_submodules", True):
            violations.append(f"submodule denied: {path}")

        added, deleted = stats.get(path, (None, None))
        if rules.get("deny_binary", True) and (added is None or deleted is None):
            violations.append(f"binary file denied: {path}")

        full = repo / path
        if full.is_file() and not full.is_symlink():
            size = full.stat().st_size
            max_file = int(limits.get("max_file_bytes", 1024 * 1024))
            if rules.get("deny_large_files", True) and size > max_file:
                violations.append(f"file too large: {path} ({size} > {max_file} bytes)")

        if target == "core" and is_kernel_path(path, kernel_paths):
            approval_paths.append(path)

    if use_gitleaks and rules.get("secrets", {}).get("gitleaks", True):
        violations.extend(gitleaks(repo))

    return {
        "ok": not violations,
        "target": target,
        "violations": violations,
        "requires_approval": bool(approval_paths),
        "approval_paths": sorted(set(approval_paths)),
        "files": paths,
        "stats": {
            "files": len(paths),
            "lines": total_lines,
            "patch_bytes": patch_bytes,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="clean clone с применённым патчем")
    parser.add_argument("--patch", required=True, help="файл патча")
    parser.add_argument("--target", required=True, help="alias target-репозитория")
    parser.add_argument("--labels", default="", help="labels issue через запятую")
    parser.add_argument("--rules", default=str(ROOT / "guard" / "rules.yml"))
    parser.add_argument("--report", default="")
    parser.add_argument("--no-gitleaks", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    patch = Path(args.patch).resolve()
    rules = load_rules(Path(args.rules))

    target_manifest: dict[str, Any] = {}
    try:
        from scripts.common import load_target

        target_manifest = load_target(args.target)
    except HarnessError:
        target_manifest = {}

    report = check(
        repo,
        target=args.target,
        labels=set(split_csv(args.labels)),
        rules=rules,
        patch_bytes=patch.stat().st_size if patch.exists() else 0,
        kernel_paths=list(target_manifest.get("kernel_paths", [])),
        use_gitleaks=not args.no_gitleaks,
    )
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
