# Vendored: tau2 airline environment (via LangChain Deep Agents evals)

| | |
|---|---|
| Upstream project | `langchain-ai/deepagents`, path `libs/evals/tests/evals/tau2_airline/` |
| Upstream commit | `07d2952d346d81d06bd181db8c560a77f2b51bc8` (2026-09-06) |
| Original source | Sierra Research τ-bench / τ²-bench / τ³-bench (`sierra-research/tau2-bench`, dev/tau3 branch, task data v1.0.0) |
| License | MIT (see `LICENSE` in this directory; both upstreams are MIT) |
| Files taken verbatim | `domain.py`, `user_sim.py`, `data/db.json`, `data/policy.md`, `data/tasks.json`, `LICENSE` |
| Files modified | `evaluation.py`: two import lines rewritten from `tests.evals.tau2_airline.*` to `firebreak.integrations.tau2_airline.*` (no logic change) |
| Files not taken | `runner.py` (replaced by `../runner.py`, which drives the MAS per turn and records Firebreak traces), `test_tau2_airline.py` (LangSmith-specific) |

Everything under `vendor/` is third-party code. Firebreak's own integration code lives one
directory up (`mas.py`, `runner.py`). Do not edit vendored files except to update this table.
