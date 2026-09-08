"""Three Mermaid diagrams, one per kind of relation, deliberately not merged into one picture.

The three answer different questions and mixing them is what makes provenance pictures unreadable:

* **Data flow** — `TaskRun --WRITE--> StateVersion --READ--> TaskRun`. Computation to data and back.
* **State lineage** — `StateVersion -.DERIVED_FROM.-> StateVersion`. How one version of a channel
  relates to the next, with the verdict of the retention check on the edge.
* **Control flow** — `RoutingVersion --TRIGGER--> TaskRun`. What caused each task to be scheduled.

GitHub renders Mermaid in Markdown, so the output needs no server and no JavaScript. Node ids are
sanitised because a Mermaid id cannot contain `:` or `@`.
"""

from __future__ import annotations

import re
from typing import Optional

from firebreak.provenance.graph import ProvenanceGraph

VERDICT_STYLE = {"verified": "-. verified .->", "refuted": "-. REFUTED .->", "unverified": "-. unverified .->"}


def _short_version(version: str) -> str:
    head, _, _ = str(version).partition(".")
    return "v" + (head.lstrip("0") or "0")


def _safe(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", str(text))


def _task_id(label: str) -> str:
    return "t_" + _safe(label)


def _state_id(key: str, prov: Optional[ProvenanceGraph] = None) -> str:
    """A readable id: the channel plus the version counter, which is unique within a channel.

    The raw version is a long ULID-like string; putting it in the id makes the Mermaid source
    unreadable for no gain, because the node label already carries the same information.
    """
    if prov is not None:
        state = prov.states.get(key)
        if state is not None:
            return "s_" + _safe(f"{state.channel}_{_short_version(state.version)}")
    return "s_" + _safe(key)


def _state_label(prov: ProvenanceGraph, key: str) -> str:
    state = prov.states.get(key)
    return f"{state.channel}:{_short_version(state.version)}" if state else key


def _routing_channels(prov: ProvenanceGraph) -> set:
    return {r.evidence.channel for r in prov.reads if r.kind == "trigger"}


def _data_channels(prov: ProvenanceGraph) -> set:
    return {r.evidence.channel for r in prov.reads if r.kind == "state"}


def data_flow(prov: ProvenanceGraph) -> str:
    """WRITE and READ, on the channels data actually travelled on."""
    channels = _data_channels(prov)
    lines = ["flowchart LR"]
    used_states: set = set()
    edges: list[str] = []

    for read in prov.reads:
        if read.kind != "state" or read.evidence.channel not in channels:
            continue
        for task_id in read.task_ids:
            edges.append(f"  {_state_id(read.state_key, prov)} -->|READ| {_task_id(prov.task_label(task_id))}")
            used_states.add(read.state_key)
    for write in prov.writes:
        state = prov.states.get(write.state_key)
        if state is None or state.channel not in channels:
            continue
        edges.append(f"  {_task_id(prov.task_label(write.task_id))} -->|WRITE| {_state_id(write.state_key, prov)}")
        used_states.add(write.state_key)

    by_turn: dict = {}
    for run in prov.tasks.values():
        by_turn.setdefault(run.turn, []).append(run)
    for turn in sorted(by_turn, key=lambda t: (t is None, t)):
        runs = sorted(by_turn[turn], key=lambda r: (r.step is None, r.step or 0))
        title = f"turn {turn}" if turn is not None else "outside a turn"
        lines.append(f"  subgraph turn_{_safe(turn)}[\"{title}\"]")
        for run in runs:
            mark = "" if run.wrote else f" · {run.outcome or 'no state write'}"
            lines.append(f"    {_task_id(run.label)}[\"{run.label}{mark}\"]")
        lines.append("  end")
    for key in sorted(used_states, key=lambda k: (prov.states[k].step is None, prov.states[k].step or 0, k)):
        lines.append(f"  {_state_id(key, prov)}((\"{_state_label(prov, key)}\"))")
    lines.extend(dict.fromkeys(edges))
    lines.append("  classDef state fill:#fff3c4,stroke:#b8860b;")
    if used_states:
        lines.append("  class " + ",".join(_state_id(k, prov) for k in sorted(used_states)) + " state;")
    return "\n".join(lines)


def state_lineage(prov: ProvenanceGraph) -> str:
    """DERIVED_FROM, with the verdict of the retention check on each edge."""
    lines = ["flowchart LR"]
    used: set = set()
    edges: list[str] = []
    for derived in prov.derived:
        state = prov.states.get(derived.state_key)
        if state is None or state.channel in _routing_channels(prov):
            continue
        arrow = VERDICT_STYLE.get(derived.verdict, "-.->")
        label = derived.verdict if derived.kept is None else f"{derived.verdict} · kept {derived.kept}"
        edges.append(f"  {_state_id(derived.from_state_key, prov)} {arrow.replace(derived.verdict, label)} "
                     f"{_state_id(derived.state_key, prov)}")
        used.update({derived.from_state_key, derived.state_key})
    for key in sorted(used, key=lambda k: (prov.states[k].step is None, prov.states[k].step or 0, k)):
        lines.append(f"  {_state_id(key, prov)}((\"{_state_label(prov, key)}\"))")
    lines.extend(dict.fromkeys(edges))
    lines.append("  classDef state fill:#fff3c4,stroke:#b8860b;")
    if used:
        lines.append("  class " + ",".join(_state_id(k, prov) for k in sorted(used)) + " state;")
    return "\n".join(lines)


def control_flow(prov: ProvenanceGraph) -> str:
    """TRIGGER: the routing version that caused each task to be scheduled."""
    lines = ["flowchart LR"]
    used: set = set()
    edges: list[str] = []
    tasks: set = set()
    for read in prov.reads:
        if read.kind != "trigger":
            continue
        used.add(read.state_key)
        for task_id in read.task_ids:
            label = prov.task_label(task_id)
            tasks.add(label)
            edges.append(f"  {_state_id(read.state_key, prov)} -->|TRIGGER| {_task_id(label)}")
        if not read.task_ids:
            edges.append(f"  {_state_id(read.state_key, prov)} -->|TRIGGER| {_task_id(read.node)}")
            tasks.add(read.node)
    for label in sorted(tasks):
        lines.append(f"  {_task_id(label)}[\"{label}\"]")
    for key in sorted(used, key=lambda k: (prov.states[k].step is None, prov.states[k].step or 0, k)):
        lines.append(f"  {_state_id(key, prov)}{{{{\"{_state_label(prov, key)}\"}}}}")
    lines.extend(dict.fromkeys(edges))
    lines.append("  classDef routing fill:#e8e8ff,stroke:#5555aa;")
    if used:
        lines.append("  class " + ",".join(_state_id(k, prov) for k in sorted(used)) + " routing;")
    return "\n".join(lines)


def render_markdown(prov: ProvenanceGraph, trace=None, source_name: str = "") -> str:
    """The three diagrams as one Markdown page GitHub renders without any tooling."""
    meta = getattr(trace, "meta", {}) or {}
    verdicts = {v: sum(1 for d in prov.derived if d.verdict == v) for v in ("verified", "refuted", "unverified")}
    data_ch = ", ".join(sorted(_data_channels(prov))) or "none"
    routing_ch = ", ".join(sorted(_routing_channels(prov))) or "none"

    out = [f"# Provenance{f' — {source_name}' if source_name else ''}", ""]
    if meta:
        out.append(f"τ² task {meta.get('task_id')} · model {meta.get('model')} · outcome "
                   f"{meta.get('outcome')} · faults {', '.join(meta.get('faults') or []) or 'none'}")
        out.append("")
    out.append(f"{len(prov.tasks)} task runs · {len(prov.states)} state versions · "
               f"{len(prov.writes)} WRITE · {sum(1 for r in prov.reads if r.kind == 'state')} READ · "
               f"{sum(1 for r in prov.reads if r.kind == 'trigger')} TRIGGER · "
               f"{len(prov.derived)} DERIVED_FROM")
    out.append("")
    out.append("Three relations, three pictures. They answer different questions, so they are not merged.")
    out.append("")
    out.extend([
        "| diagram | relation | question |",
        "|---|---|---|",
        "| Data flow | `WRITE` / `READ` | which task produced the value another task was handed |",
        "| State lineage | `DERIVED_FROM` | whether a later version of a channel still contains an earlier one |",
        "| Control flow | `TRIGGER` | what caused each task to be scheduled |",
        "",
    ])

    out.append("## Data flow")
    out.append("")
    out.append(f"Channels the data travelled on: `{data_ch}`. Both relations are **observed**: the write "
               "comes from the checkpoint's `pending_writes`, the read from the `channel_versions` of the "
               "checkpoint the task was scheduled from, intersected with the channels its recorded input "
               "carried.")
    out.append("")
    out.append("```mermaid")
    out.append(data_flow(prov))
    out.append("```")
    out.append("")

    out.append("## State lineage")
    out.append("")
    out.append(f"A folding channel merges each write into the value rather than replacing it, which does "
               f"**not** mean the new version contains the old one. Each link is checked against the "
               f"element identities recorded per version: **{verdicts['verified']} verified, "
               f"{verdicts['refuted']} refuted, {verdicts['unverified']} unverified**. Only verified links "
               "may be followed when tracing accumulation.")
    out.append("")
    out.append("```mermaid")
    out.append(state_lineage(prov))
    out.append("```")
    out.append("")

    out.append("## Control flow")
    out.append("")
    out.append(f"Routing channels: `{routing_ch}`. LangGraph stamps `versions_seen` only for a task's "
               "trigger channels, so in a `StateGraph` this records the routing channel and never the "
               "channel the data travelled on. That is why control and data are separate pictures rather "
               "than two edge types in one.")
    out.append("")
    out.append("```mermaid")
    out.append(control_flow(prov))
    out.append("```")
    out.append("")
    out.append("---")
    out.append("")
    out.append("Every relation and the field it came from are in the `.provenance.txt` beside this file; "
               "the machine-readable form is in the `.provenance.json`.")
    return "\n".join(out) + "\n"
