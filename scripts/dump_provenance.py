"""Rebuild observed state provenance from a saved trace and dump it for human inspection.

    python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_clean.jsonl

Writes, next to each input trace:
  <trace>.provenance.json     tasks, state versions, relations, every one with its evidence
  <trace>.provenance.txt      the same, readable, plus what the model cannot express yet
  <trace>.provenance.md       three Mermaid diagrams (data flow, state lineage, control flow),
                              which GitHub renders with no tooling

The trace must have been recorded with checkpoint capture (`checkpoint_fact` events); older
traces will produce an empty graph with a warning saying so.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from firebreak.provenance.graph import ProvenanceGraph
from firebreak.provenance.mermaid import render_markdown
from firebreak.provenance.render import render_json, render_text
from firebreak.tracing.recorder import Trace


def dump(path: Path) -> list[Path]:
    trace = Trace.from_jsonl(str(path))
    prov = ProvenanceGraph.from_trace(trace)

    stem = path.with_suffix("")
    json_path = Path(f"{stem}.provenance.json")
    text_path = Path(f"{stem}.provenance.txt")
    md_path = Path(f"{stem}.provenance.md")
    json_path.write_text(render_json(prov, trace))
    text_path.write_text(render_text(prov, trace, source_name=path.name))
    md_path.write_text(render_markdown(prov, trace, source_name=path.name))
    written = [json_path, text_path, md_path]

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--quiet", action="store_true", help="write the files without printing them")
    args = parser.parse_args(argv)
    for raw in args.traces:
        path = Path(raw)
        written = dump(path)
        print(f"{path}  ->  {', '.join(w.name for w in written)}")
        if not args.quiet:
            for out in written:
                print()
                print(out.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
