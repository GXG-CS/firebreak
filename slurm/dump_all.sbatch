#!/bin/bash
#SBATCH --job-name=fb_dump
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
set -uo pipefail
source /gpfs/scratchfs1/jhf24001/mca25001/env/firebreak/bin/activate
cd /gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
export PYTHONWARNINGS="ignore::UserWarning"
python scripts/dump_graph.py docs/traces/*.jsonl >/dev/null
python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_clean.jsonl --quiet
python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_lookup_corruption.jsonl --quiet
echo "=== CLEAN provenance ==="; cat docs/traces/tau2_task39_qwen14b_clean.provenance.txt
echo "=== CLEAN legacy audit ==="; cat docs/traces/tau2_task39_qwen14b_clean.legacy_audit.txt
