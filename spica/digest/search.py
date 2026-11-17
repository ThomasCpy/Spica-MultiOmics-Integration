"""Searching the digest: passages, ranked by content.

Each item of the digest becomes a passage:
- about one minute of an episode transcript,
- the show notes of an episode without a transcript,
- only the title of an episode whose publisher reserves mining,
- each trial from the watches (title, conditions, interventions, sponsor),
- the bibliographic line of each paper.
Each passage has its source, date, link, start time for speech, and the
genes it names.

Ranking uses BM25 over words, the standard keyword ranking, with no model.
A query word that names a gene also matches passages tagged with that gene,
whatever name they use. When an embedding model is installed (the one that
AI mode uses for documents), meaning also counts. The two scores are
blended, so "resistance to KRAS inhibitors" finds a passage without those
words.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from spica.digest import genes as gene_tags
from spica.digest.store import Store

#: About a minute of speech per passage: long enough to carry a point,
#: short enough that a quote from it is a quote.
WINDOW_SECONDS = 60
WINDOW_CHARS = 1100
WORD = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
STOPWORDS = frozenset("""
a an and are as at be but by for from has have i in is it its of on or so that the their there
they this to was we were what which who will with you your our not no can do does did been
also just very really um uh like know think going yeah okay right well
""".split())


@dataclass
class Passage:
    id: str
    kind: str  # "podcast" | "notes" | "title" | "trial" | "paper"
    source: str
    title: str
    date: str
    text: str
    link: str = ""
    start: float | None = None
    episode: str = ""
    genes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def words(text: str) -> list[str]:
    """Indexable words. A code with a hyphen or a dot ("XYZ-123", "CLDN18.2")
    also gives its parts and its parts joined. "XYZ 123", "XYZ123" and
    "XYZ-123" thus all find the same passages."""
    out = []
    for w in WORD.findall(text.lower()):
        if w in STOPWORDS:
            continue
        out.append(w)
        parts = re.split(r"[.\-]", w)
        if len(parts) > 1:
            out += [p for p in parts if p and p not in STOPWORDS]
            out.append("".join(parts))
    return out


def query_words(text: str) -> list[str]:
    """A query's words, with a letters-then-number pair also read as one
    code: "XYZ 123" asks for "xyz123" too, which is how the index holds it."""
    found = words(text)
    plain = [w for w in WORD.findall(text.lower()) if w not in STOPWORDS]
    for a, b in zip(plain, plain[1:]):
        if a.isalpha() and b.isdigit() and len(a) <= 6:
            found.append(a + b)
    return found


def clock(seconds: float | None) -> str:
    if seconds is None:
        return ""
    whole = int(seconds)
    return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}" if whole >= 3600 \
        else f"{whole // 60}:{whole % 60:02d}"


def _windows(segments: list[list]) -> list[tuple[float, str]]:
    out, start, buffer = [], None, []
    for begin, _end, text in segments:
        # Close the window before a segment that would stretch it past a
        # minute, so every passage starts where its first words are said.
        if buffer and (float(begin) - start >= WINDOW_SECONDS
                       or sum(len(t) for t in buffer) >= WINDOW_CHARS):
            out.append((start, " ".join(buffer)))
            start, buffer = None, []
        if start is None:
            start = float(begin)
        buffer.append(text.strip())
    if buffer:
        out.append((start or 0.0, " ".join(buffer)))
    return out


def passages(store: Store, watch_runs: list[dict[str, Any]], vocab: dict[str, str]) -> list[Passage]:
    names = {feed.key: feed.name for feed, _ in store.feeds()}
    out: list[Passage] = []
    for ident, episode in store.episodes().items():
        source = names.get(episode.get("feed", ""), episode.get("feed", ""))
        base = dict(source=source, title=episode.get("title", ""), date=episode.get("date", ""),
                    link=episode.get("link") or episode.get("audio", ""), episode=ident)
        if episode.get("reserved"):
            out.append(Passage(id=f"{ident}:title", kind="title", text=episode.get("title", ""), **base))
            continue
        found = store.transcript(ident)
        if found and found.get("segments"):
            for number, (start, text) in enumerate(_windows(found["segments"])):
                out.append(Passage(id=f"{ident}:{number}", kind="podcast", text=text, start=start,
                                   genes=gene_tags.tag(text, vocab), **base))
        else:
            text = f"{episode.get('title', '')}. {episode.get('notes', '')}".strip()
            out.append(Passage(id=f"{ident}:notes", kind="notes", text=text,
                               genes=gene_tags.tag(text, vocab), **base))
    seen: set[str] = set()
    for run in watch_runs:
        for item in (run.get("trials") or {}).get("items", []):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            text = (f"{item['title']}. Conditions: {', '.join(item['conditions'])}. "
                    f"Interventions: {', '.join(item['interventions'])}. Sponsor: {item['sponsor']}. "
                    f"{item['phase'].capitalize()}, {item['status']}.")
            out.append(Passage(id=item["id"], kind="trial", source="ClinicalTrials.gov",
                               title=f"{item['nct']}: {item['title']}", date=item["date"], text=text,
                               link=item["url"], genes=gene_tags.tag(text, vocab)))
        for item in (run.get("papers") or {}).get("items", []):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            text = f"{item.get('title', '')}. {item.get('venue', '')}"
            out.append(Passage(id=item["id"], kind="paper", source=item.get("venue") or "Europe PMC",
                               title=item.get("title", ""), date=item.get("date", ""), text=text,
                               link=item.get("url", ""), genes=gene_tags.tag(text, vocab)))
    out.sort(key=lambda p: (p.date, p.id), reverse=True)
    return out


class Index:
    """BM25 over the passages, built once per state of the store."""

    def __init__(self, items: list[Passage]) -> None:
        self.items = items
        self.postings: dict[str, dict[int, int]] = {}
        self.lengths = []
        for position, passage in enumerate(items):
            tokens = words(f"{passage.title} {passage.text}")
            self.lengths.append(len(tokens))
            for token in tokens:
                bucket = self.postings.setdefault(token, {})
                bucket[position] = bucket.get(position, 0) + 1
        self.average = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0

    def scores(self, terms: list[str]) -> dict[int, float]:
        k1, b, n = 1.2, 0.75, len(self.items)
        out: dict[int, float] = {}
        for term in set(terms):
            bucket = self.postings.get(term)
            if not bucket:
                continue
            idf = math.log(1 + (n - len(bucket) + 0.5) / (len(bucket) + 0.5))
            for position, count in bucket.items():
                norm = count * (k1 + 1) / (count + k1 * (1 - b + b * self.lengths[position] / self.average))
                out[position] = out.get(position, 0.0) + idf * norm
        return out


_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def index(store: Store, watch_runs: list[dict[str, Any]], vocab: dict[str, str],
          signature: str) -> Index:
    with _LOCK:
        if _CACHE.get("signature") != signature:
            _CACHE.update(signature=signature, index=Index(passages(store, watch_runs, vocab)))
        return _CACHE["index"]


def snippet(text: str, terms: list[str], width: int = 320) -> str:
    """The part of the passage where the query words are, whole words."""
    lowered = text.lower()
    hits = [lowered.find(term) for term in terms if term and lowered.find(term) >= 0]
    if not hits or len(text) <= width:
        return text if len(text) <= width else text[:width].rsplit(" ", 1)[0] + " ..."
    start = max(0, min(hits) - width // 3)
    start = text.rfind(" ", 0, start) + 1 if start else 0
    piece = text[start:start + width].rsplit(" ", 1)[0]
    return ("... " if start else "") + piece + (" ..." if start + width < len(text) else "")


def search(found: Index, query: str, vocab: dict[str, str], kinds: list[str] | None = None,
           gene: str = "", since: str = "", limit: int = 25, offset: int = 0,
           vectors: Any = None) -> dict[str, Any]:
    """Ranked passages for a query, with the genes it was taken to mean.

    `vectors` is an optional (scores by position) mapping from meaning
    search, blended in when present."""
    terms = query_words(query)
    wanted = sorted(set(gene_tags.tag(query, vocab)) | ({gene.upper()} if gene else set()))
    pool = range(len(found.items))
    allowed = [i for i in pool if (not kinds or found.items[i].kind in kinds)
               and (not since or found.items[i].date >= since)
               and (not gene or gene.upper() in found.items[i].genes)]
    distinct = sorted(set(terms))
    # A passage sharing one word of four with the query is not an answer:
    # it has to carry half the query's words, or name the gene it asks about.
    need = math.ceil(len(distinct) / 2)
    if terms or wanted:
        keyword = found.scores(terms)
        top = max(keyword.values(), default=0.0) or 1.0
        scored = []
        for i in allowed:
            names = bool(wanted and set(wanted) & set(found.items[i].genes))
            shared = sum(1 for term in distinct if i in found.postings.get(term, {}))
            close = vectors is not None and vectors.get(i, 0.0) >= 0.5
            if shared < need and not names and not close:
                continue
            score = keyword.get(i, 0.0) / top
            if names:
                score += 0.5  # names the gene, whatever it called it
            if vectors is not None and i in vectors:
                score = 0.6 * score + 0.4 * max(0.0, vectors[i])
            if score > 0:
                scored.append((score, found.items[i].date, i))
        scored.sort(reverse=True)
    else:
        scored = [(0.0, found.items[i].date, i) for i in allowed]  # newest first
    total = len(scored)
    naming = sum(1 for _, _, i in scored if wanted and set(wanted) & set(found.items[i].genes))
    rows = []
    for score, _, i in scored[offset:offset + limit]:
        passage = found.items[i]
        rows.append({**passage.to_dict(), "score": round(score, 3),
                     "at": clock(passage.start), "snippet": snippet(passage.text, terms)})
    return {"query": query, "terms": terms, "genes": wanted, "total": total, "naming": naming,
            "offset": offset, "results": rows, "passages": len(found.items)}
