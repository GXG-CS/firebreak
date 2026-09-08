# Roadmap

## Now: Capture and Reconstruction

The whole current scope is making one LangGraph run into provenance that can be checked line by
line:

```
LangGraph runtime -> Capture -> Trace -> Reconstruction -> .provenance.json / .provenance.txt
```

Done:

* Capture from all three runtime sources (debug/tasks stream, callbacks, checkpointer), at episode
  level, into a single offline `.jsonl`.
* Reconstruction into `TaskRun -> StateVersion -> TaskRun` with evidence on every relation.
* Observed and derived evidence kept apart; derivations checked against recorded element
  identities rather than assumed from the channel class.
* Task identity taken from the trace, not from who happened to write.

Open, in the order they matter:

* **Read the canonical example line by line.** Understand exactly what the stream, the callbacks
  and the checkpointer each report, before building anything on top.
* **Subgraphs.** `snapshot_checkpoints()` lists one checkpoint namespace. A real nested subgraph
  writes its own, so its provenance is currently incomplete. `langgraph_checkpoint_ns` is already
  captured.
* **Message-level provenance.** With a single `messages` channel every task reads and writes the
  same channel, so relations are coarse. Message ids are stable and both the writes and the task
  inputs are recorded, so this is set membership over captured data, not inference.
* **Other capture surfaces.** Other frameworks, and reading traces produced by OpenTelemetry or
  Langfuse instrumentation.

## Later, and currently frozen

Detection, propagation, cascade reporting, fault injection, containment. The code is in the tree
and still tested; none of it is being developed. Nothing should be built on the provenance layer
until the provenance layer is understood.
