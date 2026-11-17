"""AlphaFold DB: the prediction quality of the protein, and its tolerance to change.

Two data sets from one place, both CC BY 4.0:

*The confidence of the AlphaFold model.* Mean pLDDT and the share of
residues in each band. Structure-based design can start from a target with
a confident fold. A long stretch below 50 is usually disorder, not failure.

*AlphaMissense*: a pathogenicity score for each possible single amino-acid
substitution. Its mean over the protein measures constraint. A protein where
most changes are predicted damaging tolerates little change. This matters
for safety and for the reading of patient variants. Unlike a peak
expression value, it compares directly between genes.

Mirror file: `summary`, a table that Spica defines (accession, mean_plddt,
the four band shares, am_mean, am_pathogenic_share). It comes from the API
or from the bulk downloads of AlphaFold DB; `docs/data-mirror.md` gives the
columns.

API: `alphafold.ebi.ac.uk/api/prediction/<accession>`, and the per-model
AlphaMissense table that it links to.
"""

from __future__ import annotations

from typing import Any

from spica.live import Fetched, Live, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError, read_tsv

API = "https://alphafold.ebi.ac.uk/api/prediction"

BANDS = (("fractionPlddtVeryHigh", "very high (90 and above)"),
         ("fractionPlddtConfident", "confident (70 to 90)"),
         ("fractionPlddtLow", "low (50 to 70)"),
         ("fractionPlddtVeryLow", "very low (below 50)"))


def missense(table: str) -> dict[str, Any]:
    """Mean pathogenicity and the likely-pathogenic share, from the CSV."""
    scores: list[float] = []
    pathogenic = 0
    for line in table.splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        try:
            scores.append(float(parts[1]))
        except ValueError:
            continue
        if parts[2].strip() == "LPath":
            pathogenic += 1
    if not scores:
        return {}
    return {"alphamissense_mean": round(sum(scores) / len(scores), 3),
            "alphamissense_pathogenic_share": round(100 * pathogenic / len(scores), 1)}


def per_residue_missense(table: str) -> dict[int, float]:
    """Mean pathogenicity at each position, over its 19 substitutions."""
    sums: dict[int, list[float]] = {}
    for line in table.splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) < 2 or len(parts[0]) < 3:
            continue
        try:
            position = int(parts[0][1:-1])
            sums.setdefault(position, []).append(float(parts[1]))
        except ValueError:
            continue
    return {pos: round(sum(v) / len(v), 3) for pos, v in sums.items()}


class AlphaFold(Source):
    key = "alphafold"
    label = "AlphaFold DB"
    needs = ("summary",)

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        wanted = identity.uniprot_accession.strip().upper()
        if not wanted:
            raise GeneNotInSource("AlphaFold DB is keyed on UniProt accessions and there is none")
        for row in read_tsv(entry.path("summary"), ("accession", "mean_plddt")):
            if row.get("accession", "").strip().upper() != wanted:
                continue
            fields: dict[str, Any] = {"alphafold_mean_plddt": float(row["mean_plddt"])}
            bands = {}
            for column, label in (("very_high", BANDS[0][1]), ("confident", BANDS[1][1]),
                                  ("low", BANDS[2][1]), ("very_low", BANDS[3][1])):
                try:
                    bands[label] = round(100 * float(row.get(column, "")), 1)
                except ValueError:
                    continue
            if bands:
                fields["alphafold_confidence_bands"] = bands
            for column, name in (("am_mean", "alphamissense_mean"),
                                 ("am_pathogenic_share", "alphamissense_pathogenic_share")):
                try:
                    fields[name] = float(row.get(column, ""))
                except ValueError:
                    fields[name] = Absent(NullState.NOT_FOUND,
                                          "no AlphaMissense scores for this model")
            return fields
        raise GeneNotInSource(f"AlphaFold DB {entry.version} has no model for {wanted}")

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        accession = identity.uniprot_accession.strip().upper()
        if not accession:
            raise GeneNotInSource("AlphaFold DB is keyed on UniProt accessions and there is none")
        model, url, response = prediction(accession, live)
        fields: dict[str, Any] = {}
        if isinstance(model.get("globalMetricValue"), (int, float)):
            fields["alphafold_mean_plddt"] = round(float(model["globalMetricValue"]), 1)
        bands = {label: round(100 * float(model[key]), 1)
                 for key, label in BANDS if isinstance(model.get(key), (int, float))}
        if bands:
            fields["alphafold_confidence_bands"] = bands
        table = substitutions(model, live)
        scored = missense(table) if table else {}
        if scored:
            fields.update(scored)
        else:
            reason = "AlphaFold DB has no AlphaMissense table for this model"
            fields["alphamissense_mean"] = Absent(NullState.NOT_FOUND, reason)
            fields["alphamissense_pathogenic_share"] = Absent(NullState.NOT_FOUND, reason)
        version = f"v{model['latestVersion']}" if model.get("latestVersion") else "API"
        return Fetched(fields, version, response.fetched, url)


def prediction(accession: str, live: Live):
    """The canonical model's record: the one whose UniProt range starts at 1."""
    url = f"{API}/{accession}"
    try:
        response = live.get_json("alphafold", url)
    except NotFoundUpstream:
        raise GeneNotInSource(f"AlphaFold DB has no model for {accession}") from None
    models = response.payload if isinstance(response.payload, list) else []
    models = [m for m in models if isinstance(m, dict)]
    if not models:
        raise SourceError("AlphaFold DB answered with no model")
    model = next((m for m in models if m.get("uniprotAccession") == accession
                  and m.get("uniprotStart") == 1), models[0])
    return model, url, response


def substitutions(model: dict[str, Any], live: Live) -> str:
    url = model.get("amAnnotationsUrl")
    if not url:
        return ""
    try:
        return str(live.get_text("alphafold", url).payload or "")
    except NotFoundUpstream:
        return ""
