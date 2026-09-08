# Architecture

Current scope: LangGraph runtime → Capture → Trace → Reconstruction → provenance output.

```
             LangGraph runtime
   ┌──────────────┼───────────────┐
   │              │               │
debug/tasks    callbacks     checkpointer
   │              │               │
   └──────────────┼───────────────┘
                  ▼
     firebreak/tracing/  (Capture)
       events.py     Event, JSON-safe truncation, routing-channel test
       callbacks.py  tool / model / node-scoped events, attributed via langgraph_* metadata
       recorder.py   record(): runs the graph, merges both streams, snapshots the checkpointer
                  ▼
                Trace          an ordered list of Events + run metadata, one .jsonl file
                  ▼
   firebreak/provenance/  (Reconstruction)
       capture.py    snapshot_checkpoints(): checkpoint records -> `checkpoint_fact` events
       graph.py      ProvenanceGraph: TaskRun -> StateVersion -> TaskRun, every relation with evidence
       render.py     .provenance.json and .provenance.txt
                  ▼
            ProvenanceGraph
```

## Capture

Three runtime sources, merged into one ordered event list.

**Debug / tasks stream.** `graph.stream(..., stream_mode=["debug", "values"])` reports, per node
run, a `task` event (name, input state, trigger channels) and a `task_result` event (the writes as
`(channel, value)` pairs, plus any error), and a `checkpoint` event per super-step.

**Callbacks.** A `BaseCallbackHandler` on `config["callbacks"]` reports tool and model calls.
LangGraph stamps each run started inside a node with `langgraph_node`, `langgraph_step`,
`langgraph_triggers`, `langgraph_path` and `langgraph_checkpoint_ns`, which is how every call is
attributed to the node run that made it. The debug stream drops the last two as redundant, so the
callback path is the only source for them.

**Checkpointer.** After each invoke, `snapshot_checkpoints()` reads the thread's checkpoints and
appends one `checkpoint_fact` event each, holding `channel_versions`, `versions_seen`,
`updated_channels`, the `(task_id, channel, value-digest)` writes, the lineage, and element
identities for folding channels. `channel_values` is deliberately not stored: a full state snapshot
per step would make the trace grow quadratically.

A trace can hold one invoke or a whole episode of them on one thread. Every event carries
`episode_id`, `turn`, `invoke_id` and a globally increasing `seq`.

## Reconstruction

`ProvenanceGraph.from_trace` builds a bipartite graph: `TaskRunRef` for each real task execution,
`StateVersion` for each version of each channel, with `WRITE`, `READ`, `TRIGGER` and
`DERIVED_FROM` relations. Task identity comes from the trace; `pending_writes` proves where a task
ran, not whether it ran. See `docs/PROVENANCE.md` for the grounding of each relation.

## Not the current line

`firebreak/graph/` holds an earlier `ExecutionGraph` that links `A -> B` when the compiled graph
declares a static edge and `A` finished before `B` started. That is an inference over ordering, and
it is what the provenance layer replaces. It is retained because `detection/`, `reporting/` and
`runner.py` still use it. `injection/` and `integrations/` are the fault-injection and cascade work
built on top of it. All of it still runs and is still tested; none of it is the current focus.
