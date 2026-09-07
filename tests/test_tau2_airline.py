"""The first non-toy cascade: tau2 airline task 39 with a Supervisor + Lookup + Booking team.

clean run  -> tau2 reward 1, no cascade
fault run  -> lookup's report is corrupted, booking cancels the wrong reservation, reward 0,
              Firebreak reports source lookup, path lookup -> supervisor -> booking, harmful action.
"""

from firebreak.integrations.tau2_airline.runner import run_episode

TASK = "39"
EXPECTED_CANCELS = {"8C8K4E", "LU15PA", "MSJ4OA"}
SWAP = "message_corruption:lookup:1:swap_first_eligible_reservation"


def test_clean_episode_passes_tau2_task_39():
    result = run_episode(TASK, model="fake")
    assert result.success, result.success_reasons
    assert result.reward == 1.0
    cancels = {c["args"]["reservation_id"] for c in result.tool_calls if c["name"] == "cancel_reservation"}
    assert cancels == EXPECTED_CANCELS
    assert not result.analysis.report.detected
    assert result.turns >= 1 and result.terminated_by == "user_stop"


def test_the_trace_is_episode_level_not_per_invoke():
    result = run_episode(TASK, model="fake")
    trace = result.trace
    assert trace.turns and trace.turns[0] == 0
    assert all(e.turn is not None for e in trace.events if e.kind == "node_start")
    graph = result.analysis.graph
    assert {r.name for r in graph.runs} >= {"supervisor", "lookup", "booking"}
    # tool calls made inside worker loops are attributed to the worker node
    booking_tools = [t.name for r in graph.runs_named("booking") for t in r.tools]
    assert booking_tools.count("cancel_reservation") == 3
    lookup_tools = {t.name for r in graph.runs_named("lookup") for t in r.tools}
    assert {"get_user_details", "get_reservation_details"} <= lookup_tools


def test_a_corrupted_lookup_report_cascades_into_a_wrong_cancellation():
    result = run_episode(TASK, model="fake", inject=[SWAP])
    report = result.analysis.report

    # tau2 objective evaluation: the DB no longer matches the expected end state
    assert not result.success and result.db_score == 0.0
    cancels = [c["args"]["reservation_id"] for c in result.tool_calls if c["name"] == "cancel_reservation"]
    assert "UDMOP1" in cancels and "8C8K4E" not in cancels

    # Firebreak: source, propagation, harmful action, damaged utility
    assert report.detected
    assert report.source["node"] == "lookup" and report.source["oracle"]
    assert report.path[:3] == ["lookup", "supervisor", "booking"]
    assert report.reached["supervisor"] and report.reached["booking"]
    harmful = [a for a in report.harmful_actions if a["tool"] == "cancel_reservation"]
    assert any(a["args"].get("reservation_id") == "UDMOP1" for a in harmful)
    assert report.utility_damaged
    text = report.render()
    assert "Cascade detected" in text and "lookup" in text and "cancel_reservation" in text


def test_the_corrupted_message_carries_sidecar_provenance_and_no_visible_marker():
    result = run_episode(TASK, model="fake", inject=[SWAP])
    injections = result.trace.of_kind("injection")
    assert len(injections) == 1
    payload = injections[0].payload
    assert payload["fault_id"] == "fault-001" and payload["marker"] == ""
    changed = [f for f in payload["fields"] if f["changed"]]
    assert changed and "UDMOP1" in changed[0]["after"]
    # the report the supervisor saw contains no marker text
    messages = (result.trace.final_state or {}).get("messages") or []
    lookup_reports = [m for m in messages if getattr(m, "name", None) == "delegate_to_lookup"]
    assert lookup_reports and "FIREBREAK" not in lookup_reports[0].content
    assert lookup_reports[0].response_metadata.get("firebreak", {}).get("fault_id") == "fault-001"
