"""Explicit fault-signal detectors (v0.1: no semantic judgement).

``oracle=True`` additionally turns the injector's own records into signals, which is how the
containment experiments separate "can we contain a known-bad message" from "can we detect it".
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from firebreak.graph.execution import ExecutionGraph
from firebreak.injection.faults import DEFAULT_MARKER
from firebreak.tracing.recorder import Trace

Validator = Callable[[dict], str | None]


@dataclass
class Signal:
    kind: str  # tool_error | timeout | node_error | corruption_marker | validator_failure | injected_fault | custom
    node: str | None
    step: int | None
    seq: int
    name: str
    detail: str
    run_id: str | None = None
    turn: int | None = None
    oracle: bool = False

    @property
    def location(self) -> str:
        if self.name and self.name != self.node:
            return f"{self.node}.{self.name}"
        return str(self.node)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["location"] = self.location
        return data


def _blob(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except Exception:  # pragma: no cover - defensive
        return repr(value)


def detect(
    trace: Trace,
    graph: ExecutionGraph,
    validators: dict[str, Validator] | None = None,
    marker: str | None = DEFAULT_MARKER,
    custom: Callable[[Trace, ExecutionGraph], list] | None = None,
    oracle: bool = False,
) -> list[Signal]:
    """Return explicit fault signals found in the trace, earliest first."""
    signals: list[Signal] = []
    seen: set = set()

    def add(signal: Signal, run=None) -> None:
        key = (signal.kind, signal.node, signal.step, signal.name, signal.turn, signal.detail[:80])
        if key in seen:
            return
        seen.add(key)
        if run is None:
            run = graph.locate(signal.node, signal.step, signal.seq)
        signal.run_id = run.id if run else None
        if signal.node is None and run is not None:
            signal.node = run.name
        signals.append(signal)

    for event in trace.events:
        if event.kind == "tool_error":
            err = event.payload.get("error") or {}
            kind = "timeout" if str(err.get("error_type", "")).lower().startswith("timeout") else "tool_error"
            add(Signal(kind, event.node, event.step, event.seq, event.name, f"{err.get('error_type', 'Error')}: {err.get('message', '')}", turn=event.turn),
                graph.locate(event.node, event.step, event.seq, event.invoke_id))
        elif event.kind == "node_error":
            err = event.payload.get("error") or {}
            detail = f"{err.get('error_type', 'Error')}: {err.get('message', '')}" if isinstance(err, dict) else str(err)
            add(Signal("node_error", event.node, event.step, event.seq, event.name, detail, turn=event.turn),
                graph.locate(event.node, event.step, event.seq, event.invoke_id))
        elif event.kind == "tool_end":
            if marker and marker in _blob(event.payload.get("output")):
                add(Signal("corruption_marker", event.node, event.step, event.seq, event.name, "tool output carries the injected corruption marker", turn=event.turn),
                    graph.locate(event.node, event.step, event.seq, event.invoke_id))
        elif event.kind == "node_end":
            writes = event.payload.get("writes") or {}
            if marker and marker in _blob(writes):
                add(Signal("corruption_marker", event.node, event.step, event.seq, event.name, "node writes carry the injected corruption marker", turn=event.turn),
                    graph.locate(event.node, event.step, event.seq, event.invoke_id))
            validator = (validators or {}).get(str(event.node))
            if validator is not None:
                try:
                    problem = validator(writes)
                except Exception as exc:  # validator bugs must not hide the run
                    problem = f"validator raised {type(exc).__name__}: {exc}"
                if problem:
                    add(Signal("validator_failure", event.node, event.step, event.seq, event.name, str(problem), turn=event.turn),
                        graph.locate(event.node, event.step, event.seq, event.invoke_id))
        elif event.kind == "injection" and oracle:
            payload = event.payload or {}
            if not payload.get("effective", True):
                continue  # the fault was applied but changed nothing; no cascade can start here
            run = graph.run_at(event.seq, event.invoke_id)
            detail = f"{payload.get('fault_id', '?')} {payload.get('kind', '')}:{payload.get('target', '')} (oracle: injection record)"
            add(Signal("injected_fault", run.name if run else payload.get("target"), run.step if run else None, event.seq, str(payload.get("target", "")), detail, turn=event.turn, oracle=True), run)

    if custom is not None:
        for extra in custom(trace, graph) or []:
            if isinstance(extra, Signal):
                add(extra)

    signals.sort(key=lambda s: s.seq)
    return signals


def source_of(signals: list[Signal]) -> Signal | None:
    return signals[0] if signals else None
