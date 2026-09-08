"""LEGACY. Forward taint propagation over the inferred execution graph.

Part of the earlier cascade work, built on `graph/execution.py`, whose edges are inferred from
ordering. Retained and tested, but not the current line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from firebreak.graph.execution import ExecutionGraph


@dataclass
class Propagation:
    source: str
    affected: list = field(default_factory=list)  # run ids in BFS order, source first
    paths: dict = field(default_factory=dict)  # run id -> list of run ids from source
    levels: dict = field(default_factory=dict)  # run id -> BFS depth
    total: int = 0

    @property
    def blast_radius(self) -> float:
        return len(self.affected) / self.total if self.total else 0.0


def propagate(graph: ExecutionGraph, source_run_id: str) -> Propagation:
    """Every node run reachable from ``source_run_id`` through data-flow edges."""
    result = Propagation(source=source_run_id, total=graph.total_runs)
    if graph.get(source_run_id) is None:
        return result
    queue = [source_run_id]
    result.paths[source_run_id] = [source_run_id]
    result.levels[source_run_id] = 0
    while queue:
        current = queue.pop(0)
        result.affected.append(current)
        for nxt in graph.successors(current):
            if nxt.id in result.paths:
                continue
            result.paths[nxt.id] = result.paths[current] + [nxt.id]
            result.levels[nxt.id] = result.levels[current] + 1
            queue.append(nxt.id)
    return result


def content_taint(graph: ExecutionGraph, marker: str) -> list[str]:
    """Run ids whose state writes or tool outputs contain ``marker`` (ground-truth helper)."""
    tainted: list[str] = []
    for run in sorted(graph.runs, key=lambda r: r.start_seq):
        blob = json.dumps(run.data_writes, default=str)
        blob += json.dumps([t.output for t in run.tools], default=str)
        if marker in blob:
            tainted.append(run.id)
    return tainted
