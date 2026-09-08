"""Command line interface.

Current:
    firebreak trace <trace.jsonl>        read a capture, source by source
    firebreak provenance <trace.jsonl>   rebuild provenance from a capture

Legacy (the earlier cascade work, kept and still tested, not the current line):
    firebreak run <example.py>
    firebreak report <trace.jsonl>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from firebreak.injection.faults import FaultPlan
from firebreak.runner import analyze, load_example, run_app
from firebreak.tracing.recorder import Trace


def _cmd_run(args: argparse.Namespace) -> int:
    module = load_example(args.example)
    plan = FaultPlan.parse(args.inject)
    app = module.build(model=args.model, plan=plan)
    analysis = run_app(app, plan, save=args.out)
    if args.json:
        print(analysis.report.to_json(indent=2))
    else:
        print(analysis.report.render())
        if args.out:
            print(f"\nTrace saved to {args.out}")
    if args.graph:
        print("\nExecution graph")
        print(analysis.graph.to_dict())
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    trace = Trace.from_jsonl(args.trace)
    outcome = str(trace.meta.get("outcome", "UNKNOWN"))
    analysis = analyze(trace, outcome)
    print(analysis.report.to_json(indent=2) if args.json else analysis.report.render())
    return 0


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


def _cmd_provenance(args: argparse.Namespace) -> int:
    """Reconstruction: rebuild the provenance of a saved capture and write it beside the trace."""
    from scripts.dump_provenance import dump  # noqa: PLC0415 - the script owns the output layout

    for written in [dump(Path(args.trace), legacy_audit=args.legacy_audit)]:
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
        description="Capture a LangGraph run and rebuild its provenance from LangGraph's own records.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    trace = sub.add_parser("trace", help="read a capture: what the stream, the callbacks and the checkpointer each reported")
    trace.add_argument("trace", help="path to a JSONL trace")
    trace.add_argument("--out", action="store_true", help="write <trace>.capture.txt instead of printing")
    trace.add_argument("--no-checkpoints", action="store_true", help="omit the checkpointer ledger")
    trace.set_defaults(func=_cmd_trace)

    prov = sub.add_parser("provenance", help="rebuild provenance from a capture (.provenance.json / .txt / .md)")
    prov.add_argument("trace", help="path to a JSONL trace")
    prov.add_argument("--quiet", action="store_true", help="write the files without printing them")
    prov.add_argument("--legacy-audit", action="store_true", help="also check the legacy execution graph against the recorded relations")
    prov.set_defaults(func=_cmd_provenance)

    run = sub.add_parser("run", help="LEGACY: run an example graph with injected faults and report the cascade")
    run.add_argument("example", help="path to an example module exposing build(model, plan)")
    run.add_argument("--inject", action="append", default=[], metavar="SPEC", help="fault spec kind:target[:on_call[:payload]]; repeatable")
    run.add_argument("--model", default="fake", help="model backend understood by the example (default: fake)")
    run.add_argument("--out", default=None, help="save the trace as JSONL")
    run.add_argument("--json", action="store_true", help="print the report as JSON")
    run.add_argument("--graph", action="store_true", help="also print the reconstructed execution graph")
    run.set_defaults(func=_cmd_run)

    rep = sub.add_parser("report", help="LEGACY: re-analyse a saved trace with the cascade reporter")
    rep.add_argument("trace", help="path to a JSONL trace written by `firebreak run --out`")
    rep.add_argument("--json", action="store_true")
    rep.set_defaults(func=_cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
