#!/bin/bash
#SBATCH --job-name=fb_nat
#SBATCH --partition=general-gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint="a100|l40"
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --array=0-4
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%A_%a.log
#SBATCH --export=ALL
# Clean tau2 airline sweep: no fault injection, no framework changes.
# Each array shard serves its own vLLM and runs 10 tasks, so we can see how the
# LangGraph MAS fails on its own.
set -euo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
VENV="${FIREBREAK_VENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/firebreak}"
VLLM_ENV="${VLLM_ENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/marti}"
MODEL_PATH="${MODEL_PATH:-/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/before-September/models/Qwen2.5-14B-Instruct}"
MODEL_NAME="${MODEL_NAME:-qwen2.5-14b}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
MAX_TURNS="${MAX_TURNS:-15}"
SHARD_SIZE="${SHARD_SIZE:-10}"
RUN_TAG="${RUN_TAG:-natural_qwen14b}"

SHARD=${SLURM_ARRAY_TASK_ID:-0}
START=$((SHARD * SHARD_SIZE))
END=$((START + SHARD_SIZE - 1))
OUTDIR="$REPO/eval/results/$RUN_TAG/shard${SHARD}_${SLURM_ARRAY_JOB_ID:-$SLURM_JOB_ID}"
PORT=$((20000 + SLURM_JOB_ID % 10000))
LOGD=$REPO/slurm/logs
mkdir -p "$LOGD/vllm" "$OUTDIR"
echo "shard $SHARD -> tasks $START-$END, out=$OUTDIR, port=$PORT, node=$(hostname)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

"$VLLM_ENV/bin/python" -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" --served-model-name "$MODEL_NAME" --port "$PORT" \
  --gpu-memory-utilization 0.90 --max-model-len "$MAX_MODEL_LEN" --enforce-eager \
  --enable-auto-tool-choice --tool-call-parser hermes \
  > "$LOGD/vllm/${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null || true' EXIT

for i in $(seq 1 120); do
  curl -s "http://localhost:$PORT/v1/models" >/dev/null 2>&1 && break
  if ! kill -0 $VLLM_PID 2>/dev/null; then
    echo "vLLM died during startup; tail of its log:"; tail -40 "$LOGD/vllm/${SLURM_JOB_ID}.log"; exit 1
  fi
  sleep 10
done
curl -s "http://localhost:$PORT/v1/models" | head -c 200; echo

source "$VENV/bin/activate"
cd "$REPO"
export OPENAI_BASE_URL="http://localhost:$PORT/v1" OPENAI_API_KEY=EMPTY FIREBREAK_MODEL="$MODEL_NAME"
python scripts/run_natural.py --tasks "${START}-${END}" --model openai \
  --max-turns "$MAX_TURNS" --outdir "$OUTDIR"
