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

from firebreak.provenance.content import (
    clean_preview,
    format_args,
    preview_by_digest,
    short,
    task_outputs,
)
from firebreak.provenance.graph import ProvenanceGraph

VERDICT_STYLE = {"verified": "-. verified .->", "refuted": "-. REFUTED .->", "unverified": "-. unverified .->"}


def write_mermaid_blocks(markdown_path, text: str) -> list:
    """Split the ```mermaid blocks of a rendered page into numbered `.NN.mmd` files.

    The Markdown is the artifact a person reads; these are the same diagrams for anything that
    wants one diagram at a time. Kept here rather than in a shell step so a checkout can reproduce
    every output with the dump scripts alone.
    """
    from pathlib import Path

    base = Path(str(markdown_path))
    stem = base.with_suffix("")  # drops `.md`
    written: list = []
    block: list = []
    inside = False
    for line in text.splitlines():
        if not inside and line.strip() == "```mermaid":
            inside, block = True, []
            continue
        if inside and line.strip() == "```":
            target = Path(f"{stem}.{len(written) + 1:02d}.mmd")
            target.write_text("\n".join(block) + "\n")
            written.append(target)
            inside = False
            continue
        if inside:
            block.append(line)
    return written


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
        label = derived.verdict
        if derived.kept is not None:
            label = f"{label} · kept {derived.kept} · +{len(derived.new)}"
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


def _introduced_table(prov: ProvenanceGraph, trace) -> list:
    """What each step added to a folding channel, next to the lineage picture.

    The ids live on the relation because they are a comparison between two versions. The text is
    fetched from the trace at render time; it is the preview of the write that produced the newer
    version, so it is what that step contributed rather than the whole accumulated state.
    """
    if trace is None or not prov.derived:
        return []
    previews = preview_by_digest(trace)
    outputs = task_outputs(trace)
    by_state: dict = {}
    for write in prov.writes:
        if write.evidence.value_sha1:
            by_state.setdefault(write.state_key, []).append(write)

    rows: list = []
    for derived in prov.derived:
        state = prov.states.get(derived.state_key)
        if state is None or state.channel in _routing_channels(prov):
            continue
        writers = by_state.get(derived.state_key) or []
        producers = ", ".join(sorted({f"`{prov.task_label(w.task_id)}`" for w in writers})) or "-"
        # The node's own recorded output first: it is the text itself. The checkpoint preview is a
        # repr of the written value, so it is only used where no node produced this version.
        text = next(((outputs.get(w.task_id) or {}).get("text") for w in writers
                     if (outputs.get(w.task_id) or {}).get("text")), None)
        if not text:
            text = clean_preview(next((previews.get(w.evidence.value_sha1) for w in writers
                                       if previews.get(w.evidence.value_sha1)), None))
        count = "-" if derived.verdict == "unverified" else str(len(derived.new))
        rows.append(f"| `{_state_label(prov, derived.state_key)}` | {producers} | {count} | "
                    f"{short(text, 150) or '-'} |")
    if not rows:
        return []
    return [
        "### What each step introduced",
        "",
        "| version | produced by | new elements | preview of the write |",
        "|---|---|---|---|",
        *rows,
        "",
        "`new elements` is the count of element ids present in this version and not in the previous "
        "one. It describes the step, not the input of whatever read this version next: a task is "
        "handed the whole version. Previews are truncated; the full text is in the trace.",
        "",
    ]


def _tool_call_table(prov: ProvenanceGraph, mutating_tools=()) -> list:
    """Every tool a task ran, in order. The only place the run touched anything outside the graph.

    `mutating_tools` is declared by the caller, never inferred from the name: whether a tool changes
    state outside the process is a property of the domain, and guessing it from a prefix would put
    an assumption where this file otherwise only reports records.
    """
    declared = {str(name) for name in mutating_tools or ()}
    rows: list = []
    mutations = 0
    for run in sorted(prov.tasks.values(), key=lambda r: (r.step is None, r.step or 0)):
        for call in run.tool_calls:
            result = call.get("result_preview")
            cell = short(result, 70) if result else call.get("outcome", "-")
            if call.get("outcome") == "error":
                cell = f"**error** · {cell}"
            mutates = call.get("name") in declared
            mutations += 1 if mutates else 0
            rows.append(f"| `{run.label}` | {call.get('order', 0) + 1} | `{call.get('name')}` | "
                        f"{format_args(call.get('args'), 80)} | "
                        f"{'**external state mutation**' if mutates else '-'} | {cell} |")
    if not rows:
        return []
    lines = [
        "## Tool calls",
        "",
        "A worker's tool loop runs inside one task, between that task's read and its write, so these "
        "calls appear in no checkpoint and are not nodes of the state graph. They are recorded facts "
        "all the same, and they are where a run reads or changes something outside LangGraph. Each is "
        "attached to its task through the checkpoint namespace LangGraph built for that task.",
        "",
        "| task run | # | tool | arguments | effect | result |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    if declared:
        lines.append(f"`external state mutation` marks the {mutations} call(s) whose tool was declared "
                     "as one that changes state outside the process. It records what the call did, "
                     "not that it caused the episode's outcome; an unmarked call is simply not on "
                     "that list.")
        lines.append("")
    return lines


def _evaluation_lines(meta: dict, evaluation) -> list:
    """The benchmark's verdict, verbatim. Nothing on this page is marked as its cause."""
    if not evaluation:
        return []
    rows = [
        ("Outcome", "PASSED" if evaluation.get("success") else "FAILED"),
        ("Reward", evaluation.get("reward")),
        ("DB score", evaluation.get("db_score")),
        ("Communicate score", evaluation.get("communicate_score")),
        ("Reasons", ", ".join(evaluation.get("success_reasons") or []) or "-"),
    ]
    del meta
    lines = ["| | |", "|---|---|"]
    lines.extend(f"| {name} | `{value}` |" for name, value in rows if value is not None)
    lines.append("")
    lines.append("Scored by the benchmark's evaluator. No task run or state version below is marked as "
                 "the cause of this outcome.")
    lines.append("")
    return lines


def render_markdown(prov: ProvenanceGraph, trace=None, source_name: str = "",
                    evaluation: Optional[dict] = None, mutating_tools=()) -> str:
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
    out.extend(_evaluation_lines(meta, evaluation))
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
    out.extend(_introduced_table(prov, trace))

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
    out.extend(_tool_call_table(prov, mutating_tools))
    out.append("---")
    out.append("")
    out.append("Every relation and the field it came from are in the `.provenance.txt` beside this file; "
               "the machine-readable form is in the `.provenance.json`.")
    return "\n".join(out) + "\n"
