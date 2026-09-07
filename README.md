# Firebreak

**Stop cascading failures in LangGraph multi-agent systems.**

```
pip install langgraph-firebreak
```

One agent fails. The failure travels through handoffs, shared state, and tool results until the
whole team is wrong and nobody can say where it started. Firebreak captures the LangGraph runtime,
rebuilds the actual execution and dependency graph, lets you inject faults on purpose, traces where
each fault went, and reports the blast radius.

```
Agent A fails
    ↓
failure propagates
    ↓
🔥 FIREBREAK 🔥
    ↓
downstream agents protected
```

## Quick start

```bash
firebreak run examples/multi_agent/research_team.py --inject tool_error:search_web
```

```
Cascade detected

Source
  researcher.search_web        tool_error  (step 1)

Propagation
  researcher
      ↓
  reviewer
      ↓
  planner
      ↓
  executor

Affected nodes: 4 / 5
Blast radius: 80%
Detection delay: 0 steps
Final task: FAILED
```

No API key is required for the examples: `--model fake` (the default) runs a deterministic scripted
team. Point `--model openai` at any OpenAI-compatible endpoint (vLLM, Ollama, OpenAI) with
`OPENAI_BASE_URL` / `OPENAI_API_KEY`.

## What v0.1 does

| Capability | What it means |
|---|---|
| **Capture** | Records every LangGraph node start/end, state write, trigger, tool call, and model call of a run into a JSONL trace |
| **Represent** | Rebuilds the real execution graph: which node run consumed which node run's writes |
| **Inject** | Injects tool errors, bad tool output, corrupted messages, bad node output, and timeouts at a chosen call |
| **Trace** | Follows a fault forward through the dependency graph to every node, state key, and tool call it reached |
| **Report** | Prints source, propagation path, affected nodes, blast radius, detection delay, and final task outcome |

v0.1 is **detection only**. It reports on explicit, checkable fault signals: tool exceptions,
timeouts, injected corruption, validator failures, and user-defined detectors. It does not claim to
detect hallucinations or semantic inconsistency. Mitigation, prevention, and semantic detectors come
later; see `docs/ROADMAP.md`.

## Evaluation from day one

`benchmarks/` holds scenarios with ground truth (injected source, true propagation path, expected
outcome). `python -m eval.run` replays them and reports cascade detection precision/recall, source
attribution accuracy, propagation path F1, blast radius error, detection delay, and runtime overhead.

## Layout

```
firebreak/            the library
  tracing/            capture LangGraph runtime events -> Trace (JSONL)
  graph/              execution / dependency graph, taint propagation
  injection/          fault plans and tool / node wrappers
  detection/          explicit fault-signal detectors
  reporting/          cascade report model + text / JSON rendering
  cli.py              `firebreak run`, `firebreak report`
examples/             runnable LangGraph systems (fake model by default)
benchmarks/           scenarios with ground truth
eval/                 metrics + runner
tests/                pytest
```

## Where Firebreak sits

LangChain ships single-point guardrails as middleware (tool-call limits, model fallback,
human-in-the-loop, PII detection). None of them watch a failure move *between* agents at runtime.
Firebreak works during the run, on the dependency graph the run actually produced.

## Status

v0.1.0 in development. See `ARCHITECTURE.md` and `docs/ROADMAP.md`.

## License

Apache-2.0.

Firebreak is an independent open-source project and is not affiliated with or endorsed by LangChain.
