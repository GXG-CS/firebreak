# Architecture (v0.1)

Firebreak is a runtime observer for LangGraph. It never changes how the graph routes; it records
what happened, reconstructs dependencies, and (optionally) injects faults through wrappers that the
example or the user applies at build time.

```
                 +--------------------+
   graph.stream  |  LangGraph runtime |  callbacks (tool / model / chain events, node metadata)
  ─────────────▶ |  stream_mode=debug |  ────────────────────────────────────────────────┐
                 +--------------------+                                                  │
                          │ task / task_result / checkpoint                              │
                          ▼                                                              ▼
                 +--------------------+                                     +------------------------+
                 |  tracing.Trace     | ◀───────────────────────────────── |  tracing.FirebreakTracer|
                 |  ordered Events    |                                     +------------------------+
                 +--------------------+
                          │
                          ▼
                 +--------------------+      +--------------------+      +--------------------+
                 |  graph.Execution   | ───▶ |  detection.detect  | ───▶ |  reporting.Cascade |
                 |  Graph + propagate |      |  explicit signals  |      |  Report            |
                 +--------------------+      +--------------------+      +--------------------+
```

## 1. Capture (`firebreak/tracing`)

Two sources are merged into one ordered event list:

- `graph.stream(..., stream_mode=["debug", "values"])` gives, per node run: `task` (name, input
  state, trigger channels) and `task_result` (writes as `(channel, value)` pairs, error,
  interrupts), plus `checkpoint` events. This is the authoritative record of state flow.
- A `BaseCallbackHandler` attached through `config["callbacks"]` gives tool and model calls made
  inside a node. LangGraph stamps their metadata with `langgraph_node`, `langgraph_step`, and
  `langgraph_triggers`, so every tool/model event is attributed to the node run that made it.

Events are JSON-safe and truncated; a run can be saved with `Trace.to_jsonl` and re-analysed
offline with `firebreak report`.

## 2. Represent (`firebreak/graph`)

`ExecutionGraph.from_trace` builds one `NodeRun` per executed node instance (name, step, triggers,
writes, error, tool calls). The compiled graph's static edges are snapshotted at record time. A
data-flow edge `A -> B` exists when a static edge `A.name -> B.name` exists and `A` is the latest
run of that node that finished before `B` started. Edges carry the non-routing state keys `A`
wrote, which is what `B` could read from state. Fan-in (a join) yields several incoming edges;
nodes that ran in parallel in the same step never get an edge between them.

`propagate(graph, source)` does a breadth-first taint walk over these edges from the source node run
and returns affected runs, a path to each, and blast radius = affected / total node runs.

## 3. Inject (`firebreak/injection`)

`FaultPlan.parse("tool_error:search_web")` builds a plan. The plan hands out wrappers:

- `plan.tool(name)` decorates a tool function; on the chosen call it raises, returns bad output,
  or sleeps and times out.
- `plan.wrap_node(name, fn)` wraps a node function; it can corrupt the returned writes.

Every injection is recorded as an `injection` event in the trace, which is the ground truth the
evaluation compares against. Injection never touches LangGraph internals.

## 4. Detect (`firebreak/detection`)

Detectors only look for explicit signals: tool errors, timeouts, node errors, the injected
corruption marker in tool outputs or node writes, and user-supplied validators
(`{node_name: callable(writes) -> error | None}`). The earliest signal is the source.

## 5. Report (`firebreak/reporting`)

`CascadeReport` = source signal, propagation path, affected/total, blast radius, detection delay
(steps between the injection and the first signal), final outcome from the example's `evaluate`,
and wall time. Rendered as text (CLI) or JSON.

## Conventions for examples

An example module exposes `build(model: str = "fake", plan: FaultPlan | None = None) -> App` with
`App(graph, input, evaluate, validators)`. `evaluate(final_state) -> "PASSED" | "FAILED"`.

## Non-goals in v0.1

No routing changes, no retries, no quarantine, no LLM-as-judge, no hallucination detection.
