"""State provenance reconstructed from LangGraph's own runtime records.

Nothing here infers a dependency. Every relation is backed by a field LangGraph wrote down:
`pending_writes` (which task wrote which channel), `channel_versions` (the version that write
produced) and `versions_seen` (the version a node consumed). See `docs/PROVENANCE.md`.
"""

from firebreak.provenance.capture import CHECKPOINT_FACT, snapshot_checkpoints
from firebreak.provenance.graph import (
    Evidence,
    ProvenanceGraph,
    ReadRelation,
    StateVersion,
    TaskRunRef,
    WriteRelation,
)
from firebreak.provenance.mermaid import (
    control_flow,
    data_flow,
    render_markdown,
    state_lineage,
)
from firebreak.provenance.render import (
    compare_with_legacy,
    render_comparison,
    render_json,
    render_text,
)

__all__ = [
    "CHECKPOINT_FACT",
    "Evidence",
    "ProvenanceGraph",
    "ReadRelation",
    "StateVersion",
    "TaskRunRef",
    "WriteRelation",
    "compare_with_legacy",
    "control_flow",
    "data_flow",
    "render_comparison",
    "render_markdown",
    "state_lineage",
    "render_json",
    "render_text",
    "snapshot_checkpoints",
]
