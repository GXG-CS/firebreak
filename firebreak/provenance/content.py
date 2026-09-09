"""Look content back up in the trace, for the renderers only.

The graph model stores identity and evidence, not payloads: a state version is a channel and a
version, a write is a task and a digest. That is what keeps the model small and keeps it from
becoming a second copy of the trace. But a page a person reads needs to say *what* travelled, not
only that something did.

Both renderers already receive the `Trace` alongside the graph, so the text can be fetched at
render time from the events that already hold it:

* `node_end` carries a task's writes in full, so it is the source for what a task produced.
* `checkpoint_fact` carries a short preview per write, keyed by the same digest the WRITE relation
  records, so it is the source for what one version introduced.

Nothing here interprets: it selects recorded text and truncates it.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from firebreak.provenance.capture import CHECKPOINT_FACT


def short(text: Optional[str], limit: int = 240) -> str:
    """One line, collapsed whitespace, truncated with a visible marker."""
    if text is None:
        return ""
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + " […]"


_REPR_CONTENT = re.compile(
    r"content=(['\"])(.*?)\1(?=\s*,\s*(?:additional_kwargs|response_metadata|name|id|"
    r"tool_call_id|tool_calls|usage_metadata)=)",
    re.DOTALL,
)


def clean_preview(text: Optional[str]) -> str:
    """Pull the message contents out of a repr of a message list, for display only.

    A checkpoint preview is `str(value)` of whatever was written, so for a message channel it
    reads `[AIMessage(content='...', additional_kwargs={...}, response_metadata={'token_usage':
    ...})]`. The content is the part worth showing; token counts and empty option dicts are noise
    on a page a person reads.

    This is a presentation heuristic over a repr, not a parse, so it is used only where the label
    already says "preview". If the pattern does not match, the original text is returned unchanged
    rather than a guess at what it meant.
    """
    if not text:
        return ""
    found = [match.group(2) for match in _REPR_CONTENT.finditer(str(text))]
    if not found:
        return str(text)  # not a shape this recognises: show it as recorded rather than guess
    # Matched, and every content was empty: the messages really carried no text (a message whose
    # only payload is a tool call). Saying so beats falling back to the repr and its metadata.
    return " ".join(part for part in found if part.strip())


def preview_by_digest(trace: Any) -> dict:
    """digest -> the preview recorded for the write with that digest.

    The WRITE relation carries `evidence.value_sha1`, so this is the join between a state version
    and the text of the write that produced it.
    """
    previews: dict = {}
    for event in trace.events:
        if event.kind != CHECKPOINT_FACT:
            continue
        for write in event.payload.get("writes") or []:
            digest = write.get("value_sha1")
            if digest and digest not in previews:
                previews[digest] = write.get("value_preview")
    return previews


def _message_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("content") or "")
    return str(item)


def _message_calls(item: Any) -> list:
    """The tool calls an LLM asked for in this message -- the request, not the execution."""
    if not isinstance(item, dict):
        return []
    calls = item.get("tool_calls") or []
    return [{"name": c.get("name"), "args": c.get("args")} for c in calls if isinstance(c, dict)]


def task_outputs(trace: Any) -> dict:
    """task_id -> what that task wrote, in full, from its `node_end` event.

    Returns `{"text": str, "requested_calls": [{name, args}], "channels": [str]}`. The text is the
    concatenation of the message contents the task wrote; `requested_calls` are the tool calls the
    task's own message asked for, which is how a supervisor delegates and is not the same thing as
    a tool this task actually ran.
    """
    outputs: dict = {}
    for event in trace.events:
        if event.kind != "node_end" or not event.task_id:
            continue
        writes = (event.payload or {}).get("writes") or {}
        if not isinstance(writes, dict):
            continue
        texts: list[str] = []
        requested: list = []
        for channel, value in writes.items():
            items = value if isinstance(value, list) else [value]
            for item in items:
                text = _message_text(item)
                if text:
                    texts.append(text)
                requested.extend(_message_calls(item))
            del channel
        outputs[str(event.task_id)] = {
            "text": "\n".join(texts).strip(),
            "requested_calls": requested,
            "channels": sorted(writes.keys()),
        }
    return outputs


def format_args(args: Any, limit: int = 120) -> str:
    """Tool arguments as `k=v, k=v`, kept short enough for a table cell."""
    if not isinstance(args, dict):
        return short(args, limit)
    parts = [f"{k}={short(v, 48)!r}" if isinstance(v, str) else f"{k}={short(v, 48)}"
             for k, v in args.items()]
    joined = ", ".join(parts)
    return joined if len(joined) <= limit else joined[:limit] + " […]"
