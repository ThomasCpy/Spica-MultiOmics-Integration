"""The agent layer: a local model that answers questions with tools.

Four stages, three with a model and the last one in code:

    orchestrator  reads the notes and picks the next tool calls
    tool agent    runs the calls and condenses the output into a note
    writer        answers the question from the notes, with citations
    verifier      checks each citation against the tool output, in code

Each step starts from a saved state, so each step is reproducible. This
makes `Run.rollback_to` sound: it restores a checkpoint, and the pipeline
finds the next step from the state, not from a script.
"""

from __future__ import annotations

from spica.agents.run import STAGE_LABELS, STAGES, Note, Run, State
from spica.agents.session import Agents, choose_backend
from spica.agents.verify import verify

__all__ = [
    "Agents",
    "Note",
    "Run",
    "STAGES",
    "STAGE_LABELS",
    "State",
    "choose_backend",
    "verify",
]
