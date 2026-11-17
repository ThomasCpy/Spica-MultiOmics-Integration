"""Turning text into vectors, locally.

Same contract as the chat model: everything runs in-process through
llama.cpp, no server and no network. Vectors come back unit length, so
cosine similarity is a plain dot product.

Two details decide whether retrieval works at all, both learned from
Betelgeuse's `utils/embed.py`:

*Pooling.* An embedding model reduces a sequence of token vectors to one
vector, and families differ: Qwen3-Embedding takes the last token, BERT-
style models take the mean. The wrong mode still yields vectors,
plausible-looking and quietly useless. llama.cpp reads the right mode from
the GGUF metadata, so it is left to do that.

*Asymmetry.* Instruction-tuned retrieval models, the Qwen3-Embedding family
among them, expect a query wrapped in an instruction while documents are
embedded bare. Embedding both sides identically measurably degrades recall,
so these are two methods rather than one method with a flag people forget
to pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from spica import settings
from spica.agents.llm import ModelMissing, auto_gpu_layers
from spica.paths import data_dir

EMBEDDINGS_DIRNAME = "models/embeddings"

#: The wrapper the Qwen3-Embedding family expects around a search query.
#: Harmless for models that do not use it, which is why it is applied by
#: task rather than by sniffing the model.
QUERY_INSTRUCTION = (
    "Instruct: Given a search query, retrieve relevant passages that answer it\n"
    "Query: "
)


def embeddings_dir() -> Path:
    return data_dir() / "models" / "embeddings"


def available_embedders() -> list[dict]:
    """Embedding models that could be used, smallest first."""
    from spica.agents import gguf, llm

    found: dict[str, dict] = {}
    folders = [embeddings_dir()] + llm.search_dirs()
    for folder in folders:
        for pattern in ("*.gguf", "embeddings/*.gguf"):
            try:
                files = sorted(folder.glob(pattern))
            except OSError:
                continue
            for file in files:
                key = str(file.resolve())
                if key in found:
                    continue
                described = gguf.describe(file)
                # An embedding model is one whose architecture says so, or
                # whose name does; both appear in the wild.
                looks_right = ("embed" in described["architecture"].lower()
                               or "embed" in file.name.lower())
                if not looks_right:
                    continue
                try:
                    size = file.stat().st_size
                except OSError:
                    continue
                found[key] = {
                    "path": key,
                    "name": described["name"] or file.stem,
                    "file": file.name,
                    "gigabytes": round(size / 1e9, 2),
                }
    return sorted(found.values(), key=lambda m: m["gigabytes"])


def embedder_path() -> Path | None:
    """The embedding model to use, or None."""
    chosen = settings.load()["embed_model"].strip()
    if chosen:
        candidate = Path(chosen)
        if candidate.exists():
            return candidate
    models = available_embedders()
    return Path(models[-1]["path"]) if models else None


class Embedder:
    """A GGUF embedding model held open for the length of an ingest."""

    def __init__(self, path: Path | None = None, context: int = 2048) -> None:
        path = path or embedder_path()
        if path is None:
            raise ModelMissing(
                f"No embedding model found. Put one in {embeddings_dir()}, "
                f"or choose one in the menu."
            )
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ModelMissing(
                "llama-cpp-python is not installed. Run `./run.sh --agents`."
            ) from exc

        self.path = path
        self.label = path.stem
        self._llm = Llama(
            model_path=str(path),
            n_ctx=context,
            n_gpu_layers=auto_gpu_layers(path),
            embedding=True,
            verbose=False,
        )
        self.dimension = len(self._one("dimension probe"))

    def _one(self, text: str) -> list[float]:
        import numpy as np

        raw = self._llm.create_embedding(text)["data"][0]["embedding"]
        # Some builds return one vector per token rather than one per text;
        # pooling here keeps both shapes working.
        vector = np.asarray(raw, dtype="float32")
        if vector.ndim > 1:
            vector = vector.mean(axis=0)
        norm = float(np.linalg.norm(vector))
        return (vector / norm if norm else vector).tolist()

    def documents(self, texts: Sequence[str]):
        """Embed passages, bare."""
        import numpy as np

        return np.asarray([self._one(text) for text in texts], dtype="float32")

    def query(self, text: str):
        """Embed a question, wrapped in the retrieval instruction."""
        import numpy as np

        return np.asarray(self._one(QUERY_INSTRUCTION + text), dtype="float32")
