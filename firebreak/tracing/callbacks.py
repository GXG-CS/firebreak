"""LangChain callback handler that attributes tool / model events to LangGraph nodes."""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler

from firebreak.tracing.events import Event, safe


class FirebreakTracer(BaseCallbackHandler):
    """Collects tool, model, and node-level chain events into a Trace.

    LangGraph stamps every run started inside a node with metadata keys
    ``langgraph_node``, ``langgraph_step`` and ``langgraph_triggers``; that is how each
    tool / model call is attributed to the node run that made it.
    """

    def __init__(self, trace) -> None:
        super().__init__()
        self.trace = trace
        self._names: dict[str, str] = {}
        self._ctx_by_run: dict[str, tuple] = {}

    # ---- helpers -------------------------------------------------------------------
    @staticmethod
    def _ctx(metadata: Optional[dict]) -> tuple:
        md = metadata or {}
        triggers = md.get("langgraph_triggers") or []
        return md.get("langgraph_node"), md.get("langgraph_step"), [str(t) for t in triggers]

    def _remember(self, run_id: Any, name: str, metadata: Optional[dict]) -> None:
        self._names[str(run_id)] = name
        self._ctx_by_run[str(run_id)] = self._ctx(metadata)

    def _recall(self, run_id: Any) -> tuple[str, Optional[tuple]]:
        return self._names.get(str(run_id), ""), self._ctx_by_run.get(str(run_id))

    def _emit(self, kind: str, name: str, run_id: Any, parent_run_id: Any, ctx: Optional[tuple], payload: dict) -> Event:
        node, step, triggers = ctx if ctx else (None, None, [])
        return self.trace.add(
            Event(
                kind=kind,
                name=name,
                node=node,
                step=step,
                run_id=str(run_id) if run_id is not None else None,
                parent_run_id=str(parent_run_id) if parent_run_id else None,
                triggers=list(triggers),
                payload=payload,
            )
        )

    @staticmethod
    def _name_of(serialized: Optional[dict], kwargs: dict, default: str) -> str:
        return (serialized or {}).get("name") or kwargs.get("name") or default

    # ---- tools -----------------------------------------------------------------------
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs):
        name = self._name_of(serialized, kwargs, "tool")
        self._remember(run_id, name, metadata)
        self._emit("tool_start", name, run_id, parent_run_id, self._ctx(metadata), {"input": safe(inputs if inputs is not None else input_str)})

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        name, ctx = self._recall(run_id)
        self._emit("tool_end", name, run_id, parent_run_id, ctx, {"output": safe(output)})

    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        name, ctx = self._recall(run_id)
        self._emit("tool_error", name, run_id, parent_run_id, ctx, {"error": safe(error)})

    # ---- models ----------------------------------------------------------------------
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        name = self._name_of(serialized, kwargs, "chat_model")
        self._remember(run_id, name, metadata)
        self._emit("llm_start", name, run_id, parent_run_id, self._ctx(metadata), {"messages": safe(messages)})

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        name = self._name_of(serialized, kwargs, "llm")
        self._remember(run_id, name, metadata)
        self._emit("llm_start", name, run_id, parent_run_id, self._ctx(metadata), {"prompts": safe(prompts)})

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        name, ctx = self._recall(run_id)
        outputs: list[Any] = []
        try:
            for generation_list in response.generations:
                for generation in generation_list:
                    message = getattr(generation, "message", None)
                    outputs.append(safe(message) if message is not None else safe(getattr(generation, "text", "")))
        except Exception:  # pragma: no cover - defensive
            outputs = [safe(response)]
        self._emit("llm_end", name, run_id, parent_run_id, ctx, {"generations": outputs})

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        name, ctx = self._recall(run_id)
        self._emit("llm_error", name, run_id, parent_run_id, ctx, {"error": safe(error)})

    # ---- chains (node runnables) ---------------------------------------------------------
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        name = self._name_of(serialized, kwargs, "chain")
        self._remember(run_id, name, metadata)
        ctx = self._ctx(metadata)
        if ctx[0] is None:
            return  # graph-level runnable; the debug stream is the record for it
        self._emit("chain_start", name, run_id, parent_run_id, ctx, {"inputs": safe(inputs)})

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        name, ctx = self._recall(run_id)
        if not ctx or ctx[0] is None:
            return
        self._emit("chain_end", name, run_id, parent_run_id, ctx, {"outputs": safe(outputs)})

    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        name, ctx = self._recall(run_id)
        if not ctx or ctx[0] is None:
            return
        self._emit("chain_error", name, run_id, parent_run_id, ctx, {"error": safe(error)})
