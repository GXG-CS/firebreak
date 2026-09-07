"""Milestone 1: a minimal LangGraph MAS + fault injection, one complete captured cascade."""

from pathlib import Path

import pytest

from firebreak.injection.faults import FaultPlan
from firebreak.runner import analyze, load_example, run_app
from firebreak.tracing.recorder import Trace

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "multi_agent" / "research_team.py"
NODES = {"researcher", "archivist", "reviewer", "planner", "executor"}


def _run(specs):
    module = load_example(str(EXAMPLE))
    plan = FaultPlan.parse(specs)
    app = module.build(model="fake", plan=plan)
    return run_app(app, plan)


def test_clean_run_has_no_cascade():
    analysis = _run([])
    report = analysis.report
    assert set(analysis.graph.node_names()) == NODES
    assert analysis.graph.total_runs == 5
    assert not report.detected
    assert report.outcome == "PASSED"
    # every node run has a recorded end and writes
    assert all(r.end_seq is not None for r in analysis.graph.runs)
    assert analysis.graph.runs_named("researcher")[0].data_writes.get("findings")


def test_tool_failure_cascade_is_captured_end_to_end():
    analysis = _run(["tool_error:search_web"])
    trace, graph, report = analysis.trace, analysis.graph, analysis.report

    # Capture: node events, tool error, model calls, injection record.
    assert {e.node for e in trace.of_kind("node_start")} == NODES
    tool_errors = trace.of_kind("tool_error")
    assert tool_errors and tool_errors[0].name == "search_web" and tool_errors[0].node == "researcher"
    assert trace.of_kind("llm_start"), "model calls must be attributed to nodes"
    assert all(e.node in NODES for e in trace.of_kind("llm_start"))
    assert trace.of_kind("injection")

    # Represent: 5 runs, join at executor.
    edges = {(graph.get(e.src).name, graph.get(e.dst).name) for e in graph.edges}
    assert edges == {("researcher", "reviewer"), ("reviewer", "planner"), ("planner", "executor"), ("archivist", "executor")}

    # Detect + Trace + Report.
    assert report.detected
    assert report.source["node"] == "researcher" and report.source["name"] == "search_web"
    assert report.source["kind"] == "tool_error"
    assert report.path == ["researcher", "reviewer", "planner", "executor"]
    assert report.affected == 4 and report.total == 5
    assert abs(report.blast_radius - 0.8) < 1e-9
    assert report.detection_delay == 0
    assert report.outcome == "FAILED"
    text = report.render()
    assert "Cascade detected" in text and "researcher.search_web" in text and "Blast radius: 80%" in text


def test_bad_retrieval_detected_by_marker():
    analysis = _run(["tool_bad_output:search_web:1:Firebreak launched in 1999."])
    report = analysis.report
    assert report.detected and report.source["kind"] == "corruption_marker"
    assert report.source["node"] == "researcher"
    assert report.outcome == "FAILED"
    assert report.path == ["researcher", "reviewer", "planner", "executor"]


def test_message_corruption_propagates_but_task_passes():
    analysis = _run(["message_corruption:researcher"])
    report = analysis.report
    assert report.detected and report.source["node"] == "researcher"
    assert report.outcome == "PASSED"
    assert "reviewer" in report.path and "archivist" not in report.path


def test_saved_trace_reanalyses_identically(tmp_path):
    module = load_example(str(EXAMPLE))
    plan = FaultPlan.parse(["tool_error:search_web"])
    app = module.build(model="fake", plan=plan)
    path = tmp_path / "trace.jsonl"
    first = run_app(app, plan, save=str(path))
    loaded = Trace.from_jsonl(str(path))
    second = analyze(loaded, str(loaded.meta["outcome"]), validators=app.validators)
    assert second.report.source["location"] == first.report.source["location"]
    assert second.report.path == first.report.path
    assert second.report.blast_radius == first.report.blast_radius


@pytest.mark.parametrize("spec", ["timeout:search_web::0.01", "node_bad_output:planner"])
def test_other_fault_kinds_are_reported(spec):
    report = _run([spec]).report
    assert report.detected
