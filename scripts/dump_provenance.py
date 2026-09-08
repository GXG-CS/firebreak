"""Rebuild observed state provenance from a saved trace and dump it for human inspection.

    python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_clean.jsonl

Writes, next to each input trace:
  <trace>.provenance.json     tasks, state versions, WRITE / SEEN relations, every one with evidence
  <trace>.provenance.txt      the same, readable, plus what the model cannot express yet
  <trace>.legacy_audit.txt    the old static-edge heuristic checked against the observed relations

The trace must have been recorded with checkpoint capture (`checkpoint_fact` events); older
traces will produce an empty graph with a warning saying so.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from firebreak.graph.execution import ExecutionGraph
from firebreak.provenance.graph import ProvenanceGraph
from firebreak.provenance.render import compare_with_legacy, render_comparison, render_json, render_text
from firebreak.tracing.recorder import Trace


def dump(path: Path) -> tuple[Path, Path, Path]:
    trace = Trace.from_jsonl(str(path))
    prov = ProvenanceGraph.from_trace(trace)
    legacy = ExecutionGraph.from_trace(trace)

    stem = path.with_suffix("")
    json_path = Path(f"{stem}.provenance.json")
    text_path = Path(f"{stem}.provenance.txt")
    audit_path = Path(f"{stem}.legacy_audit.txt")

    json_path.write_text(render_json(prov, trace))
    text_path.write_text(render_text(prov, trace, source_name=path.name))
    audit_path.write_text(render_comparison(compare_with_legacy(prov, legacy)))
    return json_path, text_path, audit_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--quiet", action="store_true", help="write the files without printing them")
    args = parser.parse_args(argv)
    for raw in args.traces:
        path = Path(raw)
        json_path, text_path, audit_path = dump(path)
        print(f"{path}  ->  {json_path.name}, {text_path.name}, {audit_path.name}")
        if not args.quiet:
            print()
            print(text_path.read_text())
            print(audit_path.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
