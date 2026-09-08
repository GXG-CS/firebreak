"""The episode / turn projection, and the grouping it depends on.

The grouping tests matter most: an earlier renderer tracked a single "currently open" task run,
which silently mis-attributes events as soon as a super-step fans out. These build a real fan-out
graph and check that both parallel executions keep their own events.
"""

from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send

from firebreak.episode.graph import CrossTurnLink, EpisodeGraph, is_internal
from firebreak.episode.views import episode_diagram, render_episode_markdown, turn_diagram
from firebreak.integrations.tau2_airline.runner import run_episode
from firebreak.provenance.graph import ProvenanceGraph
from firebreak.tracing.grouping import group_by_task_run, task_id_from_checkpoint_ns
from firebreak.tracing.recorder import Trace, record

# The committed capture: tau2 airline task 39 on Qwen2.5-14B, three turns. The scripted `fake`
# team finishes the same task in one turn, so multi-turn structure is checked against this file.
CANONICAL_TRACE = Path(__file__).resolve().parents[1] / "docs" / "traces" / "tau2_task39_qwen14b_clean.jsonl"
CANONICAL = {
    0: ["supervisor@1"],
    1: ["supervisor@4", "lookup@5", "supervisor@6"],
    2: ["supervisor@9", "booking@10", "supervisor@11"],
}


def _canonical_episode() -> EpisodeGraph:
    return EpisodeGraph.from_trace(Trace.from_jsonl(str(CANONICAL_TRACE)))


# ---- fan-out fixture: two task runs in the same super-step -----------------------------------

class S(TypedDict):
    messages: Annotated[list, add_messages]


@tool
def note(text: str) -> str:
    """Record a note."""
    return f"noted: {text}"


def _fan_out_graph():
    """START fans out to two nodes in one super-step, which then join."""

    def left(state: S, config) -> dict:
        note.invoke({"text": "left"}, config=config)
        return {"messages": [AIMessage(content="left", id="l1")]}

    def right(state: S, config) -> dict:
        note.invoke({"text": "right"}, config=config)
        return {"messages": [AIMessage(content="right", id="r1")]}

    def join(state: S) -> dict:
        return {"messages": [AIMessage(content="joined", id="j1")]}

    builder = StateGraph(S)
    builder.add_node("left", left)
    builder.add_node("right", right)
    builder.add_node("join", join)
    builder.add_edge(START, "left")
    builder.add_edge(START, "right")
    builder.add_edge(["left", "right"], "join")
    builder.add_edge("join", END)
    return builder.compile(checkpointer=InMemorySaver())


class SendState(TypedDict):
    item: str
    messages: Annotated[list, add_messages]


def _send_fan_out_graph():
    """`Send` runs the SAME node several times in one super-step, with different task ids.

    This is the case `(node, step)` cannot separate, so it is the real test of attributing an event
    by the task id LangGraph encodes in the checkpoint namespace.
    """

    def dispatch(state: SendState) -> list:
        return [Send("worker", {"item": "a"}), Send("worker", {"item": "b"})]

    def start(state: SendState) -> dict:
        return {"messages": [AIMessage(content="dispatching", id="s1")]}

    def worker(state: SendState, config) -> dict:
        item = state["item"]
        note.invoke({"text": item}, config=config)
        return {"messages": [AIMessage(content=f"worker {item}", id=f"w_{item}")]}

    builder = StateGraph(SendState)
    builder.add_node("start_node", start)
    builder.add_node("worker", worker)
    builder.add_edge(START, "start_node")
    builder.add_conditional_edges("start_node", dispatch, ["worker"])
    builder.add_edge("worker", END)
    return builder.compile(checkpointer=InMemorySaver())


def _send_trace() -> Trace:
    trace = Trace()
    record(_send_fan_out_graph(), {"item": "", "messages": [HumanMessage(content="go", id="h1")]},
           trace=trace, thread_id="send", turn=0)
    return trace


def _fan_out_trace() -> Trace:
    trace = Trace()
    record(_fan_out_graph(), {"messages": [HumanMessage(content="go", id="h1")]},
           trace=trace, thread_id="fan", turn=0)
    return trace


# ---- grouping ---------------------------------------------------------------------------------

def test_task_id_is_parsed_from_the_checkpoint_namespace():
    """LangGraph encodes `{parent}|{node}:{task_id}`; anything else must be declined, not guessed."""
    uuid_a = "0123abcd-4567-89ab-cdef-0123456789ab"
    uuid_b = "fedcba98-7654-3210-fedc-ba9876543210"
    assert task_id_from_checkpoint_ns(f"supervisor:{uuid_a}") == uuid_a
    assert task_id_from_checkpoint_ns(f"parent|child:{uuid_b}") == uuid_b
    for unrecognised in ("", None, "no-separator", "supervisor:abc-123", "supervisor:", ":only"):
        assert task_id_from_checkpoint_ns(unrecognised) is None, unrecognised


def test_parallel_task_runs_in_one_step_keep_their_own_events():
    trace = _fan_out_trace()
    grouped = group_by_task_run(trace)
    by_node = {}
    for run in grouped.runs:
        by_node.setdefault(run.node, []).append(run)

    assert set(by_node) == {"left", "right", "join"}
    left, right = by_node["left"][0], by_node["right"][0]
    assert left.step == right.step, "the fixture must actually fan out within one super-step"
    assert left.task_id and right.task_id and left.task_id != right.task_id
    assert not grouped.warnings, f"identity should be recorded, not guessed: {grouped.warnings}"

    # each parallel run keeps its own tool call: the failure mode of a single-open-run grouper
    for run, expected in ((left, "left"), (right, "right")):
        tools = run.of_kind("tool_start")
        assert len(tools) == 1, f"{run.node} lost its tool event to the other parallel run"
        assert tools[0].payload["input"]["text"] == expected
    assert not any(e.kind.startswith("tool") for e in grouped.unattached)


def test_the_same_node_twice_in_one_step_is_separated_by_recorded_task_id():
    """Two `worker` task runs in one super-step: `(node, step)` cannot tell them apart."""
    trace = _send_trace()
    grouped = group_by_task_run(trace)
    workers = [run for run in grouped.runs if run.node == "worker"]

    assert len(workers) == 2, f"Send must produce two worker task runs, got {[r.node for r in grouped.runs]}"
    assert workers[0].step == workers[1].step, "both must be in the same super-step"
    assert workers[0].task_id != workers[1].task_id
    assert not grouped.warnings, f"attribution must be exact, not a fallback: {grouped.warnings}"
    assert {r.identity for r in workers} <= {"task_id", "checkpoint_ns"}

    # each worker keeps its own tool call; a (node, step) key would have merged them
    seen = set()
    for run in workers:
        tools = run.of_kind("tool_start")
        assert len(tools) == 1, f"a worker lost its tool event: {[e.kind for e in run.events]}"
        seen.add(tools[0].payload["input"]["text"])
    assert seen == {"a", "b"}


def test_at_least_one_worker_is_attributed_purely_by_the_checkpoint_namespace():
    """The callbacks carry no task id of their own, only the namespace it is encoded in."""
    trace = _send_trace()
    callback_events = [e for e in trace.events
                       if e.kind in ("tool_start", "chain_start") and e.node == "worker"]
    assert callback_events, "the fixture must produce callback events inside the repeated node"
    assert all(e.task_id is None for e in callback_events), (
        "callback events carry no task_id; if they ever do, this test is no longer testing the parser"
    )
    resolved = {task_id_from_checkpoint_ns((e.payload.get("langgraph") or {}).get("checkpoint_ns"))
                for e in callback_events}
    assert len(resolved) == 2 and None not in resolved, (
        f"the namespace must yield both worker task ids, got {resolved}"
    )


def test_an_unrecognised_namespace_declines_instead_of_guessing():
    assert task_id_from_checkpoint_ns("worker:not-a-uuid") is None
    assert task_id_from_checkpoint_ns("worker:") is None
    assert task_id_from_checkpoint_ns("parent|worker:0123abcd-4567-89ab-cdef-0123456789ab") == (
        "0123abcd-4567-89ab-cdef-0123456789ab"
    )


def test_two_runs_of_one_node_in_a_step_are_both_in_the_episode():
    episode = EpisodeGraph.from_trace(_send_trace())
    turn = episode.turn(0)
    workers = [r for r in turn.agent_task_runs if r.node == "worker"]
    assert len(workers) == 2, f"both runs of the repeated node must survive: {[r.label for r in turn.agent_task_runs]}"
    assert workers[0].step == workers[1].step
    assert len({r.task_id for r in workers}) == 2
    # both wrote, and both writes are relations of this turn
    written_by = {w.task_id for w in turn.writes}
    assert {r.task_id for r in workers} <= written_by


def test_a_step_with_two_task_runs_is_visible_in_the_episode():
    episode = EpisodeGraph.from_trace(_fan_out_trace())
    turn = episode.turn(0)
    per_step = {}
    for run in turn.agent_task_runs:
        per_step.setdefault(run.step, []).append(run.node)
    fan = [step for step, nodes in per_step.items() if len(nodes) > 1]
    assert fan, f"expected a step with several task runs, got {per_step}"
    assert sorted(per_step[fan[0]]) == ["left", "right"]


def test_two_producers_of_one_version_both_survive_the_projection():
    episode = EpisodeGraph.from_trace(_fan_out_trace())
    turn = episode.turn(0)
    shared = [s for s in turn.state_versions if len(s.producer_task_ids) > 1]
    assert shared, "the fan-out writes one version from two tasks; both must be kept"
    nodes = {episode.evidence.tasks[p].node for p in shared[0].producer_task_ids}
    assert nodes == {"left", "right"}


# ---- episode / turn structure ------------------------------------------------------------------

def test_turns_are_enumerated_in_order():
    episode = _canonical_episode()
    assert episode.turn_numbers == [0, 1, 2]
    assert [s.turn for s in episode.turns] == [0, 1, 2]
    assert episode.chronological_order() == [(0, 1), (1, 2)]
    assert len(episode) == 3
    assert [g.turn for g in episode] == [0, 1, 2]


def test_task_run_membership_per_turn():
    episode = _canonical_episode()
    for turn, expected in CANONICAL.items():
        labels = [r.label.split(" ")[0] for r in episode.turn(turn).agent_task_runs]
        assert labels == expected, f"turn {turn}: {labels}"


def test_langgraph_input_tasks_are_kept_but_marked_internal():
    episode = _canonical_episode()
    for turn in (0, 1, 2):
        graph = episode.turn(turn)
        internal = graph.internal_task_runs
        assert len(internal) == 1 and internal[0].node == "__input__"
        assert internal[0] not in graph.agent_task_runs
        assert internal[0] in graph.task_runs, "the input task's evidence must not be dropped"
        assert is_internal(internal[0].node)
        # it really wrote state, and that write is in the turn
        assert any(w.task_id == internal[0].task_id for w in graph.writes)


def test_events_are_reachable_from_a_task_run():
    episode = _canonical_episode()
    turn = episode.turn(1)
    lookup = next(r for r in turn.agent_task_runs if r.node == "lookup")
    events = turn.events(lookup.task_id)
    assert events, "a task run must be able to hand back its raw events"
    assert {e.kind for e in events} >= {"node_start", "node_end"}
    assert all(e.turn == 1 for e in events)
    assert any(e.kind == "tool_start" for e in events), "the lookup specialist called tools"


def test_relations_are_filtered_to_the_turn():
    episode = _canonical_episode()
    for graph in episode:
        for write in graph.writes:
            assert episode.evidence.tasks[write.task_id].turn == graph.turn
            assert episode.state_turn(write.state_key) == graph.turn
        for read in graph.reads + graph.triggers:
            assert episode.state_turn(read.state_key) == graph.turn
            assert all(episode.evidence.tasks[t].turn == graph.turn for t in read.task_ids)
        for derived in graph.derived:
            assert episode.state_turn(derived.state_key) == graph.turn
            assert episode.state_turn(derived.from_state_key) == graph.turn


def test_cross_turn_state_is_preserved_at_the_boundary():
    episode = _canonical_episode()
    links = episode.cross_turn_links()
    assert len(links) == 2, f"expected the two accumulation links between turns, got {links}"
    for link in links:
        assert link.kind == "derived_from"
        assert link.from_turn != link.to_turn
        assert link.relation.verdict == "verified"
        assert link.evidence is not None and link.evidence.channel == "messages"
    assert {(l.from_turn, l.to_turn) for l in links} == {(0, 1), (1, 2)}

    # both sides know about it, and neither turn had to absorb the other's contents
    assert [l.to_turn for l in episode.turn(0).outgoing] == [1]
    assert [l.from_turn for l in episode.turn(1).incoming] == [0]
    assert [l.to_turn for l in episode.turn(1).outgoing] == [2]
    assert not episode.turn(0).incoming and not episode.turn(2).outgoing


def test_a_cross_turn_link_keeps_the_whole_relation():
    """A read with an ambiguous consumer must not be collapsed to one task at the boundary."""
    read = next(r for r in _canonical_episode().evidence.reads if r.kind == "state")
    link = CrossTurnLink(kind="read", from_turn=0, to_turn=1, state_key=read.state_key,
                         relation=read, task_ids=list(read.task_ids), node=read.node)
    assert link.task_ids == read.task_ids
    assert isinstance(link.to_dict()["task_ids"], list)
    assert link.relation is read, "the original relation is kept whole"


def test_the_projection_does_not_change_the_evidence():
    result = run_episode("39", model="fake")
    direct = ProvenanceGraph.from_trace(result.trace)
    episode = EpisodeGraph.from_trace(result.trace)
    assert len(episode.evidence.writes) == len(direct.writes)
    assert len(episode.evidence.reads) == len(direct.reads)
    assert len(episode.evidence.derived) == len(direct.derived)
    assert set(episode.evidence.states) == set(direct.states)
    # and every relation lands in exactly one place: local to a turn, or crossing
    local = sum(len(g.writes) + len(g.reads) + len(g.triggers) + len(g.derived) for g in episode)
    crossing = len(episode.cross_turn_links())
    assert local + crossing == len(direct.writes) + len(direct.reads) + len(direct.derived)


def test_step_numbering_is_global_not_per_turn():
    episode = _canonical_episode()
    starts = [episode.turn(t).summary.first_step for t in (0, 1, 2)]
    assert starts == sorted(starts) and starts[1] > starts[0], (
        "step is LangGraph's thread-wide super-step counter; turns must not renumber it"
    )


def test_a_turn_summary_reports_only_recorded_facts():
    summary = _canonical_episode().turn(1).summary
    assert summary.invoke_ids and isinstance(summary.invoke_ids, list)
    assert summary.first_seq < summary.last_seq
    assert summary.task_steps == [2, 4, 5, 6], "only super-steps that ran a task"
    assert summary.checkpoint_steps == [2, 3, 4, 5, 6], "every super-step the turn checkpointed"
    assert set(summary.task_steps) < set(summary.checkpoint_steps), (
        "a super-step can checkpoint without running a task, so the two sets differ"
    )
    assert summary.nodes[0] == "__input__" and "lookup" in summary.nodes
    assert summary.event_count > 0 and summary.checkpoints > 0


def test_the_two_diagrams_render_and_stay_local():
    episode = _canonical_episode()
    overview = episode_diagram(episode)
    assert overview.startswith("flowchart") and "turn_0" in overview and "next" in overview
    assert "derived_from" in overview, "boundary relations belong on the episode diagram"

    turn1 = turn_diagram(episode.turn(1))
    assert "lookup" in turn1 and "supervisor" in turn1
    assert "booking" not in turn1, "a turn diagram must not pull in another turn's tasks"
    md = render_episode_markdown(episode, source_name="t.jsonl")
    assert md.count("```mermaid") == 1 + len(episode.turns)
    assert "## Turn 0" in md and "## Turn 2" in md
    assert "ordering, not causality" in md or "recording order, not causality" in md
