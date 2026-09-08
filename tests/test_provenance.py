"""Provenance must be grounded: every relation traceable to a field LangGraph recorded."""

from firebreak.integrations.tau2_airline.runner import run_episode
from firebreak.provenance.capture import CHECKPOINT_FACT
from firebreak.provenance.graph import ProvenanceGraph
from firebreak.provenance.render import render_json, render_text
from firebreak.tracing.recorder import Trace

TASK = "39"


def _prov(**kwargs):
    result = run_episode(TASK, model="fake", **kwargs)
    return result, ProvenanceGraph.from_trace(result.trace)


def test_checkpoint_facts_are_captured_without_state_snapshots():
    result, _ = _prov()
    facts = result.trace.of_kind(CHECKPOINT_FACT)
    assert facts, "record() must snapshot the checkpointer"
    payload = facts[0].payload
    assert {"checkpoint_id", "channel_versions", "versions_seen", "updated_channels", "writes"} <= set(payload)
    # channel_values would make the trace grow quadratically and is never stored
    assert "channel_values" not in payload
    assert all("value_sha1" in w and "task_id" in w and "channel" in w for w in payload["writes"])
    ids = [f.payload["checkpoint_id"] for f in facts]
    assert len(ids) == len(set(ids)), "checkpoints must not be captured twice"


def test_every_relation_carries_evidence():
    _, prov = _prov()
    assert prov.writes and prov.reads
    for write in prov.writes:
        assert write.evidence.source == "checkpoint.pending_writes"
        assert write.evidence.checkpoint_id and write.evidence.channel and write.evidence.version
    for read in prov.reads:
        assert read.evidence.source in ("checkpoint.channel_versions + task.input", "checkpoint.versions_seen")
        assert read.evidence.checkpoint_id and read.evidence.channel and read.evidence.version
    for derived in prov.derived:
        assert derived.evidence.channel in prov.accumulating


def test_the_data_path_runs_through_the_messages_channel():
    _, prov = _prov()
    labels = {t.task_id: t.label for t in prov.tasks.values()}
    direct = {
        (labels[p["producer_task_id"]].split(" ")[0], labels[p["consumer_task_id"]].split(" ")[0])
        for p in prov.observed_task_relations()
        if p["relation"] == "direct" and p["consumer_task_id"]
    }
    assert ("supervisor@1", "lookup@2") in direct
    assert ("lookup@2", "supervisor@3") in direct
    assert ("supervisor@3", "booking@4") in direct
    assert ("booking@4", "supervisor@5") in direct
    assert all(p["state"].startswith("messages:") for p in prov.observed_task_relations())


def test_triggers_are_routing_channels_and_kept_separate_from_reads():
    _, prov = _prov()
    trigger_channels = {r.evidence.channel for r in prov.reads if r.kind == "trigger"}
    read_channels = {r.evidence.channel for r in prov.reads if r.kind == "state"}
    assert all(c.startswith("branch:to:") for c in trigger_channels)
    assert read_channels == {"messages"}


def test_multiple_producers_of_one_version_are_all_kept():
    _, prov = _prov()
    for state in prov.states.values():
        writes = [w for w in prov.writes if w.state_key == state.key]
        assert len(state.producer_task_ids) == len({w.task_id for w in writes})
        # no producer is ever silently dropped in favour of a single "cause"
        assert set(state.producer_task_ids) == {w.task_id for w in writes}


def test_derivation_only_for_accumulating_channels():
    _, prov = _prov()
    assert prov.channel_types["messages"] == "BinaryOperatorAggregate"
    assert prov.channel_types["branch:to:lookup"] == "EphemeralValue"
    assert "messages" in prov.accumulating and "branch:to:lookup" not in prov.accumulating
    assert prov.derived and all(prov.states[d.state_key].channel in prov.accumulating for d in prov.derived)


def test_dumps_round_trip_through_a_saved_trace(tmp_path):
    path = tmp_path / "t.jsonl"
    result = run_episode(TASK, model="fake", save=str(path))
    reloaded = ProvenanceGraph.from_trace(Trace.from_jsonl(str(path)))
    live = ProvenanceGraph.from_trace(result.trace)
    assert len(reloaded.writes) == len(live.writes)
    assert len(reloaded.reads) == len(live.reads)
    assert set(reloaded.states) == set(live.states)
    assert "Observed state provenance" in render_text(reloaded)
    assert "write_relations" in render_json(reloaded)


def test_a_trace_without_checkpoint_facts_says_so_instead_of_guessing():
    trace = Trace()
    prov = ProvenanceGraph.from_trace(trace)
    assert not prov.writes and not prov.reads
    assert prov.warnings and "checkpoint_fact" in prov.warnings[0]


def test_the_two_framework_keys_the_debug_stream_drops_are_captured():
    """`langgraph_path` and `langgraph_checkpoint_ns` only reach us through the callbacks."""
    result, prov = _prov()
    extras = [e.payload["langgraph"] for e in result.trace.events if "langgraph" in e.payload]
    assert extras, "callback events must carry the framework extras"
    assert any("checkpoint_ns" in x for x in extras)
    assert any("path" in x for x in extras)
    assert any(run.checkpoint_ns is not None for run in prov.tasks.values())
