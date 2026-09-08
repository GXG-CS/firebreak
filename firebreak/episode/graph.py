"""Episode and turn structure, projected over the recorded evidence.

    EpisodeGraph
      └── TurnGraph
            └── TaskRun
                  └── Event

`StateVersion` is a node inside a TurnGraph, not another level of the hierarchy, and raw events
are details of a TaskRun rather than a graph of their own.

This is a projection. All evidence — WRITE, READ, TRIGGER, DERIVED_FROM and the fields each came
from — is built by `firebreak.provenance`, which this layer does not modify. What is added here is
slicing: which task ran in which turn, which state versions that turn touched, which relations are
local to it, and which relations cross a turn boundary.

**What a turn is.** A turn is a Firebreak-assigned analysis unit, stamped by the caller when the
run is recorded. By convention an integration maps one external interaction to one `record()`
call, but the recorder does not enforce that: the same trace can be recorded with any turn
numbering the caller chooses, and a turn may span more than one invoke. LangGraph has no notion of
a turn.

**What a step is not.** `step` is LangGraph's super-step counter for the whole thread. It keeps
increasing across turns, so a turn's steps do not start at zero, and one step can hold several
task runs when a super-step fans out.

**Membership**, all three answerable from records:

* a TaskRun belongs to the turn stamped on its events;
* a StateVersion belongs to the turn in which the checkpoint that first held it was captured;
* a relation is local to a turn when both of its ends are in that turn, and becomes a
  `CrossTurnLink` otherwise. Nothing is dropped either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from firebreak.provenance.graph import (
    DerivedRelation,
    ProvenanceGraph,
    ReadRelation,
    StateVersion,
    TaskRunRef,
    WriteRelation,
)
from firebreak.tracing.grouping import GroupedTrace, group_by_task_run
from firebreak.tracing.recorder import Trace

INTERNAL_PREFIX = "__"


def is_internal(node: Optional[str]) -> bool:
    """LangGraph's own tasks (`__input__`, `__unknown__`) rather than a node someone wrote."""
    return bool(node) and str(node).startswith(INTERNAL_PREFIX)


@dataclass
class TurnSummary:
    """Factual metadata about one turn. Everything here is already in the trace."""

    turn: Optional[int]
    invoke_ids: list = field(default_factory=list)
    first_seq: Optional[int] = None
    last_seq: Optional[int] = None
    first_step: Optional[int] = None
    last_step: Optional[int] = None
    steps: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    task_runs: int = 0
    agent_task_runs: int = 0
    event_count: int = 0
    checkpoints: int = 0
    wall_time: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "invoke_ids": list(self.invoke_ids),
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "first_step": self.first_step,
            "last_step": self.last_step,
            "steps": list(self.steps),
            "nodes": list(self.nodes),
            "task_runs": self.task_runs,
            "agent_task_runs": self.agent_task_runs,
            "event_count": self.event_count,
            "checkpoints": self.checkpoints,
            "wall_time": self.wall_time,
            "error": self.error,
        }


@dataclass
class CrossTurnLink:
    """A recorded relation whose two ends fall in different turns.

    Held at the episode boundary so a TurnGraph stays locally readable while the fact survives.
    The original relation is kept whole — in particular a `ReadRelation` keeps its full
    `task_ids` list, because an ambiguous consumer must not be collapsed to one task here.
    """

    kind: str  # write | read | trigger | derived_from
    from_turn: Optional[int]
    to_turn: Optional[int]
    state_key: str
    relation: Any  # the original WriteRelation / ReadRelation / DerivedRelation
    from_state_key: Optional[str] = None
    task_ids: list = field(default_factory=list)
    node: Optional[str] = None

    @property
    def evidence(self):
        return getattr(self.relation, "evidence", None)

    def to_dict(self) -> dict:
        data = {
            "kind": self.kind,
            "from_turn": self.from_turn,
            "to_turn": self.to_turn,
            "state": self.state_key,
            "from_state": self.from_state_key,
            "task_ids": list(self.task_ids),
            "node": self.node,
        }
        evidence = self.evidence
        if evidence is not None:
            data["evidence"] = evidence.to_dict()
        if isinstance(self.relation, DerivedRelation):
            data["verdict"] = self.relation.verdict
        return data


class TurnGraph:
    """One turn: its task runs, the state versions it touched, and its local relations."""

    def __init__(self, turn: Optional[int], episode: "EpisodeGraph") -> None:
        self.turn = turn
        self.episode = episode
        self.summary: TurnSummary = TurnSummary(turn=turn)
        self.task_runs: list[TaskRunRef] = []
        self.state_versions: list[StateVersion] = []
        self.writes: list[WriteRelation] = []
        self.reads: list[ReadRelation] = []
        self.triggers: list[ReadRelation] = []
        self.derived: list[DerivedRelation] = []
        self.incoming: list[CrossTurnLink] = []
        self.outgoing: list[CrossTurnLink] = []
        self.checkpoints: list[dict] = []

    # ---- views ---------------------------------------------------------------------------
    @property
    def agent_task_runs(self) -> list:
        """Task runs for nodes someone wrote, excluding LangGraph's own input tasks."""
        return [run for run in self.task_runs if not is_internal(run.node)]

    @property
    def internal_task_runs(self) -> list:
        return [run for run in self.task_runs if is_internal(run.node)]

    def events(self, task_id: str) -> list:
        """The raw events recorded for one task run of this turn."""
        run = self.episode.grouped.by_task_id().get(task_id)
        return list(run.events) if run else []

    def state(self, key: str) -> Optional[StateVersion]:
        return self.episode.evidence.states.get(key)

    def task(self, task_id: str) -> Optional[TaskRunRef]:
        return self.episode.evidence.tasks.get(task_id)

    def label(self, task_id: str) -> str:
        return self.episode.evidence.task_label(task_id)

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "summary": self.summary.to_dict(),
            "task_runs": [t.to_dict() for t in self.task_runs],
            "state_versions": [s.to_dict() for s in self.state_versions],
            "writes": [w.to_dict() for w in self.writes],
            "reads": [r.to_dict() for r in self.reads],
            "triggers": [r.to_dict() for r in self.triggers],
            "derived": [d.to_dict() for d in self.derived],
            "incoming": [link.to_dict() for link in self.incoming],
            "outgoing": [link.to_dict() for link in self.outgoing],
            "checkpoints": list(self.checkpoints),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"TurnGraph(turn={self.turn}, task_runs={len(self.task_runs)}, "
                f"states={len(self.state_versions)}, cross_turn={len(self.incoming) + len(self.outgoing)})")


class EpisodeGraph:
    """One episode, sliced into turns, over evidence built by `firebreak.provenance`."""

    def __init__(self, trace: Trace, evidence: ProvenanceGraph, grouped: GroupedTrace) -> None:
        self.trace = trace
        self.evidence = evidence
        self.grouped = grouped
        self.episode_id: Optional[str] = trace.meta.get("episode_id")
        self.thread_id: Optional[str] = trace.meta.get("thread_id")
        self.turns: list[TurnSummary] = []
        self.warnings: list[str] = list(evidence.warnings) + list(grouped.warnings)
        self._graphs: dict = {}
        self._state_turn: dict = {}

    # ---- construction --------------------------------------------------------------------
    @classmethod
    def from_trace(cls, trace: Trace) -> "EpisodeGraph":
        evidence = ProvenanceGraph.from_trace(trace)
        episode = cls(trace, evidence, group_by_task_run(trace))
        episode._build()
        return episode

    def _build(self) -> None:
        checkpoint_turn = {str(c["checkpoint_id"]): c.get("turn") for c in self.evidence.checkpoints}
        checkpoints_by_turn: dict = {}
        for checkpoint in self.evidence.checkpoints:
            checkpoints_by_turn.setdefault(checkpoint.get("turn"), []).append(checkpoint)
        # a state version belongs to the turn in which its birth checkpoint was captured
        for key, state in self.evidence.states.items():
            self._state_turn[key] = checkpoint_turn.get(state.checkpoint_id)

        turns = sorted({run.turn for run in self.evidence.tasks.values()} | set(checkpoints_by_turn),
                       key=lambda t: (t is None, t))
        invokes = {i.get("turn"): i for i in (self.trace.meta.get("invokes") or [])}

        for turn in turns:
            graph = TurnGraph(turn, self)
            graph.task_runs = sorted(
                (t for t in self.evidence.tasks.values() if t.turn == turn),
                key=lambda t: (t.step is None, t.step or 0, t.node),
            )
            graph.checkpoints = checkpoints_by_turn.get(turn, [])
            self._slice_relations(graph, turn)
            graph.summary = self._summarise(graph, turn, invokes.get(turn))
            self._graphs[turn] = graph
            self.turns.append(graph.summary)

    def _turn_of_task(self, task_id: Optional[str]) -> Optional[int]:
        run = self.evidence.tasks.get(task_id or "")
        return run.turn if run else None

    def _slice_relations(self, graph: TurnGraph, turn: Optional[int]) -> None:
        """Split every relation into turn-local or crossing, symmetrically on both sides.

        A relation is local when both of its ends fall in this turn. Otherwise it is recorded as
        `outgoing` on the turn it leaves and `incoming` on the turn it enters, so neither turn
        loses the fact and neither has to carry the other turn's contents.
        """
        touched: set = set()

        for write in self.evidence.writes:
            task_turn = self._turn_of_task(write.task_id)
            state_turn = self._state_turn.get(write.state_key)
            if task_turn == turn and state_turn == turn:
                graph.writes.append(write)
                touched.add(write.state_key)
            elif task_turn == turn:
                graph.outgoing.append(CrossTurnLink(
                    kind="write", from_turn=turn, to_turn=state_turn,
                    state_key=write.state_key, relation=write, task_ids=[write.task_id]))
            elif state_turn == turn:
                graph.incoming.append(CrossTurnLink(
                    kind="write", from_turn=task_turn, to_turn=turn,
                    state_key=write.state_key, relation=write, task_ids=[write.task_id]))

        for read in self.evidence.reads:
            kind = "trigger" if read.kind == "trigger" else "read"
            bucket = graph.triggers if read.kind == "trigger" else graph.reads
            state_turn = self._state_turn.get(read.state_key)
            consumer_turns = {self._turn_of_task(t) for t in read.task_ids} or {None}
            here = turn in consumer_turns
            if here and state_turn == turn:
                bucket.append(read)
                touched.add(read.state_key)
            elif here:
                graph.incoming.append(CrossTurnLink(
                    kind=kind, from_turn=state_turn, to_turn=turn, state_key=read.state_key,
                    relation=read, task_ids=list(read.task_ids), node=read.node))
            elif state_turn == turn:
                for consumer_turn in sorted(consumer_turns - {turn}, key=lambda t: (t is None, t)):
                    graph.outgoing.append(CrossTurnLink(
                        kind=kind, from_turn=turn, to_turn=consumer_turn, state_key=read.state_key,
                        relation=read, task_ids=list(read.task_ids), node=read.node))

        for derived in self.evidence.derived:
            new_turn = self._state_turn.get(derived.state_key)
            old_turn = self._state_turn.get(derived.from_state_key)
            if new_turn == turn and old_turn == turn:
                graph.derived.append(derived)
                touched.update({derived.state_key, derived.from_state_key})
            elif new_turn == turn:
                graph.incoming.append(CrossTurnLink(
                    kind="derived_from", from_turn=old_turn, to_turn=turn,
                    state_key=derived.state_key, from_state_key=derived.from_state_key, relation=derived))
            elif old_turn == turn:
                graph.outgoing.append(CrossTurnLink(
                    kind="derived_from", from_turn=turn, to_turn=new_turn,
                    state_key=derived.state_key, from_state_key=derived.from_state_key, relation=derived))

        # every version born in this turn belongs to it, plus any this turn's relations touched
        keys = {k for k, t in self._state_turn.items() if t == turn} | touched
        graph.state_versions = sorted(
            (self.evidence.states[k] for k in keys if k in self.evidence.states),
            key=lambda s: (s.step is None, s.step or 0, s.channel),
        )

    def _summarise(self, graph: TurnGraph, turn: Optional[int], invoke: Optional[dict]) -> TurnSummary:
        events = [e for e in self.trace.events if e.turn == turn]
        steps = sorted({t.step for t in graph.task_runs if t.step is not None})
        nodes: list[str] = []
        for run in graph.task_runs:
            if run.node not in nodes:
                nodes.append(run.node)
        invoke_ids: list[str] = []
        for event in events:
            if event.invoke_id and event.invoke_id not in invoke_ids:
                invoke_ids.append(event.invoke_id)

        # the grouping is an independent read of the same trace; disagreement is worth surfacing
        grouped_ids = {run.task_id for run in self.grouped.for_turn(turn) if run.task_id}
        evidence_ids = {t.task_id for t in graph.task_runs}
        missing = grouped_ids - evidence_ids
        if missing:
            self.warnings.append(
                f"turn {turn}: {len(missing)} task run(s) appear in the events but not in the "
                f"evidence graph: {sorted(missing)}"
            )
        return TurnSummary(
            turn=turn,
            invoke_ids=invoke_ids,
            first_seq=min((e.seq for e in events), default=None),
            last_seq=max((e.seq for e in events), default=None),
            first_step=steps[0] if steps else None,
            last_step=steps[-1] if steps else None,
            steps=steps,
            nodes=nodes,
            task_runs=len(graph.task_runs),
            agent_task_runs=len(graph.agent_task_runs),
            event_count=len(events),
            checkpoints=len(graph.checkpoints),
            wall_time=(invoke or {}).get("wall_time"),
            error=(invoke or {}).get("error"),
        )

    # ---- access --------------------------------------------------------------------------
    def turn(self, number: Optional[int]) -> TurnGraph:
        if number not in self._graphs:
            raise KeyError(f"no turn {number} in this episode; turns are {[t.turn for t in self.turns]}")
        return self._graphs[number]

    @property
    def turn_numbers(self) -> list:
        return [summary.turn for summary in self.turns]

    def __iter__(self) -> Iterator[TurnGraph]:
        return (self._graphs[summary.turn] for summary in self.turns)

    def __len__(self) -> int:
        return len(self.turns)

    def cross_turn_links(self) -> list:
        """Every relation whose ends fall in different turns, deduplicated across turns."""
        seen: set = set()
        links: list[CrossTurnLink] = []
        for graph in self:
            for link in graph.outgoing + graph.incoming:
                key = (link.kind, link.from_turn, link.to_turn, link.state_key,
                       link.from_state_key, tuple(link.task_ids))
                if key in seen:
                    continue
                seen.add(key)
                links.append(link)
        return links

    def chronological_order(self) -> list:
        """Consecutive turn pairs, in the order they were recorded.

        This is ordering, not provenance: it says one turn came after another, never that one
        caused the other. Anything causal has to come from the relations.
        """
        numbers = self.turn_numbers
        return [(numbers[i], numbers[i + 1]) for i in range(len(numbers) - 1)]

    def state_turn(self, state_key: str) -> Optional[int]:
        return self._state_turn.get(state_key)

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "thread_id": self.thread_id,
            "turns": [summary.to_dict() for summary in self.turns],
            "chronological_order": self.chronological_order(),
            "cross_turn_links": [link.to_dict() for link in self.cross_turn_links()],
            "warnings": self.warnings,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"EpisodeGraph(episode_id={self.episode_id!r}, turns={self.turn_numbers})"
