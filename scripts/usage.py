#!/usr/bin/env python3
"""Usage: агрегировать usage*.json прогонов в отчёт по маршрутам и стоимости."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_usage(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def aggregate(directory: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    totals = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
    for path in sorted(directory.rglob("usage*.json")):
        data = load_usage(path)
        if not data:
            continue
        row = {
            "file": str(path),
            "route": data.get("route") or data.get("model") or path.stem,
            "model": data.get("model"),
            "api_calls": int(number(data.get("api_calls"))),
            "input_tokens": int(number(data.get("input_tokens") or data.get("prompt_tokens"))),
            "output_tokens": int(number(data.get("output_tokens") or data.get("completion_tokens"))),
            "estimated_cost_usd": number(data.get("estimated_cost") or data.get("estimated_cost_usd")),
        }
        rows.append(row)
        totals["api_calls"] += row["api_calls"]
        totals["input_tokens"] += row["input_tokens"]
        totals["output_tokens"] += row["output_tokens"]
        totals["estimated_cost_usd"] += row["estimated_cost_usd"]
    return {"rows": rows, "totals": totals}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=".", help="каталог с usage*.json")
    parser.add_argument("--json", action="store_true", help="вывести JSON")
    args = parser.parse_args(argv)

    report = aggregate(Path(args.dir))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print(f"{'route':28} {'model':40} {'calls':>6} {'in':>10} {'out':>10} {'usd':>10}")
    for row in report["rows"]:
        print(
            f"{str(row['route'])[:28]:28} {str(row['model'])[:40]:40} "
            f"{row['api_calls']:6d} {row['input_tokens']:10d} {row['output_tokens']:10d} "
            f"{row['estimated_cost_usd']:10.4f}"
        )
    totals = report["totals"]
    print(
        f"{'TOTAL':28} {'':40} {totals['api_calls']:6d} "
        f"{totals['input_tokens']:10d} {totals['output_tokens']:10d} "
        f"{totals['estimated_cost_usd']:10.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
