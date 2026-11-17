"""The user's own documents, indexed for search.

Everything dropped into the input folder is extracted, cut into passages
that remember where they came from, embedded locally, and searched by
cosine similarity. Nothing here touches the network, and the index is
three plain files so it can be inspected with ordinary tools.

    from spica.corpus import Index, Embedder
    index = Index.load()
    for score, chunk in index.search(Embedder().query("screen result")):
        print(score, chunk.citation, chunk.text[:200])

This is the retrieval half of AI mode. The gene report does not use it and
never will: a report is deterministic, and an answer is synthesised.
"""

from __future__ import annotations

from spica.corpus.chunks import Chunk, chunk_units
from spica.corpus.embed import Embedder, available_embedders, embedder_path
from spica.corpus.extract import SUPPORTED, ExtractionError, extract
from spica.corpus.index import Index, Ingested, discover, index_dir, input_dir

__all__ = [
    "Chunk",
    "Embedder",
    "ExtractionError",
    "Index",
    "Ingested",
    "SUPPORTED",
    "available_embedders",
    "chunk_units",
    "discover",
    "embedder_path",
    "extract",
    "index_dir",
    "input_dir",
]
