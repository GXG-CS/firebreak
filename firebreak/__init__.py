"""Firebreak: stop cascading failures in LangGraph multi-agent systems."""

from firebreak.detection.signals import Signal, detect, source_of
from firebreak.graph.execution import ExecutionGraph
from firebreak.graph.propagation import Propagation, propagate
from firebreak.injection.faults import DEFAULT_MARKER, Fault, FaultPlan
from firebreak.reporting.report import CascadeReport, build_report
from firebreak.runner import App, analyze, run_app
from firebreak.tracing.recorder import Trace, record

__version__ = "0.1.0.dev0"

__all__ = [
    "App",
    "CascadeReport",
    "DEFAULT_MARKER",
    "ExecutionGraph",
    "Fault",
    "FaultPlan",
    "Propagation",
    "Signal",
    "Trace",
    "analyze",
    "build_report",
    "detect",
    "propagate",
    "record",
    "run_app",
    "source_of",
]
