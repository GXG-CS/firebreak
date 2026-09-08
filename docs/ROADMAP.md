# Roadmap

## Now: Capture, and the episode / turn structure over it

The whole current scope is making one LangGraph run into provenance that can be checked line by
line:

```
LangGraph runtime -> Capture -> Trace -> EpisodeGraph -> TurnGraph -> TaskRun -> Event
```

Done:

* Capture from all three runtime sources (debug/tasks stream, callbacks, checkpointer), at episode
  level, into a single offline `.jsonl`.
* Evidence as `TaskRun -> StateVersion -> TaskRun`, with the field each relation came from.
* Observed and derived evidence kept apart; derivations checked against recorded element
  identities rather than assumed from the channel class.
* Task identity taken from the trace, not from who happened to write.
* An explicit hierarchy over the evidence: `EpisodeGraph -> TurnGraph -> TaskRun -> Event`, with
  turn-local slicing and cross-turn relations preserved at the boundary.
* Task-run grouping by recorded identity, correct when a super-step fans out, including the
  same node running several times in one super-step via `Send`.

Supported but not yet integration-validated: `write`, `read` and `trigger` relations crossing a
turn boundary. Only `derived_from` has been observed crossing, because every invoke begins by
writing its input, so a task always reads a version produced in its own turn. An
`interrupt` / `Command(resume=...)` run is the case expected to produce the others.

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

## Later

Detection, propagation, containment. Nothing should be built on this layer until the layer itself
is understood, so none of it is being developed. The earlier attempt — an execution graph inferred
from the static topology plus execution ordering, with cascade detection and reporting on it — was
removed from the tree once the recorded evidence made the inference unnecessary; it is in the git
history. Controlled fault injection stays, because that is how a capture with a known bad value
gets made.
