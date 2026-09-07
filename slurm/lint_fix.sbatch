#!/bin/bash
#SBATCH --job-name=fb_lint
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
set -uo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
source "${FIREBREAK_VENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/firebreak}/bin/activate"
cd "$REPO"
export PYTHONWARNINGS="ignore::UserWarning"
echo "=== ruff before ==="; ruff check firebreak tests eval examples --exclude firebreak/integrations/tau2_airline/vendor --statistics | tail -15
ruff check firebreak tests eval examples --exclude firebreak/integrations/tau2_airline/vendor --fix -q
echo "=== ruff after ==="; ruff check firebreak tests eval examples --exclude firebreak/integrations/tau2_airline/vendor --statistics | tail -15
echo "=== pytest after fix ==="; pytest -q --no-header -p no:cacheprovider 2>&1 | tail -5
