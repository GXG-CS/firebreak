# The canonical example

One run, three files. τ²-bench airline task 39, Supervisor + Lookup + Booking on LangGraph,
Qwen2.5-14B-Instruct served locally with vLLM. The task succeeds (τ² reward 1.00).

| file | stage | what it is |
|---|---|---|
| `tau2_task39_qwen14b_clean.jsonl` | Capture | the raw Firebreak trace: every runtime fact recorded during the run |
| `tau2_task39_qwen14b_clean.provenance.json` | Reconstruction | machine-readable provenance: tasks, state versions, relations, each with its evidence |
| `tau2_task39_qwen14b_clean.provenance.txt` | Reconstruction | the same, readable, plus what the model cannot express |

Regenerate the reconstruction from the capture:

```bash
python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_clean.jsonl
```

Earlier artifacts (the legacy execution-graph dumps, the legacy audit, the fault-injection run)
are in the git history and are not part of the current path.
