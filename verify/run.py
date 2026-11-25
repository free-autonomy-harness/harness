#!/usr/bin/env python3
"""Verify: запуск проверок target из манифеста core/targets/<alias>.yml.

Манифест читается из base-версии core, не из патча target.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import HarnessError, load_target, write_json  # noqa: E402


def run_check(workdir: Path, check: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    name = str(check["name"])
    command = str(check["run"])
    timeout = int(check.get("timeout_seconds", 600))
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(workdir),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        duration = round(time.monotonic() - started, 2)
        return {
            "name": name,
            "command": command,
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "duration_s": duration,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-8000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.monotonic() - started, 2)
        return {
            "name": name,
            "command": command,
            "ok": False,
            "exit_code": None,
            "duration_s": duration,
            "stdout": (exc.stdout or "")[-8000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-8000:] if isinstance(exc.stderr, str) else "",
            "timed_out": True,
            "error": f"timeout after {timeout}s",
        }


def verify(workdir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("CI", "1")
    env["HARNESS_TARGET"] = str(manifest.get("alias", ""))
    results = [run_check(workdir, check, env) for check in manifest.get("verify", [])]
    return {
        "ok": all(item["ok"] for item in results),
        "target": manifest.get("alias"),
        "checks": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="core/targets/<alias>.yml")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--report", default="")
    parser.add_argument("--alias", default="")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if args.alias:
        manifest = load_target(args.alias)
    else:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise HarnessError("PyYAML is required") from exc
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        manifest.setdefault("alias", manifest_path.stem)

    report = verify(Path(args.workdir).resolve(), manifest)
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
