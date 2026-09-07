"""Shared pipeline: build app -> record -> graph -> detect -> propagate -> report."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from firebreak.detection.signals import detect
from firebreak.graph.execution import ExecutionGraph
from firebreak.graph.propagation import content_taint, propagate
from firebreak.injection.faults import DEFAULT_MARKER, FaultPlan
from firebreak.reporting.report import CascadeReport, build_report
from firebreak.tracing.recorder import Trace, record


@dataclass
class App:
    """What an example module's ``build()`` returns."""

    graph: Any
    input: Any
    evaluate: Callable[[Any], str]
    validators: dict = field(default_factory=dict)
    name: str = ""


@dataclass
class Analysis:
    trace: Trace
    graph: ExecutionGraph
    signals: list
    propagation: Any
    report: CascadeReport


def load_example(path: str) -> Any:
    """Import an example module from a file path."""
    file = Path(path).resolve()
    if not file.exists():
        raise FileNotFoundError(file)
    module_name = f"firebreak_example_{file.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "build"):
        raise AttributeError(f"{file} has no build(model=..., plan=...) function")
    return module


def analyze(
    trace: Trace,
    outcome: str,
    validators: Optional[dict] = None,
    injected: Optional[list] = None,
    marker: Optional[str] = DEFAULT_MARKER,
    oracle: bool = False,
    sensitive_tools: Optional[Iterable[str]] = None,
) -> Analysis:
    graph = ExecutionGraph.from_trace(trace)
    signals = detect(trace, graph, validators=validators, marker=marker, oracle=oracle)
    propagation = None
    tainted = None
    if signals and signals[0].run_id:
        propagation = propagate(graph, signals[0].run_id)
        tainted = content_taint(graph, marker) if marker else None
    if injected is None:
        injected = [e.payload for e in trace.of_kind("injection")]
    report = build_report(trace, graph, signals, propagation, outcome, injected=injected, content_tainted=tainted, sensitive_tools=sensitive_tools)
    return Analysis(trace=trace, graph=graph, signals=signals, propagation=propagation, report=report)


def run_app(app: App, plan: Optional[FaultPlan] = None, *, save: Optional[str] = None, config: Optional[dict] = None) -> Analysis:
    """Record one run of ``app`` (with ``plan`` already applied at build time) and analyse it."""
    trace = Trace()
    if plan is not None:
        plan.bind(trace)
    record(app.graph, app.input, trace=trace, config=config)
    try:
        outcome = app.evaluate(trace.final_state)
    except Exception as exc:  # the evaluator must never crash the report
        outcome = f"UNKNOWN ({type(exc).__name__}: {exc})"
    trace.meta["outcome"] = outcome
    trace.meta["app"] = app.name
    if plan is not None:
        trace.meta["faults"] = [f.spec for f in plan.faults]
    if save:
        trace.to_jsonl(save)
    marker = plan.marker if plan is not None else DEFAULT_MARKER
    return analyze(trace, outcome, validators=app.validators, injected=list(plan.log) if plan else [], marker=marker)
