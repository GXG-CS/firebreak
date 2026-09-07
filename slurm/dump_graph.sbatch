#!/bin/bash
#SBATCH --job-name=fb_graph
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
set -uo pipefail
source /gpfs/scratchfs1/jhf24001/mca25001/env/firebreak/bin/activate
cd /gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
export PYTHONWARNINGS="ignore::UserWarning"
python scripts/dump_graph.py docs/traces/tau2_task39_qwen14b_clean.jsonl docs/traces/tau2_task39_qwen14b_lookup_corruption.jsonl
