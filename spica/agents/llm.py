"""The local model, and the interface that allows tests without it.

A backend yields `(kind, text)` chunks during generation. The kind is
`reasoning` or `answer`. This split lets the interface show the thoughts of
an agent apart from its decision. The split must happen here: `</think>`
arrives mid-stream and can cross two chunks. A caller that splits the text
itself would sooner or later leak half a tag into an answer.

Two backends:

`Llama` runs a GGUF through llama-cpp-python. Qwen ships with reasoning off
unless the chat template gets `enable_thinking`. This module thus drives the
template directly, not through the convenience wrapper. The method comes
from `utils/llm.py` in Betelgeuse, an earlier project.

`Scripted` replays canned text. All tests use it, and so does the interface
when no model is installed. The pipeline, the streaming and the rollback
thus all work on a machine without model weights.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from spica import settings
from spica.agents import gguf
from spica.paths import data_dir

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
#: Said in the trace when a thinking budget runs out and the model is made to act.
CAPPED = "\n[thinking budget reached; acting on what it has]\n"

MODELS_DIRNAME = "models"


class ModelMissing(RuntimeError):
    """No usable model file, with a sentence saying where one should go."""


class Backend(Protocol):
    name: str
    label: str

    def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.6,
        thinking: bool = True,
        seed: int = 0,
        max_tokens: int = 2048,
        presence_penalty: float = 0.0,
        think_budget: int = 0,
    ) -> Iterator[tuple[str, str]]:
        """Yield ("reasoning" | "answer", text) as the model generates."""


# -- finding a model --------------------------------------------------------


def search_dirs() -> list[Path]:
    """Everywhere a model might be: the mirror, and anywhere else chosen.

    The extra directories exist so a 22 GB file kept beside another project
    never has to be copied in. They are a preference, not a dependency: a
    directory that has gone away is skipped, not an error.
    """
    folders = [data_dir() / MODELS_DIRNAME]
    for extra in settings.load()["model_dirs"]:
        candidate = Path(str(extra))
        if candidate not in folders:
            folders.append(candidate)
    return folders


def available_models() -> list[dict[str, Any]]:
    """Every model that could be run, newest-looking first.

    Only the header of each file is read, so listing a directory of 22 GB
    models costs a few kilobytes rather than minutes.
    """
    found: dict[str, dict[str, Any]] = {}
    for folder in search_dirs():
        try:
            files = sorted(folder.glob("*.gguf"))
        except OSError:
            continue
        for file in files:
            try:
                size = file.stat().st_size
            except OSError:
                continue
            key = str(file.resolve())
            if key in found:
                continue
            described = gguf.describe(file)
            found[key] = {
                "path": key,
                "name": described["name"] or file.stem,
                "file": file.name,
                "folder": str(folder),
                "gigabytes": round(size / 1e9, 1),
                "layers": described["layers"],
                "architecture": described["architecture"],
            }
    return sorted(found.values(), key=lambda m: m["gigabytes"])


def model_path() -> Path | None:
    """The GGUF to run, or None.

    `SPICA_MODEL` wins so a run can be pointed anywhere from the command
    line; then the saved choice; then the largest model found, which is the
    one a person who dropped two files in a directory meant.
    """
    override = os.environ.get("SPICA_MODEL", "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.exists() else None

    chosen = settings.load()["model"].strip()
    if chosen:
        candidate = Path(chosen)
        if candidate.exists():
            return candidate

    models = available_models()
    return Path(models[-1]["path"]) if models else None


def models_dir_hint() -> str:
    return str(data_dir() / MODELS_DIRNAME)


# -- fitting it on the card -------------------------------------------------


def free_vram() -> int:
    """Free VRAM in bytes, or 0 when there is no card to ask."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return 0
    try:
        out = subprocess.run(
            [smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return 0
        return int(out.stdout.strip().splitlines()[0].strip()) * 1024 * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def auto_gpu_layers(path: Path) -> int:
    """The number of layers that fit in VRAM, rounded down.

    The number must be correct before the file opens. With too few, a large
    model runs fully on the CPU. With too many, llama.cpp runs out of VRAM
    and stops the process. The layer count comes from the header, so this is
    arithmetic, not a guess. It keeps a margin, because the KV cache and the
    compute buffers also need memory.
    """
    free = free_vram()
    if free <= 0:
        return 0
    try:
        size = path.stat().st_size
    except OSError:
        return 0

    layers = gguf.block_count(path)
    if not layers:
        # No header to go on: offload everything only if it clearly fits.
        return -1 if size < free * 0.7 else 0
    if size < free * 0.8:
        return -1  # the whole model fits, cache and all

    usable = free * 0.85 - 384 * 1024 * 1024  # leave room for the KV cache
    per_layer = size / layers
    return max(0, min(layers, int(usable / per_layer)))


# -- the real one -----------------------------------------------------------


class Llama:
    """A GGUF model, driven through llama-cpp-python."""

    name = "llama"

    def __init__(self, path: Path, context: int = 8192,
                 gpu_layers: int | None = None) -> None:
        try:
            from llama_cpp import Llama as LlamaCpp
            from llama_cpp.llama_chat_format import Jinja2ChatFormatter
        except ImportError as exc:  # the dependency is optional on purpose
            raise ModelMissing(
                "llama-cpp-python is not installed. Run `./run.sh --agents` "
                "to add it to the runtime."
            ) from exc

        if not path.exists():
            raise ModelMissing(f"No model at {path}")

        self.path = path
        self.label = path.stem
        self.gpu_layers = auto_gpu_layers(path) if gpu_layers is None else gpu_layers
        self._llm = LlamaCpp(
            model_path=str(path),
            n_ctx=context,
            n_gpu_layers=self.gpu_layers,
            verbose=False,
        )
        template = self._llm.metadata.get("tokenizer.chat_template")
        if not template:
            raise ModelMissing(f"{path.name} carries no chat template")
        eos, bos = self._llm.token_eos(), self._llm.token_bos()
        self._formatter = Jinja2ChatFormatter(
            template=template,
            eos_token=self._token(eos),
            bos_token=self._token(bos),
            stop_token_ids=[eos],
        )

    def _token(self, token_id: int) -> str:
        if token_id == -1:
            return ""
        return self._llm.detokenize([token_id], special=True).decode("utf-8", "ignore")

    def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.6,
        thinking: bool = True,
        seed: int = 0,
        max_tokens: int = 2048,
        presence_penalty: float = 0.0,
        think_budget: int = 0,
    ) -> Iterator[tuple[str, str]]:
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})

        formatted = self._formatter(messages=messages, enable_thinking=thinking)
        tokens = self._llm.tokenize(
            formatted.prompt.encode("utf-8"),
            # The template already emitted any special prefix; adding BOS here
            # as well shifts the model off the distribution it was trained on.
            add_bos=not formatted.added_special,
            special=True,
        )
        if seed:
            self._llm.set_seed(seed)

        raw = self._llm.create_completion(
            prompt=tokens,
            max_tokens=max_tokens,
            temperature=temperature,
            # Discourages circling ground already covered, which is how a
            # small model spends a whole budget restating one consideration
            # instead of concluding. Betelgeuse's value, for the same reason.
            presence_penalty=presence_penalty,
            stop=formatted.stop,
            stopping_criteria=formatted.stopping_criteria,
            stream=True,
        )
        pieces = (chunk["choices"][0]["text"] for chunk in raw)
        if not (thinking and think_budget):
            yield from split_thinking_stream(pieces, thinking)
            return
        # A capped trace. Past the budget, the trace closes where it is. The
        # model then gets the trace in front of it and gives its answer. The
        # trace is not discarded.
        thought: list[str] = []
        answering = False
        for kind, text in split_thinking_stream(pieces, True):
            yield kind, text
            if kind == "answer":
                answering = True
                continue
            thought.append(text)
            if not answering and len(thought) >= think_budget:
                break
        else:
            return
        yield "reasoning", CAPPED
        closed = formatted.prompt + THINK_OPEN + "\n" + "".join(thought).rstrip() + "\n" + THINK_CLOSE + "\n\n"
        rest = self._llm.create_completion(
            prompt=self._llm.tokenize(closed.encode("utf-8"), add_bos=not formatted.added_special,
                                      special=True),
            max_tokens=max(64, max_tokens - len(thought)),
            temperature=temperature,
            stop=formatted.stop,
            stopping_criteria=formatted.stopping_criteria,
            stream=True,
        )
        for chunk in rest:
            text = chunk["choices"][0]["text"]
            if text:
                yield "answer", text


def split_thinking_stream(pieces, thinking: bool) -> Iterator[tuple[str, str]]:
    """Label each piece `reasoning` or `answer`, and watch for `</think>`.

    The tag is held back across chunk boundaries. A caller that shows the
    two streams in different places thus never gets `</thi` as reasoning and
    `nk>` as an answer.
    """
    if not thinking:
        for piece in pieces:
            if piece:
                yield "answer", piece
        return

    in_reasoning = True
    hold = ""
    opened = False
    first_answer = True

    for piece in pieces:
        if not piece:
            continue
        if not in_reasoning:
            if first_answer:
                piece = piece.lstrip("\n")
                first_answer = not piece
            if piece:
                yield "answer", piece
            continue

        hold += piece
        if not opened:
            # Some models emit the opening tag themselves; wait rather than
            # flush a fragment of it as reasoning.
            head = hold.lstrip()
            if len(head) < len(THINK_OPEN) and THINK_OPEN.startswith(head):
                continue
            if head.startswith(THINK_OPEN):
                hold = head[len(THINK_OPEN):].lstrip("\n")
            opened = True

        if THINK_CLOSE in hold:
            head, _, tail = hold.partition(THINK_CLOSE)
            hold = ""
            in_reasoning = False
            if head:
                yield "reasoning", head
            tail = tail.lstrip("\n")
            if tail:
                first_answer = False
                yield "answer", tail
            continue

        # Keep back as much as could still turn out to be the closing tag.
        safe = len(hold) - len(THINK_CLOSE)
        if safe > 0:
            yield "reasoning", hold[:safe]
            hold = hold[safe:]

    if hold:
        yield ("reasoning" if in_reasoning else "answer"), hold


# -- the stand-in -----------------------------------------------------------


@dataclass
class Scripted:
    """A backend that replays text, for tests and for having no model.

    Replies are matched on a marker in the prompt, so the pipeline's four
    agents can be given four different canned answers in one object. The
    text is split into word-sized chunks so that anything downstream which
    assembles a stream is exercised.
    """

    replies: dict[str, tuple[str, str]] = field(default_factory=dict)
    fallback: tuple[str, str] = ("thinking about it", "nothing to say")
    name: str = "scripted"
    label: str = "No model (scripted)"
    calls: list[str] = field(default_factory=list)
    delay: float = 0.0

    def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.6,
        thinking: bool = True,
        seed: int = 0,
        max_tokens: int = 2048,
        presence_penalty: float = 0.0,
        think_budget: int = 0,
    ) -> Iterator[tuple[str, str]]:
        self.calls.append(prompt)
        reasoning, answer = self.fallback
        for marker, reply in self.replies.items():
            if marker in prompt:
                reasoning, answer = reply
                break

        if thinking:
            pieces = list(self._chunks("reasoning", reasoning, seed))
            if think_budget and len(pieces) > think_budget:
                pieces = pieces[:think_budget] + [("reasoning", CAPPED)]
            yield from pieces
        yield from self._chunks("answer", answer, seed)

    def _chunks(self, kind: str, text: str, seed: int) -> Iterator[tuple[str, str]]:
        import time

        if not text:
            return
        # A different seed should visibly produce a different run, so that
        # rolling back and retrying shows an effect in a demo.
        if seed:
            text = text.replace("{seed}", str(seed))
        for piece in re.findall(r"\S+\s*", text):
            if self.delay:
                time.sleep(self.delay)
            yield kind, piece


def demo_backend(seed: int = 0) -> Scripted:
    """The stand-in the interface uses when no model is installed."""
    rng = random.Random(seed)
    del rng  # kept deliberate: the demo text is fixed, the seed only labels it
    return Scripted()
