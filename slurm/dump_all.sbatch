#!/bin/bash
#SBATCH --job-name=fb_dump
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
# Regenerate every derived artifact of the canonical capture, from the capture itself.
set -uo pipefail
source /gpfs/scratchfs1/jhf24001/mca25001/env/firebreak/bin/activate
cd /gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
export PYTHONWARNINGS="ignore::UserWarning"
T=docs/traces/tau2_task39_qwen14b_clean.jsonl
python scripts/dump_trace.py "$T" --out
python scripts/dump_episode.py "$T" --json --quiet
python scripts/dump_provenance.py "$T" --quiet
