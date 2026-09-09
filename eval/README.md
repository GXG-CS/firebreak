# Natural τ² airline runs

Episodes of the Supervisor + Lookup + Booking LangGraph MAS on τ²-bench airline,
run with **no fault injection**. The point is to collect executions that the system
produced on its own, so later analysis works on natural behaviour rather than
planted faults.

For rendered examples of Firebreak's own output formats, see [`docs/traces/`](../docs/traces/).

## Setup

| | |
|---|---|
| Model | Qwen2.5-14B-Instruct, served locally with vLLM |
| Temperature | 0 |
| Context length | 16384 tokens |
| Max turns | 15 |
| User | τ² user simulator, same model and endpoint |
| Injection | none |
| Date of the batch below | 2026-09-09 |

## Reproduce

```bash
sbatch slurm/tau2_natural.sbatch            # 5 shards x 10 tasks, one vLLM per shard
```

or, against an already-running OpenAI-compatible endpoint:

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1 OPENAI_API_KEY=EMPTY FIREBREAK_MODEL=qwen2.5-14b
python scripts/run_natural.py --tasks 0-9 --outdir eval/results/myrun
python scripts/triage_natural.py eval/results/myrun
```

## Outcome categories

| | meaning |
|---|---|
| **PASS** | the episode ran to completion and the τ² evaluator scored it `db_score == 1` and `communicate_score == 1` |
| **FAIL** | the episode ran to completion and the evaluator scored it below that |
| **CRASH** | the episode did not complete — a Python exception, a context-length error, a killed process |

CRASH is a defect in the experiment, not a task failure, and is excluded from analysis.
Crashed episodes are still listed in the index so the exclusion is visible.

## The 2026-09-09 batch

50 tasks were planned; 37 were attempted before the run was stopped.

| | count | tasks |
|---|---|---|
| PASS | 8 | 0, 4, 5, 6, 10, 13, 43, 49 |
| FAIL | 27 | 1, 2, 3, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 30, 31, 40, 41, 42, 44, 45, 46, 47, 48 |
| CRASH | 2 | 23, 32 — both exceeded the 16384-token context |
| not run | 13 | 24–29, 33–39 |

`cases/index.jsonl` has one line per attempted episode: outcome, τ² scores, turn count,
how the episode terminated, the tools it called, and the recorded event counts. It carries
observable metadata only — no interpretation of why an episode failed.

The full raw results (every trace and summary) stay on the cluster under
`eval/results/`, which is not tracked in git.

## Cases

Two episodes are kept in full, as `trace.jsonl` (the Firebreak capture) and
`summary.json` (τ² scores, the whole transcript, and every tool call with its arguments).

| case | outcome | notes |
|---|---|---|
| [`cases/task_0_pass/`](cases/task_0_pass/) | PASS | episode completed normally, no injection |
| [`cases/task_1_fail/`](cases/task_1_fail/) | FAIL | episode completed normally, no injection |

Both tasks are cancellation scenarios of the same shape: the customer asks to cancel a
reservation, pushes back if refused, and does not want to proceed without a refund.
Task 0 expects no database action at all; task 1 expects two read actions and no write.
They are kept together as a pair because the task shape is held roughly constant while
the outcome differs.

Read a case with the CLI:

```bash
firebreak episode    eval/cases/task_1_fail/trace.jsonl --quiet
firebreak provenance eval/cases/task_1_fail/trace.jsonl --quiet
firebreak trace      eval/cases/task_1_fail/trace.jsonl
```
