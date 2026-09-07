#!/bin/bash
#SBATCH --job-name=fb_test
#SBATCH --partition=debug
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
# Fast smoke lane: unit + milestone + tau2(fake) tests, CLI demos, benchmark runner. No GPU.
set -uo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
VENV="${FIREBREAK_VENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/firebreak}"
source "$VENV/bin/activate"
cd "$REPO"
export PYTHONWARNINGS="ignore::UserWarning"
echo "=== pytest ==="; pytest -q --no-header -p no:cacheprovider 2>&1 | tail -60
echo "=== CLI: research_team tool_error ==="; firebreak run examples/multi_agent/research_team.py --inject tool_error:search_web 2>&1 | tail -32
echo "=== tau2 task 39 clean (fake) ==="; python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake 2>&1 | tail -14
echo "=== tau2 task 39 lookup corruption (fake) ==="; python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake --inject message_corruption:lookup:1:swap_first_eligible_reservation --out slurm/logs/tau2_cascade_fake_$SLURM_JOB_ID.jsonl 2>&1 | tail -50
echo "=== benchmarks ==="; python -m eval.run 2>&1 | tail -22
echo "DONE"
