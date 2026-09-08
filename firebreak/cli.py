"""Command line interface.

    firebreak trace <trace.jsonl>        read a capture, source by source
    firebreak episode <trace.jsonl>      the episode / turn structure
    firebreak provenance <trace.jsonl>   the relation-level evidence underneath it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from firebreak.tracing.recorder import Trace


def _cmd_trace(args: argparse.Namespace) -> int:
    """Capture, read back: what each runtime source reported, per task execution."""
    from firebreak.tracing.view import render_trace

    path = Path(args.trace)
    text = render_trace(Trace.from_jsonl(str(path)), source_name=path.name,
                        show_checkpoints=not args.no_checkpoints)
    if args.out:
        target = Path(f"{path.with_suffix('')}.capture.txt")
        target.write_text(text)
        print(f"{path}  ->  {target.name}")
    else:
        print(text)
    return 0


def _cmd_episode(args: argparse.Namespace) -> int:
    """Project a capture into the episode / turn hierarchy."""
    from scripts.dump_episode import dump  # noqa: PLC0415 - the script owns the output layout

    written = dump(Path(args.trace), with_json=args.json)
    print(f"{args.trace}  ->  {', '.join(w.name for w in written)}")
    if not args.quiet:
        print()
        print(written[0].read_text())
    return 0


def _cmd_provenance(args: argparse.Namespace) -> int:
    """The evidence underneath the structure: WRITE, READ, TRIGGER, DERIVED_FROM."""
    from scripts.dump_provenance import dump  # noqa: PLC0415 - the script owns the output layout

    written = dump(Path(args.trace))
    print(f"{args.trace}  ->  {', '.join(w.name for w in written)}")
    if not args.quiet:
        for out in written:
            if out.suffix in (".txt", ".md"):
                print()
                print(out.read_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firebreak",
        description="Capture a LangGraph run and rebuild its structure from LangGraph's own records.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    trace = sub.add_parser("trace", help="read a capture: what the stream, the callbacks and the checkpointer each reported")
    trace.add_argument("trace", help="path to a JSONL trace")
    trace.add_argument("--out", action="store_true", help="write <trace>.capture.txt instead of printing")
    trace.add_argument("--no-checkpoints", action="store_true", help="omit the checkpointer ledger")
    trace.set_defaults(func=_cmd_trace)

    episode = sub.add_parser("episode", help="the episode / turn hierarchy (.episode.md)")
    episode.add_argument("trace", help="path to a JSONL trace")
    episode.add_argument("--json", action="store_true", help="also write <trace>.episode.json")
    episode.add_argument("--quiet", action="store_true", help="write the files without printing them")
    episode.set_defaults(func=_cmd_episode)

    prov = sub.add_parser("provenance", help="the relation-level evidence (.provenance.json / .txt / .md)")
    prov.add_argument("trace", help="path to a JSONL trace")
    prov.add_argument("--quiet", action="store_true", help="write the files without printing them")
    prov.set_defaults(func=_cmd_provenance)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
