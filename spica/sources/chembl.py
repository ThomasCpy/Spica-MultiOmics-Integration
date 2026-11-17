"""ChEMBL: the compounds already made against this target.

Adapted from the druggability pipeline of the integrator, as facts, not a
recommendation. The data: the ChEMBL target, each drug or clinical
candidate with a known mechanism on it and its phase, the highest phase
reached, and the number of bioactivity measurements. A target with an
approved drug and thousands of measurements is a different start point
from a target with none.

Licence: CC BY-SA 3.0. Share-alike applies to all that is built from these
values, as `docs/licences.md` records. The record names ChEMBL on each value.

Mirror file: `targets`, JSON Lines that Spica defines, one object per
UniProt accession: {"accession", "target", "activities", "drugs": [{"name",
"phase", "action"}]}.

API: `ebi.ac.uk/chembl/api/data`, target by accession, then its mechanisms,
the molecules that they name, and a count of its activities.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from spica.live import Fetched, Live, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError
from spica.sources.index import lines_for

API = "https://www.ebi.ac.uk/chembl/api/data"
PHASES = {4: "approved", 3: "phase 3", 2: "phase 2", 1: "phase 1", 0.5: "early phase 1"}


def summarise(target: str, activities: int, drugs: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {"chembl_target": target, "chembl_activities": activities}
    ordered = sorted(drugs, key=lambda d: (-(d.get("phase") or 0), d.get("name") or ""))
    lines = []
    for drug in ordered:
        phase = drug.get("phase")
        stage = PHASES.get(phase, f"phase {phase:g}") if isinstance(phase, (int, float)) else "phase unknown"
        action = str(drug.get("action") or "").lower().replace("_", " ")
        lines.append(f"{drug.get('name') or drug.get('id')} ({stage}{', ' + action if action else ''})")
    if lines:
        fields["chembl_drugs"] = lines
        phases = [d["phase"] for d in drugs if isinstance(d.get("phase"), (int, float))]
        if phases:
            fields["chembl_max_phase"] = float(max(phases))
    else:
        reason = "ChEMBL records no drug or candidate with a mechanism on this target"
        fields["chembl_drugs"] = Absent(NullState.NOT_FOUND, reason)
        fields["chembl_max_phase"] = Absent(NullState.NOT_FOUND, reason)
    return fields


class ChEMBL(Source):
    key = "chembl"
    label = "ChEMBL"
    needs = ("targets",)

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        wanted = identity.uniprot_accession.strip().upper()
        if not wanted:
            raise GeneNotInSource("ChEMBL targets are matched on UniProt accessions and there is none")
        for line in lines_for(entry.path("targets"), "accession", wanted):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SourceError(f"ChEMBL targets file: {exc}") from None
            if str(row.get("accession", "")).upper() == wanted:
                return summarise(str(row.get("target", "")), int(row.get("activities") or 0),
                                 list(row.get("drugs") or []))
        raise GeneNotInSource(f"ChEMBL {entry.version} has no single-protein target for {wanted}")

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        accession = identity.uniprot_accession.strip().upper()
        if not accession:
            raise GeneNotInSource("ChEMBL targets are matched on UniProt accessions and there is none")
        url = self._url("target.json", target_components__accession=accession,
                        target_type="SINGLE PROTEIN", limit=20)
        try:
            response = live.get_json(self.key, url)
        except NotFoundUpstream:
            raise GeneNotInSource(f"ChEMBL has no single-protein target for {accession}") from None
        targets = [t for t in (response.payload or {}).get("targets", [])
                   if t.get("organism") == "Homo sapiens"]
        if not targets:
            raise GeneNotInSource(f"ChEMBL has no single-protein target for {accession}")
        target = str(targets[0]["target_chembl_id"])

        mechanisms = self._all(live, "mechanism.json", "mechanisms", target_chembl_id=target)
        names: dict[str, str] = {}
        ids = sorted({m["molecule_chembl_id"] for m in mechanisms if m.get("molecule_chembl_id")})
        for start in range(0, len(ids), 50):
            molecules = self._all(live, "molecule.json", "molecules",
                                  molecule_chembl_id__in=",".join(ids[start:start + 50]))
            names.update({m["molecule_chembl_id"]: m.get("pref_name") or m["molecule_chembl_id"]
                          for m in molecules})
        drugs = []
        for mechanism in mechanisms:
            mid = mechanism.get("molecule_chembl_id")
            phase = mechanism.get("max_phase")
            try:
                phase = float(phase) if phase is not None else None
            except (TypeError, ValueError):
                phase = None
            drugs.append({"id": mid, "name": names.get(mid, mid), "phase": phase,
                          "action": mechanism.get("action_type")})
        # One line per molecule: a drug with two mechanism rows is one drug.
        unique = {}
        for drug in drugs:
            held = unique.get(drug["id"])
            if held is None or (drug["phase"] or 0) > (held["phase"] or 0):
                unique[drug["id"]] = drug

        count = live.get_json(self.key, self._url("activity.json", target_chembl_id=target, limit=1))
        activities = int(((count.payload or {}).get("page_meta") or {}).get("total_count") or 0)
        return Fetched(summarise(target, activities, list(unique.values())), "API",
                       response.fetched, url)

    @staticmethod
    def _url(path: str, **query: Any) -> str:
        return f"{API}/{path}?{urllib.parse.urlencode({**query, 'format': 'json'})}"

    def _all(self, live: Live, path: str, key: str, **query: Any) -> list[dict[str, Any]]:
        """Every page of a ChEMBL list: nothing is cut to the first page."""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            try:
                page = live.get_json(self.key, self._url(path, limit=1000, offset=offset, **query))
            except NotFoundUpstream:
                return out
            payload = page.payload or {}
            items = payload.get(key) or []
            out.extend(i for i in items if isinstance(i, dict))
            total = int((payload.get("page_meta") or {}).get("total_count") or 0)
            offset += len(items)
            if not items or offset >= total:
                return out
