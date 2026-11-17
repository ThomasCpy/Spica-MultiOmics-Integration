"""GWAS Catalog: the traits associated with common variants at the gene.

All published genome-wide associations that the Catalog curates, with the
gene mapping of the Catalog: a variant inside the gene or, between genes,
the nearest gene on each side. The second case is weaker evidence for this
gene, and each trait says which case applies.

Mirror file: `traits`, one row per gene and trait, built by
`spica/mirrorbuild.py` from the full associations download of the Catalog.
It holds the p-value and lead variant of the strongest association, the
association and study counts, and the ontology terms of the trait (EFO,
MONDO). The disease view uses these terms to join it to Open Targets.

No API route: the Catalog REST API answers per variant and per study, not
per gene in one call. EMBL-EBI terms of use; cite the Catalog.
"""

from __future__ import annotations

from typing import Any

from spica.mirror import MirrorEntry
from spica.record import Resolution
from spica.sources.base import GeneNotInSource, Source
from spica.sources.index import rows_for

#: p below 5e-8, the conventional genome-wide threshold, as -log10 p.
GENOME_WIDE = 7.3


def traits(ensembl_id: str, path) -> list[dict[str, Any]]:
    """The gene's rows from the traits file, strongest first."""
    found = []
    for row in rows_for(path, "gene_id", ensembl_id.strip().upper()):
        found.append({**row, "mlog10p": float(row["mlog10p"]), "associations": int(row["associations"]),
                      "studies": int(row["studies"])})
    return sorted(found, key=lambda row: (-row["mlog10p"], row["trait"]))


class Gwas(Source):
    key = "gwas"
    label = "GWAS Catalog"
    needs = ("traits",)

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        found = traits(identity.ensembl_gene_id, entry.path("traits")) if identity.ensembl_gene_id else []
        if not found:
            raise GeneNotInSource(f"The GWAS Catalog ({entry.version}) maps no association to "
                                  f"{identity.ensembl_gene_id or identity.symbol}")
        lead = []
        for row in found:
            effect = f", OR or beta {row['or_beta']}" if row["or_beta"] else ""
            context = f", {row['context'].replace('_', ' ')}" if row["context"] else ""
            allele = str(row["risk_allele"])
            # The Catalog writes an unreported risk allele as "rs123-?".
            if allele.endswith("-?"):
                allele = f"{allele[:-2]} (risk allele not reported)"
            n, k = int(row["associations"]), int(row["studies"])
            lead.append(f"{row['trait']}: {allele}, p {row['p_value']}{effect}{context}, "
                        f"{row['relation']}; {n} {'association' if n == 1 else 'associations'} in "
                        f"{k} {'study' if k == 1 else 'studies'} ({row['study']})")
        return {
            "gwas_associations": sum(row["associations"] for row in found),
            "gwas_genome_wide_traits": sum(row["mlog10p"] >= GENOME_WIDE for row in found),
            "gwas_traits": {row["trait"]: round(row["mlog10p"], 1) for row in found},
            "gwas_lead_variants": lead,
        }

    def locator(self, field_name: str, entry: MirrorEntry) -> str:
        return entry.files.get("traits", "")
