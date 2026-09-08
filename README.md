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
      Capture                   firebreak/tracing/   -> one Trace, a .jsonl file
         │
         ▼
   EpisodeGraph                 firebreak/episode/   -> .episode.md
     ├── TurnGraph 0
     ├── TurnGraph 1            each turn: its TaskRuns, its StateVersions, its relations
     └── TurnGraph 2
         │
         ▼
   later: detection
```

Underneath the structure, `firebreak/provenance/` holds the evidence: every relation and the field
it came from.

The stream, the callbacks and the checkpointer are LangGraph's and LangChain's own runtime
sources. Capture persists what they report into a trace that can be read offline, with no service
and no re-run. The episode layer projects that trace into structure.

A turn is a Firebreak-assigned analysis unit stamped when the run is recorded — by convention one
external interaction per `record()`, though nothing enforces it. `step` is LangGraph's thread-wide
super-step counter, so a turn's steps do not start at zero and one step can run several tasks.

## What the evidence says

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
firebreak trace docs/traces/tau2_task39_qwen14b_clean.jsonl        # read the capture
firebreak episode docs/traces/tau2_task39_qwen14b_clean.jsonl      # the episode / turn structure
firebreak provenance docs/traces/tau2_task39_qwen14b_clean.jsonl   # the evidence underneath
```

`trace` regroups the capture by turn and task execution and shows what each runtime source
reported about the same execution, keeping every event's original `seq`. `provenance` writes the
reconstruction beside the trace as `.provenance.json`, `.provenance.txt` and `.provenance.md`.

`episode` writes `.episode.md`, the structural view: the turns of the episode, the relations that
cross between them, and one diagram per turn.

```
EpisodeGraph
  └── TurnGraph
        └── TaskRun
              └── Event
```

`provenance` writes `.provenance.md` underneath it: three relation-level Mermaid diagrams, kept
apart because they answer different questions.

| diagram | relation | question |
|---|---|---|
| Data flow | `WRITE` / `READ` | which task produced the value another task was handed |
| State lineage | `DERIVED_FROM` | whether a later version of a channel still contains an earlier one |
| Control flow | `TRIGGER` | what caused each task to be scheduled |

The run behind the canonical example is τ²-bench airline task 39 with a Supervisor + Lookup +
Booking team on a local Qwen2.5-14B; see `docs/traces/README.md`.

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
  tracing/       Capture: events.py, callbacks.py, recorder.py, grouping.py, view.py
  provenance/    Evidence: capture.py, graph.py, render.py, mermaid.py
  episode/       Structure: graph.py (EpisodeGraph / TurnGraph), views.py
  cli.py         firebreak trace / episode / provenance
scripts/
  dump_trace.py, dump_episode.py, dump_provenance.py
docs/
  PROVENANCE.md  where every relation comes from
  traces/        the canonical example
```

`firebreak/injection/` applies controlled faults to a run, which is how a capture containing a
known bad value gets made. `firebreak/integrations/tau2_airline/` is the environment the canonical
capture comes from: a Supervisor + Lookup + Booking team on τ²-bench airline, with a real database
and an objective evaluator.

## Status

Pre-alpha. Current scope is Capture and the episode / turn structure over it. Detection comes
after that, and only once the structure is understood.

## License

Apache-2.0.

Firebreak is an independent open-source project and is not affiliated with or endorsed by LangChain.
