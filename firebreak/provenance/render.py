"""Human-readable and machine-readable dumps of a ProvenanceGraph, plus a legacy audit."""

from __future__ import annotations

import json
from typing import Any, Optional

from firebreak.graph.execution import ExecutionGraph
from firebreak.provenance.graph import ProvenanceGraph

SUPPORTED = "supported"
ACCUMULATED = "accumulated"
AMBIGUOUS = "ambiguous"
UNSUPPORTED = "unsupported"


def render_json(prov: ProvenanceGraph, trace: Any = None) -> str:
    data = prov.to_dict()
    if trace is not None:
        data["meta"] = {
            "episode_id": trace.meta.get("episode_id"),
            "thread_id": trace.meta.get("thread_id"),
            "task_id": trace.meta.get("task_id"),
            "model": trace.meta.get("model"),
            "outcome": trace.meta.get("outcome"),
            "faults": trace.meta.get("faults"),
        }
    return json.dumps(data, indent=2, default=str)


def _channels(prov: ProvenanceGraph) -> list:
    return sorted({s.channel for s in prov.states.values()})


def _short(version: str) -> str:
    """Channel versions are long ULID-ish strings; show the counter and a tail."""
    head, _, tail = str(version).partition(".")
    counter = head.lstrip("0") or "0"
    return f"v{counter}" if not tail else f"v{counter}.{tail.split('.')[-1][:4]}"


def render_text(prov: ProvenanceGraph, trace: Any = None, source_name: str = "") -> str:
    out: list[str] = []
    add = out.append
    add(f"# Observed state provenance{f' — {source_name}' if source_name else ''}")
    add("")
    add("Two evidence classes, never mixed:")
    add("  observed  WRITE, READ and TRIGGER. Each is a field LangGraph itself recorded.")
    add("  derived   DERIVED_FROM between consecutive versions of a folding channel. Folding does")
    add("            not imply the new version contains the old one, so each one is checked against")
    add("            the element ids recorded per version: verified / refuted / unverified.")
    add("Nothing is inferred from wall-clock time, from the static graph, or by a model.")
    add("")
    if trace is not None:
        add(f"episode {trace.meta.get('episode_id')}  thread {trace.meta.get('thread_id')}")
        add(f"task {trace.meta.get('task_id')}  model {trace.meta.get('model')}  "
            f"outcome {trace.meta.get('outcome')}  faults {trace.meta.get('faults') or 'none'}")
        add("")
    state_reads = [r for r in prov.reads if r.kind == "state"]
    trigger_reads = [r for r in prov.reads if r.kind == "trigger"]
    add(f"{len(prov.tasks)} task runs, {len(prov.states)} state versions, "
        f"{len(prov.writes)} WRITE relations, {len(state_reads)} READ relations, "
        f"{len(trigger_reads)} TRIGGER relations, {len(prov.checkpoints)} checkpoints")
    add(f"channels: {', '.join(_channels(prov)) or 'none'}")
    if prov.channel_types:
        add("channel classes: " + ", ".join(f"{c}={prov.channel_types.get(c, '?')}" for c in _channels(prov)))
        verdicts = {v: sum(1 for d in prov.derived if d.verdict == v) for v in ("verified", "refuted", "unverified")}
        add(f"folding channels (a write is merged into the value, not replacing it): "
            f"{', '.join(sorted(prov.accumulating)) or 'none'}")
        add(f"derivations checked against recorded element ids: {verdicts['verified']} verified, "
            f"{verdicts['refuted']} refuted, {verdicts['unverified']} unverified")
    resolution = {r: sum(1 for t in prov.tasks.values() if t.resolution == r)
                  for r in ("checkpoint_writes", "step_alignment", "unresolved")}
    add(f"task placement: {resolution['checkpoint_writes']} by their own writes, "
        f"{resolution['step_alignment']} by step alignment (wrote nothing), "
        f"{resolution['unresolved']} unplaced")
    add("")
    add("Two kinds of read, kept apart because LangGraph records them differently:")
    add("  READ     the version was in the state handed to the task")
    add("           (checkpoint.channel_versions of the checkpoint it was scheduled from,")
    add("            intersected with the channels its own recorded input carried)")
    add("  TRIGGER  the version is what caused the task to be scheduled")
    add("           (checkpoint.versions_seen; in a StateGraph this is the routing channel,")
    add("            not the channel the data travelled on)")
    add("")

    if prov.warnings:
        add("## Warnings")
        add("")
        for warning in prov.warnings:
            add(f"  ! {warning}")
        add("")

    add("## Checkpoints  (the record the provenance is read from)")
    add("")
    add(f"  {'checkpoint_id':<40} {'step':>5} {'source':<8} {'writes':>6}  updated_channels")
    for cp in prov.checkpoints:
        add(f"  {str(cp['checkpoint_id']):<40} {str(cp['step']):>5} {str(cp['source'] or ''):<8} "
            f"{cp['n_writes']:>6}  {', '.join(cp['updated_channels']) or '-'}")
    add("")

    add("## Task runs")
    add("")
    add(f"  {'label':<26} {'task_id':<40} {'turn':>4} {'step':>5} {'wrote':<6} {'outcome':<10} "
        f"{'placed by':<17} triggers")
    for run in sorted(prov.tasks.values(), key=lambda t: (t.step is None, t.step or 0, t.node)):
        add(f"  {run.label:<26} {run.task_id:<40} {str(run.turn):>4} {str(run.step):>5} "
            f"{('yes' if run.wrote else 'NO'):<6} {(run.outcome or '-'):<10} {run.resolution:<17} "
            f"{', '.join(run.triggers) or '-'}")
    outcomes = sorted({t.outcome for t in prov.tasks.values() if t.outcome})
    if outcomes:
        add("")
        add("  outcome comes from LangGraph's own sentinel write for the task "
            "(__error__ / __no_writes__ / ...),")
        add("  which is why every executed task appears in a checkpoint's writes even when it "
            "wrote no state.")
    add("")

    add("## Provenance, per state version")
    add("")
    add("  TaskRun --WRITE--> StateVersion --READ--> TaskRun")
    add("")
    for key in sorted(prov.states, key=lambda k: (prov.states[k].step is None, prov.states[k].step or 0, k)):
        state = prov.states[key]
        add(f"STATE {key}")
        add(f"  born in checkpoint {state.checkpoint_id or '(not observed)'}  step {state.step}")
        for derived in prov.derived:
            if derived.state_key != key:
                continue
            older = prov.states.get(derived.from_state_key)
            add(f"  DERIVED_FROM {_short(older.version) if older else derived.from_state_key}"
                f"   verdict={derived.verdict}"
                + (f" kept={derived.kept}" if derived.kept is not None else "")
                + (f" lost={len(derived.lost)}" if derived.lost else ""))
            add(f"      evidence: {derived.evidence.source}  checkpoint={derived.evidence.checkpoint_id}")
            if derived.evidence.note:
                add(f"      note: {derived.evidence.note}")
        writes = [w for w in prov.writes if w.state_key == key]
        if writes:
            add("  WRITTEN BY")
            for write in writes:
                add(f"    {prov.task_label(write.task_id):<26} task_id={write.task_id}")
                ev = write.evidence
                add(f"      evidence: {ev.source}  checkpoint={ev.checkpoint_id}  step={ev.step}  "
                    f"channel={ev.channel}  value_sha1={ev.value_sha1}")
            if len(writes) > 1:
                add(f"    ^ {len(writes)} tasks wrote this version in the same super-step; all kept as producers")
        else:
            add("  WRITTEN BY  (no write observed for this version)")
        for kind, heading in (("state", "READ BY"), ("trigger", "TRIGGERED")):
            reads = [r for r in prov.reads_of(key) if r.kind == kind]
            if not reads:
                if kind == "state":
                    add("  READ BY  (no task received this version)")
                continue
            add(f"  {heading}")
            for read in reads:
                who = " | ".join(prov.task_label(t) for t in read.task_ids) or f"{read.node} (task id unresolved)"
                mark = "  [AMBIGUOUS]" if read.ambiguous else ""
                add(f"    {who}{mark}")
                ev = read.evidence
                add(f"      evidence: {ev.source}  checkpoint={ev.checkpoint_id}  step={ev.step}  "
                    f"node={ev.node}  channel={ev.channel}  version={ev.version}")
                if ev.note:
                    add(f"      note: {ev.note}")
        add("")

    add("## The data path, one line each  (READ relations only)")
    add("")
    for key in sorted(prov.states, key=lambda k: (prov.states[k].step is None, prov.states[k].step or 0, k)):
        state = prov.states[key]
        producers = state.producer_task_ids
        left = (prov.task_label(producers[0]) if len(producers) == 1
                else "{" + ", ".join(prov.task_label(p) for p in producers) + "}" if producers
                else "(no observed producer)")
        short = f"{state.channel}:{_short(state.version)}"
        for read in prov.reads_of(key):
            if read.kind != "state":
                continue
            right = " | ".join(prov.task_label(t) for t in read.task_ids) or f"{read.node}?"
            add(f"  {left:<26} --{short:<22}--> {right}")
    add("")

    add("## What this cannot say yet")
    add("")
    add("  * An `accumulated` relation is only followed through derivations that verified. A")
    add("    refuted or unverified link stops the chain rather than being assumed through.")
    add("  * The TRIGGER relation is not the data path. LangGraph only stamps `versions_seen`")
    add("    for a task's trigger channels, which in a StateGraph are the routing channels, so")
    add("    the channel carrying the data never appears there.")
    add("  * Provenance is per channel, not per message. With one `messages` channel and an")
    add("    add_messages reducer every task reads and writes the same channel, so a relation")
    add("    means \"this task read the state version that included that task's write\", not")
    add("    \"this task read that message\".")
    add("  * A relation is a data path, not a cause. Nothing here claims the consumer used what")
    add("    the producer wrote, only that it was in the state it consumed.")
    add("  * Reads are attributed to a task by the super-step it ran in. A node that advanced its")
    add("    seen version without writing anything is recorded with the node name and no task id.")
    add("  * A task that wrote nothing is placed on its checkpoint by step alignment, using an")
    add("    offset calibrated on the tasks that did write. That is weaker than a task id match,")
    add("    and the task table says which placement each task got.")
    return "\n".join(out) + "\n"


def compare_with_legacy(prov: ProvenanceGraph, legacy: ExecutionGraph) -> dict:
    """Audit the old static-edge + ordering heuristic against the observed provenance.

    The provenance side is the substrate; the heuristic is only the thing being audited. Nothing
    here changes either graph.
    """
    observed = prov.observed_task_relations()
    by_pair: dict[tuple, list] = {}
    direct_pairs: set = set()
    for pair in observed:
        if pair["consumer_task_id"]:
            key = (pair["producer_task_id"], pair["consumer_task_id"])
            by_pair.setdefault(key, []).append(pair)
            if pair.get("relation") == "direct":
                direct_pairs.add(key)
    by_node_pair: dict[tuple, list] = {}
    for pair in observed:
        by_node_pair.setdefault((pair["producer"].split(" ")[0], str(pair["consumer"]).split(" ")[0]), []).append(pair)

    legacy_rows = []
    for edge in legacy.edges:
        src, dst = legacy.get(edge.src), legacy.get(edge.dst)
        if src is None or dst is None:
            continue
        src_task, dst_task = _strip(src.id), _strip(dst.id)
        exact = by_pair.get((src_task, dst_task))
        if exact:
            verdict = SUPPORTED if (src_task, dst_task) in direct_pairs else ACCUMULATED
            states = sorted({p["via"] for p in exact})
        else:
            loose = by_node_pair.get((src.label.split(" ")[0], dst.label.split(" ")[0]))
            verdict = AMBIGUOUS if loose else UNSUPPORTED
            states = sorted({p["state"] for p in loose}) if loose else []
        legacy_rows.append(
            {"edge": f"{src.label} -> {dst.label}", "verdict": verdict, "states": states}
        )

    legacy_pairs = {(_strip(legacy.get(e.src).id), _strip(legacy.get(e.dst).id))
                    for e in legacy.edges if legacy.get(e.src) and legacy.get(e.dst)}
    missed = []
    for (producer, consumer), pairs in sorted(by_pair.items()):
        if (producer, consumer) in legacy_pairs:
            continue
        missed.append(
            {
                "relation": f"{prov.task_label(producer)} -> {prov.task_label(consumer)}",
                "states": sorted({p["via"] for p in pairs}),
                "kind": "direct" if (producer, consumer) in direct_pairs else "accumulated",
            }
        )
    return {
        "legacy_edges": legacy_rows,
        "observed_not_in_legacy": missed,
        "counts": {
            "legacy_edges": len(legacy_rows),
            "supported": sum(1 for r in legacy_rows if r["verdict"] == SUPPORTED),
            "accumulated": sum(1 for r in legacy_rows if r["verdict"] == ACCUMULATED),
            "ambiguous": sum(1 for r in legacy_rows if r["verdict"] == AMBIGUOUS),
            "unsupported": sum(1 for r in legacy_rows if r["verdict"] == UNSUPPORTED),
            "observed_relations": len(by_pair),
            "observed_not_in_legacy": len(missed),
        },
    }


def _strip(run_id: str) -> str:
    """ExecutionGraph run ids are `<invoke_id>:<task_id>`; provenance keys on the task id."""
    return run_id.split(":", 1)[1] if ":" in run_id else run_id


def render_comparison(comparison: dict) -> str:
    out: list[str] = []
    add = out.append
    add("# Legacy heuristic edges audited against observed provenance")
    add("")
    add("The legacy graph connects A -> B when the compiled graph declares a static edge A -> B")
    add("and A's run finished before B's started. That is an inference over ordering. Below, each")
    add("of its edges is checked against relations LangGraph actually recorded.")
    add("")
    counts = comparison["counts"]
    add(f"  legacy edges: {counts['legacy_edges']}   supported {counts['supported']}   "
        f"accumulated {counts.get('accumulated', 0)}   ambiguous {counts['ambiguous']}   "
        f"unsupported {counts['unsupported']}")
    add(f"  observed task-to-task relations: {counts['observed_relations']}   "
        f"of which missing from the legacy graph: {counts['observed_not_in_legacy']}")
    add("")
    add(f"  {'legacy edge':<56} {'verdict':<12} carried by")
    for row in comparison["legacy_edges"]:
        add(f"  {row['edge']:<56} {row['verdict']:<12} {', '.join(row['states']) or '-'}")
    add("")
    add("## Observed relations the legacy graph has no edge for")
    add("")
    if not comparison["observed_not_in_legacy"]:
        add("  (none)")
    for row in comparison["observed_not_in_legacy"]:
        add(f"  {row['relation']:<56} {row['kind']:<12} carried by {', '.join(row['states'])}")
    add("")
    add("supported   = the consumer directly read a version this producer wrote")
    add("accumulated = the consumer read a later version of an accumulating channel that this")
    add("              producer's version was folded into (recorded via the channel class, not guessed)")
    add("ambiguous   = the node pair appears, but not this pair of runs")
    add("unsupported = no observed relation between these nodes at all")
    return "\n".join(out) + "\n"
