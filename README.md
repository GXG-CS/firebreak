# Firebreak

**Turn a LangGraph run into provenance you can check, not a graph you have to trust.**

```
pip install langgraph-firebreak
```

When several agents share state, the question that matters is which task produced the value
another task acted on. Most tools answer it after the fact, by reading a text trace and guessing.
LangGraph already writes the answer down. Firebreak captures those records and materialises them.

```
LangGraph runtime
   │
   ├─ debug / tasks stream      node runs, their triggers, the channels they wrote
   ├─ callbacks                 tool and model calls, attributed to the node that made them
   └─ checkpointer              channel versions, versions seen, per-task writes, lineage
         │
         ▼
      Capture                   firebreak/tracing/  -> one Trace, a .jsonl file
         │
         ▼
   Reconstruction               firebreak/provenance/  -> ProvenanceGraph
         │
         ▼
   .provenance.json / .provenance.txt
```

The stream, the callbacks and the checkpointer are LangGraph's and LangChain's own runtime
sources. Capture persists what they report into a trace that can be analysed offline, with no
service and no re-run. Reconstruction turns that trace into provenance.

## What the provenance says

Not `task -> task`, but the state artifact in the middle, so two tasks writing the same version
stay two producers instead of one being picked as the cause:

```
lookup@5  --WRITE-->  messages:v7  --READ-->  supervisor@6
```

Every relation carries the field it came from, and the two evidence classes are never mixed:

* **observed** — WRITE, READ and TRIGGER. Each is a field LangGraph wrote down.
* **derived** — DERIVED_FROM between consecutive versions of a folding channel. Folding is not
  retention, so each one is checked against element identities recorded per version and comes out
  `verified`, `refuted` or `unverified`.

`docs/PROVENANCE.md` states where each relation comes from and what the model cannot express yet.

## Try it

```bash
python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_clean.jsonl
```

That reads the canonical capture in `docs/traces/` and writes the reconstruction beside it. The
run behind it is τ²-bench airline task 39 with a Supervisor + Lookup + Booking team on a local
Qwen2.5-14B; see `docs/traces/README.md`.

To capture a run of your own, record it instead of invoking it:

```python
from firebreak.tracing.recorder import Trace, record

trace = Trace()
record(graph, {"messages": [...]}, trace=trace, thread_id="t", turn=0)   # once per turn
trace.to_jsonl("run.jsonl")
```

The graph must be compiled with a checkpointer; that is where the provenance lives.

## Layout

```
firebreak/
  tracing/       Capture: events.py, callbacks.py, recorder.py
  provenance/    Reconstruction: capture.py, graph.py, render.py
scripts/
  dump_provenance.py
docs/
  PROVENANCE.md  where every relation comes from
  traces/        the canonical example
```

Everything else in the tree (`firebreak/graph/`, `detection/`, `injection/`, `reporting/`,
`integrations/`) is earlier experimental work: an execution graph built from the static topology
plus execution ordering, fault injection, and cascade reporting on top of it. It still runs and is
still tested, but it is not the current line and it is not what the provenance layer uses.

## Status

Pre-alpha. Current scope is Capture and Reconstruction only.

## License

Apache-2.0.

Firebreak is an independent open-source project and is not affiliated with or endorsed by LangChain.
