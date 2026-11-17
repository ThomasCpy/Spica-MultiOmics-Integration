"""Active runs: start, watch, stop, roll back.

One object owns all runs of this process. The interface never touches a
`Run` directly: it polls a snapshot and sends commands. The threading thus
stays in one place. A run executes on its own thread, and each read goes
through the lock of the run.

The backend is chosen once, at the first run, and then reused. A quantised
model takes seconds to load, and a large one most of a minute. The load
thus happens on the worker thread, with the run already visible. The click
that started it does not block.
"""

from __future__ import annotations

import threading
from typing import Any

from spica.agents import llm, pipeline
from spica.agents.demo import Demo
from spica.agents.run import Run
from spica.agents.tools import default_tools

def choose_backend() -> tuple[Any, str]:
    """The model if there is one, otherwise the stand-in. Never raises.

    Falling back rather than refusing is deliberate: the agent panel should
    be usable on a machine with no weights, and the label says plainly which
    of the two is running.
    """
    path = llm.model_path()
    if path is None:
        return Demo(), f"No model found in {llm.models_dir_hint()}"
    try:
        backend = llm.Llama(path)
        return backend, ""
    except llm.ModelMissing as exc:
        return Demo(), str(exc)
    except Exception as exc:  # a bad GGUF should not take the app with it
        return Demo(), f"{path.name} did not load: {exc}"


class Agents:
    """Every run this process knows about."""

    def __init__(self, tools=None) -> None:
        self._runs: dict[str, Run] = {}
        self._tools = tools if tools is not None else default_tools()
        self._threads: dict[str, threading.Thread] = {}
        self._backend: Any = None
        self._backend_note = ""
        self._lock = threading.Lock()

    # -- the model ----------------------------------------------------------

    def backend(self) -> tuple[Any, str]:
        with self._lock:
            if self._backend is None:
                self._backend, self._backend_note = choose_backend()
            return self._backend, self._backend_note

    def status(self) -> dict[str, Any]:
        path = llm.model_path()
        with self._lock:
            loaded = self._backend
            note = self._backend_note
        return {
            "model": str(path) if path else "",
            "models_dir": llm.models_dir_hint(),
            "loaded": bool(loaded) and getattr(loaded, "name", "") == "llama",
            "backend": getattr(loaded, "label", "") if loaded else "",
            "note": note,
            "runs": sorted(self._runs),
        }

    # -- running ------------------------------------------------------------

    def ask(self, question: str, thinking: bool = True) -> dict[str, Any]:
        """Start a run that answers `question` from the tools."""
        backend, _ = self.backend()
        run = Run(
            question=question,
            backend=getattr(backend, "label", "unknown"),
            thinking=thinking,
            tools=[
                {"key": key, "label": tool.label, "usage": tool.usage,
                 "status": self._status(tool)}
                for key, tool in self._tools.items()
            ],
        )
        with self._lock:
            self._runs[run.id] = run
        self._spawn(run)
        return run.snapshot()

    @staticmethod
    def _status(tool) -> str:
        try:
            return tool.status()
        except Exception as exc:  # a broken status must not stop a run
            return f"unavailable: {exc}"

    def _spawn(self, run: Run) -> None:
        backend, _ = self.backend()
        thread = threading.Thread(
            target=pipeline.execute,
            args=(run, self._tools, backend),
            name=f"spica-agents-{run.id}",
            daemon=True,
        )
        self._threads[run.id] = thread
        thread.start()

    # -- watching and steering ----------------------------------------------

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def poll(self, run_id: str, version: int = -1) -> dict[str, Any]:
        """The run, or only its version when nothing has moved.

        The interface polls several times a second while a model streams;
        a run is only a few kilobytes, but not resending it unchanged keeps
        the window quiet when nothing is happening.
        """
        run = self._runs.get(run_id)
        if run is None:
            return {"missing": True, "id": run_id}
        if version >= 0 and run.version == version:
            return {"unchanged": True, "id": run_id, "version": run.version}
        return run.snapshot()

    def cancel(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            return {"missing": True, "id": run_id}
        run.cancel()
        self._join(run_id)
        return run.snapshot()

    def rollback(self, run_id: str, index: int) -> dict[str, Any]:
        """Go back to the state before step `index`, stopping the run if needed."""
        run = self._runs.get(run_id)
        if run is None:
            return {"missing": True, "id": run_id}
        if run.status == "running":
            run.cancel()
            self._join(run_id)
        problem = run.rollback_to(int(index))
        snapshot = run.snapshot()
        if problem:
            snapshot["problem"] = problem
        return snapshot

    def resume(self, run_id: str) -> dict[str, Any]:
        """Carry on from wherever the state now stands, with fresh seeds."""
        run = self._runs.get(run_id)
        if run is None:
            return {"missing": True, "id": run_id}
        if run.status == "running":
            return run.snapshot()
        self._join(run_id)
        run.resuming()
        self._spawn(run)
        return run.snapshot()

    def _join(self, run_id: str, timeout: float = 5.0) -> None:
        thread = self._threads.get(run_id)
        if thread and thread.is_alive():
            thread.join(timeout)
