"""Two diagrams for the hierarchy: the episode, and one turn at a time.

Deliberately not a third "relation type" view — that already exists in `.provenance.md`, which
stays as the low-level evidence artifact. These two answer structural questions instead: what
turns did this episode have, and what happened inside one of them.
"""

from __future__ import annotations

from typing import Optional

from firebreak.episode.graph import EpisodeGraph, TurnGraph, is_internal
from firebreak.provenance.content import (
    clean_preview,
    format_args,
    preview_by_digest,
    short,
    task_outputs,
)
from firebreak.provenance.mermaid import _safe, _short_version

ARROW = {"read": "-->|READ|", "write": "-->|WRITE|", "trigger": "-.->|TRIGGER|",
         "derived_from": "-. DERIVED .->"}


def _steps(steps: list) -> str:
    """Spell the steps out while the list is short, so a gap is visible rather than hidden."""
    if not steps:
        return "-"
    if len(steps) <= 8:
        return ", ".join(str(s) for s in steps)
    return f"{steps[0]}–{steps[-1]} ({len(steps)})"


def _turn_id(turn: Optional[int]) -> str:
    return "turn_" + _safe(turn)


def _task_id(label: str) -> str:
    return "t_" + _safe(label)


def _state_id(state) -> str:
    return "s_" + _safe(f"{state.channel}_{_short_version(state.version)}")


def _state_label(state) -> str:
    return f"{state.channel}:{_short_version(state.version)}"


def episode_diagram(episode: EpisodeGraph) -> str:
    """Turns in the order they were recorded, with the relations that cross between them.

    The turn-to-turn arrow is ordering, not causality. Anything causal would have to come from a
    relation, and those are drawn as the labelled cross-turn edges.
    """
    lines = ["flowchart LR"]
    for summary in episode.turns:
        steps = f"steps {summary.first_step}–{summary.last_step}" if summary.task_steps else "no steps"
        detail = (f"{summary.agent_task_runs} agent tasks · {steps}<br/>"
                  f"{summary.event_count} events · {summary.checkpoints} checkpoints")
        lines.append(f'  {_turn_id(summary.turn)}["<b>turn {summary.turn}</b><br/>{detail}"]')
    for left, right in episode.chronological_order():
        lines.append(f"  {_turn_id(left)} -.->|next| {_turn_id(right)}")
    for link in episode.cross_turn_links():
        label = link.kind
        if link.kind == "derived_from":
            label += f" · {getattr(link.relation, 'verdict', '?')}"
        state = episode.evidence.states.get(link.from_state_key or link.state_key)
        carrier = f"{state.channel}:{_short_version(state.version)}" if state else link.state_key
        lines.append(f"  {_turn_id(link.from_turn)} ==>|{label}<br/>{carrier}| {_turn_id(link.to_turn)}")
    lines.append("  classDef turn fill:#eef7ff,stroke:#4477aa;")
    if episode.turns:
        lines.append("  class " + ",".join(_turn_id(s.turn) for s in episode.turns) + " turn;")
    return "\n".join(lines)


def turn_diagram(graph: TurnGraph) -> str:
    """One turn: its task runs and state versions, with the relations local to it.

    Relations that cross a boundary are drawn as stubs to a small marker rather than pulling the
    other turn's contents in, so the picture stays locally readable without losing the fact.
    """
    episode = graph.episode
    lines = ["flowchart LR"]
    used_states: set = set()
    edges: list[str] = []

    for run in graph.task_runs:
        shape = f'(["{run.label}"])' if is_internal(run.node) else f'["{run.label}"]'
        mark = "" if run.wrote or run.outcome is None else f"<br/>{run.outcome}"
        lines.append(f"  {_task_id(run.label)}{shape.replace(run.label, run.label + mark)}")

    for write in graph.writes:
        state = episode.evidence.states.get(write.state_key)
        if state is None:
            continue
        used_states.add(write.state_key)
        edges.append(f"  {_task_id(episode.evidence.task_label(write.task_id))} "
                     f"{ARROW['write']} {_state_id(state)}")
    for read in graph.reads:
        state = episode.evidence.states.get(read.state_key)
        if state is None:
            continue
        used_states.add(read.state_key)
        for task_id in read.task_ids:
            edges.append(f"  {_state_id(state)} {ARROW['read']} "
                         f"{_task_id(episode.evidence.task_label(task_id))}")
    for trigger in graph.triggers:
        state = episode.evidence.states.get(trigger.state_key)
        if state is None:
            continue
        used_states.add(trigger.state_key)
        for task_id in trigger.task_ids:
            edges.append(f"  {_state_id(state)} {ARROW['trigger']} "
                         f"{_task_id(episode.evidence.task_label(task_id))}")
    for derived in graph.derived:
        older = episode.evidence.states.get(derived.from_state_key)
        newer = episode.evidence.states.get(derived.state_key)
        if older is None or newer is None:
            continue
        used_states.update({derived.from_state_key, derived.state_key})
        edges.append(f"  {_state_id(older)} -. {derived.verdict} .-> {_state_id(newer)}")

    for key in sorted(used_states, key=lambda k: (episode.evidence.states[k].step is None,
                                                  episode.evidence.states[k].step or 0, k)):
        state = episode.evidence.states[key]
        routing = any(t.state_key == key for t in graph.triggers)
        shape = f'{{{{"{_state_label(state)}"}}}}' if routing else f'(("{_state_label(state)}"))'
        lines.append(f"  {_state_id(state)}{shape}")

    # boundary stubs: draw the relation's end that is *inside* this turn, and a marker for the
    # other turn, so the fact is visible without dragging the other turn's contents in
    for direction, links in (("in", graph.incoming), ("out", graph.outgoing)):
        for index, link in enumerate(links):
            near_key = link.state_key if direction == "in" else (link.from_state_key or link.state_key)
            far_key = link.from_state_key if direction == "in" else link.state_key
            near = None
            if near_key in used_states:
                near = _state_id(episode.evidence.states[near_key])
            elif link.task_ids:
                labels = [episode.evidence.task_label(t) for t in link.task_ids]
                near = next((_task_id(x) for x in labels
                             if any(r.label == x for r in graph.task_runs)), None)
            if near is None:
                continue  # nothing of this relation is inside the turn; the episode view has it
            marker = f"x_{direction}_{index}"
            other = link.from_turn if direction == "in" else link.to_turn
            label = link.kind if link.kind != "derived_from" else f"derived · {getattr(link.relation, 'verdict', '?')}"
            far = episode.evidence.states.get(far_key or "")
            carrier = _state_label(far) if far is not None else link.state_key
            lines.append(f'  {marker}[/"turn {other}<br/>{carrier}"/]')
            if direction == "in":
                edges.append(f"  {marker} -. {label} .-> {near}")
            else:
                edges.append(f"  {near} -. {label} .-> {marker}")

    lines.extend(dict.fromkeys(edges))
    lines.append("  classDef state fill:#fff3c4,stroke:#b8860b;")
    lines.append("  classDef boundary fill:#f0f0f0,stroke:#999,stroke-dasharray:3 3;")
    if used_states:
        lines.append("  class " + ",".join(_state_id(episode.evidence.states[k])
                                           for k in sorted(used_states)) + " state;")
    return "\n".join(lines)


def _evaluation_block(meta: dict, evaluation: Optional[dict]) -> list:
    """The benchmark's own verdict, and nothing derived from it.

    This is the only failure information on the page. It says how the episode was scored; it does
    not say which task run or which state version was responsible, because nothing here measures
    that.
    """
    fields = [
        ("Outcome", meta.get("outcome")),
        ("Reward", meta.get("reward")),
    ]
    if evaluation:
        fields = [
            ("Outcome", "PASSED" if evaluation.get("success") else "FAILED"),
            ("Reward", evaluation.get("reward")),
            ("DB score", evaluation.get("db_score")),
            ("Communicate score", evaluation.get("communicate_score")),
            ("Reasons", ", ".join(evaluation.get("success_reasons") or []) or "-"),
            ("Turns", evaluation.get("turns")),
            ("Terminated by", evaluation.get("terminated_by")),
        ]
    rows = [(name, value) for name, value in fields if value is not None]
    if not rows:
        return []
    lines = ["### Evaluation", "", "| | |", "|---|---|"]
    lines.extend(f"| {name} | `{value}` |" for name, value in rows)
    lines.append("")
    lines.append("Scored by the benchmark's evaluator. No task run or state version on this page is "
                 "marked as the cause of the outcome.")
    lines.append("")
    return lines


def _delta_size(graph: TurnGraph, state_key: str) -> Optional[int]:
    """How many elements the step that produced this version introduced, if it was checked."""
    for derived in graph.episode.evidence.derived:
        if derived.state_key == state_key:
            return len(derived.new) if derived.verdict != "unverified" else None
    return None


def task_run_details(graph: TurnGraph, previews: dict, outputs: dict, mutating_tools=()) -> list:
    """One block per task run: what it read, what it ran, what it produced.

    Kept out of the diagram on purpose. A tool call is not a node in the state graph -- it happens
    inside one task, between that task's read and its write -- so drawing it as one would claim a
    structure LangGraph never recorded.
    """
    lines: list = []
    evidence = graph.episode.evidence
    for run in graph.task_runs:
        reads = sorted({_state_label(evidence.states[r.state_key])
                        for r in graph.reads
                        if run.task_id in r.task_ids and r.state_key in evidence.states})
        written = [w.state_key for w in graph.writes if w.task_id == run.task_id]
        write_bits = []
        for key in written:
            state = evidence.states.get(key)
            if state is None:
                continue
            size = _delta_size(graph, key)
            write_bits.append(f"`{_state_label(state)}`" + (f" (+{size})" if size is not None else ""))

        lines.append(f"#### `{run.label}`")
        lines.append("")
        header = []
        if reads:
            header.append("reads " + ", ".join(f"`{r}`" for r in reads))
        if write_bits:
            header.append("writes " + ", ".join(write_bits))
        if run.outcome:
            header.append(f"outcome `{run.outcome}`")
        lines.append(" · ".join(header) if header else "no recorded reads or writes")
        lines.append("")

        if run.tool_calls:
            declared = {str(name) for name in mutating_tools or ()}
            lines.append(f"Tools it ran ({len(run.tool_calls)}):")
            lines.append("")
            lines.append("| # | tool | arguments | effect | result |")
            lines.append("|---|---|---|---|---|")
            for call in run.tool_calls:
                result = call.get("result_preview")
                cell = short(result, 70) if result else call.get("outcome", "-")
                if call.get("outcome") == "error":
                    cell = f"**error** · {cell}"
                effect = "**external state mutation**" if call.get("name") in declared else "-"
                lines.append(f"| {call.get('order', 0) + 1} | `{call.get('name')}` | "
                             f"{format_args(call.get('args'), 80)} | {effect} | {cell} |")
            lines.append("")

        # A task that ran a node has a `node_end` with its writes in full. LangGraph's own input
        # task has none, so there the checkpoint's write preview is the only record -- and it is a
        # repr of the value, which is why the two are labelled differently rather than blended.
        output = outputs.get(run.task_id)
        if output is not None:
            text = output.get("text")
            heading = "What it wrote:"
        else:
            digests = [w.evidence.value_sha1 for w in graph.writes
                       if w.task_id == run.task_id and w.evidence.value_sha1]
            text = clean_preview(next((previews.get(d) for d in digests if previews.get(d)), None))
            heading = "Recorded write (preview of the raw value):"
        if text:
            lines.append(heading)
            lines.append("")
            lines.append("> " + short(text, 600))
            lines.append("")
        elif output is not None and output.get("requested_calls"):
            lines.append("It wrote no text: the message it produced carried only the call below.")
            lines.append("")
        for call in (output or {}).get("requested_calls") or []:
            lines.append(f"Handed on: `{call.get('name')}({format_args(call.get('args'), 200)})`")
            lines.append("")
    return lines


def render_episode_markdown(episode: EpisodeGraph, source_name: str = "",
                            evaluation: Optional[dict] = None, mutating_tools=()) -> str:
    """The hierarchy as one Markdown page: the episode, then each turn."""
    meta = episode.trace.meta
    out = [f"# Episode{f' — {source_name}' if source_name else ''}", ""]
    out.append(f"episode `{episode.episode_id}` · thread `{episode.thread_id}` · "
               f"{len(episode.turns)} turns")
    if meta.get("task_id"):
        out.append(f"τ² task {meta.get('task_id')} · model {meta.get('model')} · outcome "
                   f"{meta.get('outcome')} · faults {', '.join(meta.get('faults') or []) or 'none'}")
    out.append("")
    out.extend(_evaluation_block(meta, evaluation))
    out.append("```")
    out.append("EpisodeGraph")
    out.append("  └── TurnGraph")
    out.append("        └── TaskRun")
    out.append("              ├── tool calls")
    out.append("              └── WRITE / READ")
    out.append("```")
    out.append("")
    out.append("`task steps` are the super-steps that ran a task; `all steps` are every super-step "
               "the turn checkpointed, which is wider because a super-step can checkpoint without "
               "running a task.")
    out.append("")
    out.append("A turn is a Firebreak-assigned analysis unit, stamped by whoever recorded the run. "
               "By convention one external interaction is recorded as one turn, but nothing enforces "
               "that. `step` is LangGraph's super-step counter for the whole thread, so a turn's "
               "steps do not start at zero and one step can hold several task runs.")
    out.append("")
    out.append("### How to read this")
    out.append("")
    out.append("| notation | means |")
    out.append("|---|---|")
    out.append("| `messages:v4` | one version of one channel |")
    out.append("| `(+n)` after a version | that step introduced n new elements, relative to the "
               "previous version |")
    out.append("| reads `messages:v4` | the task was handed **the whole version**, not the delta. "
               "The delta is a property of the step, not the task's input; the exact input is in "
               "the trace's `node_start` event |")
    out.append("| round node | a data channel · hexagon | a routing channel |")
    out.append("| solid arrow | an observed relation · dotted | a checked derivation |")
    out.append("| `external state mutation` | the tool was declared as one that changes state "
               "outside the process. It says what the call did, not that it caused the outcome |")
    out.append("")
    out.append("Version counters skip numbers because LangGraph advances one counter for the whole "
               "checkpoint, so a number spent on another channel never appears on this one.")
    out.append("")

    out.append("## Episode")
    out.append("")
    out.append("| turn | invokes | task steps | all steps | agent tasks | events | checkpoints | wall time |")
    out.append("|---|---|---|---|---|---|---|---|")
    for summary in episode.turns:
        wall = f"{summary.wall_time:.1f}s" if summary.wall_time else "-"
        out.append(f"| {summary.turn} | {len(summary.invoke_ids)} | "
                   f"{_steps(summary.task_steps)} | {_steps(summary.checkpoint_steps)} | "
                   f"{summary.agent_task_runs} | {summary.event_count} | {summary.checkpoints} | {wall} |")
    out.append("")
    links = episode.cross_turn_links()
    out.append(f"The dotted `next` arrows are recording order, not causality. The {len(links)} thick "
               "arrows are relations that actually cross a turn boundary.")
    out.append("")
    out.append("```mermaid")
    out.append(episode_diagram(episode))
    out.append("```")
    out.append("")
    if links:
        out.append("### Relations that cross a turn boundary")
        out.append("")
        out.append("| kind | from turn | to turn | carrier | evidence |")
        out.append("|---|---|---|---|---|")
        for link in links:
            state = episode.evidence.states.get(link.from_state_key or link.state_key)
            carrier = _state_label(state) if state else link.state_key
            evidence = link.evidence
            source = evidence.source if evidence is not None else "-"
            verdict = f" ({link.relation.verdict})" if link.kind == "derived_from" else ""
            out.append(f"| `{link.kind}`{verdict} | {link.from_turn} | {link.to_turn} | "
                       f"`{carrier}` | {source} |")
        out.append("")

    previews = preview_by_digest(episode.trace)
    outputs = task_outputs(episode.trace)
    for graph in episode:
        summary = graph.summary
        out.append(f"## Turn {summary.turn}")
        out.append("")
        agents = ", ".join(f"`{r.label.split(' ')[0]}`" for r in graph.agent_task_runs) or "none"
        out.append(f"{summary.agent_task_runs} agent task runs ({agents}), "
                   f"{len(graph.internal_task_runs)} internal, "
                   f"{len(graph.state_versions)} state versions, "
                   f"{len(graph.writes)} WRITE · {len(graph.reads)} READ · "
                   f"{len(graph.triggers)} TRIGGER · {len(graph.derived)} DERIVED_FROM, "
                   f"{len(graph.incoming)} in / {len(graph.outgoing)} out across the boundary.")
        out.append("")
        out.append("```mermaid")
        out.append(turn_diagram(graph))
        out.append("```")
        out.append("")
        out.append(f"### Turn {summary.turn} · task runs")
        out.append("")
        out.extend(task_run_details(graph, previews, outputs, mutating_tools))
    out.append("---")
    out.append("")
    out.append("Relation-level evidence and the field each relation came from are in the "
               "`.provenance.txt` and `.provenance.md` beside this file.")
    return "\n".join(out) + "\n"
