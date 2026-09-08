#!/bin/bash
#SBATCH --job-name=fb_prov
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
# Re-run tau2 task 39 with checkpoint capture, then dump the observed provenance.
set -uo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
source "${FIREBREAK_VENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/firebreak}/bin/activate"
cd "$REPO"
export PYTHONWARNINGS="ignore::UserWarning"
OUT=${OUT:-slurm/logs/prov_fake_$SLURM_JOB_ID.jsonl}
echo "=== pytest ==="; pytest -q --no-header -p no:cacheprovider 2>&1 | tail -20
echo "=== re-run tau2 task 39 (fake) with checkpoint capture ==="
python -m firebreak.integrations.tau2_airline.runner --task 39 --model fake --out "$OUT" 2>&1 | tail -12
echo "=== provenance dump ==="
python scripts/dump_provenance.py "$OUT" --quiet
python scripts/dump_provenance.py "$OUT" 2>&1 | tail -80
