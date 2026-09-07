#!/bin/bash
#SBATCH --job-name=fb_setup
#SBATCH --partition=debug
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:25:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
# Build the Firebreak venv on a compute node (login nodes mount scratch noexec) and run the
# full CPU test suite in the same job.
set -uo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
VENV="${FIREBREAK_VENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/firebreak}"
BASE_PY="${BASE_PY:-/gpfs/scratchfs1/jhf24001/mca25001/env/marti/bin/python3.12}"
WHEELS=/gpfs/scratchfs1/jhf24001/mca25001/env/wheelhouse_firebreak
echo "host $(hostname); base python: $($BASE_PY --version)"
rm -rf "$VENV"
"$BASE_PY" -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install -q --upgrade pip
# offline wheelhouse first (fast, deterministic), then online for anything missing
python -m pip install -q --no-index --find-links "$WHEELS" "langgraph>=1.2,<2" "langchain-core>=1.6,<2" "langchain-openai>=1.6,<2" "pyyaml>=6" "pytest>=8" "ruff>=0.6" hatchling 2>&1 | tail -2 || true
python -m pip install -q -e "$REPO[dev,openai]" 2>&1 | tail -3
python - <<'PY'
import langgraph, langchain_core, langchain_openai, importlib.metadata as m
print("langgraph", m.version("langgraph"), "| langchain-core", m.version("langchain-core"), "| langchain-openai", m.version("langchain-openai"), "| openai", m.version("openai"))
PY
cd "$REPO"
echo "=== ruff ==="; ruff check firebreak tests eval examples --exclude firebreak/integrations/tau2_airline/vendor | tail -5
echo "=== pytest ==="; pytest -q -x --no-header -p no:cacheprovider 2>&1 | tail -40
echo "=== CLI: research_team clean ==="; firebreak run examples/multi_agent/research_team.py 2>&1 | tail -12
echo "=== CLI: research_team tool_error ==="; firebreak run examples/multi_agent/research_team.py --inject tool_error:search_web 2>&1 | tail -30
echo "=== tau2 task 39 clean (fake) ==="; python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake 2>&1 | tail -25
echo "=== tau2 task 39 lookup corruption (fake) ==="; python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake --inject message_corruption:lookup:1:swap_first_eligible_reservation --out slurm/logs/tau2_cascade_fake_$SLURM_JOB_ID.jsonl 2>&1 | tail -45
echo "=== benchmarks ==="; python -m eval.run 2>&1 | tail -25
echo "DONE"
