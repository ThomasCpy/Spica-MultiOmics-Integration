"""The stand-in that runs when no model is installed.

It follows the real protocol. The orchestrator writes a PLAN line and a
TOOL call. The tool agent condenses the output. The writer gives an answer
that the verifier can check. The loop, the schematic, the streamed thoughts
and the rewind thus all work on a machine without model weights.

It cannot reason, and the run header says so: the backend chip shows
"No model (scripted)", not a model name.
"""

from __future__ import annotations

import re
from typing import Iterator

from spica.agents.llm import Scripted

MOVES = (
    'PLAN: what the documents say; what the record says\n'
    'TOOL: documents("the question")',
    'PLAN: what the record says\nTOOL: record("PCSK9")',
    "PLAN:\nDONE",
)

ORCHESTRATOR_THOUGHT = (
    "No model is loaded, so this trace is scripted. A real orchestrator "
    "would read the newest note here, drop the goals it settled, and pick "
    "the move that adds the most."
)

ANSWER = (
    "This answer is scripted, not reasoned: no model is loaded.\n\n"
    "## What a real answer would do\n"
    "Each claim would carry the citation the tool returned it with, and the "
    "verifier would check every one against the notes.\n\n"
    "## What this is not\n"
    "Install a model to replace this with a real answer."
)


class Demo(Scripted):
    """Scripted, but it plays the moves in order so the loop terminates."""

    label = "No model (scripted)"

    def __init__(self) -> None:
        super().__init__(replies={
            # The tool agent condenses; it keeps whatever citation it was
            # shown, so the scripted note stays checkable.
            "turn raw output into short factual notes": (
                "",
                "The scripted stand-in returned this line instead of a note.",
            ),
            "answer a question from notes": (
                "Scripted again. A writer would arrange the notes into an "
                "argument and say plainly what they do not support.",
                ANSWER,
            ),
        })
        self.moves = list(MOVES)

    def stream(self, prompt: str, **kw) -> Iterator[tuple[str, str]]:
        if "gathering evidence, one step at a time" in prompt:
            self.calls.append(prompt)
            reply = self.moves.pop(0) if self.moves else "DONE"
            for piece in re.findall(r"\S+\s*", ORCHESTRATOR_THOUGHT):
                yield "reasoning", piece
            for piece in re.findall(r"\S+\s*", reply):
                yield "answer", piece
            return
        yield from super().stream(prompt, **kw)
