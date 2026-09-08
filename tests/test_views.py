"""The two human-facing outputs: the capture view and the provenance diagrams.

They exist so a person can audit what was captured and what was rebuilt, so the tests check that
each one actually shows the things that would let someone catch a mistake.
"""

from firebreak.integrations.tau2_airline.runner import run_episode
from firebreak.provenance.graph import ProvenanceGraph
from firebreak.provenance.mermaid import control_flow, data_flow, render_markdown, state_lineage
from firebreak.tracing.view import CALLBACK_KINDS, CHECKPOINTER_KINDS, STREAM_KINDS, render_trace, source_of


def _episode():
    result = run_episode("39", model="fake")
    return result.trace, ProvenanceGraph.from_trace(result.trace)


def test_every_event_kind_is_attributed_to_a_runtime_source():
    trace, _ = _episode()
    kinds = {e.kind for e in trace.events}
    assert kinds <= (STREAM_KINDS | CALLBACK_KINDS | CHECKPOINTER_KINDS | {"injection", "run_error"}), (
        f"unattributed event kinds: {kinds - (STREAM_KINDS | CALLBACK_KINDS | CHECKPOINTER_KINDS)}"
    )
    assert all(source_of(e) != "?" for e in trace.events)


def test_the_capture_view_groups_by_execution_and_keeps_the_original_seq():
    trace, _ = _episode()
    text = render_trace(trace, source_name="t.jsonl")
    assert "STREAM" in text and "CALLBACK" in text and "CHECKPOINTER" in text
    # grouped by turn and task, not by file order
    for node in ("supervisor", "lookup", "booking"):
        assert f"· {node} · task " in text
    assert "captured at seq" in text, "the raw capture position must stay visible"
    assert "snapshotted later" in text, "checkpoint facts must be marked as recorded after the fact"
    # the checkpointer ledger is the record provenance is rebuilt from
    assert "CHECKPOINTER LEDGER" in text and "versions" in text and "seen" in text


def test_the_capture_view_shows_what_only_the_callbacks_know():
    trace, _ = _episode()
    text = render_trace(trace)
    assert "path=" in text and "checkpoint_ns=" in text, (
        "langgraph_path and langgraph_checkpoint_ns are dropped by the debug stream, so the view "
        "must surface them from the callbacks"
    )


def test_the_three_diagrams_are_separate_and_carry_different_relations():
    _, prov = _episode()
    data, lineage, control = data_flow(prov), state_lineage(prov), control_flow(prov)
    assert "WRITE" in data and "READ" in data and "TRIGGER" not in data
    assert "TRIGGER" in control and "WRITE" not in control
    assert "verified" in lineage or "unverified" in lineage or "REFUTED" in lineage
    # data travels on the state channel, control on the routing channels
    assert "messages:" in data and "branch:to:" not in data
    assert "branch:to:" in control


def test_diagram_ids_are_readable_and_valid_mermaid_identifiers():
    _, prov = _episode()
    for diagram in (data_flow(prov), state_lineage(prov), control_flow(prov)):
        assert diagram.startswith("flowchart ")
        for line in diagram.splitlines():
            stripped = line.strip()
            if stripped.startswith(("subgraph", "end", "classDef", "class ", "flowchart")):
                continue
            ident = stripped.split("[")[0].split("(")[0].split("{")[0].split(" ")[0]
            assert ":" not in ident and "@" not in ident, f"invalid mermaid id in {line!r}"
        # the long ULID version strings must not end up in ids
        assert "00000000000000000000" not in diagram


def test_the_markdown_states_the_evidence_class_of_each_diagram():
    trace, prov = _episode()
    md = render_markdown(prov, trace, source_name="t.jsonl")
    assert md.count("```mermaid") == 3
    assert "## Data flow" in md and "## State lineage" in md and "## Control flow" in md
    assert "observed" in md, "the data-flow diagram must say its relations are observed"
    assert "verified" in md, "the lineage diagram must report the retention verdicts"
    assert "versions_seen" in md, "the control diagram must say why it is separate from data"
