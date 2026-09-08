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
echo "=== tau2 task 39 (fake), capture only ==="; python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake --out slurm/logs/capture_$SLURM_JOB_ID.jsonl 2>&1 | tail -20
echo "=== episode / turn structure ==="; python scripts/dump_episode.py slurm/logs/capture_$SLURM_JOB_ID.jsonl --quiet
echo "=== evidence ==="; python scripts/dump_provenance.py slurm/logs/capture_$SLURM_JOB_ID.jsonl --quiet
echo "DONE"
