#!/usr/bin/env python3
"""Bootstrap labels: создать стандартные labels в репозитории.

Пример:
    GH_TOKEN=... python scripts/bootstrap_labels.py --repo owner/harness-core
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import GitHub, label_color  # noqa: E402

LABELS = {
    "harness:task": "Открытая задача для агента",
    "harness:active": "Взята в работу",
    "harness:failed": "Была ошибка",
    "harness:blocked": "Вторая ошибка, не брать",
    "harness:done": "Закрыта",
    "harness:needs-approval": "Kernel PR ждёт ручного approve",
    "harness:dry-run": "PR создан без merge (phase 0)",
    "allow-tests": "Разрешить менять tests",
    "allow-deps": "Разрешить менять dependency-файлы",
    "target:sandbox": "Target: sandbox",
    "target:core": "Target: core",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    args = parser.parse_args(argv)
    api = GitHub()
    for name, description in LABELS.items():
        api.ensure_label(args.repo, name, label_color(name), description)
        print(f"ok {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
