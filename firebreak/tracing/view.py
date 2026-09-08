"""Source-aligned view of a capture: what each runtime source reported, per task execution.

A trace is a flat, ordered event list, but the three sources that produced it do not observe the
same things and do not arrive at the same time. The stream and the callbacks are recorded while
the graph runs; `checkpoint_fact` events are snapshotted from the checkpointer *after* the invoke
finishes, so their position in the file says nothing about when the facts came to be.

This view therefore regroups the events by turn, task execution and checkpoint, and prints each
one's original `seq` so the raw capture position is never lost.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from firebreak.tracing.events import Event
from firebreak.tracing.grouping import group_by_task_run
from firebreak.tracing.recorder import Trace

STREAM_KINDS = {"node_start", "node_end", "node_error", "checkpoint"}
CALLBACK_KINDS = {"chain_start", "chain_end", "chain_error", "llm_start", "llm_end", "llm_error",
                  "tool_start", "tool_end", "tool_error"}
CHECKPOINTER_KINDS = {"checkpoint_fact"}

SOURCE = (
    [(k, "STREAM") for k in STREAM_KINDS]
    + [(k, "CALLBACK") for k in CALLBACK_KINDS]
    + [(k, "CHECKPOINTER") for k in CHECKPOINTER_KINDS]
    + [("injection", "FIREBREAK"), ("run_error", "FIREBREAK")]
)
SOURCE_OF = dict(SOURCE)

WIDTH = 96


def source_of(event: Event) -> str:
    return SOURCE_OF.get(event.kind, "?")


def _short_version(version: Any) -> str:
    head, _, tail = str(version).partition(".")
    counter = head.lstrip("0") or "0"
    return f"v{counter}"


def _short_id(value: Any, n: int = 8) -> str:
    text = str(value or "")
    return text[:n] + "…" if len(text) > n else text


def _one_line(value: Any, limit: int = 62) -> str:
    if isinstance(value, str):
        text = " ".join(value.split())
    else:
        try:
            text = json.dumps(value, default=str)
        except Exception:  # pragma: no cover - defensive
            text = repr(value)
        text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _channel_summary(mapping: Any) -> str:
    """`{"messages": [3 items], "branch:to:x": ...}` as `messages[3] · branch:to:x`."""
    if not isinstance(mapping, dict):
        return _one_line(mapping)
    parts = []
    for key, value in mapping.items():
        if isinstance(value, list):
            parts.append(f"{key}[{len(value)}]")
        else:
            parts.append(str(key))
    return " · ".join(parts) or "-"


def _message_summary(messages: Any) -> str:
    if not isinstance(messages, list):
        return _one_line(messages)
    flat = messages[0] if len(messages) == 1 and isinstance(messages[0], list) else messages
    if not isinstance(flat, list):
        return _one_line(messages)
    kinds: list[str] = []
    for message in flat:
        if isinstance(message, dict):
            kind = str(message.get("type", "?"))
            if message.get("tool_calls"):
                kind += f"+{len(message['tool_calls'])}tc"
            kinds.append(kind)
    return f"{len(flat)} messages: " + ", ".join(kinds) if kinds else _one_line(messages)


def _event_line(event: Event, indent: int = 2) -> list[str]:
    """One event as a labelled line plus whatever detail that kind actually carries."""
    pad = " " * indent
    src = source_of(event)
    head = f"{pad}{src:<13}{event.kind:<14}{event.name or '':<24}"
    lines = [f"{head}{'':<4}seq {event.seq}"]
    detail = " " * (indent + 15)
    payload = event.payload or {}

    if event.kind == "node_start":
        lines.append(f"{detail}triggers   {', '.join(event.triggers) or '-'}")
        lines.append(f"{detail}input      {_channel_summary(payload.get('input'))}")
    elif event.kind in ("node_end", "node_error"):
        lines.append(f"{detail}writes     {_channel_summary(payload.get('writes'))}")
        if payload.get("error"):
            lines.append(f"{detail}error      {_one_line(payload['error'])}")
    elif event.kind == "checkpoint":
        lines.append(f"{detail}next       {', '.join(payload.get('next') or []) or '-'}")
        lines.append(f"{detail}state keys {', '.join(payload.get('keys') or []) or '-'}")
    elif event.kind == "llm_start":
        lines.append(f"{detail}prompt     {_message_summary(payload.get('messages') or payload.get('prompts'))}")
    elif event.kind == "llm_end":
        lines.append(f"{detail}reply      {_message_summary(payload.get('generations'))}")
    elif event.kind == "tool_start":
        lines.append(f"{detail}args       {_one_line(payload.get('input'))}")
    elif event.kind == "tool_end":
        lines.append(f"{detail}result     {_one_line(payload.get('output'))}")
    elif event.kind in ("tool_error", "llm_error", "chain_error", "run_error"):
        lines.append(f"{detail}error      {_one_line(payload.get('error'))}")
    elif event.kind == "injection":
        lines.append(f"{detail}fault      {payload.get('fault_id')} {payload.get('kind')}:{payload.get('target')}")
    return lines


def _langgraph_extras(events: list) -> Optional[dict]:
    for event in events:
        extras = (event.payload or {}).get("langgraph")
        if extras:
            return extras
    return None


def render_trace(trace: Trace, source_name: str = "", show_checkpoints: bool = True) -> str:
    out: list[str] = []
    add = out.append
    meta = trace.meta

    add(f"# Capture{f' — {source_name}' if source_name else ''}")
    add("")
    add("Three runtime sources, one trace. Grouped by turn and task execution, not by file order:")
    add("  STREAM        graph.stream(debug): node runs, their triggers, input state and writes")
    add("  CALLBACK      chain / model / tool calls, attributed to the node run that made them")
    add("  CHECKPOINTER  durable records, snapshotted after each invoke, so their file position")
    add("                is not when they came to be. Every line keeps its original seq.")
    add("")
    add(f"episode {meta.get('episode_id')}  thread {meta.get('thread_id')}  "
        f"task {meta.get('task_id')}  model {meta.get('model')}  outcome {meta.get('outcome')}")
    add(f"{len(trace.events)} events over {len(trace.turns)} turns, "
        f"{len(meta.get('invokes') or [])} invokes, {meta.get('wall_time', 0):.1f}s")
    if meta.get("faults"):
        add(f"faults injected: {', '.join(meta['faults'])}")
    add("")

    facts = {str(e.payload.get("checkpoint_id")): e for e in trace.of_kind("checkpoint_fact")}
    facts_by_step = {e.payload.get("step"): e for e in facts.values()}
    writes_by_task: dict[str, list] = {}
    for event in facts.values():
        for write in event.payload.get("writes") or []:
            writes_by_task.setdefault(write["task_id"], []).append((event, write))

    grouped = group_by_task_run(trace)
    runs = grouped.runs
    loose = [e for e in grouped.unattached] + [e for e in grouped.turn_events if e.kind != "checkpoint_fact"]
    loose.sort(key=lambda e: e.seq)

    last_turn = object()
    for run in runs:
        if run.turn != last_turn:
            last_turn = run.turn
            add("")
            add("=" * WIDTH)
            add(f"TURN {run.turn}")
            add("=" * WIDTH)
        seqs = [e.seq for e in run.events]
        add("")
        add(f"turn {run.turn} · step {run.step} · {run.node} · task {run.task_id or run.key}")
        extras = _langgraph_extras(run.events)
        if extras:
            path = extras.get("path")
            add(f"  langgraph   path={path}  checkpoint_ns={extras.get('checkpoint_ns')}")
        add(f"  captured at seq {min(seqs)}–{max(seqs)}  ·  grouped by {run.identity}")
        add("")
        for event in run.events:
            out.extend(_event_line(event))
        # what the checkpointer durably recorded about this same execution
        recorded = writes_by_task.get(str(run.task_id or ""), [])
        if recorded:
            add("")
            fact, _ = recorded[0]
            payload = fact.payload
            add(f"  CHECKPOINTER  durable record of this execution                    "
                f"seq {fact.seq} (snapshotted later)")
            add(f"               scheduled from  checkpoint {_short_id(payload['checkpoint_id'], 13)} "
                f"step {payload['step']}")
            for _, write in recorded:
                add(f"               wrote           {write['channel']:<22} sha1 {write['value_sha1']}")
            after = facts_by_step.get((payload.get("step") or 0) + 1)
            if after is not None:
                versions = after.payload.get("channel_versions") or {}
                produced = [f"{w['channel']}={_short_version(versions.get(w['channel']))}"
                            for _, w in recorded if w["channel"] in versions]
                if produced:
                    add(f"               produced        {' · '.join(produced)}  "
                        f"(in checkpoint {_short_id(after.payload['checkpoint_id'], 13)} step {after.payload['step']})")

    if loose:
        add("")
        add("=" * WIDTH)
        add("EVENTS OUTSIDE A TASK EXECUTION")
        add("=" * WIDTH)
        add("")
        for event in loose:
            out.extend(_event_line(event))

    if show_checkpoints and facts:
        add("")
        add("=" * WIDTH)
        add("CHECKPOINTER LEDGER")
        add("=" * WIDTH)
        add("")
        add("Snapshotted after each invoke. This is the record the provenance is rebuilt from.")
        add("")
        for event in sorted(facts.values(), key=lambda e: str(e.payload.get("checkpoint_id"))):
            payload = event.payload
            add(f"checkpoint {payload['checkpoint_id']}  step {payload['step']}  "
                f"source {payload['source']}                seq {event.seq}")
            versions = payload.get("channel_versions") or {}
            add(f"  versions   {' · '.join(f'{c}={_short_version(v)}' for c, v in versions.items()) or '-'}")
            seen = payload.get("versions_seen") or {}
            seen_text = " · ".join(
                f"{node}{{{', '.join(f'{c}={_short_version(v)}' for c, v in channels.items()) or '-'}}}"
                for node, channels in seen.items()
            )
            add(f"  seen       {seen_text or '-'}")
            add(f"  updated    {', '.join(payload.get('updated_channels') or []) or '-'}")
            writes = payload.get("writes") or []
            if writes:
                add("  writes     " + " · ".join(f"{_short_id(w['task_id'])}→{w['channel']}" for w in writes))
            elements = payload.get("elements") or {}
            for channel, info in elements.items():
                ids = info.get("ids")
                add(f"  elements   {channel}: {len(ids) if ids is not None else '?'} "
                    f"{'ids recorded' if ids is not None else 'not recorded'}")
            add("")
    return "\n".join(out) + "\n"
