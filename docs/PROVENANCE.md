# Observed state provenance

Firebreak reconstructs how data moved between agents from records LangGraph already keeps. No
relation in this layer is inferred from wall-clock time, from the static graph, or by a model.

## The model

Not `task -> task`, but a bipartite graph with the state artifact in the middle:

```
lookup@2  --WRITE-->  messages:v4  --READ-->  supervisor@3
```

The middle node matters. When two tasks write the same channel in one super-step, both are kept
as producers of that version rather than one being chosen as the cause:

```
taskA --WRITE--┐
               ├--> messages:v7 --READ--> supervisor@9
taskB --WRITE--┘
```

Entities: `TaskRunRef` (one real LangGraph task execution), `StateVersion` (one version of one
channel). Relations: `WriteRelation`, `ReadRelation` (kind `state` or `trigger`),
`DerivedRelation`.

## Where each relation comes from

| Relation | LangGraph record | Meaning |
|---|---|---|
| `TaskRun --WRITE--> StateVersion` | `CheckpointTuple.pending_writes`, a list of `(task_id, channel, value)`, paired with `channel_versions` in the following checkpoint | this task wrote this channel, producing this version |
| `StateVersion --READ--> TaskRun` (kind `state`) | `channel_versions` of the checkpoint the task was scheduled from, intersected with the channels the task's own recorded `input` carried | this version was in the state handed to the task |
| `StateVersion --TRIGGER--> TaskRun` (kind `trigger`) | `versions_seen[node][channel]`, diffed across the super-step | this version is what caused the task to be scheduled |
| `StateVersion --DERIVED_FROM--> StateVersion` | consecutive `channel_versions` of a channel whose class accumulates (`BinaryOperatorAggregate`, `Topic`, `DeltaChannel`) | the newer version contains the older one |

`versions_seen` is only stamped for a task's *trigger* channels (`pregel/_algo.py`, "update seen
versions"). In a `StateGraph` those are the routing channels (`branch:to:lookup`), so the trigger
relation is never the data path. That is why the two kinds of read are kept apart.

`versions_seen` is keyed by node *name*, not task id. Within one super-step the mapping back to a
task is still exact, because the tasks of that step are precisely the ones named in that
checkpoint's `pending_writes`. If two tasks of the same node ran in one step, both are recorded as
candidates rather than one being picked.

## Capture

`record()` calls `snapshot_checkpoints()` after each invoke. It appends a `checkpoint_fact` event
per checkpoint of the thread, holding `channel_versions`, `versions_seen`, `updated_channels`, the
`(task_id, channel, value-digest)` writes, and the checkpoint lineage. Checkpoints are immutable
and keyed by id, so calling it once per turn simply adds the new ones.

`channel_values` is deliberately not stored: it is a full state snapshot per step and would make a
trace grow quadratically. Write values are reduced to a sha1 and a 200-character preview; the full
values are already in the `node_end` writes.

## Using it

```bash
python scripts/dump_provenance.py <trace>.jsonl
```

writes `<trace>.provenance.json`, `<trace>.provenance.txt` and `<trace>.legacy_audit.txt`.

## What it cannot say

* **Per channel, not per message.** With one `messages` channel and an `add_messages` reducer,
  every task reads and writes the same channel. A relation means "this task read the state version
  that included that task's write", not "this task read that message". Message-level provenance is
  also derivable from records (`add_messages` gives stable message ids, and both the writes and the
  task inputs are captured), and is the natural next step.
* **A data path, not a cause.** Nothing here claims the consumer used what the producer wrote.
* **Accumulation is transitive.** On an accumulating channel every earlier version is contained in
  every later one, so the task-level view of such a channel approaches a transitive closure. That
  is a true property of the channel, not an artefact, but it is coarse.

## The heuristic this replaces

`ExecutionGraph._build_edges` links `A -> B` when the compiled graph declares a static edge
`A.name -> B.name` and `A`'s run finished before `B`'s started. It is kept as a legacy baseline for
the audit and is still what detection and reporting use. `scripts/dump_provenance.py` writes the
audit that checks each of its edges against the recorded relations.
