#!/bin/bash
#SBATCH --job-name=fb_views
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
set -uo pipefail
source /gpfs/scratchfs1/jhf24001/mca25001/env/firebreak/bin/activate
cd /gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
export PYTHONWARNINGS="ignore::UserWarning"
T=docs/traces/tau2_task39_qwen14b_clean.jsonl
python scripts/dump_trace.py "$T" --out
python scripts/dump_provenance.py "$T" --quiet
echo "=== capture view (first 90 lines) ==="; head -90 docs/traces/tau2_task39_qwen14b_clean.capture.txt
echo; echo "=== markdown ==="; cat docs/traces/tau2_task39_qwen14b_clean.provenance.md
