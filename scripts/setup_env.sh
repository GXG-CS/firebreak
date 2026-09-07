#!/bin/bash
# One-time environment setup on the UConn cluster (run on a login node; installs only).
# Usage: bash scripts/setup_env.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
module load python/3.12.5
python -m venv "$REPO/.venv"
source "$REPO/.venv/bin/activate"
pip install --upgrade pip
pip install -e "$REPO[dev,openai]"
python -c "import langgraph, langchain_core; print('ok: langgraph installed')"
