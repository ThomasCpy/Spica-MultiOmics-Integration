"""Meaning search over the digest, when an embedding model is installed.

The same local embedding model AI mode uses for documents
(`spica/corpus/embed.py`), when there is one. Passages are embedded during
an update, never during a search, and kept in `data/digest/vectors.npz`
by passage ID, so a passage is embedded once. A search embeds the query
alone and adds each passage's cosine similarity to its keyword score
(`spica/digest/search.py`). Without a model, search is keyword search, and
says nothing it cannot back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

#: Passages worth a vector: what was said and what was registered. A title
#: alone, from a reserved feed, is left to keyword search.
EMBEDDED = ("podcast", "notes", "trial", "paper")

_EMBEDDERS: dict[str, Any] = {}


def available() -> bool:
    try:
        import numpy  # noqa: F401
        from spica.corpus.embed import embedder_path
    except ImportError:
        return False
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        return False
    return embedder_path() is not None


def embedder():
    from spica.corpus.embed import Embedder, embedder_path

    path = embedder_path()
    key = str(path)
    if key not in _EMBEDDERS:
        _EMBEDDERS.clear()
        _EMBEDDERS[key] = Embedder(path)
    return _EMBEDDERS[key]


def _path(root: Path) -> Path:
    return Path(root) / "digest" / "vectors.npz"


def load(root: Path) -> tuple[list[str], Any]:
    import numpy as np

    try:
        with np.load(_path(root), allow_pickle=False) as found:
            return [str(i) for i in found["ids"]], found["vectors"]
    except (OSError, KeyError, ValueError):
        return [], np.zeros((0, 0), dtype="float32")


def refresh(items: list, root: Path, model=None,
            progress: Callable[[int, int], None] | None = None) -> int:
    """Embed the passages that have no vector yet; returns how many."""
    import numpy as np

    ids, matrix = load(root)
    have = set(ids)
    missing = [p for p in items if p.kind in EMBEDDED and p.id not in have]
    if not missing:
        return 0
    model = model or embedder()
    fresh = []
    for done, passage in enumerate(missing, start=1):
        fresh.append(model.documents([f"{passage.title}. {passage.text}"[:2000]])[0])
        if progress:
            progress(done, len(missing))
    added = np.asarray(fresh, dtype="float32")
    matrix = added if matrix.size == 0 else np.vstack([matrix, added])
    target = _path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    np.savez(target.with_suffix(".tmp.npz"), ids=np.asarray(ids + [p.id for p in missing]),
             vectors=matrix)
    target.with_suffix(".tmp.npz").replace(target)
    return len(missing)


def scores(items: list, query: str, root: Path, model=None) -> dict[int, float]:
    """Cosine similarity of the query to each passage that has a vector, by
    the passage's position in `items`."""
    import numpy as np

    ids, matrix = load(root)
    if not ids or not query.strip():
        return {}
    model = model or embedder()
    wanted = np.asarray(model.query(query), dtype="float32")
    similarity = matrix @ wanted
    at = {ident: row for row, ident in enumerate(ids)}
    return {position: float(similarity[at[p.id]]) for position, p in enumerate(items) if p.id in at}
