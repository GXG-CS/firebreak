"""Run a shard of clean tau2 airline episodes and keep every result for inspection.

No fault injection and no framework changes: this measures how the LangGraph MAS
fails on its own, so we can see what natural failures actually look like before
building anything on top of them.

    python scripts/run_natural.py --tasks 0-9 --outdir eval/results/natural/run1

Per task it writes:
    task<ID>.jsonl          the Firebreak trace
    task<ID>.summary.json   reward, transcript, tool calls, episode structure
and appends one line per task to index.jsonl (flushed immediately, so a job that
runs out of time still leaves a readable index).
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

from firebreak.integrations.tau2_airline.mas import SENSITIVE_TOOLS
from firebreak.integrations.tau2_airline.runner import DEFAULT_MAX_TURNS, run_episode


def parse_tasks(spec: str) -> list[str]:
    """Expand "0-9,20,30-32" into a list of task ids."""
    ids: list[str] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            ids.extend(str(i) for i in range(int(lo), int(hi) + 1))
        else:
            ids.append(part)
    return ids


def episode_row(task_id: str, result, wall_s: float) -> dict:
    """One index line: enough to triage a failure without opening the trace."""
    tool_names = [c["name"] for c in result.tool_calls]
    episode = result.episode
    trace = result.trace
    kinds: dict[str, int] = {}
    if trace is not None:
        for event in trace.events:
            kinds[event.kind] = kinds.get(event.kind, 0) + 1
    return {
        "task_id": task_id,
        "status": "ok",
        "success": result.success,
        "reward": result.reward,
        "db_score": result.db_score,
        "communicate_score": result.communicate_score,
        "success_reasons": result.success_reasons,
        "turns": result.turns,
        "terminated_by": result.terminated_by,
        "wall_s": round(wall_s, 1),
        "tool_calls": tool_names,
        "sensitive_calls": [n for n in tool_names if n in SENSITIVE_TOOLS],
        "tool_errors": [c["name"] for c in result.tool_calls if c["error"]],
        "event_kinds": kinds,
        "graph_turns": None if episode is None else len(episode.turns),
        "cross_turn_links": None if episode is None else len(episode.cross_turn_links()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run clean tau2 airline episodes and save them all.")
    parser.add_argument("--tasks", default="0-49", help="task ids, e.g. 0-9 or 0,3,5-7")
    parser.add_argument("--model", default="openai")
    parser.add_argument("--user-model", default=None)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    index_path = outdir / "index.jsonl"

    task_ids = parse_tasks(args.tasks)
    print(f"running {len(task_ids)} clean episodes: {task_ids}", flush=True)

    passed = failed = crashed = 0
    for task_id in task_ids:
        trace_path = outdir / f"task{task_id}.jsonl"
        started = time.time()
        try:
            result = run_episode(
                task_id,
                model=args.model,
                inject=[],
                max_turns=args.max_turns,
                user_model=args.user_model,
                save=str(trace_path),
            )
        except Exception:  # one bad task must not end the shard
            crashed += 1
            row = {
                "task_id": task_id,
                "status": "crashed",
                "success": False,
                "wall_s": round(time.time() - started, 1),
                "error": traceback.format_exc(limit=8),
            }
            print(f"task {task_id}: CRASHED after {row['wall_s']}s", flush=True)
        else:
            row = episode_row(task_id, result, time.time() - started)
            summary = result.summary()
            summary["transcript"] = result.transcript
            (outdir / f"task{task_id}.summary.json").write_text(
                json.dumps(summary, indent=2, default=str)
            )
            if result.success:
                passed += 1
            else:
                failed += 1
            print(
                f"task {task_id}: {result.outcome} reward={result.reward:.2f} "
                f"db={result.db_score:.0f} comm={result.communicate_score:.2f} "
                f"turns={result.turns} end={result.terminated_by} "
                f"tools={row['tool_calls']} ({row['wall_s']}s)",
                flush=True,
            )
        with index_path.open("a") as fp:
            fp.write(json.dumps(row, default=str) + "\n")

    print(f"\nshard done: {passed} passed, {failed} failed, {crashed} crashed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
