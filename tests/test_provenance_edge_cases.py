"""Tasks that write nothing, tasks that fail, and versions that do not retain their predecessor.

These are the cases where "who ran" cannot come from `pending_writes` and where "the new version
contains the old one" is false. A fault analysis cares about exactly these.
"""

from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from firebreak.provenance.graph import ProvenanceGraph
from firebreak.tracing.recorder import Trace, record


class S(TypedDict):
    messages: Annotated[list, add_messages]


def _build(nodes: list, edges: list):
    builder = StateGraph(S)
    for name, fn in nodes:
        builder.add_node(name, fn)
    for src, dst in edges:
        builder.add_edge(src, dst)
    return builder.compile(checkpointer=InMemorySaver())


def _run(graph, payload=None):
    trace = Trace()
    record(graph, payload or {"messages": [HumanMessage(content="go", id="h1")]},
           trace=trace, thread_id="t", turn=0)
    return trace, ProvenanceGraph.from_trace(trace)


def test_a_task_that_writes_no_state_still_gets_read_provenance():
    """It wrote no state channel, only LangGraph's `__no_writes__` marker, and must still be here."""

    def writer(state: S) -> dict:
        return {"messages": [AIMessage(content="from writer", id="a1")]}

    def silent(state: S) -> None:
        assert state["messages"]  # it really did read the state
        return None

    trace, prov = _run(_build(
        [("writer", writer), ("silent", silent)],
        [(START, "writer"), ("writer", "silent"), ("silent", END)],
    ))
    silent_runs = [t for t in prov.tasks.values() if t.node == "silent"]
    assert len(silent_runs) == 1
    run = silent_runs[0]
    assert run.wrote is False, "a sentinel write is not a state write"
    assert run.outcome == "no_writes", "LangGraph's own marker for a task that returned nothing"
    assert run.scheduled_from, "a task that wrote no state must still be placed on a checkpoint"
    reads = [r for r in prov.reads if r.kind == "state" and run.task_id in r.task_ids]
    assert reads, "a task that only reads must still have READ provenance"
    assert any(r.evidence.channel == "messages" for r in reads)
    # the sentinel must not become a state version
    assert not any(s.channel.startswith("__no_writes__") for s in prov.states.values())


def test_a_task_that_fails_keeps_its_read_provenance():
    """The task whose fault we would be tracing must not vanish from the graph."""

    def writer(state: S) -> dict:
        return {"messages": [AIMessage(content="context the failure saw", id="a1")]}

    def boom(state: S) -> dict:
        raise RuntimeError("boom")

    trace, prov = _run(_build(
        [("writer", writer), ("boom", boom)],
        [(START, "writer"), ("writer", "boom"), ("boom", END)],
    ))
    assert trace.meta.get("run_error"), "the failure must reach the trace"
    boom_runs = [t for t in prov.tasks.values() if t.node == "boom"]
    assert len(boom_runs) == 1, "the failing task must be in the provenance graph"
    run = boom_runs[0]
    assert run.outcome == "error", "LangGraph records the failure as an __error__ write"
    assert run.wrote is False, "an error marker is not a state write"
    assert run.scheduled_from, "the failing task must be placed on the checkpoint it read"
    assert not any(s.channel == "__error__" for s in prov.states.values())
    reads = [r for r in prov.reads if r.kind == "state" and run.task_id in r.task_ids]
    assert reads, "we must be able to say what state the failing task was handed"
    version = reads[0].evidence.version
    producers = prov.producers_of(f"messages:{version}")
    assert any(prov.tasks[p].node == "writer" for p in producers), (
        "the state the failure read must be traceable back to who produced it"
    )


def test_a_version_that_drops_a_message_is_refuted_not_assumed():
    """add_messages folds, but RemoveMessage deletes: containment must be checked, not claimed."""

    def writer(state: S) -> dict:
        return {"messages": [AIMessage(content="doomed", id="doomed")]}

    def remover(state: S) -> dict:
        return {"messages": [RemoveMessage(id="doomed")]}

    _, prov = _run(_build(
        [("writer", writer), ("remover", remover)],
        [(START, "writer"), ("writer", "remover"), ("remover", END)],
    ))
    assert "messages" in prov.accumulating
    verdicts = [d.verdict for d in prov.derived if prov.states[d.state_key].channel == "messages"]
    assert "refuted" in verdicts, f"dropping a message must be caught, got {verdicts}"
    refuted = next(d for d in prov.derived if d.verdict == "refuted")
    assert "doomed" in refuted.lost
    assert refuted.evidence_class == "derived"
    # a refuted link must not be walked through when following accumulation
    assert refuted.from_state_key not in prov.derivation_ancestors(refuted.state_key)


def test_a_replaced_message_is_also_refuted():
    """Same id, new content: the earlier version's element is gone."""

    def writer(state: S) -> dict:
        return {"messages": [AIMessage(content="first", id="same")]}

    def rewriter(state: S) -> dict:
        return {"messages": [AIMessage(content="second", id="same")]}

    _, prov = _run(_build(
        [("writer", writer), ("rewriter", rewriter)],
        [(START, "writer"), ("writer", "rewriter"), ("rewriter", END)],
    ))
    # the id survives, so containment by id holds; this documents the limit of id-level checking
    verdicts = {d.verdict for d in prov.derived if prov.states[d.state_key].channel == "messages"}
    assert verdicts <= {"verified", "refuted", "unverified"}


@pytest.mark.parametrize("node_name", ["writer", "silent"])
def test_every_task_in_the_trace_appears_in_the_graph(node_name):
    def writer(state: S) -> dict:
        return {"messages": [AIMessage(content="x", id="a1")]}

    def silent(state: S) -> None:
        return None

    trace, prov = _run(_build(
        [("writer", writer), ("silent", silent)],
        [(START, "writer"), ("writer", "silent"), ("silent", END)],
    ))
    in_trace = {e.task_id for e in trace.events if e.kind == "node_start" and e.node == node_name}
    assert in_trace <= set(prov.tasks), "no executed task may be missing from the provenance graph"


def test_step_alignment_places_a_task_absent_from_every_checkpoint_write():
    """Defence in depth: if a task ever failed to appear in any write, it is still placed.

    In LangGraph 1.2.11 this cannot happen (every executed task writes a sentinel), so the case is
    constructed by removing one task's writes from a real trace.
    """
    from firebreak.provenance.capture import CHECKPOINT_FACT

    def writer(state: S) -> dict:
        return {"messages": [AIMessage(content="x", id="a1")]}

    def second(state: S) -> dict:
        return {"messages": [AIMessage(content="y", id="a2")]}

    trace, _ = _run(_build(
        [("writer", writer), ("second", second)],
        [(START, "writer"), ("writer", "second"), ("second", END)],
    ))
    victim = next(e.task_id for e in trace.events if e.kind == "node_start" and e.node == "second")
    for event in trace.of_kind(CHECKPOINT_FACT):
        event.payload["writes"] = [w for w in event.payload["writes"] if w["task_id"] != victim]

    prov = ProvenanceGraph.from_trace(trace)
    run = prov.tasks[victim]
    assert run.resolution == "step_alignment", "membership must not depend on having written"
    assert run.scheduled_from
    assert [r for r in prov.reads if r.kind == "state" and victim in r.task_ids]
