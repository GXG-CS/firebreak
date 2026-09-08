"""Copy LangGraph's checkpoint records into the trace, so provenance survives offline.

A `checkpoint_fact` event holds, per checkpoint, exactly the fields LangGraph uses to schedule
work: `channel_versions`, `versions_seen`, `updated_channels`, and the `(task_id, channel, value)`
writes made from that checkpoint. Values are reduced to a digest and a short preview; the full
values are already in the `node_end` writes, and `channel_values` is a whole state snapshot per
step, which would make the trace grow quadratically.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from firebreak.tracing.events import Event

CHECKPOINT_FACT = "checkpoint_fact"
PREVIEW = 200

# LangGraph channel classes that fold each write into the existing value rather than replacing it.
# Folding does NOT imply the new version contains the old one: `BinaryOperatorAggregate` takes an
# arbitrary binary operator, and even `add_messages` replaces a message when the id matches and
# drops messages on `RemoveMessage`. So this list only decides *where it is worth checking*;
# whether a version actually retained the previous one is verified per version from element ids.
FOLDING_CHANNELS = ("BinaryOperatorAggregate", "Topic", "DeltaChannel")
ACCUMULATING_CHANNELS = FOLDING_CHANNELS  # kept for compatibility with the previous name

# Channels LangGraph writes to record a task's *outcome* rather than any state. Every executed
# task produces one write, so a task that returned nothing (`__no_writes__`) or raised
# (`__error__`) still appears in `pending_writes` — which makes those writes a first-hand record
# of the outcome, and means they must not be turned into state versions.
# (`langgraph/_internal/_constants.py`.)
SENTINEL_CHANNELS = {
    "__error__": "error",
    "__no_writes__": "no_writes",
    "__interrupt__": "interrupt",
    "__resume__": "resume",
    "__return__": "return",
}

# Element ids are recorded so containment can be checked instead of assumed. Beyond this many the
# channel is marked truncated and derivation over it stays unverified.
MAX_ELEMENT_IDS = 2000


def _digest(value: Any) -> str:
    try:
        blob = json.dumps(value, sort_keys=True, default=str)
    except Exception:  # pragma: no cover - defensive
        blob = repr(value)
    return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:12]


def _preview(value: Any) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= PREVIEW else text[:PREVIEW] + "..."


def _versions(mapping: Any) -> dict:
    return {str(k): str(v) for k, v in (mapping or {}).items()}


def _config_ids(config: Any) -> dict:
    conf = (config or {}).get("configurable") or {}
    return {
        "thread_id": conf.get("thread_id"),
        "checkpoint_ns": conf.get("checkpoint_ns", ""),
        "checkpoint_id": conf.get("checkpoint_id"),
    }


def element_ids(value: Any) -> list | None:
    """Stable per-element identity of a list-valued channel, for checking containment.

    Only identities are kept, never content. LangChain messages carry a stable `id`; anything else
    falls back to a digest of the element. Returns None when the value is not a list, or when it is
    longer than MAX_ELEMENT_IDS, in which case containment is left unverified rather than guessed.
    """
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) > MAX_ELEMENT_IDS:
        return None
    ids: list[str] = []
    for element in value:
        ident = getattr(element, "id", None)
        if ident is None and isinstance(element, dict):
            ident = element.get("id")
        ids.append(str(ident) if ident is not None else f"#{_digest(element)}")
    return ids


def channel_types(graph: Any) -> dict:
    """Channel name -> LangGraph channel class name, read off the compiled graph."""
    channels = getattr(graph, "channels", None) or {}
    out: dict[str, str] = {}
    try:
        for name, channel in channels.items():
            out[str(name)] = type(channel).__name__
    except Exception:  # pragma: no cover - defensive
        return {}
    return out


def snapshot_checkpoints(graph: Any, config: dict | None, trace: Any) -> int:
    """Append a `checkpoint_fact` event for every checkpoint of this thread not yet recorded.

    Safe to call after each invoke: checkpoints are immutable and identified by `checkpoint_id`,
    so re-reading the thread only adds the new ones. Returns how many were added.
    """
    checkpointer = getattr(graph, "checkpointer", None)
    if checkpointer is None or not hasattr(checkpointer, "list"):
        return 0
    conf = (config or {}).get("configurable") or {}
    thread_id = conf.get("thread_id") or trace.meta.get("thread_id")
    if not thread_id:
        return 0
    known = {
        e.payload.get("checkpoint_id")
        for e in trace.of_kind(CHECKPOINT_FACT)
        if e.payload.get("checkpoint_id")
    }
    listing_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": conf.get("checkpoint_ns", "")}}
    try:
        tuples = list(checkpointer.list(listing_config))
    except Exception as exc:  # a provenance snapshot must never break a run
        trace.meta.setdefault("provenance_errors", []).append(repr(exc))
        return 0

    if "channel_types" not in trace.meta:
        types = channel_types(graph)
        if types:
            trace.meta["channel_types"] = types
            trace.meta["accumulating_channels"] = sorted(
                name for name, cls in types.items() if cls in ACCUMULATING_CHANNELS
            )

    added = 0
    for item in reversed(tuples):  # list() yields newest first
        ids = _config_ids(item.config)
        checkpoint_id = ids.get("checkpoint_id")
        if not checkpoint_id or checkpoint_id in known:
            continue
        checkpoint = item.checkpoint or {}
        metadata = item.metadata or {}
        # element identities for folding channels, so `derived from` can be checked, not assumed
        elements: dict[str, dict] = {}
        folding = set(trace.meta.get("accumulating_channels") or [])
        for channel, value in (checkpoint.get("channel_values") or {}).items():
            if str(channel) not in folding:
                continue
            member_ids = element_ids(value)
            elements[str(channel)] = {
                "ids": member_ids,
                "n": len(value) if isinstance(value, (list, tuple)) else None,
                "truncated": member_ids is None and isinstance(value, (list, tuple)),
            }
        writes = []
        for entry in item.pending_writes or []:
            try:
                task_id, channel, value = entry[0], entry[1], entry[2]
            except (IndexError, TypeError):  # pragma: no cover - defensive
                continue
            writes.append(
                {
                    "task_id": str(task_id),
                    "channel": str(channel),
                    "value_sha1": _digest(value),
                    "value_preview": _preview(value),
                    "value_type": type(value).__name__,
                }
            )
        trace.add(
            Event(
                CHECKPOINT_FACT,
                name=str(checkpoint_id),
                step=metadata.get("step"),
                payload={
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_ns": ids.get("checkpoint_ns", ""),
                    "thread_id": ids.get("thread_id"),
                    "parent_checkpoint_id": _config_ids(item.parent_config).get("checkpoint_id"),
                    "source": metadata.get("source"),
                    "step": metadata.get("step"),
                    "parents": dict(metadata.get("parents") or {}),
                    "channel_versions": _versions(checkpoint.get("channel_versions")),
                    "versions_seen": {
                        str(node): _versions(seen)
                        for node, seen in (checkpoint.get("versions_seen") or {}).items()
                    },
                    "updated_channels": [str(c) for c in (checkpoint.get("updated_channels") or [])],
                    "elements": elements,
                    "writes": writes,
                },
            )
        )
        added += 1
    return added
