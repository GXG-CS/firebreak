"""Task -> StateVersion -> Task provenance, built only from recorded LangGraph facts.

The model is deliberately bipartite rather than `task -> task`:

    lookup@5  --WRITE-->  messages:v17  --SEEN-->  supervisor@9

so that when several tasks write the same channel in one super-step, all of them are kept as
producers of that version instead of one being invented as *the* cause.

How each relation is grounded (all fields are LangGraph's own):

* Tasks scheduled from checkpoint C record their writes as `C.pending_writes`, a list of
  `(task_id, channel, value)`. That is the WRITE relation, and it names the task exactly.
* Applying those writes bumps `channel_versions[channel]` in the next checkpoint C'. The new
  value is the version those writes produced.
There are two different recorded facts about reading, and they are kept apart because they mean
different things:

* TRIGGER. Before a task's writes are applied, LangGraph stamps the version that *caused it to be
  scheduled* into `versions_seen[node_name][channel]` (`pregel/_algo.py`, "update seen versions").
  Only the task's trigger channels are stamped, so in a `StateGraph` this records the routing
  channel (`branch:to:lookup`), not the channel the data travelled on.
* STATE. A task scheduled from checkpoint C is handed the channels named in its recorded
  `task.input`, at the versions C records in `channel_versions`. That is the path the data
  actually takes, and both halves are recorded: the input keys in the debug stream, the versions
  in the checkpoint.

`versions_seen` is keyed by node *name*, not task id. Within one super-step the mapping back to a
task is still exact, because the tasks of that step are precisely the ones named in
`C.pending_writes`. If two tasks of the same node name ran in the same step, both are recorded as
candidate consumers rather than one being chosen.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from firebreak.provenance.capture import CHECKPOINT_FACT

if TYPE_CHECKING:  # avoids a cycle: the recorder pulls in this package to snapshot checkpoints
    from firebreak.tracing.recorder import Trace

INTERNAL_NODES = ("__start__", "__interrupt__", "__end__", "__input__", "__pregel_pull", "__pregel_push")


@dataclass
class Evidence:
    """Where a relation comes from. Every relation carries one."""

    source: str  # checkpoint.pending_writes | checkpoint.versions_seen
    checkpoint_id: str
    step: Optional[int] = None
    channel: Optional[str] = None
    version: Optional[str] = None
    task_id: Optional[str] = None
    node: Optional[str] = None
    value_sha1: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TaskRunRef:
    """One real LangGraph task execution, as seen in the trace and in the checkpoints."""

    task_id: str
    node: str
    step: Optional[int] = None
    turn: Optional[int] = None
    invoke_id: Optional[str] = None
    triggers: list = field(default_factory=list)
    checkpoint_ns: Optional[str] = None
    path: Optional[str] = None
    input_channels: list = field(default_factory=list)
    from_trace: bool = False
    from_checkpoint: bool = False

    @property
    def label(self) -> str:
        base = self.node if self.step is None else f"{self.node}@{self.step}"
        return base if self.turn is None else f"{base} (turn {self.turn})"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["label"] = self.label
        return data


@dataclass
class StateVersion:
    """One version of one channel: the artifact that carries data between tasks."""

    channel: str
    version: str
    checkpoint_id: str  # the checkpoint in which this version first appears
    step: Optional[int] = None
    producer_task_ids: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.channel}:{self.version}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        return data


@dataclass
class WriteRelation:
    task_id: str
    state_key: str
    evidence: Evidence

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "state": self.state_key, "evidence": self.evidence.to_dict()}


@dataclass
class DerivedRelation:
    """version N+1 of a channel contains version N, because the channel accumulates."""

    state_key: str  # the newer version
    from_state_key: str  # the version it was folded onto
    evidence: Evidence

    def to_dict(self) -> dict:
        return {"state": self.state_key, "derived_from": self.from_state_key, "evidence": self.evidence.to_dict()}


@dataclass
class ReadRelation:
    """kind="state": the version was in the state handed to the task (this is the data path).
    kind="trigger": the version is what caused the task to be scheduled (routing)."""

    state_key: str
    task_ids: list  # >1 only when the same node ran twice in one super-step
    node: str
    evidence: Evidence
    kind: str = "state"

    @property
    def ambiguous(self) -> bool:
        return len(self.task_ids) != 1

    def to_dict(self) -> dict:
        return {
            "state": self.state_key,
            "task_ids": list(self.task_ids),
            "node": self.node,
            "kind": self.kind,
            "ambiguous": self.ambiguous,
            "evidence": self.evidence.to_dict(),
        }


class ProvenanceGraph:
    """Observed state provenance for one thread. No inference, no semantics."""

    def __init__(self) -> None:
        self.tasks: dict[str, TaskRunRef] = {}
        self.states: dict[str, StateVersion] = {}
        self.writes: list[WriteRelation] = []
        self.reads: list[ReadRelation] = []
        self.derived: list[DerivedRelation] = []
        self.channel_types: dict = {}
        self.accumulating: set = set()
        self.checkpoints: list[dict] = []
        self.warnings: list[str] = []

    # ---- construction ---------------------------------------------------------------------
    @classmethod
    def from_trace(cls, trace: "Trace") -> "ProvenanceGraph":
        graph = cls()
        graph.channel_types = dict(trace.meta.get("channel_types") or {})
        graph.accumulating = set(trace.meta.get("accumulating_channels") or [])
        graph._load_tasks_from_trace(trace)
        facts = graph._load_checkpoints(trace)
        if not facts:
            graph.warnings.append(
                f"no {CHECKPOINT_FACT} events in this trace: it was recorded before provenance "
                "capture existed, or the graph was compiled without a checkpointer"
            )
            return graph
        graph._build(facts)
        return graph

    def _load_tasks_from_trace(self, trace: Trace) -> None:
        for event in trace.events:
            if event.kind != "node_start" or not event.task_id:
                continue
            task_input = event.payload.get("input")
            self.tasks[str(event.task_id)] = TaskRunRef(
                task_id=str(event.task_id),
                node=str(event.node),
                step=event.step,
                turn=event.turn,
                invoke_id=event.invoke_id,
                triggers=list(event.triggers),
                input_channels=sorted(task_input.keys()) if isinstance(task_input, dict) else [],
                from_trace=True,
            )
        # the callback stream carries the two framework keys the debug stream drops
        for event in trace.events:
            if event.kind not in ("chain_start", "llm_start", "tool_start"):
                continue
            extra = event.payload.get("langgraph") or {}
            run = self._task_by_node_step(event.node, event.step)
            if run is not None:
                run.checkpoint_ns = run.checkpoint_ns or extra.get("checkpoint_ns")
                run.path = run.path or extra.get("path")

    def _task_by_node_step(self, node: Optional[str], step: Optional[int]) -> Optional[TaskRunRef]:
        for run in self.tasks.values():
            if run.node == node and run.step == step:
                return run
        return None

    @staticmethod
    def _load_checkpoints(trace: "Trace") -> list[dict]:
        facts = [e.payload for e in trace.of_kind(CHECKPOINT_FACT)]
        return sorted(facts, key=lambda f: str(f.get("checkpoint_id") or ""))

    def _build(self, facts: list[dict]) -> None:
        self.checkpoints = [
            {
                "checkpoint_id": f.get("checkpoint_id"),
                "parent_checkpoint_id": f.get("parent_checkpoint_id"),
                "step": f.get("step"),
                "source": f.get("source"),
                "updated_channels": f.get("updated_channels") or [],
                "n_writes": len(f.get("writes") or []),
            }
            for f in facts
        ]
        for index, current in enumerate(facts):
            nxt = facts[index + 1] if index + 1 < len(facts) else None
            writes = current.get("writes") or []
            if not writes:
                continue
            # tasks scheduled from `current` are exactly the ones named in its writes
            tasks_here: dict[str, set] = {}
            for write in writes:
                tasks_here.setdefault(write["task_id"], set()).add(write["channel"])
                self._ensure_task(write["task_id"], current)
            if nxt is None:
                self.warnings.append(
                    f"checkpoint {current.get('checkpoint_id')} has {len(writes)} writes but no "
                    "following checkpoint, so the versions they produced were never saved"
                )
                continue
            self._add_writes(writes, current, nxt)
            self._add_state_reads(current, tasks_here)
            self._add_trigger_reads(current, nxt, tasks_here)
            self._add_derivations(current, nxt)

    def _ensure_task(self, task_id: str, fact: dict) -> TaskRunRef:
        run = self.tasks.get(task_id)
        if run is None:
            # not in the trace: LangGraph's own input write, named by the checkpoint's source
            node = "__input__" if fact.get("source") == "input" else "__unknown__"
            run = TaskRunRef(task_id=task_id, node=node, step=fact.get("step"))
            self.tasks[task_id] = run
        run.from_checkpoint = True
        run.checkpoint_ns = run.checkpoint_ns if run.checkpoint_ns is not None else fact.get("checkpoint_ns")
        return run

    def _add_writes(self, writes: list, current: dict, nxt: dict) -> None:
        """Each write produced the version the channel has in the next checkpoint."""
        next_versions = nxt.get("channel_versions") or {}
        for write in writes:
            channel = write["channel"]
            version = next_versions.get(channel)
            if version is None:
                self.warnings.append(
                    f"task {write['task_id']} wrote channel {channel!r} at checkpoint "
                    f"{current.get('checkpoint_id')} but that channel has no version in the next "
                    "checkpoint (internal or transient channel); write kept without a state version"
                )
                continue
            state = self._ensure_state(channel, version, nxt)
            if write["task_id"] not in state.producer_task_ids:
                state.producer_task_ids.append(write["task_id"])
            self.writes.append(
                WriteRelation(
                    task_id=write["task_id"],
                    state_key=state.key,
                    evidence=Evidence(
                        source="checkpoint.pending_writes",
                        checkpoint_id=str(current.get("checkpoint_id")),
                        step=current.get("step"),
                        channel=channel,
                        version=version,
                        task_id=write["task_id"],
                        value_sha1=write.get("value_sha1"),
                        note=f"version read from channel_versions of {nxt.get('checkpoint_id')}",
                    ),
                )
            )

    def _add_state_reads(self, current: dict, tasks_here: dict) -> None:
        """A task scheduled from checkpoint C received C's version of each channel in its input.

        The channels come from the task's own recorded `input`; the versions come from the
        checkpoint it was scheduled from. This is the relation the data actually travels on.
        """
        versions = current.get("channel_versions") or {}
        for task_id in tasks_here:
            run = self.tasks.get(task_id)
            if run is None or not run.input_channels:
                continue
            for channel in run.input_channels:
                version = versions.get(channel)
                if version is None:
                    continue
                state = self.states.get(f"{channel}:{version}")
                if state is None:
                    state = self._ensure_state(channel, version, current, born_here=False)
                self.reads.append(
                    ReadRelation(
                        state_key=state.key,
                        task_ids=[task_id],
                        node=run.node,
                        kind="state",
                        evidence=Evidence(
                            source="checkpoint.channel_versions + task.input",
                            checkpoint_id=str(current.get("checkpoint_id")),
                            step=current.get("step"),
                            channel=channel,
                            version=version,
                            task_id=task_id,
                            node=run.node,
                            note="the version this channel held in the checkpoint the task was scheduled from; "
                            "the channel is one the task's recorded input carried",
                        ),
                    )
                )

    def _add_trigger_reads(self, current: dict, nxt: dict, tasks_here: dict) -> None:
        """A node's `versions_seen` entry changing across a super-step is what triggered it."""
        before = current.get("versions_seen") or {}
        after = nxt.get("versions_seen") or {}
        names_here = {self.tasks[t].node: [] for t in tasks_here if t in self.tasks}
        for task_id in tasks_here:
            node = self.tasks[task_id].node
            names_here.setdefault(node, []).append(task_id)
        for node, seen_after in after.items():
            if node in INTERNAL_NODES:
                continue
            seen_before = before.get(node) or {}
            for channel, version in seen_after.items():
                if seen_before.get(channel) == version:
                    continue  # unchanged: this node did not consume a new version in this step
                state = self.states.get(f"{channel}:{version}")
                if state is None:
                    state = self._ensure_state(channel, version, current, born_here=False)
                candidates = names_here.get(node, [])
                note = None
                if not candidates:
                    note = (
                        f"node {node!r} advanced its seen version but made no write in this "
                        "super-step, so no task id could be attached"
                    )
                elif len(candidates) > 1:
                    note = f"{len(candidates)} tasks of node {node!r} ran in this super-step; both kept"
                self.reads.append(
                    ReadRelation(
                        state_key=state.key,
                        task_ids=list(candidates),
                        node=node,
                        kind="trigger",
                        evidence=Evidence(
                            source="checkpoint.versions_seen",
                            checkpoint_id=str(nxt.get("checkpoint_id")),
                            step=nxt.get("step"),
                            channel=channel,
                            version=version,
                            node=node,
                            note=note,
                        ),
                    )
                )

    def _add_derivations(self, current: dict, nxt: dict) -> None:
        """For an accumulating channel, the next version was folded onto the current one."""
        before = current.get("channel_versions") or {}
        after = nxt.get("channel_versions") or {}
        for channel, new_version in after.items():
            if channel not in self.accumulating:
                continue  # a replacing channel: the old value is gone, no derivation to claim
            old_version = before.get(channel)
            if old_version is None or old_version == new_version:
                continue
            newer = self.states.get(f"{channel}:{new_version}")
            older = self.states.get(f"{channel}:{old_version}")
            if newer is None or older is None:
                continue
            self.derived.append(
                DerivedRelation(
                    state_key=newer.key,
                    from_state_key=older.key,
                    evidence=Evidence(
                        source="channel_versions across checkpoints + channel class",
                        checkpoint_id=str(nxt.get("checkpoint_id")),
                        step=nxt.get("step"),
                        channel=channel,
                        version=new_version,
                        note=f"channel class {self.channel_types.get(channel, '?')} folds new writes onto "
                        "the existing value, so this version contains the previous one",
                    ),
                )
            )

    def derivation_ancestors(self, state_key: str) -> list:
        """Versions this one accumulated from, oldest last. Recorded, not inferred."""
        by_key = {d.state_key: d.from_state_key for d in self.derived}
        chain: list[str] = []
        current = by_key.get(state_key)
        while current is not None and current not in chain:
            chain.append(current)
            current = by_key.get(current)
        return chain

    def _ensure_state(self, channel: str, version: str, fact: dict, born_here: bool = True) -> StateVersion:
        key = f"{channel}:{version}"
        state = self.states.get(key)
        if state is None:
            state = StateVersion(
                channel=channel,
                version=version,
                checkpoint_id=str(fact.get("checkpoint_id")) if born_here else "",
                step=fact.get("step") if born_here else None,
            )
            self.states[key] = state
        return state

    # ---- queries --------------------------------------------------------------------------
    def producers_of(self, state_key: str) -> list:
        state = self.states.get(state_key)
        return list(state.producer_task_ids) if state else []

    def writes_by(self, task_id: str) -> list:
        return [w for w in self.writes if w.task_id == task_id]

    def reads_of(self, state_key: str) -> list:
        return [r for r in self.reads if r.state_key == state_key]

    def task_label(self, task_id: str) -> str:
        run = self.tasks.get(task_id)
        return run.label if run else task_id[:8]

    def observed_task_relations(self) -> list:
        """Producer task -> consumer task pairs, each carrying the state version between them.

        This is a *derived view* for comparing against the legacy heuristic graph. The graph
        itself stays bipartite; a pair here means "the consumer read a state version that this
        producer contributed to", never "the producer caused the consumer".
        """
        pairs: list[dict] = []
        for read in self.reads:
            if read.kind != "state":
                continue  # routing triggers are not a data path
            state = self.states.get(read.state_key)
            if state is None:
                continue
            reachable = [(state.key, "direct")] + [(k, "accumulated") for k in self.derivation_ancestors(state.key)]
            for source_key, relation in reachable:
                source = self.states.get(source_key)
                if source is None:
                    continue
                for producer in source.producer_task_ids:
                    for consumer in read.task_ids or [None]:
                        if consumer is not None and producer == consumer:
                            continue
                        pairs.append(
                            {
                                "producer_task_id": producer,
                                "producer": self.task_label(producer),
                                "consumer_task_id": consumer,
                                "consumer": self.task_label(consumer) if consumer else read.node,
                                "state": read.state_key,
                                "via": source_key,
                                "relation": relation,
                                "shared_producers": len(source.producer_task_ids),
                                "consumer_resolved": consumer is not None,
                            }
                        )
        return pairs

    def to_dict(self) -> dict:
        return {
            "tasks": [t.to_dict() for t in sorted(self.tasks.values(), key=lambda t: (t.step is None, t.step or 0, t.node))],
            "state_versions": [s.to_dict() for s in self.states.values()],
            "write_relations": [w.to_dict() for w in self.writes],
            "read_relations": [r.to_dict() for r in self.reads],
            "derived_relations": [d.to_dict() for d in self.derived],
            "channel_types": self.channel_types,
            "accumulating_channels": sorted(self.accumulating),
            "checkpoints": self.checkpoints,
            "warnings": self.warnings,
        }
