"""Record one LangGraph run into an ordered, serialisable Trace."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable, Optional

from firebreak.tracing.callbacks import FirebreakTracer
from firebreak.tracing.events import Event, safe


class Trace:
    """Ordered list of Events plus run metadata (static graph, final state, timing)."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.meta: dict[str, Any] = {}
        self.final_state: Any = None
        self._seq = 0

    def add(self, event: Event) -> Event:
        self._seq += 1
        event.seq = self._seq
        self.events.append(event)
        return event

    def of_kind(self, *kinds: str) -> list[Event]:
        return [e for e in self.events if e.kind in kinds]

    def to_jsonl(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"__meta__": self.meta}) + "\n")
            for event in self.events:
                handle.write(json.dumps(event.to_dict()) + "\n")

    @classmethod
    def from_jsonl(cls, path: str) -> "Trace":
        trace = cls()
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if "__meta__" in data:
                    trace.meta = data["__meta__"]
                    continue
                event = Event.from_dict(data)
                trace.events.append(event)
                trace._seq = max(trace._seq, event.seq)
        trace.final_state = trace.meta.get("final_state")
        return trace


# ---- debug-stream ingestion -------------------------------------------------------------

def _task_id(payload: dict) -> Optional[str]:
    value = payload.get("id")
    return str(value) if value is not None else None


def _writes_from_result(result: Any) -> dict[str, Any]:
    writes: dict[str, Any] = {}
    if isinstance(result, dict):
        return {str(k): safe(v) for k, v in result.items()}
    if isinstance(result, (list, tuple)):
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                writes[str(item[0])] = safe(item[1])
    return writes


def _ingest_debug(trace: Trace, chunk: Any) -> None:
    if not isinstance(chunk, dict):
        return
    kind = chunk.get("type")
    payload = chunk.get("payload") or {}
    step = chunk.get("step")
    if kind == "task":
        name = str(payload.get("name"))
        trace.add(
            Event(
                "node_start",
                name=name,
                node=name,
                step=step,
                task_id=_task_id(payload),
                triggers=[str(t) for t in (payload.get("triggers") or [])],
                payload={"input": safe(payload.get("input"))},
            )
        )
    elif kind == "task_result":
        name = str(payload.get("name"))
        error = payload.get("error")
        trace.add(
            Event(
                "node_error" if error else "node_end",
                name=name,
                node=name,
                step=step,
                task_id=_task_id(payload),
                payload={
                    "writes": _writes_from_result(payload.get("result")),
                    "error": safe(error) if error else None,
                    "interrupts": safe(payload.get("interrupts") or []),
                },
            )
        )
    elif kind == "checkpoint":
        values = payload.get("values")
        trace.add(
            Event(
                "checkpoint",
                step=step,
                payload={
                    "next": safe(payload.get("next")),
                    "keys": sorted(values.keys()) if isinstance(values, dict) else None,
                },
            )
        )


def _ingest_task(trace: Trace, chunk: Any) -> None:
    """Fallback for ``stream_mode='tasks'`` (no step numbers)."""
    if not isinstance(chunk, dict):
        return
    name = str(chunk.get("name"))
    if "result" in chunk or "error" in chunk:
        error = chunk.get("error")
        trace.add(
            Event(
                "node_error" if error else "node_end",
                name=name,
                node=name,
                task_id=_task_id(chunk),
                payload={
                    "writes": _writes_from_result(chunk.get("result")),
                    "error": safe(error) if error else None,
                    "interrupts": safe(chunk.get("interrupts") or []),
                },
            )
        )
    else:
        trace.add(
            Event(
                "node_start",
                name=name,
                node=name,
                task_id=_task_id(chunk),
                triggers=[str(t) for t in (chunk.get("triggers") or [])],
                payload={"input": safe(chunk.get("input"))},
            )
        )


def _static_graph(graph: Any) -> dict[str, Any]:
    """Snapshot the compiled graph's static structure (node names, edges)."""
    try:
        drawable = graph.get_graph()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": repr(exc), "nodes": [], "edges": []}
    nodes = [str(n) for n in getattr(drawable, "nodes", {}).keys()]
    edges = []
    for edge in getattr(drawable, "edges", []):
        edges.append(
            {
                "source": str(getattr(edge, "source", "")),
                "target": str(getattr(edge, "target", "")),
                "conditional": bool(getattr(edge, "conditional", False)),
            }
        )
    return {"nodes": nodes, "edges": edges}


def _iter_stream(stream: Iterable[Any]):
    """Normalise multi-mode stream items to ``(mode, data)``.

    LangGraph's default (v1) multi-mode streaming yields ``(mode, data)`` tuples; the v2
    protocol yields ``StreamPart`` dicts with a ``type`` key.  Both are accepted here.
    """
    for item in stream:
        if isinstance(item, tuple) and len(item) == 2:
            yield item[0], item[1]
        elif isinstance(item, dict) and "type" in item:
            mode = item["type"]
            data = item.get("data", item.get("chunk", item))
            yield mode, data
        else:
            yield "unknown", item


def record(
    graph: Any,
    input: Any,
    *,
    config: Optional[dict] = None,
    trace: Optional[Trace] = None,
    thread_id: Optional[str] = None,
    extra_callbacks: Optional[Iterable[Any]] = None,
) -> Trace:
    """Run ``graph`` on ``input`` and capture everything into a Trace.

    The trace merges LangGraph's debug stream (node starts, writes, triggers, checkpoints)
    with callback events (tool / model calls attributed to nodes).
    """
    trace = trace or Trace()
    tracer = FirebreakTracer(trace)
    cfg = dict(config or {})
    cfg["callbacks"] = list(cfg.get("callbacks") or []) + list(extra_callbacks or []) + [tracer]
    configurable = dict(cfg.get("configurable") or {})
    configurable.setdefault("thread_id", thread_id or str(uuid.uuid4()))
    cfg["configurable"] = configurable

    trace.meta["thread_id"] = configurable["thread_id"]
    trace.meta["static_graph"] = _static_graph(graph)
    trace.meta["started"] = time.time()
    last_values: Any = None
    try:
        try:
            for mode, chunk in _iter_stream(graph.stream(input, cfg, stream_mode=["debug", "values"])):
                if mode == "values":
                    last_values = chunk
                elif mode == "debug":
                    _ingest_debug(trace, chunk)
        except ValueError as exc:
            if "stream_mode" not in str(exc) and "debug" not in str(exc):
                raise
            trace.meta["stream_fallback"] = "tasks"
            for mode, chunk in _iter_stream(graph.stream(input, cfg, stream_mode=["tasks", "values"])):
                if mode == "values":
                    last_values = chunk
                elif mode == "tasks":
                    _ingest_task(trace, chunk)
    except Exception as exc:
        trace.add(Event("run_error", payload={"error": safe(exc)}))
        trace.meta["run_error"] = repr(exc)
    trace.meta["finished"] = time.time()
    trace.meta["wall_time"] = trace.meta["finished"] - trace.meta["started"]
    trace.final_state = last_values
    trace.meta["final_state"] = safe(last_values)
    return trace
