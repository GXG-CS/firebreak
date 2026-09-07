#!/bin/bash
#SBATCH --job-name=firebreak_test
#SBATCH --partition=general
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
# CPU-only: runs the unit tests, milestone-1 tests, the CLI demo and the benchmark runner
# with the fake model.  No GPU, no API key.
set -euo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
VENV="${FIREBREAK_VENV:-$REPO/.venv}"
source "$VENV/bin/activate"
cd "$REPO"
python -c "import langgraph, langchain_core; print('langgraph', langgraph.__version__ if hasattr(langgraph,'__version__') else '?', 'langchain-core', langchain_core.__version__)"
pytest -q
echo "=== CLI demo: clean run ==="
firebreak run examples/multi_agent/research_team.py
echo "=== CLI demo: tool_error:search_web ==="
firebreak run examples/multi_agent/research_team.py --inject tool_error:search_web --out slurm/logs/cascade_$SLURM_JOB_ID.jsonl --graph
echo "=== benchmarks ==="
python -m eval.run
