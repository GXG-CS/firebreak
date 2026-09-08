#!/bin/bash
#SBATCH --job-name=fb_ep
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
set -uo pipefail
source /gpfs/scratchfs1/jhf24001/mca25001/env/firebreak/bin/activate
cd /gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak
export PYTHONWARNINGS="ignore::UserWarning"
T=docs/traces/tau2_task39_qwen14b_clean.jsonl
python - <<'PYEOF'
from firebreak.episode.graph import EpisodeGraph
from firebreak.tracing.recorder import Trace
ep = EpisodeGraph.from_trace(Trace.from_jsonl("docs/traces/tau2_task39_qwen14b_clean.jsonl"))
print("episode", ep.episode_id, "turns", ep.turn_numbers)
for g in ep:
    s = g.summary
    print(f"\nTURN {s.turn}  invokes={s.invoke_ids}  steps={s.steps}  events={s.event_count}  checkpoints={s.checkpoints}")
    print(f"  agent tasks   {[t.label for t in g.agent_task_runs]}")
    print(f"  internal      {[t.label for t in g.internal_task_runs]}")
    print(f"  states        {[f'{v.channel}:{v.version.split(chr(46))[0].lstrip(chr(48)) or chr(48)}' for v in g.state_versions]}")
    print(f"  local         W{len(g.writes)} R{len(g.reads)} T{len(g.triggers)} D{len(g.derived)}")
    print(f"  boundary      in={[(l.kind, l.from_turn) for l in g.incoming]}  out={[(l.kind, l.to_turn) for l in g.outgoing]}")
print("\ncross-turn links:")
for l in ep.cross_turn_links():
    print(" ", l.kind, l.from_turn, "->", l.to_turn, l.from_state_key and l.from_state_key.split(":")[0], getattr(l.relation, "verdict", ""))
print("\nchronological order:", ep.chronological_order())
print("warnings:", ep.warnings or "none")
PYEOF
python scripts/dump_episode.py "$T" --json --quiet
