#!/bin/bash
#SBATCH --job-name=fb_case
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
# Render the Phase 1 views for the curated eval cases and the canonical example, from their
# captures. The .mmd files come from the dump scripts, so a checkout reproduces every output
# without this wrapper.
set -uo pipefail
source /gpfs/scratchfs1/jhf24001/mca25001/env/firebreak/bin/activate
cd /gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
export PYTHONWARNINGS="ignore::UserWarning"

# The tools of this domain that change the airline database. Declared here rather than inferred
# from the tool name, so the marking on the page is an input and not a guess.
TAU2_MUTATING="cancel_reservation,book_reservation,update_reservation_flights,update_reservation_baggages,update_reservation_passengers,send_certificate"

if [ "${RUN_TESTS:-1}" = "1" ]; then
  echo "===== tests ====="
  python -m pytest -q 2>&1 | tail -25
fi

for C in ${CASES:-eval/cases/task_1_fail eval/cases/task_0_pass}; do
  T="$C/trace.jsonl"
  E="$C/summary.json"
  echo "===== $T ====="
  python scripts/dump_episode.py    "$T" --json --eval "$E" --mutating-tools "$TAU2_MUTATING" --quiet \
    || echo "episode FAILED"
  python scripts/dump_provenance.py "$T" --eval "$E" --mutating-tools "$TAU2_MUTATING" --quiet \
    || echo "provenance FAILED"
  python scripts/dump_trace.py      "$T" --out || echo "capture FAILED"
  ls -la "$C"
done

if [ "${CANONICAL:-1}" = "1" ]; then
  echo "===== canonical example ====="
  T=docs/traces/tau2_task39_qwen14b_clean.jsonl
  python scripts/dump_trace.py      "$T" --out                                        || echo "capture FAILED"
  python scripts/dump_episode.py    "$T" --json --mutating-tools "$TAU2_MUTATING" --quiet || echo "episode FAILED"
  python scripts/dump_provenance.py "$T" --mutating-tools "$TAU2_MUTATING" --quiet        || echo "provenance FAILED"
  ls -la docs/traces
fi
