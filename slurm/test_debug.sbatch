#!/bin/bash
#SBATCH --job-name=fb_test
#SBATCH --partition=debug
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
# Fast smoke lane: the full test suite plus a regeneration of the canonical reconstruction.
set -uo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
source "${FIREBREAK_VENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/firebreak}/bin/activate"
cd "$REPO"
export PYTHONWARNINGS="ignore::UserWarning"
echo "=== pytest ==="; pytest -q --no-header -p no:cacheprovider 2>&1 | tail -40
echo "=== ruff ==="; ruff check firebreak tests eval examples scripts --exclude firebreak/integrations/tau2_airline/vendor --statistics 2>&1 | tail -8
echo "=== regenerate the canonical reconstruction ==="
python scripts/dump_provenance.py docs/traces/tau2_task39_qwen14b_clean.jsonl --quiet
git -C "$REPO" diff --stat -- docs/traces/ || true
echo "DONE"
