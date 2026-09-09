"""Human-readable and machine-readable dumps of the evidence: every relation and its source."""

from __future__ import annotations

import json
from typing import Any

from firebreak.provenance.content import format_args, short
from firebreak.provenance.graph import ProvenanceGraph



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
        add(f"  {cp['checkpoint_id']!s:<40} {cp['step']!s:>5} {cp['source'] or ''!s:<8} "
            f"{cp['n_writes']:>6}  {', '.join(cp['updated_channels']) or '-'}")
    add("")

    add("## Task runs")
    add("")
    add(f"  {'label':<26} {'task_id':<40} {'turn':>4} {'step':>5} {'wrote':<6} {'outcome':<10} "
        f"{'placed by':<17} triggers")
    for run in sorted(prov.tasks.values(), key=lambda t: (t.step is None, t.step or 0, t.node)):
        add(f"  {run.label:<26} {run.task_id:<40} {run.turn!s:>4} {run.step!s:>5} "
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

    with_tools = [t for t in prov.tasks.values() if t.tool_calls]
    if with_tools:
        add("## Tool calls, per task run")
        add("")
        add("  These happen inside a task, between its read and its write, so no checkpoint records")
        add("  them. Each is attached to its task through the checkpoint namespace LangGraph built")
        add("  for that task; `by` says how the attribution was resolved.")
        add("")
        for run in sorted(with_tools, key=lambda t: (t.step is None, t.step or 0, t.node)):
            add(f"{run.label}")
            for call in run.tool_calls:
                add(f"  {call.get('order', 0) + 1:>2}. {call.get('name')}"
                    f"({format_args(call.get('args'), 160)})")
                add(f"      -> {call.get('outcome')}  sha1={call.get('result_sha1')}  "
                    f"by={call.get('attribution')}")
                if call.get("result_preview"):
                    add(f"      {short(call['result_preview'], 160)}")
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
                + (f" lost={len(derived.lost)}" if derived.lost else "")
                + (f" new={len(derived.new)}" if derived.verdict != "unverified" else ""))
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
        carrier = f"{state.channel}:{_short(state.version)}"
        for read in prov.reads_of(key):
            if read.kind != "state":
                continue
            right = " | ".join(prov.task_label(t) for t in read.task_ids) or f"{read.node}?"
            add(f"  {left:<26} --{carrier:<22}--> {right}")
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
