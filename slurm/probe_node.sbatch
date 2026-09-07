#!/bin/bash
#SBATCH --job-name=fb_probe
#SBATCH --partition=debug
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --output=/gpfs/scratchfs1/jhf24001/mca25001/mas_safety/firebreak/slurm/logs/%x_%j.log
echo "host: $(hostname)  $(cat /etc/redhat-release 2>/dev/null)"
echo "--- scratchfs mount flags ---"; mount | grep " /gpfs/scratchfs1 " | sed 's/.*type wekafs (\(.*\)).*/\1/'
echo "--- exec tests ---"
/gpfs/scratchfs1/jhf24001/mca25001/env/marti/bin/python --version 2>&1
ls -la /gpfs/software/RHEL8/python/3.12.5/bin/python3.12 2>&1 | head -1
/gpfs/software/RHEL8/python/3.12.5/bin/python3.12 --version 2>&1
echo "--- module python ---"; module avail python 2>&1 | tr ' ' '\n' | grep -i python | head -8
module load python/3.12.5 2>&1 | head -1; python --version 2>&1; which python 2>&1
echo "--- internet ---"
curl -s -o /dev/null -m 10 -w 'pypi %{http_code}\n' https://pypi.org/simple/langgraph/ || echo "pypi unreachable"
curl -s -o /dev/null -m 10 -w 'github %{http_code}\n' https://github.com || echo "github unreachable"
echo "--- gpu? ---"; nvidia-smi -L 2>/dev/null | head -2 || echo "no gpu on this node"
