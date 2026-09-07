#!/bin/bash
#SBATCH --job-name=fb_tau2
#SBATCH --partition=general-gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint="l40|a100"
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
#SBATCH --export=ALL
# Serve a local Qwen with vLLM (summer env, unchanged) and run tau2 airline episodes with the
# Firebreak LangGraph MAS: one clean run and one lookup-corruption run per task.
set -euo pipefail
REPO=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
VENV="${FIREBREAK_VENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/firebreak}"
VLLM_ENV="${VLLM_ENV:-/gpfs/scratchfs1/jhf24001/mca25001/env/marti}"
MODEL_PATH="${MODEL_PATH:-/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/before-September/models/Qwen2.5-7B-Instruct}"
MODEL_NAME="${MODEL_NAME:-qwen2.5-7b}"
MAX_TURNS="${MAX_TURNS:-20}"
TASKS="${TASKS:-39}"
PORT=$((20000 + SLURM_JOB_ID % 10000))
LOGD=$REPO/slurm/logs; mkdir -p "$LOGD/vllm" "$REPO/eval/results/tau2"

"$VLLM_ENV/bin/python" -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" --served-model-name "$MODEL_NAME" --port "$PORT" \
  --gpu-memory-utilization 0.90 --max-model-len 16384 --enforce-eager \
  --enable-auto-tool-choice --tool-call-parser hermes \
  > "$LOGD/vllm/${SLURM_JOB_ID}.log" 2>&1 &
VLLM_PID=$!
trap 'kill $VLLM_PID 2>/dev/null || true' EXIT
for i in $(seq 1 90); do
  curl -s "http://localhost:$PORT/v1/models" >/dev/null 2>&1 && break
  sleep 10
done
curl -s "http://localhost:$PORT/v1/models" | head -c 300; echo

source "$VENV/bin/activate"
cd "$REPO"
export OPENAI_BASE_URL="http://localhost:$PORT/v1" OPENAI_API_KEY=EMPTY FIREBREAK_MODEL="$MODEL_NAME"
for T in $TASKS; do
  echo "=== task $T clean ==="
  python -m firebreak.integrations.tau2_airline.runner --task "$T" --model openai \
    --max-turns "$MAX_TURNS" --out "eval/results/tau2/${MODEL_NAME}_task${T}_clean_${SLURM_JOB_ID}.jsonl" || true
  echo "=== task $T lookup corruption ==="
  python -m firebreak.integrations.tau2_airline.runner --task "$T" --model openai \
    --inject message_corruption:lookup:1:swap_first_eligible_reservation \
    --max-turns "$MAX_TURNS" --out "eval/results/tau2/${MODEL_NAME}_task${T}_fault_${SLURM_JOB_ID}.jsonl" || true
done
