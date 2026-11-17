"""Patents, from the EPO Open Patent Services (OPS).

OPS is the only free, documented patent API with worldwide coverage (EP,
WO, US, CN, JP, KR and most other offices, in DOCDB). Its terms let a
registered user use its results inside their own product. It needs a free
registration: the user's own consumer key and secret, kept in the settings.
Without them, this source says `not_configured`. That is a different
statement from "no patents".

Two facts about OPS shape the code:

- **No hits is a 404**, not an empty list. The code reads it as zero,
  never as a failure.
- **Its JSON is XML in disguise.** Text sits under `"$"`, attributes under
  `"@..."`, and a list of one item is a bare object. All access thus goes
  through `_list` and `_text`.

Results come as publications, and one invention usually has several (a WO
application, then EP and US filings of the same family). They are grouped
by DOCDB family, because one invention of a competitor is one row.
"""

from __future__ import annotations

import base64
import re
import time
import urllib.parse
from datetime import date
from typing import Any

from spica.intel.literature import Found
from spica.live import Live, LiveError, NotFoundUpstream, OFF

BASE = "https://ops.epo.org/3.2"
TOKEN_URL = f"{BASE}/auth/accesstoken"
SEARCH_URL = f"{BASE}/rest-services/published-data/search/biblio"
SOURCE_KEY = "epo_ops"
LABEL = "EPO OPS"
PAGE = 100  # the most OPS returns per request
CAP = 500  # per check: five requests, inside the fair-use rate

#: CPC main groups worth naming on a target-discovery screen. A code with
#: no label here is still shown, as its code.
CPC_LABELS = {
    "C07K16": "Antibodies",
    "A61K39": "Antibodies and vaccines (medicinal use)",
    "A61K47": "Conjugates and carriers (incl. ADCs)",
    "A61K40": "Cell therapy (CAR and engineered cells)",
    "A61K35": "Cells and tissues (medicinal use)",
    "C12N5": "Engineered cells",
    "C12N15": "Nucleic acids and gene engineering",
    "A61K31": "Small molecules",
    "A61K38": "Peptides and proteins (medicinal use)",
    "A61K48": "Gene therapy",
    "C07K14": "Peptides and proteins",
    "C07K19": "Fusion proteins",
    "G01N33": "Assays and diagnostics",
    "C12Q1": "Nucleic acid assays",
    "A61P35": "Anticancer activity",
    "A61P37": "Immunomodulation",
    "A61P3": "Metabolic disorders",
    "A61P9": "Cardiovascular disorders",
}


class Credentials:
    """The user's OPS key and secret, and the short-lived token they buy."""

    def __init__(self, key: str, secret: str) -> None:
        self.key = (key or "").strip()
        self.secret = (secret or "").strip()
        self._token = ""
        self._expires = 0.0

    @property
    def present(self) -> bool:
        return bool(self.key and self.secret)

    def token(self, live: Live) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        payload = live.post_form(SOURCE_KEY, TOKEN_URL,
                                 {"grant_type": "client_credentials"},
                                 headers={"Authorization": f"Basic {basic}"})
        token = str(payload.get("access_token") or "")
        if not token:
            raise LiveError("OPS did not issue an access token; check the key and secret")
        self._token = token
        self._expires = time.time() + float(payload.get("expires_in") or 1200)
        return token


def cql(terms: list[str], since: date, until: date) -> str:
    """OPS's query language: any term in title or abstract, in the window."""
    quoted = " or ".join(f'ta="{_escape(term)}"' for term in terms)
    return (f'({quoted}) and pd within '
            f'"{since.strftime("%Y%m%d")} {until.strftime("%Y%m%d")}"')


def _escape(term: str) -> str:
    return re.sub(r'["\\]', " ", term).strip()


def search(live: Live, credentials: Credentials, terms: list[str],
           since: date, until: date, stamp: str) -> Found:
    if not credentials.present:
        return Found(state="not_configured",
                     reason="EPO Open Patent Services key required (free).")
    if not terms:
        return Found(state="failed", reason="no terms to search")

    query = cql(terms, since, until)
    publications: list[dict[str, Any]] = []
    total = 0
    begin = 1
    while begin <= min(CAP, total or CAP):
        end = begin + PAGE - 1
        url = (f"{SEARCH_URL}?{urllib.parse.urlencode({'q': query})}"
               f"&Range={begin}-{end}")
        try:
            token = credentials.token(live)
            response = live.get_json(SOURCE_KEY, url,
                                     headers={"Authorization": f"Bearer {token}"},
                                     cache_key=f"{url}#{stamp}")
        except NotFoundUpstream:
            break  # OPS's way of saying "no results"
        except LiveError as exc:
            state = "offline" if OFF in str(exc) else "failed"
            return Found(state=state, reason=f"{LABEL}: {exc}")
        found_total, page = parse(response.payload)
        total = total or found_total
        publications += page
        if not page:
            break
        begin = end + 1

    families = group(publications)
    return Found(
        total=total,
        items=families,
        search_url=("https://worldwide.espacenet.com/patent/search?q="
                    + urllib.parse.quote(query)),
    )


# -- reading OPS's JSON -------------------------------------------------------


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("$", "")).strip()
    return "" if value is None else str(value).strip()


def parse(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    """The total hit count and one entry per publication on this page."""
    root = (payload or {}).get("ops:world-patent-data", {}) if isinstance(payload, dict) else {}
    search = root.get("ops:biblio-search", {})
    try:
        total = int(search.get("@total-result-count") or 0)
    except (TypeError, ValueError):
        total = 0
    documents = (search.get("ops:search-result") or {}).get("exchange-documents")
    out = []
    for wrapper in _list(documents):
        document = wrapper.get("exchange-document") if isinstance(wrapper, dict) else None
        for doc in _list(document):
            if isinstance(doc, dict):
                out.append(publication(doc))
    return total, out


def publication(doc: dict[str, Any]) -> dict[str, Any]:
    biblio = doc.get("bibliographic-data") or {}
    country = str(doc.get("@country") or "")
    number = str(doc.get("@doc-number") or "")
    kind = str(doc.get("@kind") or "")

    published = ""
    for ident in _list((biblio.get("publication-reference") or {}).get("document-id")):
        if isinstance(ident, dict) and ident.get("@document-id-type") == "docdb":
            published = _text(ident.get("date"))
            break

    titles = _list(biblio.get("invention-title"))
    title = next((_text(t) for t in titles
                  if isinstance(t, dict) and t.get("@lang") == "en"), "")
    title = title or next((_text(t) for t in titles if _text(t)), "")

    applicants: list[str] = []
    for party in _list(((biblio.get("parties") or {}).get("applicants") or {}).get("applicant")):
        if isinstance(party, dict) and party.get("@data-format") == "epodoc":
            name = _text((party.get("applicant-name") or {}).get("name"))
            if name and name not in applicants:
                applicants.append(name)

    cpc: list[str] = []
    for item in _list((biblio.get("patent-classifications") or {}).get("patent-classification")):
        if not isinstance(item, dict):
            continue
        code = (f"{_text(item.get('section'))}{_text(item.get('class'))}"
                f"{_text(item.get('subclass'))}{_text(item.get('main-group'))}")
        sub = _text(item.get("subgroup"))
        full = f"{code}/{sub}" if sub else code
        if code and full not in cpc:
            cpc.append(full)

    return {
        "number": f"{country}{number}{kind}",
        "country": country,
        "kind": kind,
        "date": _iso(published),
        "family": str(doc.get("@family-id") or f"{country}{number}"),
        "title": title,
        "applicants": applicants,
        "cpc": cpc,
    }


def _iso(stamp: str) -> str:
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if re.fullmatch(r"\d{8}", stamp) else stamp


def applicant(name: str) -> tuple[str, str]:
    """`ASTELLAS PHARMA INC [JP]` -> (`ASTELLAS PHARMA INC`, `JP`)."""
    match = re.match(r"^(.*?)\s*\[([A-Z]{2})\]\s*$", name)
    if match:
        return match.group(1).strip().rstrip(",."), match.group(2)
    return name.strip().rstrip(",."), ""


def group(publications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per invention: publications merged by DOCDB family."""
    families: dict[str, dict[str, Any]] = {}
    for pub in publications:
        family = families.setdefault(pub["family"], {
            "id": f"family:{pub['family']}",
            "family": pub["family"],
            "title": "",
            "applicants": [],
            "countries": [],
            "cpc": [],
            "publications": [],
            "date": "",
            "first": "",
        })
        family["publications"].append({"number": pub["number"], "date": pub["date"]})
        family["title"] = family["title"] or pub["title"]
        for name in pub["applicants"]:
            clean, country = applicant(name)
            if clean and clean not in family["applicants"]:
                family["applicants"].append(clean)
            if country and country not in family["countries"]:
                family["countries"].append(country)
        for code in pub["cpc"]:
            if code not in family["cpc"]:
                family["cpc"].append(code)
        if pub["date"] > family["date"]:
            family["date"] = pub["date"]  # the latest publication in the window
        if not family["first"] or (pub["date"] and pub["date"] < family["first"]):
            family["first"] = pub["date"]

    rows = list(families.values())
    for row in rows:
        row["publications"].sort(key=lambda p: (p["date"], p["number"]))
        lead = row["publications"][0]["number"] if row["publications"] else ""
        row["link"] = (f"https://worldwide.espacenet.com/patent/search?q=pn%3D{lead}"
                       if lead else "")
    rows.sort(key=lambda row: (row["date"], row["family"]), reverse=True)
    return rows


def facets(families: list[dict[str, Any]]) -> dict[str, list[list[Any]]]:
    """Who is filing, and on what: families per applicant and per CPC group."""
    by_applicant: dict[str, int] = {}
    by_group: dict[str, int] = {}
    for family in families:
        for name in family["applicants"]:
            by_applicant[name] = by_applicant.get(name, 0) + 1
        groups = {code.split("/")[0] for code in family["cpc"]}
        for code in groups:
            by_group[code] = by_group.get(code, 0) + 1
    order = lambda counts: sorted(([k, v] for k, v in counts.items()),
                                  key=lambda kv: (-kv[1], kv[0]))
    return {
        "applicant": order(by_applicant),
        "cpc": [[code, count, CPC_LABELS.get(code, "")]
                for code, count in order(by_group)],
    }
