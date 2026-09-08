"""LEGACY. Execution graph inferred from the static topology plus execution ordering.

An edge `A -> B` is added when the compiled graph declares a static edge `A.name -> B.name` and
`A`'s run finished before `B`'s started. That is an inference over ordering, not a record of what
`B` read, and it is what `firebreak/provenance/` replaces: LangGraph writes the real read/write
relation down, so it does not have to be guessed.

This module is retained only because `detection/`, `reporting/` and `runner.py` still build on it.
Do not use it for provenance, and do not extend it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from firebreak.tracing.events import is_routing_channel

START_NAME = "__start__"
END_NAME = "__end__"


@dataclass
class ToolCall:
    name: str
    node: str | None
    step: int | None
    run_id: str | None
    input: Any = None
    output: Any = None
    error: Any = None
    seq_start: int = 0
    seq_end: int | None = None
    turn: int | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None


@dataclass
class ModelCall:
    name: str
    node: str | None
    step: int | None
    run_id: str | None
    seq_start: int = 0
    seq_end: int | None = None
    error: Any = None


@dataclass
class NodeRun:
    """One executed instance of a graph node."""

    id: str
    name: str
    step: int | None
    triggers: list = field(default_factory=list)
    start_seq: int = 0
    end_seq: int | None = None
    writes: dict = field(default_factory=dict)
    error: Any = None
    tools: list = field(default_factory=list)
    models: list = field(default_factory=list)
    invoke_id: str | None = None
    turn: int | None = None

    @property
    def data_writes(self) -> dict:
        return {k: v for k, v in self.writes.items() if not is_routing_channel(k)}

    @property
    def failed(self) -> bool:
        return self.error is not None

    def contains(self, seq: int) -> bool:
        if seq < self.start_seq:
            return False
        return self.end_seq is None or seq <= self.end_seq

    @property
    def label(self) -> str:
        base = self.name if self.step is None else f"{self.name}@{self.step}"
        return base if self.turn is None else f"{base} (turn {self.turn})"


@dataclass
class Edge:
    src: str
    dst: str
    via: list = field(default_factory=list)  # static-edge labels
    data_keys: list = field(default_factory=list)  # state keys the source wrote
    cross_turn: bool = False


class ExecutionGraph:
    """Node runs plus data-flow edges between them.

    An edge ``A -> B`` is added when the compiled graph has a static edge ``A.name -> B.name``
    and ``A`` is the latest run of that node that finished before ``B`` started, in this or an
    earlier invocation of the same thread (state persists across turns through the
    checkpointer, so a later turn really does read what an earlier turn wrote).
    """

    def __init__(self) -> None:
        self.runs: list[NodeRun] = []
        self.edges: list[Edge] = []
        self.static_edges: list[dict] = []
        self._by_id: dict[str, NodeRun] = {}
        self._out: dict[str, list[Edge]] = {}
        self._in: dict[str, list[Edge]] = {}

    # ---- construction ------------------------------------------------------------------------
    @classmethod
    def from_trace(cls, trace) -> ExecutionGraph:
        graph = cls()
        graph.static_edges = list((trace.meta.get("static_graph") or {}).get("edges") or [])
        open_by_task: dict[str, NodeRun] = {}
        tool_by_run: dict[str, ToolCall] = {}
        model_by_run: dict[str, ModelCall] = {}

        for event in trace.events:
            if event.kind == "node_start":
                task_key = f"{event.invoke_id or 'i'}:{event.task_id or f'{event.node}#{event.step}#{event.seq}'}"
                run = NodeRun(
                    id=task_key,
                    name=str(event.node),
                    step=event.step,
                    triggers=list(event.triggers),
                    start_seq=event.seq,
                    invoke_id=event.invoke_id,
                    turn=event.turn,
                )
                graph.runs.append(run)
                graph._by_id[run.id] = run
                open_by_task[task_key] = run
            elif event.kind in ("node_end", "node_error"):
                task_key = f"{event.invoke_id or 'i'}:{event.task_id}" if event.task_id else None
                run = open_by_task.pop(task_key, None) if task_key else None
                if run is None:
                    run = graph._latest_open(event.node, event.invoke_id)
                    if run is not None:
                        open_by_task.pop(run.id, None)
                if run is None:
                    continue
                run.end_seq = event.seq
                run.writes = dict(event.payload.get("writes") or {})
                run.error = event.payload.get("error")
            elif event.kind == "tool_start":
                call = ToolCall(
                    name=event.name,
                    node=event.node,
                    step=event.step,
                    run_id=event.run_id,
                    input=event.payload.get("input"),
                    seq_start=event.seq,
                    turn=event.turn,
                )
                if event.run_id:
                    tool_by_run[event.run_id] = call
                owner = graph.locate(event.node, event.step, event.seq, event.invoke_id)
                if owner is not None:
                    owner.tools.append(call)
            elif event.kind in ("tool_end", "tool_error"):
                call = tool_by_run.get(event.run_id or "")
                if call is None:
                    call = ToolCall(name=event.name, node=event.node, step=event.step, run_id=event.run_id, seq_start=event.seq, turn=event.turn)
                    owner = graph.locate(event.node, event.step, event.seq, event.invoke_id)
                    if owner is not None:
                        owner.tools.append(call)
                call.seq_end = event.seq
                if event.kind == "tool_end":
                    call.output = event.payload.get("output")
                else:
                    call.error = event.payload.get("error")
            elif event.kind == "llm_start":
                call_m = ModelCall(name=event.name, node=event.node, step=event.step, run_id=event.run_id, seq_start=event.seq)
                if event.run_id:
                    model_by_run[event.run_id] = call_m
                owner = graph.locate(event.node, event.step, event.seq, event.invoke_id)
                if owner is not None:
                    owner.models.append(call_m)
            elif event.kind in ("llm_end", "llm_error"):
                call_m = model_by_run.get(event.run_id or "")
                if call_m is not None:
                    call_m.seq_end = event.seq
                    if event.kind == "llm_error":
                        call_m.error = event.payload.get("error")

        graph._build_edges()
        return graph

    def _latest_open(self, name: str | None, invoke_id: str | None) -> NodeRun | None:
        candidates = [r for r in self.runs if r.name == name and r.end_seq is None and (invoke_id is None or r.invoke_id == invoke_id)]
        return candidates[-1] if candidates else None

    def locate(self, node: str | None, step: int | None, seq: int, invoke_id: str | None = None) -> NodeRun | None:
        """Find the node run that was executing when event ``seq`` happened."""
        if node is None:
            return self.run_at(seq, invoke_id)
        candidates = [r for r in self.runs if r.name == node]
        if invoke_id is not None:
            same_invoke = [r for r in candidates if r.invoke_id == invoke_id]
            if same_invoke:
                candidates = same_invoke
        if step is not None:
            same_step = [r for r in candidates if r.step == step]
            if same_step:
                candidates = same_step
        active = [r for r in candidates if r.contains(seq)]
        if active:
            return active[-1]
        return candidates[-1] if candidates else None

    def run_at(self, seq: int, invoke_id: str | None = None) -> NodeRun | None:
        """The node run whose execution window contains ``seq`` (used for injection events)."""
        active = [r for r in self.runs if r.contains(seq) and (invoke_id is None or r.invoke_id == invoke_id)]
        return active[-1] if active else None

    def _static_predecessors(self, name: str) -> list[str]:
        preds = []
        for edge in self.static_edges:
            if edge.get("target") == name and edge.get("source") not in (START_NAME, None):
                preds.append(str(edge["source"]))
        return preds

    def _build_edges(self) -> None:
        ordered = sorted(self.runs, key=lambda r: r.start_seq)
        for dst in ordered:
            for pred_name in self._static_predecessors(dst.name):
                writer: NodeRun | None = None
                for src in ordered:
                    if src is dst or src.name != pred_name:
                        continue
                    if src.end_seq is None or src.end_seq > dst.start_seq:
                        continue
                    if writer is None or src.end_seq > writer.end_seq:
                        writer = src
                if writer is not None:
                    self._add_edge(writer, dst, f"{pred_name}->{dst.name}")

    def _add_edge(self, src: NodeRun, dst: NodeRun, via: str) -> None:
        for edge in self._out.get(src.id, []):
            if edge.dst == dst.id:
                if via not in edge.via:
                    edge.via.append(via)
                return
        edge = Edge(
            src=src.id,
            dst=dst.id,
            via=[via],
            data_keys=sorted(src.data_writes.keys()),
            cross_turn=(src.invoke_id != dst.invoke_id),
        )
        self.edges.append(edge)
        self._out.setdefault(src.id, []).append(edge)
        self._in.setdefault(dst.id, []).append(edge)

    # ---- queries ------------------------------------------------------------------------------
    def get(self, run_id: str) -> NodeRun | None:
        return self._by_id.get(run_id)

    def successors(self, run_id: str) -> list[NodeRun]:
        return [self._by_id[e.dst] for e in self._out.get(run_id, []) if e.dst in self._by_id]

    def predecessors(self, run_id: str) -> list[NodeRun]:
        return [self._by_id[e.src] for e in self._in.get(run_id, []) if e.src in self._by_id]

    @property
    def total_runs(self) -> int:
        return len(self.runs)

    def node_names(self) -> list[str]:
        seen: list[str] = []
        for run in sorted(self.runs, key=lambda r: r.start_seq):
            if run.name not in seen:
                seen.append(run.name)
        return seen

    def runs_named(self, name: str) -> list[NodeRun]:
        return [r for r in self.runs if r.name == name]

    def to_dict(self) -> dict:
        return {
            "runs": [
                {
                    "id": r.id,
                    "name": r.name,
                    "step": r.step,
                    "turn": r.turn,
                    "invoke_id": r.invoke_id,
                    "triggers": r.triggers,
                    "writes": sorted(r.data_writes.keys()),
                    "error": r.error,
                    "tools": [t.name + ("!" if t.failed else "") for t in r.tools],
                    "models": len(r.models),
                }
                for r in self.runs
            ],
            "edges": [
                {"src": e.src, "dst": e.dst, "via": e.via, "data_keys": e.data_keys, "cross_turn": e.cross_turn}
                for e in self.edges
            ],
        }
