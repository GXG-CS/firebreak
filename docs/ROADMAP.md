# Roadmap

## v0.1 — Detection only

Five capabilities, nothing else: Capture, Represent, Inject, Trace, Report.

Supported fault signals (explicit and checkable):

- tool exception
- timeout
- node exception
- injected corruption marker (from Firebreak's own injector)
- validator failure (user-defined `callable(writes) -> error | None`)
- user-defined detector

Injectable faults: `tool_error`, `tool_bad_output`, `node_bad_output`, `message_corruption`,
`timeout`.

Metrics (computed by `eval/run.py` on `benchmarks/`): cascade detection precision / recall, source
attribution accuracy, propagation path F1, blast radius error, detection delay, runtime overhead.

Explicit non-goals: hallucination detection, semantic inconsistency, LLM-as-judge, uncertainty,
provenance-carrying state, mitigation, prevention.

Milestone 1 (this): a minimal LangGraph multi-agent system + fault injection, and one complete
captured cascade trace with a correct report.

## Later

- Semantic signals: conflicting results between parallel agents, schema drift, LLM-as-judge.
- Provenance-carrying state (reducers that tag every write with its origin).
- Containment: quarantine a node run's writes, re-dispatch, escalate via `interrupt()`.
- Exporters: Langfuse / LangSmith spans with cascade annotations.
- More systems: supervisor, swarm/handoff, deep-agents style subagents.
