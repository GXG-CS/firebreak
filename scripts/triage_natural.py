"""Aggregate a natural-run directory: what passed, what failed, and how.

Reads every index.jsonl under a run directory and prints a table plus counts.
No classification of failure *type* yet -- that needs reading the traces first.

    python scripts/triage_natural.py eval/results/natural_qwen14b
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def load_rows(root: Path) -> list[dict]:
    rows: list[dict] = []
    for index in sorted(root.rglob("index.jsonl")):
        for line in index.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                row["_dir"] = str(index.parent)
                rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise a clean tau2 sweep.")
    parser.add_argument("root")
    parser.add_argument("--failed-only", action="store_true")
    args = parser.parse_args(argv)

    rows = load_rows(Path(args.root))
    if not rows:
        print("no index.jsonl found")
        return 1
    rows.sort(key=lambda r: int(r["task_id"]) if str(r["task_id"]).isdigit() else 0)

    header = f"{'task':>5} {'result':>8} {'db':>4} {'comm':>5} {'turns':>5} {'end':>14} {'s':>6}  tools"
    print(header)
    print("-" * len(header))
    for row in rows:
        if args.failed_only and row.get("success"):
            continue
        if row.get("status") == "crashed":
            print(f"{row['task_id']:>5} {'CRASH':>8} {'-':>4} {'-':>5} {'-':>5} {'-':>14} "
                  f"{row.get('wall_s', 0):>6}  {row.get('error', '').splitlines()[-1][:80]}")
            continue
        tools = ",".join(row.get("tool_calls", [])) or "-"
        print(f"{row['task_id']:>5} {'PASS' if row['success'] else 'FAIL':>8} "
              f"{row['db_score']:>4.0f} {row['communicate_score']:>5.2f} {row['turns']:>5} "
              f"{row['terminated_by']:>14} {row['wall_s']:>6.0f}  {tools[:100]}")

    ok = [r for r in rows if r.get("status") == "ok"]
    passed = [r for r in ok if r["success"]]
    failed = [r for r in ok if not r["success"]]
    crashed = [r for r in rows if r.get("status") == "crashed"]
    print(f"\n{len(passed)} passed / {len(failed)} failed / {len(crashed)} crashed  "
          f"(of {len(rows)} episodes)")

    if failed:
        print("\nfailure reasons:")
        for reason, n in collections.Counter(
            tuple(r.get("success_reasons", [])) for r in failed
        ).most_common():
            print(f"  {n:>3}  {' + '.join(reason) or 'none recorded'}")
        print("\nhow those episodes ended:")
        for end, n in collections.Counter(r["terminated_by"] for r in failed).most_common():
            print(f"  {n:>3}  {end}")
        print("\nsensitive tools used in failed episodes:")
        counts = collections.Counter(
            name for r in failed for name in r.get("sensitive_calls", [])
        )
        for name, n in counts.most_common():
            print(f"  {n:>3}  {name}")
        if not counts:
            print("   -  none (no failed episode wrote to the database)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
