#!/usr/bin/env python3
"""Config check: валидация targets, guard rules и workflow-файлов core."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guard.check import load_rules  # noqa: E402
from scripts.common import HarnessError, TARGETS_DIR, load_target  # noqa: E402


def main() -> int:
    errors: list[str] = []
    targets = sorted(TARGETS_DIR.glob("*.yml"))
    if not targets:
        errors.append("no targets/*.yml")
    for path in targets:
        try:
            manifest = load_target(path.stem)
            if "OWNER/" in manifest["repo"]:
                errors.append(f"{path.name}: repo placeholder OWNER/")
            print(f"target {path.stem}: {manifest['repo']} checks={len(manifest['verify'])}")
        except HarnessError as exc:
            errors.append(f"{path.name}: {exc}")

    try:
        rules = load_rules(ROOT / "guard" / "rules.yml")
        for key in ("deny_paths", "protected_tests", "dependency_files", "limits"):
            if key not in rules:
                errors.append(f"guard/rules.yml: missing {key}")
        print(f"guard rules: {len(rules.get('deny_paths', []))} deny patterns")
    except HarnessError as exc:
        errors.append(f"guard/rules.yml: {exc}")

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        errors.append(f"PyYAML: {exc}")
        yaml = None
    if yaml:
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not data.get("jobs"):
                    errors.append(f"{path.name}: no jobs")
                # PyYAML 1.1 parses the key `on` as boolean True.
                if "on" not in data and True not in data:
                    errors.append(f"{path.name}: no trigger")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.name}: {exc}")
        print(f"workflows: {len(list((ROOT / '.github' / 'workflows').glob('*.yml')))}")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("config ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
