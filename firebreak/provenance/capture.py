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
from typing import Any, Optional

from firebreak.tracing.events import Event

CHECKPOINT_FACT = "checkpoint_fact"
PREVIEW = 200

# LangGraph channel classes that fold a new write into the existing value, so version N+1 of the
# channel contains version N. Everything else replaces, and no derivation may be claimed.
ACCUMULATING_CHANNELS = ("BinaryOperatorAggregate", "Topic", "DeltaChannel")


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


def snapshot_checkpoints(graph: Any, config: Optional[dict], trace: Any) -> int:
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
                    "writes": writes,
                },
            )
        )
        added += 1
    return added
