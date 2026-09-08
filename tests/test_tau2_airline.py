"""tau2 airline task 39: the run the canonical capture comes from.

clean run  -> tau2 reward 1
fault run  -> the lookup specialist's report is corrupted, booking cancels the wrong reservation,
              and the objective evaluator fails the task

These check the environment and the injection, not any analysis on top: what the capture is then
used for is covered by the provenance and episode tests.
"""

from firebreak.episode.graph import EpisodeGraph
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
    assert result.turns >= 1 and result.terminated_by == "user_stop"
    assert not result.trace.of_kind("injection"), "a clean run injects nothing"


def test_the_capture_is_episode_level_and_attributes_tools_to_workers():
    result = run_episode(TASK, model="fake")
    trace = result.trace
    assert trace.turns and trace.turns[0] == 0
    assert all(e.turn is not None for e in trace.events if e.kind == "node_start")

    episode = result.episode
    assert episode is not None
    turn = episode.turn(0)
    assert {r.node for r in turn.agent_task_runs} >= {"supervisor", "lookup", "booking"}

    booking = next(r for r in turn.agent_task_runs if r.node == "booking")
    tools = [e.name for e in turn.events(booking.task_id) if e.kind == "tool_start"]
    assert tools.count("cancel_reservation") == 3
    lookup = next(r for r in turn.agent_task_runs if r.node == "lookup")
    lookup_tools = {e.name for e in turn.events(lookup.task_id) if e.kind == "tool_start"}
    assert {"get_user_details", "get_reservation_details"} <= lookup_tools


def test_a_corrupted_lookup_report_leads_to_a_wrong_cancellation():
    """The objective evaluator, not any analysis of ours, is what says the task failed."""
    result = run_episode(TASK, model="fake", inject=[SWAP])
    assert not result.success and result.db_score == 0.0
    cancels = [c["args"]["reservation_id"] for c in result.tool_calls if c["name"] == "cancel_reservation"]
    assert "UDMOP1" in cancels and "8C8K4E" not in cancels


def test_the_corrupted_message_carries_sidecar_provenance_and_no_visible_marker():
    result = run_episode(TASK, model="fake", inject=[SWAP])
    injections = result.trace.of_kind("injection")
    assert len(injections) == 1
    payload = injections[0].payload
    assert payload["fault_id"] == "fault-001" and payload["marker"] == ""
    changed = [f for f in payload["fields"] if f["changed"]]
    assert changed and "UDMOP1" in changed[0]["after"]
    messages = (result.trace.final_state or {}).get("messages") or []
    lookup_reports = [m for m in messages if getattr(m, "name", None) == "delegate_to_lookup"]
    assert lookup_reports and "FIREBREAK" not in lookup_reports[0].content
    assert lookup_reports[0].response_metadata.get("firebreak", {}).get("fault_id") == "fault-001"


def test_the_injected_write_is_traceable_to_a_task_in_the_episode():
    """The corrupted report is a real state write, so the projection must attribute it."""
    result = run_episode(TASK, model="fake", inject=[SWAP])
    episode = result.episode
    turn = episode.turn(0)
    lookup = next(r for r in turn.agent_task_runs if r.node == "lookup")
    written = [w for w in turn.writes if w.task_id == lookup.task_id]
    assert written, "the lookup task's write must appear in the turn"
    assert any(w.evidence.channel == "messages" for w in written)
