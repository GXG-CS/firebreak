"""Command line interface: ``firebreak run`` and ``firebreak report``."""

from __future__ import annotations

import argparse
import sys

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="firebreak", description="Stop cascading failures in LangGraph multi-agent systems.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run an example graph, optionally with injected faults, and report the cascade")
    run.add_argument("example", help="path to an example module exposing build(model, plan)")
    run.add_argument("--inject", action="append", default=[], metavar="SPEC", help="fault spec kind:target[:on_call[:payload]]; repeatable")
    run.add_argument("--model", default="fake", help="model backend understood by the example (default: fake)")
    run.add_argument("--out", default=None, help="save the trace as JSONL")
    run.add_argument("--json", action="store_true", help="print the report as JSON")
    run.add_argument("--graph", action="store_true", help="also print the reconstructed execution graph")
    run.set_defaults(func=_cmd_run)

    rep = sub.add_parser("report", help="re-analyse a saved trace")
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
