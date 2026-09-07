"""Unit tests that need no LangGraph run: fault specs, graph building, propagation."""

from firebreak.graph.execution import ExecutionGraph
from firebreak.graph.propagation import propagate
from firebreak.injection.faults import DEFAULT_MARKER, Fault, FaultPlan
from firebreak.tracing.events import Event, is_routing_channel, safe
from firebreak.tracing.recorder import Trace


def test_fault_parse_variants():
    f = Fault.parse("tool_error:search_web")
    assert (f.kind, f.target, f.on_call, f.payload) == ("tool_error", "search_web", 1, None)
    f = Fault.parse("tool_bad_output:search_web:2:Firebreak launched in 1999.")
    assert f.on_call == 2 and f.payload == "Firebreak launched in 1999."
    f = Fault.parse("timeout:planner::0.01")
    assert f.on_call == 1 and f.payload == "0.01"


def test_fault_parse_rejects_bad_kind():
    try:
        Fault.parse("explode:search_web")
    except ValueError as exc:
        assert "unknown fault kind" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_plan_tool_wrapper_injects_on_nth_call():
    plan = FaultPlan.parse(["tool_error:echo:2"])

    @plan.tool("echo", "echo the input")
    def echo(text: str) -> str:
        return text

    assert echo.invoke({"text": "a"}) == "a"
    try:
        echo.invoke({"text": "b"})
    except Exception as exc:
        assert DEFAULT_MARKER in str(exc)
    else:
        raise AssertionError("second call should fail")
    assert plan.log and plan.log[0]["call_no"] == 2


def test_safe_truncates_and_handles_exceptions():
    assert safe(ValueError("boom"))["error_type"] == "ValueError"
    assert len(safe("x" * 10000)) < 10000
    assert is_routing_channel("branch:to:reviewer") and not is_routing_channel("findings")


def _synthetic_trace() -> Trace:
    """researcher -> reviewer -> executor, archivist -> executor; researcher tool fails."""
    trace = Trace()
    trace.meta["static_graph"] = {
        "nodes": ["__start__", "researcher", "archivist", "reviewer", "executor", "__end__"],
        "edges": [
            {"source": "__start__", "target": "researcher"},
            {"source": "__start__", "target": "archivist"},
            {"source": "researcher", "target": "reviewer"},
            {"source": "reviewer", "target": "executor"},
            {"source": "archivist", "target": "executor"},
            {"source": "executor", "target": "__end__"},
        ],
    }
    trace.add(Event("node_start", name="researcher", node="researcher", step=1, task_id="t1"))
    trace.add(Event("node_start", name="archivist", node="archivist", step=1, task_id="t2"))
    trace.add(Event("tool_start", name="search_web", node="researcher", step=1, run_id="r1"))
    trace.add(Event("tool_error", name="search_web", node="researcher", step=1, run_id="r1", payload={"error": {"error_type": "RuntimeError", "message": "down"}}))
    trace.add(Event("node_end", name="researcher", node="researcher", step=1, task_id="t1", payload={"writes": {"findings": "guess"}}))
    trace.add(Event("node_end", name="archivist", node="archivist", step=1, task_id="t2", payload={"writes": {"archive_note": "ok"}}))
    trace.add(Event("node_start", name="reviewer", node="reviewer", step=2, task_id="t3"))
    trace.add(Event("node_end", name="reviewer", node="reviewer", step=2, task_id="t3", payload={"writes": {"review": "APPROVED"}}))
    trace.add(Event("node_start", name="executor", node="executor", step=3, task_id="t4"))
    trace.add(Event("node_end", name="executor", node="executor", step=3, task_id="t4", payload={"writes": {"status": "failed"}}))
    return trace


def test_execution_graph_edges_and_propagation():
    graph = ExecutionGraph.from_trace(_synthetic_trace())
    assert graph.total_runs == 4
    edges = {(graph.get(e.src).name, graph.get(e.dst).name) for e in graph.edges}
    assert edges == {("researcher", "reviewer"), ("reviewer", "executor"), ("archivist", "executor")}
    researcher = graph.runs_named("researcher")[0]
    assert researcher.tools and researcher.tools[0].failed
    prop = propagate(graph, researcher.id)
    names = [graph.get(r).name for r in prop.affected]
    assert names == ["researcher", "reviewer", "executor"]
    assert abs(prop.blast_radius - 0.75) < 1e-9


def test_trace_jsonl_roundtrip(tmp_path):
    trace = _synthetic_trace()
    path = tmp_path / "t.jsonl"
    trace.to_jsonl(str(path))
    loaded = Trace.from_jsonl(str(path))
    assert len(loaded.events) == len(trace.events)
    assert loaded.meta["static_graph"]["edges"] == trace.meta["static_graph"]["edges"]
