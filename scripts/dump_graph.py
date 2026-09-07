"""Reconstruct the ExecutionGraph of saved traces and write it next to them.

    python scripts/dump_graph.py docs/traces/*.jsonl

For each input trace `X.jsonl` it writes `X.graph.json` (machine-readable: node runs, data-flow
edges, per-run tool calls, plus the static graph the run was compiled from) and `X.graph.txt`
(the same thing as a table, followed by the cascade report derived from it).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from firebreak.graph.execution import ExecutionGraph
from firebreak.integrations.tau2_airline.mas import SENSITIVE_TOOLS
from firebreak.runner import analyze
from firebreak.tracing.recorder import Trace


def dump(path: Path) -> tuple[Path, Path]:
    trace = Trace.from_jsonl(str(path))
    graph = ExecutionGraph.from_trace(trace)
    data = graph.to_dict()
    for run, raw in zip(sorted(graph.runs, key=lambda r: r.start_seq), data["runs"]):
        raw["label"] = run.label
        raw["tool_calls"] = [{"name": t.name, "input": t.input, "failed": t.failed} for t in run.tools]
        raw["model_calls"] = len(run.models)
    data["static_graph"] = trace.meta.get("static_graph")
    json_path = path.with_suffix(".graph.json")
    json_path.write_text(json.dumps(data, indent=2, default=str))

    static_edges = [(e["source"], e["target"]) for e in (data["static_graph"] or {}).get("edges", [])]
    lines = [f"# ExecutionGraph reconstructed from {path.name}", ""]
    lines.append(f"static edges declared by the compiled graph: {static_edges}")
    lines.append(f"{len(graph.runs)} node runs, {len(graph.edges)} data-flow edges")
    lines += ["", "## Node runs", "", f"{'id':<26} {'node':<12} {'turn':>4} {'step':>4}  {'writes':<12} tools"]
    for run in sorted(graph.runs, key=lambda r: r.start_seq):
        tools = ", ".join(
            f"{t.name}({list(t.input.values())[0] if isinstance(t.input, dict) and t.input else ''})"
            for t in run.tools
        )
        lines.append(
            f"{run.id:<26} {run.name:<12} {run.turn!s:>4} {run.step!s:>4}  "
            f"{','.join(run.data_writes.keys()):<12} {tools}"
        )
    lines += ["", "## Data-flow edges  (A -> B means B could read what A wrote)", ""]
    for edge in graph.edges:
        src, dst = graph.get(edge.src), graph.get(edge.dst)
        mark = "  [cross-turn]" if edge.cross_turn else ""
        lines.append(f"{src.label:<24} -> {dst.label:<24} via {edge.via[0]:<26} keys={edge.data_keys}{mark}")
    analysis = analyze(trace, str(trace.meta.get("outcome", "?")), marker=None, oracle=True, sensitive_tools=SENSITIVE_TOOLS)
    lines += ["", "## Cascade report derived from this graph", "", analysis.report.render()]
    text_path = path.with_suffix(".graph.txt")
    text_path.write_text("\n".join(lines) + "\n")
    return json_path, text_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", help="trace JSONL files")
    args = parser.parse_args(argv)
    for raw in args.traces:
        path = Path(raw)
        if path.name.endswith(".graph.json"):
            continue
        json_path, text_path = dump(path)
        print(f"{path}  ->  {json_path.name}, {text_path.name}")
        print(text_path.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
