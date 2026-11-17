"""Open Targets: what the gene is implicated in, and whether it can be drugged.

The widest of the sources, and the one that turns a description of a gene
into a judgement about a target. Four things come from it:

*Disease associations*, each with a score between 0 and 1 aggregated from
genetics, expression, literature and clinical evidence. Scores are the
point: a list of diseases is a description, a scored list is something two
genes can be compared on.

*Tractability*, by modality. Whether a small molecule has ever been
co-crystallised with it, whether an antibody against it is approved, and
so on: the difference between a target that is interesting and one that
can be worked on.

*Mouse phenotypes* from knockouts, which is the cheapest read on what
happens when the gene is removed.

*Safety liabilities*, curated from the literature and from trials. Usually
empty, and worth seeing when it is not.

Mirror file: `targets`, JSON Lines, one object per target keyed by
`ensemblId`, holding the same shape the API returns. Open Targets ships its
releases as parquet, which Spica does not read; `docs/data-mirror.md` says
how to produce the lines.
"""

from __future__ import annotations

import json
from typing import Any

from spica.live import Fetched, Live, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import Resolution
from spica.sources.base import GeneNotInSource, Source, SourceError, open_text
from spica.sources.index import lines_for

API = "https://api.platform.opentargets.org/api/v4/graphql"

#: Associations per request. Every association is fetched, page by page:
#: the record keeps all of them and the views decide how many to show at
#: first, never how many exist. Open Targets answers 3,000 rows in well
#: under a second.
PAGE = 3000
#: A ceiling on pages, so a malformed count can never loop forever.
MAX_PAGES = 20

#: Modality codes as Open Targets writes them.
MODALITIES = {"SM": "Small molecule", "AB": "Antibody", "PR": "PROTAC",
              "OC": "Other clinical", "GT": "Gene therapy"}

QUERY = """
query Target($ensg: String!, $index: Int!, $size: Int!) {
  target(ensemblId: $ensg) {
    approvedSymbol
    tractability { label value modality }
    safetyLiabilities { event datasource }
    associatedDiseases(page: {index: $index, size: $size}) {
      count
      rows { score disease { name } }
    }
    mousePhenotypes { modelPhenotypeLabel }
  }
}"""


def _fields(target: dict[str, Any]) -> dict[str, Any]:
    """The record's fields out of one Open Targets target object.

    Shared by both routes, so a mirrored record and a fetched one say the
    same thing in the same shape.
    """
    fields: dict[str, Any] = {}

    associated = target.get("associatedDiseases") or {}
    rows = associated.get("rows") or []
    scored = {}
    for row in rows:
        name = ((row or {}).get("disease") or {}).get("name")
        score = (row or {}).get("score")
        if name and isinstance(score, (int, float)):
            scored[str(name)] = round(float(score), 3)
    if scored:
        fields["disease_associations"] = scored
    if isinstance(associated.get("count"), int):
        fields["disease_association_count"] = associated["count"]

    tractable = []
    for entry in target.get("tractability") or []:
        if not (entry or {}).get("value"):
            continue
        modality = MODALITIES.get(entry.get("modality", ""), entry.get("modality", ""))
        label = entry.get("label", "")
        if label:
            tractable.append(f"{modality}: {label}" if modality else label)
    if tractable:
        fields["tractability"] = tractable

    phenotypes = []
    for entry in target.get("mousePhenotypes") or []:
        label = (entry or {}).get("modelPhenotypeLabel")
        if label and label not in phenotypes:
            phenotypes.append(str(label))
    if phenotypes:
        fields["mouse_phenotypes"] = phenotypes

    liabilities = []
    for entry in target.get("safetyLiabilities") or []:
        event = (entry or {}).get("event")
        if event and event not in liabilities:
            liabilities.append(str(event))
    if liabilities:
        fields["safety_liabilities"] = liabilities

    return fields


class OpenTargets(Source):
    key = "opentargets"
    label = "Open Targets"
    needs = ("targets",)

    # -- the mirror ---------------------------------------------------------

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        wanted = identity.ensembl_gene_id.strip()
        if not wanted:
            raise GeneNotInSource(
                f"Open Targets is keyed on Ensembl gene IDs and HGNC lists "
                f"none for {identity.symbol}"
            )

        path = entry.path("targets")
        try:
            if path.suffix == ".gz":
                lines = (line for line in open_text(path))
            else:
                lines = lines_for(path, "ensemblId", wanted)
            for line in lines:
                if not line.strip():
                    continue
                target = json.loads(line)
                if str(target.get("ensemblId", "")).strip() == wanted:
                    return _fields(target)
        except json.JSONDecodeError as exc:
            raise SourceError(f"{path.name} is not JSON Lines: {exc}") from None
        raise GeneNotInSource(f"{wanted} is not in Open Targets {entry.version}")

    # -- the API ------------------------------------------------------------

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        wanted = identity.ensembl_gene_id.strip()
        if not wanted:
            raise GeneNotInSource(
                f"Open Targets is keyed on Ensembl gene IDs and HGNC lists "
                f"none for {identity.symbol}"
            )

        url = f"{API}?target={wanted}&diseases=all"  # the cache key
        target, response = self._page(live, wanted, 0, url)
        if not target:
            raise GeneNotInSource(f"Open Targets has no target {wanted}")

        # Every association, not the first page of them.
        associated = target.setdefault("associatedDiseases", {}) or {}
        rows = associated.setdefault("rows", [])
        count = associated.get("count") if isinstance(associated.get("count"), int) else 0
        index = 1
        while len(rows) < count and index < MAX_PAGES:
            more, _ = self._page(live, wanted, index, f"{url}&page={index}")
            page_rows = (((more or {}).get("associatedDiseases") or {}).get("rows")) or []
            if not page_rows:
                break
            rows.extend(page_rows)
            index += 1

        # The platform names its release in the response headers only on
        # some deployments; the fetch date carries the weight otherwise.
        version = response.headers.get("X-Api-Version") or "API"
        return Fetched(_fields(target), version, response.fetched, url)

    def _page(self, live: Live, wanted: str, index: int, cache_key: str):
        try:
            response = live.post_json(
                self.key, API, {"query": QUERY, "variables": {
                    "ensg": wanted, "index": index, "size": PAGE}},
                cache_key=cache_key,
            )
        except NotFoundUpstream:
            raise GeneNotInSource(f"Open Targets has no target {wanted}") from None
        payload = response.payload or {}
        if payload.get("errors"):
            first = payload["errors"][0].get("message", "rejected the query")
            raise SourceError(f"Open Targets {first}")
        return (payload.get("data") or {}).get("target"), response
