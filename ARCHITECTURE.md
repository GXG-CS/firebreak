# Architecture

Current scope: LangGraph runtime → Capture → Trace → evidence → episode / turn structure.

```
EpisodeGraph
  └── TurnGraph
        └── TaskRun
              └── Event
```

`StateVersion` is a node inside a TurnGraph, not another level; raw events are details of a
TaskRun, not a graph of their own. A turn is a Firebreak-assigned analysis unit stamped by the
caller when the run is recorded — by convention one external interaction per `record()`, but the
recorder does not enforce it. `step` is LangGraph's thread-wide super-step counter, so a turn's
steps do not start at zero and one step can hold several task runs.

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
       grouping.py   task runs by recorded identity (task_id, else the checkpoint namespace),
                     safe when a super-step fans out and two tasks are in flight at once
       view.py       the capture read back, regrouped by turn and task execution
                  ▼
                Trace          an ordered list of Events + run metadata, one .jsonl file
                  ▼
   firebreak/provenance/  (evidence)
       capture.py    snapshot_checkpoints(): checkpoint records -> `checkpoint_fact` events
       graph.py      ProvenanceGraph: TaskRun -> StateVersion -> TaskRun, every relation with evidence
       render.py     .provenance.json and .provenance.txt
       mermaid.py    .provenance.md: data flow, state lineage and control flow, kept separate
                  ▼
            ProvenanceGraph     the evidence index: relations and where each came from
                  ▼
   firebreak/episode/  (structure, a projection: evidence is never modified here)
       graph.py      EpisodeGraph -> TurnGraph, turn-local slicing, CrossTurnLink
       views.py      .episode.md: the episode, and one diagram per turn
                  ▼
             EpisodeGraph
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

## Evidence

## Structure

`EpisodeGraph.from_trace` builds the evidence, then slices it: a task belongs to the turn stamped
on its events, a state version to the turn in which the checkpoint that first held it was
captured, and a relation is local to a turn when both of its ends are in it. A relation whose ends
straddle turns becomes a `CrossTurnLink`, recorded as outgoing on the turn it leaves and incoming
on the turn it enters, with the original relation kept whole. Nothing is dropped, and no turn has
to carry another turn's contents.

## Evidence

`ProvenanceGraph.from_trace` builds a bipartite graph: `TaskRunRef` for each real task execution,
`StateVersion` for each version of each channel, with `WRITE`, `READ`, `TRIGGER` and
`DERIVED_FROM` relations. Task identity comes from the trace; `pending_writes` proves where a task
ran, not whether it ran. See `docs/PROVENANCE.md` for the grounding of each relation.

## Supporting packages

`firebreak/injection/` applies controlled faults so a capture can contain a known bad value: fault
specs, wrappers for tools and node functions, and a record of exactly what each injection changed.
`firebreak/integrations/tau2_airline/` is the environment the canonical capture comes from.

An earlier line — an execution graph inferred from the static topology plus execution ordering,
with cascade detection and reporting on top of it — was removed once the recorded evidence made the
inference unnecessary. It is in the git history.
