"""Event model and JSON-safe conversion for captured runtime data."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_TEXT = 4000
MAX_ITEMS = 64
MAX_DEPTH = 6

# Channels LangGraph uses for routing rather than user state.
ROUTING_PREFIXES = ("branch:", "__", "start:")


def is_routing_channel(name: str) -> bool:
    return any(str(name).startswith(prefix) for prefix in ROUTING_PREFIXES)


def safe(value: Any, depth: int = 0) -> Any:
    """Return a JSON-safe, size-bounded copy of an arbitrary Python value."""
    if depth > MAX_DEPTH:
        return repr(value)[:MAX_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + "...<truncated>"
    if isinstance(value, BaseException):
        return {"error_type": type(value).__name__, "message": str(value)[:MAX_TEXT]}
    if isinstance(value, dict):
        return {str(k): safe(v, depth + 1) for k, v in list(value.items())[:MAX_ITEMS]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [safe(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
    if hasattr(value, "type") and hasattr(value, "content"):
        # LangChain message objects.
        out: dict[str, Any] = {
            "type": getattr(value, "type", None),
            "content": safe(value.content, depth + 1),
        }
        for attr in ("name", "tool_call_id", "id"):
            val = getattr(value, attr, None)
            if val:
                out[attr] = val
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            out["tool_calls"] = safe(tool_calls, depth + 1)
        provenance = (getattr(value, "response_metadata", None) or {}).get("firebreak")
        if provenance:
            out["firebreak"] = safe(provenance, depth + 1)
        return out
    if hasattr(value, "model_dump"):
        try:
            return safe(value.model_dump(), depth + 1)
        except Exception:  # pragma: no cover - defensive
            pass
    return repr(value)[:MAX_TEXT]


@dataclass
class Event:
    """One captured runtime event.

    kind: node_start | node_end | node_error | tool_start | tool_end | tool_error |
          llm_start | llm_end | llm_error | chain_start | chain_end | chain_error |
          checkpoint | injection | run_error

    ``episode_id`` / ``turn`` / ``invoke_id`` place the event inside a multi-invocation
    episode (one ``graph.invoke`` per user turn). ``seq`` is global across the episode.
    """

    kind: str
    name: str = ""
    node: str | None = None
    step: int | None = None
    task_id: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    triggers: list = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    seq: int = 0
    episode_id: str | None = None
    turn: int | None = None
    invoke_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        return cls(**data)
