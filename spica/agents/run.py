"""A run: the steps, the thoughts during each step, and the way back.

The structure comes from Betelgeuse: an append-only list, written to disk
as it grows. An interrupted, cancelled or killed run thus keeps all its
data on disk. This version adds two things.

**A checkpoint on each step.** Each step stores the state of the pipeline
*before* the step ran. A rollback restores that state and continues from
it. This is well defined: the inputs stay fixed for the run, so the same
state gives the same next step.

**No deletion.** Rolled-back steps move to `history`. A run that took a bad
path thus still shows it. A step keeps its seed, so a retry with a new seed
is a different attempt, not a repeat of the failed one.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spica.paths import data_dir

# The four roles. The first two are a loop: the orchestrator picks one move,
# the tool agent runs it and files a note, and the orchestrator reads that
# note before picking the next. A run therefore has as many steps as it took
# cycles, plus the two that close it.
STAGES = ("orchestrate", "tool", "write", "verify")
STAGE_LABELS = {
    "orchestrate": "Orchestrator",
    "tool": "Tool agent",
    "write": "Writer",
    "verify": "Verifier",
}
LOOPING = ("orchestrate", "tool")

RUNS_DIRNAME = "runs"
FLUSH_SECONDS = 0.5  # while a step streams; every boundary flushes anyway


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Note:
    """One fact that the tool agent found, and its origin.

    `tool` and `argument` are the move that produced it. The notes thus
    record what was done, and a repeat is detectable. `fields` holds the
    citations that the tool vouched for. `sources` holds the tool output, so
    a number in the answer is checked against the output, not the note.
    """

    tool: str
    tool_label: str
    text: str
    argument: str = ""
    fields: list[str] = field(default_factory=list)
    sources: str = ""
    # The move it came from: one move can call several tools at once, and
    # each call leaves its own note with the same batch number.
    batch: int = 0


@dataclass
class State:
    """Everything the pipeline knows. A checkpoint is a copy of this."""

    plan: list[str] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    # The move the orchestrator chose and the tool agent has not yet run.
    # Part of the state so that rewinding to a tool step re-runs that tool,
    # rather than sending the orchestrator back to choose again.
    pending: str = ""
    # The orchestrator has said DONE. Its own flag rather than an empty
    # plan, which it may legitimately write at any point in the loop.
    closed: bool = False
    draft: str = ""
    verdict: dict[str, Any] | None = None

    def copy(self) -> "State":
        return State(
            plan=list(self.plan),
            notes=[Note(n.tool, n.tool_label, n.text, n.argument, list(n.fields), n.sources)
                   for n in self.notes],
            pending=self.pending,
            closed=self.closed,
            draft=self.draft,
            verdict=None if self.verdict is None else dict(self.verdict),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": list(self.plan),
            "notes": [asdict(note) for note in self.notes],
            "pending": self.pending,
            "closed": self.closed,
            "draft": self.draft,
            "verdict": self.verdict,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "State":
        return cls(
            plan=list(raw.get("plan") or []),
            notes=[Note(**note) for note in (raw.get("notes") or [])],
            pending=raw.get("pending", ""),
            closed=bool(raw.get("closed")),
            draft=raw.get("draft", ""),
            verdict=raw.get("verdict"),
        )


@dataclass
class Step:
    index: int
    stage: str
    title: str
    status: str = "running"  # running | done | failed | cancelled
    cycle: int = 0  # which turn of the loop this belongs to
    tool: str = ""  # the source the tool agent read, e.g. "gtex"
    tool_label: str = ""  # as the record names it, e.g. "GTEx"
    thought: str = ""  # the reasoning trace, streamed
    output: str = ""  # what the agent decided, streamed
    seed: int = 0
    started: str = ""
    finished: str = ""
    error: str = ""
    state_before: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stage_label"] = STAGE_LABELS.get(self.stage, self.stage)
        return payload


class Run:
    """One pass of the loop over one question. Safe to read from another thread."""

    def __init__(self, question: str, backend: str,
                 root: Path | None = None,
                 tools: list[dict[str, Any]] | None = None,
                 thinking: bool = True) -> None:
        self.id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.question = question
        self.backend = backend
        # Whether the planner and the writer reason before answering.
        self.thinking = thinking
        # The moves available in this run, so the interface can draw them
        # and show which one each cycle fired.
        self.tools = tools or []
        self.created = _now()
        self.status = "running"  # running | paused | done | failed | cancelled
        self.steps: list[Step] = []
        self.history: list[Step] = []  # rolled back, kept
        self.state = State()
        self.error = ""
        self.version = 0  # bumped on every change, so the interface can poll

        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._last_flush = 0.0
        self.root = (root or data_dir()) / RUNS_DIRNAME
        self.path = self.root / f"{self.id}.json"

    # -- steps --------------------------------------------------------------

    def begin(self, stage: str, title: str, seed: int, cycle: int = 0,
              tool: str = "", tool_label: str = "") -> Step:
        with self._lock:
            step = Step(
                index=len(self.steps),
                stage=stage,
                title=title,
                seed=seed,
                cycle=cycle,
                tool=tool,
                tool_label=tool_label,
                started=_now(),
                state_before=self.state.to_dict(),
            )
            self.steps.append(step)
            self._touch()
            self.flush()
            return step

    def append(self, kind: str, text: str) -> None:
        """Add a streamed chunk to the step in flight."""
        with self._lock:
            if not self.steps:
                return
            step = self.steps[-1]
            if kind == "reasoning":
                step.thought += text
            else:
                step.output += text
            self._touch()
        # Flushing every token would write megabytes for one run; this keeps a
        # crash to at most half a second of lost thinking.
        if time.monotonic() - self._last_flush > FLUSH_SECONDS:
            self.flush()

    def finish(self, output: str | None = None) -> None:
        with self._lock:
            if not self.steps:
                return
            step = self.steps[-1]
            if output is not None:
                step.output = output
            step.status = "done"
            step.finished = _now()
            self._touch()
            self.flush()

    def fail(self, message: str) -> None:
        with self._lock:
            if self.steps:
                step = self.steps[-1]
                step.status = "failed"
                step.error = message
                step.finished = _now()
            self.status = "failed"
            self.error = message
            self._touch()
            self.flush()

    # -- going back ---------------------------------------------------------

    def rollback_to(self, index: int) -> str:
        """Discard all steps after `index` and restore its start state.

        The step at `index` is also discarded. A rollback *to* a step goes
        back to the state before that step ran. Only this reading allows a
        retry of a failed step. Returns "" or the reason for a refusal.
        """
        with self._lock:
            if self.status == "running":
                return "The run is still going. Stop it before rolling back."
            if not (0 <= index < len(self.steps)):
                return f"No step {index}."

            removed = self.steps[index:]
            self.state = State.from_dict(removed[0].state_before)
            for step in removed:
                if step.status == "running":
                    step.status = "cancelled"
            self.history.extend(removed)
            self.steps = self.steps[:index]
            self.status = "paused"
            self.error = ""
            self._touch()
            self.flush()
            return ""

    # -- lifecycle ----------------------------------------------------------

    def cancel(self) -> None:
        with self._lock:
            self._cancel.set()
            if self.status == "running":
                self.status = "cancelled"
                if self.steps and self.steps[-1].status == "running":
                    self.steps[-1].status = "cancelled"
                    self.steps[-1].finished = _now()
            self._touch()
            self.flush()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def resuming(self) -> None:
        with self._lock:
            self._cancel.clear()
            self.status = "running"
            self.error = ""
            self._touch()

    def done(self) -> None:
        with self._lock:
            if self.status == "running":
                self.status = "done"
            self._touch()
            self.flush()

    # -- reading it ---------------------------------------------------------

    def _touch(self) -> None:
        self.version += 1

    def snapshot(self) -> dict[str, Any]:
        """The whole run as plain data, consistent at one instant."""
        with self._lock:
            return {
                "id": self.id,
                "question": self.question,
                "status": self.status,
                "backend": self.backend,
                "thinking": self.thinking,
                "created": self.created,
                "error": self.error,
                "version": self.version,
                "stages": list(STAGES),
                "stage_labels": dict(STAGE_LABELS),
                "current_stage": self.steps[-1].stage if self.steps else "",
                "cycle": self.steps[-1].cycle if self.steps else 0,
                "looping": list(LOOPING),
                "tools": list(self.tools),
                "read": [note.tool for note in self.state.notes],
                "steps": [step.to_dict() for step in self.steps],
                "history": [step.to_dict() for step in self.history],
                "state": self.state.to_dict(),
            }

    def flush(self) -> None:
        """Write the run out. A few KB, so the whole thing goes every time."""
        with self._lock:
            payload = self.snapshot()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            self._last_flush = time.monotonic()
        except OSError:
            # A run that cannot be saved is still a run worth finishing.
            pass
