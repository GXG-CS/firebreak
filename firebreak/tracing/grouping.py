"""Group a flat trace into task runs, using the task identity LangGraph recorded.

A trace is one ordered event list, but several tasks can be in flight at once: LangGraph runs
every task of a super-step together, so a fan-out puts two `node_start` events back to back and
then interleaves their callbacks. Grouping therefore cannot track a single "currently open" run,
and cannot key on `(node, step)` either, since a `Send` fan-out runs the same node several times
in one step.

The identity is recorded, so it does not have to be guessed:

* `node_start` / `node_end` carry `task_id` directly (LangGraph's debug stream).
* Every run started inside a node carries `langgraph_checkpoint_ns`, which LangGraph builds as
  ``{parent_ns}|{node}:{task_id}`` (`pregel/_algo.py`), so the segment after the final `:` of the
  last `|`-separated part is the task id of the task the call was made in.

Only when neither is present does this fall back to `(invoke, node, step)`, and it says so on the
group rather than hiding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from firebreak.tracing.events import Event

# langgraph/_internal/_constants.py
NS_SEP = "|"
NS_END = ":"

# Events that are about the thread rather than about one task execution.
TURN_LEVEL_KINDS = {"checkpoint", "checkpoint_fact", "run_error", "injection"}


def task_id_from_checkpoint_ns(namespace: Optional[str]) -> Optional[str]:
    """The task id LangGraph encoded in a checkpoint namespace, or None."""
    if not namespace:
        return None
    last = str(namespace).split(NS_SEP)[-1]
    _, separator, task_id = last.partition(NS_END)
    return task_id or None if separator else None


def event_task_id(event: Event) -> tuple[Optional[str], str]:
    """(task id, how it was resolved). `how` is one of task_id | checkpoint_ns | none."""
    if event.task_id:
        return str(event.task_id), "task_id"
    namespace = (event.payload or {}).get("langgraph", {}).get("checkpoint_ns")
    resolved = task_id_from_checkpoint_ns(namespace)
    if resolved:
        return resolved, "checkpoint_ns"
    return None, "none"


@dataclass
class TaskRunEvents:
    """Every event recorded for one task execution."""

    key: str
    task_id: Optional[str]
    node: Optional[str]
    step: Optional[int]
    turn: Optional[int]
    invoke_id: Optional[str]
    identity: str  # task_id | checkpoint_ns | invoke_node_step
    events: list = field(default_factory=list)

    @property
    def first_seq(self) -> int:
        return min(e.seq for e in self.events) if self.events else 0

    @property
    def last_seq(self) -> int:
        return max(e.seq for e in self.events) if self.events else 0

    @property
    def label(self) -> str:
        base = self.node if self.step is None else f"{self.node}@{self.step}"
        return base if self.turn is None else f"{base} (turn {self.turn})"

    @property
    def failed(self) -> bool:
        return any(e.kind in ("node_error", "tool_error", "llm_error", "chain_error") for e in self.events)

    def of_kind(self, *kinds: str) -> list:
        return [e for e in self.events if e.kind in kinds]


@dataclass
class GroupedTrace:
    runs: list = field(default_factory=list)  # TaskRunEvents, in start order
    turn_events: list = field(default_factory=list)  # checkpoints, injections, run errors
    unattached: list = field(default_factory=list)  # events with no resolvable task
    warnings: list = field(default_factory=list)

    def by_task_id(self) -> dict:
        return {run.task_id: run for run in self.runs if run.task_id}

    def for_turn(self, turn: Optional[int]) -> list:
        return [run for run in self.runs if run.turn == turn]


def group_by_task_run(trace) -> GroupedTrace:
    """Split a trace into task executions by recorded identity, safe under fan-out."""
    grouped = GroupedTrace()
    runs: dict[str, TaskRunEvents] = {}
    fallbacks: set = set()

    for event in trace.events:
        if event.kind in TURN_LEVEL_KINDS:
            grouped.turn_events.append(event)
            continue
        task_id, how = event_task_id(event)
        if task_id is not None:
            key = task_id
        elif event.node is not None:
            key = f"{event.invoke_id}:{event.node}@{event.step}"
            how = "invoke_node_step"
            fallbacks.add(key)
        else:
            grouped.unattached.append(event)
            continue
        run = runs.get(key)
        if run is None:
            run = TaskRunEvents(
                key=key,
                task_id=task_id,
                node=event.node,
                step=event.step,
                turn=event.turn,
                invoke_id=event.invoke_id,
                identity=how,
            )
            runs[key] = run
            grouped.runs.append(run)
        else:
            # a group keeps the first identity that resolved it, but fills in blanks
            run.node = run.node or event.node
            run.step = run.step if run.step is not None else event.step
            run.turn = run.turn if run.turn is not None else event.turn
            run.invoke_id = run.invoke_id or event.invoke_id
        run.events.append(event)

    for key in sorted(fallbacks):
        grouped.warnings.append(
            f"events for {key} carried neither a task id nor a checkpoint namespace, so they were "
            "grouped by (invoke, node, step); two tasks of the same node in that step would merge"
        )
    grouped.runs.sort(key=lambda r: r.first_seq)
    return grouped
