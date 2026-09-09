"""Rebuild observed state provenance from a saved trace and dump it for human inspection.

    python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_clean.jsonl

Writes, next to each input trace:
  <trace>.provenance.json     tasks, state versions, relations, every one with its evidence
  <trace>.provenance.txt      the same, readable, plus what the model cannot express yet
  <trace>.provenance.md       three Mermaid diagrams (data flow, state lineage, control flow),
                              which GitHub renders with no tooling
  <trace>.provenance.NN.mmd   each of those diagrams on its own

The trace must have been recorded with checkpoint capture (`checkpoint_fact` events); older
traces will produce an empty graph with a warning saying so.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from firebreak.provenance.graph import ProvenanceGraph
from firebreak.provenance.mermaid import render_markdown, write_mermaid_blocks
from firebreak.provenance.render import render_json, render_text
from firebreak.tracing.recorder import Trace


def load_evaluation(path: Path | None) -> dict | None:
    """The benchmark's own scoring of this episode, read verbatim from a run summary."""
    if path is None:
        return None
    data = json.loads(Path(path).read_text())
    keys = ("success", "reward", "db_score", "communicate_score", "success_reasons",
            "turns", "terminated_by")
    return {k: data.get(k) for k in keys if k in data}


def dump(path: Path, evaluation: dict | None = None, mutating_tools=()) -> list[Path]:
    trace = Trace.from_jsonl(str(path))
    prov = ProvenanceGraph.from_trace(trace)

    stem = path.with_suffix("")
    json_path = Path(f"{stem}.provenance.json")
    text_path = Path(f"{stem}.provenance.txt")
    md_path = Path(f"{stem}.provenance.md")
    markdown = render_markdown(prov, trace, source_name=path.name, evaluation=evaluation,
                               mutating_tools=mutating_tools)
    json_path.write_text(render_json(prov, trace))
    text_path.write_text(render_text(prov, trace, source_name=path.name))
    md_path.write_text(markdown)
    written = [json_path, text_path, md_path]
    written.extend(write_mermaid_blocks(md_path, markdown))

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--eval", dest="evaluation", default=None,
                        help="a run summary JSON whose evaluator scores are shown on the page")
    parser.add_argument("--mutating-tools", default="",
                        help="comma-separated tool names that change state outside the process; "
                             "they are marked as such, never inferred from the name")
    parser.add_argument("--quiet", action="store_true", help="write the files without printing them")
    args = parser.parse_args(argv)
    evaluation = load_evaluation(Path(args.evaluation) if args.evaluation else None)
    mutating = [n.strip() for n in args.mutating_tools.split(",") if n.strip()]
    for raw in args.traces:
        path = Path(raw)
        written = dump(path, evaluation=evaluation, mutating_tools=mutating)
        print(f"{path}  ->  {', '.join(w.name for w in written)}")
        if not args.quiet:
            for out in written:
                print()
                print(out.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
