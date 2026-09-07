# Benchmarks

Each directory holds a `scenario.yaml`:

```yaml
name: tool_failure
example: examples/multi_agent/research_team.py
model: fake
inject: ["tool_error:search_web"]
ground_truth:
  cascade: true                 # is there a fault to detect at all
  source_node: researcher       # node run where the fault entered
  source_tool: search_web       # optional
  path: [researcher, reviewer, planner, executor]   # node names the fault reached
  outcome: FAILED               # PASSED | FAILED
```

`python -m eval.run` replays every scenario and reports the metrics listed in `eval/metrics.py`.
Ground truth comes from the injection itself and from the example's known topology; nothing is
hand-labelled.
