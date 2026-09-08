"""Firebreak: capture a LangGraph run and rebuild its structure from LangGraph's own records.

    LangGraph runtime -> Capture -> Trace -> EpisodeGraph -> TurnGraph -> TaskRun -> Event
"""

from firebreak.episode.graph import CrossTurnLink, EpisodeGraph, TurnGraph, TurnSummary
from firebreak.injection.faults import DEFAULT_MARKER, Fault, FaultPlan
from firebreak.provenance.graph import ProvenanceGraph, StateVersion, TaskRunRef
from firebreak.tracing.grouping import group_by_task_run
from firebreak.tracing.recorder import Trace, record

__version__ = "0.2.0.dev0"

__all__ = [
    "DEFAULT_MARKER",
    "CrossTurnLink",
    "EpisodeGraph",
    "Fault",
    "FaultPlan",
    "ProvenanceGraph",
    "StateVersion",
    "TaskRunRef",
    "Trace",
    "TurnGraph",
    "TurnSummary",
    "group_by_task_run",
    "record",
]
