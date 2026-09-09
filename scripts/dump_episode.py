"""Project a saved capture into the episode / turn hierarchy and write it beside the trace.

    python scripts/dump_episode.py docs/traces/tau2_task39_qwen14b_clean.jsonl

Writes `<trace>.episode.md`: the episode diagram, the relations that cross a turn boundary, and
one diagram per turn. `--json` additionally writes `<trace>.episode.json`.

The evidence itself is unchanged; this is a projection over what `firebreak provenance` builds.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from firebreak.episode.graph import EpisodeGraph
from firebreak.episode.views import render_episode_markdown
from firebreak.provenance.mermaid import write_mermaid_blocks
from firebreak.tracing.recorder import Trace
from scripts.dump_provenance import load_evaluation


def dump(path: Path, with_json: bool = False, evaluation: dict | None = None,
         mutating_tools=()) -> list[Path]:
    episode = EpisodeGraph.from_trace(Trace.from_jsonl(str(path)))
    stem = path.with_suffix("")
    md_path = Path(f"{stem}.episode.md")
    markdown = render_episode_markdown(episode, source_name=path.name, evaluation=evaluation,
                                       mutating_tools=mutating_tools)
    md_path.write_text(markdown)
    written = [md_path]
    written.extend(write_mermaid_blocks(md_path, markdown))
    if with_json:
        json_path = Path(f"{stem}.episode.json")
        data = episode.to_dict()
        data["turn_graphs"] = [graph.to_dict() for graph in episode]
        json_path.write_text(json.dumps(data, indent=2, default=str))
        written.append(json_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--json", action="store_true", help="also write <trace>.episode.json")
    parser.add_argument("--eval", dest="evaluation", default=None,
                        help="a run summary JSON whose evaluator scores are shown on the page")
    parser.add_argument("--mutating-tools", default="",
                        help="comma-separated tool names that change state outside the process")
    parser.add_argument("--quiet", action="store_true", help="write the files without printing them")
    args = parser.parse_args(argv)
    evaluation = load_evaluation(Path(args.evaluation) if args.evaluation else None)
    mutating = [n.strip() for n in args.mutating_tools.split(",") if n.strip()]
    for raw in args.traces:
        path = Path(raw)
        written = dump(path, with_json=args.json, evaluation=evaluation, mutating_tools=mutating)
        print(f"{path}  ->  {', '.join(w.name for w in written)}")
        if not args.quiet:
            print()
            print(written[0].read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
