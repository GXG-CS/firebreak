#!/bin/bash
# Environment setup on the UConn cluster.
#
# Login nodes mount /gpfs/scratchfs1 with `noexec`, so a venv that lives on scratch can only be
# created and used on a compute node. Submit the SLURM wrapper instead of running this here:
#
#     sbatch slurm/setup_env.sbatch      # builds /gpfs/scratchfs1/jhf24001/mca25001/env/firebreak and runs the tests
#
# Base interpreter: the Python 3.12 from the existing vLLM env (env/marti). A wheelhouse for
# offline installs is kept at env/wheelhouse_firebreak (built on a login node with
# `python3 -m pip download --python-version 3.12 ...`).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
exec sbatch "$REPO/slurm/setup_env.sbatch"
