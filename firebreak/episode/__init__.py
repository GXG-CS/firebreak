"""Episode and turn structure over the recorded evidence.

    EpisodeGraph -> TurnGraph -> TaskRun -> Event

A projection layer: evidence (WRITE, READ, TRIGGER, DERIVED_FROM) is built by
`firebreak.provenance` and is not modified here. See `firebreak/episode/graph.py`.
"""

from firebreak.episode.graph import (
    CrossTurnLink,
    EpisodeGraph,
    TurnGraph,
    TurnSummary,
    is_internal,
)
from firebreak.episode.views import episode_diagram, render_episode_markdown, turn_diagram

__all__ = [
    "CrossTurnLink",
    "EpisodeGraph",
    "TurnGraph",
    "TurnSummary",
    "episode_diagram",
    "is_internal",
    "render_episode_markdown",
    "turn_diagram",
]
