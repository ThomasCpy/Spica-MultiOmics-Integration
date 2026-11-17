"""Papers and preprints, from Europe PMC.

One REST API, no key, PubMed plus the preprint servers (bioRxiv, medRxiv,
Research Square and others). Searched on title and abstract, inside a
first-publication window, newest first.

Only bibliographic metadata is kept: title, authors, journal, date and
identifiers. Abstracts are left at the source behind a link, because their
copyright sits with each publisher and this is a product, not a mirror.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from spica.live import Live, LiveError, NotFoundUpstream, OFF

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
SOURCE_KEY = "europepmc"
LABEL = "Europe PMC"
#: Per check and per kind. More than this many hits in one window is a
#: topic to narrow, and the screen says how many were not fetched.
CAP = 1000
PAGE = 1000  # Europe PMC's own maximum page size

#: Europe PMC's source codes, as the screen names them.
KINDS = {"MED": "paper", "PPR": "preprint"}


@dataclass
class Found:
    """What one source gave for one check, or why it gave nothing."""

    state: str = "ok"  # "ok" | "not_configured" | "failed" | "offline"
    reason: str = ""
    total: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    search_url: str = ""  # the same search, on the source's own site

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "total": self.total,
                "fetched": len(self.items), "items": self.items,
                "search_url": self.search_url}


#: A gene symbol as written in papers: capitals, digits, the odd hyphen.
SYMBOL = re.compile(r"^[A-Z][A-Z0-9-]*[0-9][A-Z0-9-]*$")


def clause(term: str) -> str:
    """One term in the form that Europe PMC must match.

    Europe PMC indexes `CLDN18.2` as one token. A search for `CLDN18` thus
    misses the papers about the isoform (measured: 15 hits against 67 in one
    quarter). A symbol therefore also matches its dotted forms (`CLDN18.*`).
    A bare `CLDN18*` fails in the other direction: `IL1*` gives IL10, IL17
    and the rest of the family, but `IL1.*` gives only IL1.
    """
    text = _escape(term)
    if SYMBOL.match(text):
        return f'(TITLE_ABS:"{text}" OR TITLE_ABS:{text}.*)'
    return f'TITLE_ABS:"{text}"'


def query(terms: list[str], since: date, until: date, source: str) -> str:
    """Europe PMC syntax: any term in title or abstract, inside the window."""
    quoted = " OR ".join(clause(term) for term in terms)
    return (f"({quoted}) AND FIRST_PDATE:[{since.isoformat()} TO {until.isoformat()}]"
            f" AND SRC:{source}")


def _escape(term: str) -> str:
    return term.replace("\\", " ").replace('"', " ").strip()


def search(live: Live, terms: list[str], since: date, until: date,
           stamp: str) -> Found:
    """Papers and preprints together, newest first.

    `stamp` goes into the cache key: the same check on the same day reads
    the cache and agrees with itself, and tomorrow's check asks again.
    """
    if not terms:
        return Found(state="failed", reason="no terms to search")

    found = Found()
    for source in KINDS:
        q = query(terms, since, until, source)
        cursor = "*"
        while len([i for i in found.items if i["source"] == source]) < CAP:
            params = {"query": q, "format": "json", "resultType": "lite",
                      "pageSize": PAGE, "sort": "FIRST_PDATE_D desc",
                      "cursorMark": cursor}
            url = f"{API}?{urllib.parse.urlencode(params)}"
            try:
                response = live.get_json(SOURCE_KEY, url,
                                         cache_key=f"{url}#{stamp}")
            except NotFoundUpstream:
                break
            except LiveError as exc:
                state = "offline" if OFF in str(exc) else "failed"
                return Found(state=state, reason=f"{LABEL}: {exc}")
            payload = response.payload if isinstance(response.payload, dict) else {}
            if cursor == "*":
                found.total += int(payload.get("hitCount") or 0)
            results = (payload.get("resultList") or {}).get("result") or []
            found.items += [paper(r) for r in results if isinstance(r, dict)]
            following = payload.get("nextCursorMark")
            if not results or not following or following == cursor:
                break
            cursor = following

    found.items.sort(key=lambda item: (item["date"], item["id"]), reverse=True)
    found.search_url = ("https://europepmc.org/search?query="
                        + urllib.parse.quote(query(terms, since, until, "MED")
                                             .replace(" AND SRC:MED", "")))
    return found


def paper(record: dict[str, Any]) -> dict[str, Any]:
    """One Europe PMC result, reduced to what is ours to keep."""
    source = str(record.get("source") or "")
    ident = str(record.get("id") or "")
    venue = (record.get("journalTitle")
             or (record.get("bookOrReportDetails") or {}).get("publisher") or "")
    doi = str(record.get("doi") or "")
    kinds = [part.strip() for part in str(record.get("pubType") or "").split(";")
             if part.strip()]
    return {
        "id": f"{source}:{ident}",
        "source": source,
        "kind": KINDS.get(source, source.lower()),
        # Titles carry the journal's markup, escaped ("&lt;i&gt;KRAS&lt;/i&gt;"):
        # read as text. Only formatting tags go, so "p < 0.05" stays.
        "title": re.sub(r"</?(?:i|b|em|strong|sup|sub|u|span)\b[^>]*>", "",
                        html.unescape(str(record.get("title") or ""))).strip().rstrip("."),
        "authors": html.unescape(str(record.get("authorString") or "")).strip().rstrip("."),
        "venue": html.unescape(str(venue)),
        "date": str(record.get("firstPublicationDate") or record.get("pubYear") or ""),
        "pmid": str(record.get("pmid") or ""),
        "doi": doi,
        "types": kinds,
        "link": (f"https://doi.org/{doi}" if doi
                 else f"https://europepmc.org/article/{source}/{ident}"),
    }


def facets(items: list[dict[str, Any]]) -> dict[str, list[list[Any]]]:
    """Counts the screen can show without reading every title."""
    by_kind: dict[str, int] = {}
    by_venue: dict[str, int] = {}
    for item in items:
        label = item["kind"]
        if item["kind"] == "paper":
            types = {t.lower() for t in item["types"]}
            if "review" in types:
                label = "review"
            elif any("clinical trial" in t for t in types):
                label = "clinical trial"
        by_kind[label] = by_kind.get(label, 0) + 1
        if item["venue"]:
            by_venue[item["venue"]] = by_venue.get(item["venue"], 0) + 1
    order = lambda counts: sorted(([k, v] for k, v in counts.items()),
                                  key=lambda kv: (-kv[1], kv[0]))
    return {"kind": order(by_kind), "venue": order(by_venue)}
