"""Cascade report model and rendering."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from firebreak.detection.signals import Signal
from firebreak.graph.execution import ExecutionGraph
from firebreak.graph.propagation import Propagation
from firebreak.tracing.recorder import Trace


@dataclass
class CascadeReport:
    detected: bool
    outcome: str
    source: Optional[dict] = None
    injected: list = field(default_factory=list)
    signals: list = field(default_factory=list)
    path: list = field(default_factory=list)  # node names, BFS order from the source
    levels: list = field(default_factory=list)  # list of lists of node labels per BFS depth
    affected: int = 0
    total: int = 0
    blast_radius: float = 0.0
    detection_delay: Optional[int] = None
    wall_time: float = 0.0
    node_runs: list = field(default_factory=list)
    propagation_vs_content: Optional[dict] = None
    turns: Optional[int] = None
    reached: dict = field(default_factory=dict)  # node name -> bool
    harmful_actions: list = field(default_factory=list)  # sensitive tool calls made by affected runs

    @property
    def utility_damaged(self) -> bool:
        return self.outcome.upper().startswith("FAIL")

    # ---- rendering ------------------------------------------------------------------------
    def render(self) -> str:
        lines: list[str] = []
        if self.detected:
            lines.append("Cascade detected")
            lines.append("")
            lines.append("Source")
            src = self.source or {}
            tag = "oracle" if src.get("oracle") else src.get("kind", "?")
            turn = f", turn {src.get('turn')}" if src.get("turn") is not None else ""
            lines.append(f"  {src.get('location', '?'):<28} {tag}  (step {src.get('step', '?')}{turn})")
            lines.append("")
            lines.append("Propagation")
            for depth, labels in enumerate(self.levels):
                if depth:
                    lines.append("      ↓")
                lines.append("  " + "  |  ".join(labels))
            lines.append("")
            lines.append(f"Affected nodes: {self.affected} / {self.total}")
            lines.append(f"Blast radius: {self.blast_radius:.0%}")
            delay = "n/a" if self.detection_delay is None else f"{self.detection_delay} steps"
            lines.append(f"Detection delay: {delay}")
            if self.reached:
                lines.append("")
                for name, hit in self.reached.items():
                    lines.append(f"Reached {name:<20} {'yes' if hit else 'no'}")
            if self.harmful_actions:
                lines.append("")
                lines.append("Harmful actions (sensitive tools called downstream of the source)")
                for action in self.harmful_actions:
                    turn = f"turn {action.get('turn')}" if action.get("turn") is not None else ""
                    lines.append(f"  {action.get('node')}.{action.get('tool')}({action.get('args')})  {turn}")
        else:
            lines.append("No cascade detected")
            lines.append("")
            lines.append(f"Nodes executed: {', '.join(self.node_runs)}  ({self.total} runs)")
        if self.injected:
            lines.append("")
            lines.append("Injected (ground truth)")
            for entry in self.injected:
                lines.append(f"  {entry.get('fault_id', '?')}  {entry.get('kind')}:{entry.get('target')}  call #{entry.get('call_no')}")
                for change in entry.get("fields") or []:
                    if change.get("changed"):
                        lines.append(f"      {change.get('field')}: {change.get('before')}")
                        lines.append(f"      {' ' * len(str(change.get('field')))}  -> {change.get('after')}")
        if len(self.signals) > 1:
            lines.append("")
            lines.append("Other signals")
            for sig in self.signals[1:]:
                lines.append(f"  {sig.get('location', '?'):<28} {sig.get('kind', '?')}  (step {sig.get('step', '?')})")
        lines.append("")
        if self.turns is not None:
            lines.append(f"Turns: {self.turns}")
        lines.append(f"Final task: {self.outcome}")
        lines.append(f"Utility damaged: {'yes' if self.utility_damaged else 'no'}")
        lines.append(f"Wall time: {self.wall_time:.2f}s")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["utility_damaged"] = self.utility_damaged
        return data

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), default=str, **kwargs)


def _levels(graph: ExecutionGraph, propagation: Propagation) -> list[list[str]]:
    by_depth: dict[int, list[str]] = {}
    for run_id in propagation.affected:
        run = graph.get(run_id)
        if run is None:
            continue
        by_depth.setdefault(propagation.levels.get(run_id, 0), []).append(run.label)
    return [by_depth[d] for d in sorted(by_depth)]


def _path_names(graph: ExecutionGraph, propagation: Propagation) -> list[str]:
    names: list[str] = []
    for run_id in propagation.affected:
        run = graph.get(run_id)
        if run is not None and run.name not in names:
            names.append(run.name)
    return names


def _injection_step(trace: Trace, graph: ExecutionGraph) -> Optional[int]:
    for event in trace.events:
        if event.kind != "injection":
            continue
        run = graph.run_at(event.seq, event.invoke_id)
        return run.step if run else None
    return None


def build_report(
    trace: Trace,
    graph: ExecutionGraph,
    signals: list[Signal],
    propagation: Optional[Propagation],
    outcome: str,
    injected: Optional[list] = None,
    content_tainted: Optional[list] = None,
    sensitive_tools: Optional[Iterable[str]] = None,
) -> CascadeReport:
    source = signals[0] if signals else None
    turns = trace.turns
    report = CascadeReport(
        detected=source is not None,
        outcome=outcome,
        source=source.to_dict() if source else None,
        injected=list(injected or []),
        signals=[s.to_dict() for s in signals],
        total=graph.total_runs,
        wall_time=float(trace.meta.get("wall_time") or 0.0),
        node_runs=graph.node_names(),
        turns=len(turns) if turns else None,
    )
    if propagation is not None and source is not None:
        report.path = _path_names(graph, propagation)
        report.levels = _levels(graph, propagation)
        report.affected = len(propagation.affected)
        report.blast_radius = propagation.blast_radius
        injected_step = _injection_step(trace, graph)
        if injected_step is not None and source.step is not None:
            report.detection_delay = max(0, int(source.step) - int(injected_step))
        report.reached = {name: (name in report.path) for name in graph.node_names()}
        sensitive = set(sensitive_tools or [])
        if sensitive:
            for run_id in propagation.affected:
                run = graph.get(run_id)
                if run is None:
                    continue
                for call in run.tools:
                    if call.name in sensitive:
                        report.harmful_actions.append(
                            {"node": run.name, "tool": call.name, "args": call.input, "turn": run.turn, "failed": call.failed}
                        )
        if content_tainted is not None:
            tainted_names = [graph.get(r).name for r in content_tainted if graph.get(r)]
            report.propagation_vs_content = {"dependency_affected": report.path, "content_tainted": tainted_names}
    return report
