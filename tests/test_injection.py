"""Controlled fault injection: the specs, the wrappers, and the record each injection leaves.

Injection is not the current line of work, but it is how a capture with a known bad value gets
made, so the machinery has to stay honest: faults fire on the call they say they will, and every
one leaves a record naming what it changed.
"""

from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from firebreak.injection.faults import DEFAULT_MARKER, Fault, FaultPlan
from firebreak.tracing.recorder import Trace, record


def test_fault_spec_parsing():
    fault = Fault.parse("tool_error:search_web")
    assert (fault.kind, fault.target, fault.on_call, fault.payload) == ("tool_error", "search_web", 1, None)
    fault = Fault.parse("tool_bad_output:search_web:2:Firebreak launched in 1999.")
    assert fault.on_call == 2 and fault.payload == "Firebreak launched in 1999."
    fault = Fault.parse("timeout:planner::0.01")
    assert fault.on_call == 1 and fault.payload == "0.01"


@pytest.mark.parametrize("spec", ["explode:search_web", "tool_error", ":search_web", "tool_error:"])
def test_a_bad_spec_is_rejected_rather_than_ignored(spec):
    with pytest.raises(ValueError):
        Fault.parse(spec)


def test_on_call_is_one_based_and_must_be_positive():
    with pytest.raises(ValueError):
        Fault(kind="tool_error", target="x", on_call=0)


def test_a_tool_fault_fires_on_the_call_it_names():
    plan = FaultPlan.parse(["tool_error:echo:2"])

    @plan.tool("echo", "echo the input")
    def echo(text: str) -> str:
        return text

    assert echo.invoke({"text": "a"}) == "a", "the first call must be untouched"
    with pytest.raises(RuntimeError) as raised:
        echo.invoke({"text": "b"})
    assert DEFAULT_MARKER in str(raised.value)
    assert echo.invoke({"text": "c"}) == "c", "only the named call is affected"
    assert [entry["call_no"] for entry in plan.log] == [2]


def test_a_literal_payload_replaces_the_tool_without_calling_it():
    """The clean value is never produced, so there is no `before` to record, and none is invented.

    Not calling the real tool is deliberate: it may have side effects, and a fault that replaces
    its result has no business triggering them.
    """
    plan = FaultPlan.parse(["tool_bad_output:lookup:1:wrong"])
    calls = []

    @plan.tool("lookup", "look something up")
    def lookup(key: str) -> str:
        calls.append(key)
        return "right"

    assert "wrong" in lookup.invoke({"key": "k"})
    assert calls == [], "the replaced call must not reach the real tool"
    entry = plan.log[0]
    assert entry["fault_id"] == "fault-001" and entry["effective"] is True
    changed = [field for field in entry["fields"] if field["changed"]]
    assert changed and changed[0]["before"] == "" and "wrong" in changed[0]["after"]


def test_a_transform_records_both_sides_of_what_it_changed():
    """A transform needs the clean value, so it is produced and both sides are recorded."""
    plan = FaultPlan.parse(["tool_bad_output:lookup:1:swap"], marker="")
    plan.register_transform("swap", lambda text: text.replace("right", "wrong"))
    calls = []

    @plan.tool("lookup", "look something up")
    def lookup(key: str) -> str:
        calls.append(key)
        return "right"

    assert lookup.invoke({"key": "k"}) == "wrong"
    assert calls == ["k"], "a transform needs the real result, so the tool does run"
    changed = [field for field in plan.log[0]["fields"] if field["changed"]]
    assert changed and changed[0]["before"] == "right" and changed[0]["after"] == "wrong"
    assert changed[0]["before_sha1"] != changed[0]["after_sha1"]


def test_a_transform_that_changes_nothing_is_marked_ineffective():
    """An injection that fired but altered no text cannot be the start of anything."""
    plan = FaultPlan.parse(["node_bad_output:n:1:identity"], marker="")
    plan.register_transform("identity", lambda text: text)

    def node(state: dict) -> dict:
        return {"messages": "unchanged"}

    assert plan.wrap_node("n", node)({}) == {"messages": "unchanged"}
    assert plan.log[0]["effective"] is False


class S(TypedDict):
    messages: Annotated[list, add_messages]


def test_a_node_fault_rewrites_the_message_and_records_sidecar_provenance():
    """The model must see only the corrupted content; the ground truth rides in metadata."""
    plan = FaultPlan.parse(["message_corruption:worker:1:swap"], marker="")
    plan.register_transform("swap", lambda text: text.replace("ABC123", "XYZ999"))

    def worker(state: S) -> dict:
        return {"messages": [AIMessage(content="reservation ABC123", id="w1")]}

    builder = StateGraph(S)
    builder.add_node("worker", plan.wrap_node("worker", worker))
    builder.add_edge(START, "worker")
    builder.add_edge("worker", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    trace = Trace()
    plan.bind(trace)
    record(graph, {"messages": [HumanMessage(content="go", id="h1")]}, trace=trace, thread_id="t", turn=0)

    messages = (trace.final_state or {}).get("messages") or []
    corrupted = next(m for m in messages if getattr(m, "id", None) == "w1")
    assert corrupted.content == "reservation XYZ999"
    assert DEFAULT_MARKER not in corrupted.content, "no visible marker may leak into what the model reads"
    assert corrupted.response_metadata["firebreak"]["fault_id"] == "fault-001"

    injections = trace.of_kind("injection")
    assert len(injections) == 1 and injections[0].payload["effective"] is True
    assert injections[0].turn == 0, "an injection is stamped with the turn it happened in"
