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
from firebreak.tracing.recorder import Trace


def dump(path: Path, with_json: bool = False) -> list[Path]:
    episode = EpisodeGraph.from_trace(Trace.from_jsonl(str(path)))
    stem = path.with_suffix("")
    md_path = Path(f"{stem}.episode.md")
    md_path.write_text(render_episode_markdown(episode, source_name=path.name))
    written = [md_path]
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
    parser.add_argument("--quiet", action="store_true", help="write the files without printing them")
    args = parser.parse_args(argv)
    for raw in args.traces:
        path = Path(raw)
        written = dump(path, with_json=args.json)
        print(f"{path}  ->  {', '.join(w.name for w in written)}")
        if not args.quiet:
            print()
            print(written[0].read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
