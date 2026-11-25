#!/usr/bin/env python3
"""publish/prepare: чтение и проверка meta.json от work/agent."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import HarnessError, read_json  # noqa: E402


def load_meta(artifact_dir: Path) -> dict[str, Any]:
    path = artifact_dir / "meta.json"
    if not path.exists():
        raise HarnessError(f"artifact meta.json not found in {artifact_dir}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise HarnessError("meta.json must be an object")
    return data


def validate_meta(meta: dict[str, Any], *, target: str, issue: int) -> None:
    if str(meta.get("target")) != target:
        raise HarnessError(f"meta target {meta.get('target')!r} != {target!r}")
    try:
        meta_issue = int(meta.get("issue"))
    except (TypeError, ValueError) as exc:
        raise HarnessError(f"invalid issue in meta: {meta.get('issue')!r}") from exc
    if meta_issue != issue:
        raise HarnessError(f"meta issue {meta_issue} != {issue}")
    if meta.get("status") != "success":
        attempts = meta.get("attempts") or []
        detail = "; ".join(
            f"{a.get('route')}: {a.get('error') or a.get('exit')}" for a in attempts[-4:]
        )
        raise HarnessError(f"agent failed: {meta.get('error') or detail or 'unknown error'}")
    if not meta.get("base_sha"):
        raise HarnessError("meta.json has no base_sha")


def load_patch(artifact_dir: Path) -> Path:
    for name in ("patch.diff", "patch"):
        path = artifact_dir / name
        if path.exists() and path.stat().st_size > 0:
            return path
    raise HarnessError(f"patch not found in {artifact_dir}")
