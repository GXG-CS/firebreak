"""Replay every benchmarks/*/scenario.yaml and report the metrics."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

import yaml

from eval.metrics import blast_radius_error, path_f1, source_attribution, summarize
from firebreak.injection.faults import FaultPlan
from firebreak.runner import load_example, run_app

ROOT = Path(__file__).resolve().parents[1]


def _baseline_wall_time(module, model: str) -> float:
    """Same graph, no tracer, plain invoke: the reference for runtime overhead."""
    app = module.build(model=model, plan=FaultPlan())
    started = time.time()
    app.graph.invoke(app.input, {"configurable": {"thread_id": str(uuid.uuid4())}})
    return time.time() - started


def run_scenario(path: Path, model_override: str | None = None, save_dir: Path | None = None) -> dict:
    scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
    truth = scenario.get("ground_truth") or {}
    model = model_override or scenario.get("model", "fake")
    module = load_example(str(ROOT / scenario["example"]))
    plan = FaultPlan.parse(scenario.get("inject") or [])
    app = module.build(model=model, plan=plan)
    save = str(save_dir / f"{scenario['name']}.jsonl") if save_dir else None
    analysis = run_app(app, plan, save=save)
    report = analysis.report

    true_cascade = bool(truth.get("cascade", False))
    true_path = list(truth.get("path") or [])
    baseline = _baseline_wall_time(module, model)
    overhead = (report.wall_time / baseline) if baseline > 0 else None
    row = {
        "scenario": scenario["name"],
        "predicted_cascade": report.detected,
        "true_cascade": true_cascade,
        "predicted_source": (report.source or {}).get("node"),
        "true_source": truth.get("source_node"),
        "source_correct": source_attribution((report.source or {}).get("node"), truth.get("source_node")) if true_cascade else None,
        "predicted_path": report.path,
        "true_path": true_path,
        "path_f1": path_f1(report.path, true_path) if true_cascade else None,
        "blast_radius": report.blast_radius,
        "blast_radius_error": blast_radius_error(report.blast_radius, len(true_path), report.total) if true_cascade else None,
        "detection_delay": report.detection_delay,
        "outcome": report.outcome,
        "true_outcome": truth.get("outcome"),
        "outcome_match": (report.outcome == truth.get("outcome")) if truth.get("outcome") else None,
        "wall_time": report.wall_time,
        "baseline_wall_time": baseline,
        "overhead": overhead,
    }
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Firebreak benchmark scenarios.")
    parser.add_argument("--model", default=None, help="override the model backend for every scenario")
    parser.add_argument("--only", default=None, help="run a single scenario by name")
    parser.add_argument("--save-traces", action="store_true", help="write traces under eval/results/traces")
    args = parser.parse_args(argv)

    scenario_files = sorted((ROOT / "benchmarks").glob("*/scenario.yaml"))
    if args.only:
        scenario_files = [p for p in scenario_files if p.parent.name == args.only]
    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = results_dir / "traces" if args.save_traces else None
    if trace_dir:
        trace_dir.mkdir(parents=True, exist_ok=True)

    rows = [run_scenario(p, args.model, trace_dir) for p in scenario_files]
    summary = summarize(rows)

    header = f"{'scenario':<22}{'cascade':<9}{'source':<12}{'pathF1':<8}{'blast':<7}{'delay':<7}{'outcome':<9}{'ovh':<6}"
    print(header)
    print("-" * len(header))
    for r in rows:
        f1 = "-" if r["path_f1"] is None else f"{r['path_f1']:.2f}"
        src = "-" if r["source_correct"] is None else ("ok" if r["source_correct"] else "WRONG")
        delay = "-" if r["detection_delay"] is None else str(r["detection_delay"])
        ovh = "-" if r["overhead"] is None else f"{r['overhead']:.1f}x"
        flag = "" if r["predicted_cascade"] == r["true_cascade"] else " <- mismatch"
        print(f"{r['scenario']:<22}{str(r['predicted_cascade']):<9}{src:<12}{f1:<8}{r['blast_radius']:<7.0%}{delay:<7}{r['outcome']:<9}{ovh:<6}{flag}")
    print()
    print(json.dumps(summary, indent=2))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    (results_dir / f"{stamp}.json").write_text(json.dumps({"rows": rows, "summary": summary}, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
