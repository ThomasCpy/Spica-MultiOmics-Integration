"""Human Protein Atlas: antibody staining by tissue, and imaging localization.

Two mirror files, read independently:

    normal_tissue         Gene, Tissue, Cell type, Level, Reliability
    subcellular_location  Gene, Reliability, Main location, Additional location

Both are optional, not required. A mirror often has one before the other,
and half of HPA is better than none. The fields of an absent file say
`failed` and name the file. The fields of a present file build as usual.

API fallback: `proteinatlas.org/<ensembl id>.json` for the summary, and the
download API (`search_download.php`) for the profiles, one column per
tissue: consensus RNA (`t_RNA_*`), antibody staining by tissue (`t_APE_*`),
staining by cell type in each tissue (`ct_APE_*`), and mass-spectrometry
intensity in the 20 proteomics tissues of HPA (`t_ms_*`). Single-cell RNA
comes as the HPA call plus its enriched cell types. The full single-cell
atlas is a download file only, and its field says so.
"""

from __future__ import annotations

import re
from typing import Any

from spica.live import Fetched, Live, NotFoundUpstream
from spica.mirror import MirrorEntry
from spica.record import NullState, Resolution
from spica.sources.base import Absent, GeneNotInSource, Source, SourceError, read_tsv
from spica.sources.index import rows_for

GENE_COLUMN = "Gene"  # the Ensembl gene ID, despite the column title

# Staining strength, strongest last. Other values in the column (the
# pathology files use "Ascending" and the like) carry no strength and are
# left out rather than ranked against these.
LEVELS = ("Not detected", "Low", "Medium", "High")
LEVEL_RANK = {level.lower(): rank for rank, level in enumerate(LEVELS)}

# Antibody reliability, strongest last.
RELIABILITY = ("Uncertain", "Approved", "Supported", "Enhanced")
RELIABILITY_RANK = {word.lower(): rank for rank, word in enumerate(RELIABILITY)}

API = "https://www.proteinatlas.org"
DOWNLOAD = f"{API}/api/search_download.php"

#: HPA's 51 consensus tissues, as its download API names them. The numeric
#: suffixes are the API's own ("stomach 1", "skin 1"): they distinguish
#: sampling sites, and dropping them makes the column name invalid.
CONSENSUS_TISSUES = (
    "adipose tissue", "adrenal gland", "amygdala", "appendix", "basal ganglia",
    "blood vessel", "bone marrow", "breast", "cerebellum", "cerebral cortex",
    "cervix", "choroid plexus", "colon", "duodenum", "endometrium 1",
    "epididymis", "esophagus", "fallopian tube", "gallbladder", "heart muscle",
    "hippocampal formation", "hypothalamus", "kidney", "liver", "lung",
    "lymph node", "midbrain", "ovary", "pancreas", "parathyroid gland",
    "pituitary gland", "placenta", "prostate", "rectum", "retina",
    "salivary gland", "seminal vesicle", "skeletal muscle", "skin 1",
    "small intestine", "smooth muscle", "spinal cord", "spleen", "stomach 1",
    "testis", "thymus", "thyroid gland", "tongue", "tonsil", "urinary bladder",
    "vagina",
)

#: Tissues HPA scores by immunohistochemistry, as `t_APE_*` / `ct_APE_*`
#: columns name them.
STAINED_TISSUES = (
    "adipose_tissue", "adrenal_gland", "appendix", "bone_marrow", "breast", "bronchus",
    "brown_adipose_tissue", "cartilage", "caudate", "cerebellum", "cerebral_cortex",
    "cervix", "choroid_plexus", "colon", "dorsal_raphe", "duodenum", "efferent_ducts",
    "endometrium", "epididymis", "esophagus", "eye", "fallopian_tube", "gallbladder",
    "hair", "heart_muscle", "hippocampus", "hypothalamus", "kidney", "lactating_breast",
    "liver", "lung", "lymph_node", "nasopharynx", "oral_mucosa", "ovary", "pancreas",
    "parathyroid_gland", "pituitary_gland", "placenta", "prostate", "rectum", "retina",
    "salivary_gland", "seminal_vesicle", "skeletal_muscle", "skin", "small_intestine",
    "smooth_muscle", "soft_tissue", "sole_of_foot", "spleen", "stomach",
    "substantia_nigra", "testis", "thymus", "thyroid_gland", "tonsil", "urinary_bladder",
    "vagina",
)

#: HPA's 20 mass-spectrometry tissues, spelled as their `t_ms_*` columns are
#: (stomach is capitalised in HPA's own column code).
MS_TISSUES = (
    "blood_vessel", "bone_marrow", "cerebral_cortex", "colon", "duodenum",
    "fallopian_tube", "heart_muscle", "ileum", "jejunum", "kidney", "liver", "lung",
    "lymph_node", "ovary", "pancreas", "salivary_gland", "skeletal_muscle", "skin",
    "spleen", "Stomach",
)

#: Summary columns worth having beside the profiles.
SUMMARY_COLUMNS = {
    "rnats": "hpa_rna_tissue_specificity",
    "rnatd": "hpa_rna_tissue_distribution",
    "rnascs": "hpa_single_cell_specificity",
}

TISSUE_STAIN = "Tissue Annotation (IH) - "
CELL_STAIN = "Tissue Cell type Annotation (IH) - "
TISSUE_MS = "Tissue protein MS - "
CELL_TYPE_KEY = " / "  # "lung / alveolar cells type II"

EXPRESSION_FIELDS = ("hpa_protein_tissue_level", "hpa_protein_cell_type_level",
                     "hpa_protein_tissue_intensity", "hpa_protein_reliability")
RNA_FIELDS = ("hpa_rna_tissue_ntpm", "hpa_rna_tissue_specificity",
              "hpa_rna_tissue_distribution")
SINGLE_CELL_FIELDS = ("hpa_single_cell_specificity", "hpa_single_cell_enriched")
#: Fields only HPA's download files carry, each from its own optional file.
FILE_ONLY = {
    "hpa_single_cell_ncpm": "single_cell",
    "hpa_single_cell_tissue": "single_cell_tissue",
    "hpa_interactors": "interactions",
    "hpa_brain_region_ntpm": "brain_region",
}
LOCALIZATION_FIELDS = (
    "hpa_subcellular_main",
    "hpa_subcellular_additional",
    "hpa_subcellular_reliability",
)


def split_locations(cell: str) -> list[str]:
    """HPA location cells, which separate terms with `;` and sometimes `,`.

    No HPA location name contains either character, so splitting on both is
    safe and survives the separator changing between releases.
    """
    terms: list[str] = []
    for part in re.split(r"[;,]", cell):
        part = part.strip()
        if part and part not in terms:
            terms.append(part)
    return terms


def strongest(words: list[str], ranking: dict[str, int]) -> str:
    """The strongest of several ranked words, keeping the release's spelling."""
    ranked = [(ranking[w.strip().lower()], w.strip()) for w in words
              if w.strip().lower() in ranking]
    return max(ranked)[1] if ranked else ""


#: Fields only the download API fills. The mass-spectrometry profile is not
#: among them: the entry JSON carries a partial one to fall back on.
PROFILE_FIELDS = ("hpa_rna_tissue_ntpm", "hpa_rna_tissue_specificity",
                  "hpa_rna_tissue_distribution", "hpa_protein_tissue_level",
                  "hpa_protein_cell_type_level", "hpa_single_cell_specificity",
                  "hpa_single_cell_enriched", "hpa_interactions")


def profile_gap(state: NullState, reason: str) -> dict[str, Any]:
    return {name: Absent(state, reason) for name in PROFILE_FIELDS}


def stain_level(value: str) -> str:
    """A staining level as HPA's release files write it: "High", "Not detected"."""
    return value.strip().capitalize()


def consensus_name(tissue: str) -> str:
    """A consensus-RNA tissue as the release file names it.

    The API suffixes three of them with their sampling site ("skin 1",
    "stomach 1", "endometrium 1"); the consensus file, which is one value
    per tissue, does not.
    """
    return re.sub(r"\s+\d+$", "", tissue.strip().lower())


def stain_profiles(row: dict[str, Any]) -> dict[str, Any]:
    """Antibody staining by tissue and by cell type, from download columns.

    A tissue HPA has not stained comes back as null and is left out; a
    tissue it stained and saw nothing in comes back as "not detected" and
    is kept, because that is a result.
    """
    by_tissue: dict[str, str] = {}
    by_cell: dict[str, str] = {}
    for key, value in row.items():
        if not isinstance(value, str) or value.strip().lower() not in LEVEL_RANK:
            continue
        level = stain_level(value)
        if key.startswith(CELL_STAIN):
            tissue, _, cell = key[len(CELL_STAIN):].partition(" - ")
            if tissue and cell:
                by_cell[f"{tissue.strip().lower()}{CELL_TYPE_KEY}{cell.strip()}"] = level
        elif key.startswith(TISSUE_STAIN):
            by_tissue[key[len(TISSUE_STAIN):].strip().lower()] = level
    # A tissue's level is its strongest cell type, as on the mirror route:
    # HPA's own per-tissue call can sit below a cell type it scored higher.
    for key, level in by_cell.items():
        tissue = consensus_name(key.split(CELL_TYPE_KEY, 1)[0])
        held = by_tissue.get(tissue)
        if held is None or LEVEL_RANK[level.lower()] > LEVEL_RANK[held.lower()]:
            by_tissue[tissue] = level
    out: dict[str, Any] = {}
    if by_tissue:
        out["hpa_protein_tissue_level"] = by_tissue
    if by_cell:
        out["hpa_protein_cell_type_level"] = by_cell
    if not by_tissue and not by_cell:
        reason = "HPA has no antibody staining for this gene in normal tissue"
        out["hpa_protein_tissue_level"] = Absent(NullState.NOT_FOUND, reason)
        out["hpa_protein_cell_type_level"] = Absent(NullState.NOT_FOUND, reason)
    return out


def ms_profile(row: dict[str, Any]) -> dict[str, Any]:
    """Mass-spectrometry intensity in HPA's 20 proteomics tissues.

    HPA leaves a tissue empty where no peptide of the protein was found.
    Every one of the 20 tissues was run, so empty there is "not detected"
    and recorded as 0: a tissue with high RNA and no detected protein is a
    finding, and dropping it would hide exactly that.
    """
    profile: dict[str, float] = {}
    seen = False
    for key, value in row.items():
        if not key.startswith(TISSUE_MS):
            continue
        seen = True
        tissue = key[len(TISSUE_MS):].split(" [")[0].strip().lower()
        try:
            profile[tissue] = round(float(value), 2) if value not in (None, "") else 0.0
        except (TypeError, ValueError):
            continue
    if not seen:
        return {}
    if not any(profile.values()):
        return {"hpa_protein_tissue_intensity": Absent(
            NullState.NOT_FOUND,
            "HPA mass spectrometry: no peptide in 20 tissues")}
    return {"hpa_protein_tissue_intensity": profile}


_CACHE: dict[tuple[str, str], Any] = {}


def header_of(path) -> list[str]:
    from spica.sources.base import open_text

    with open_text(path) as handle:
        return handle.readline().rstrip("\r\n").lstrip("\ufeff").split("\t")


def _unit_column(path) -> str:
    return "nCPM" if "nCPM" in header_of(path) else "nTPM"


def _all_values(path, column: str) -> list[str]:
    """Every distinct value of a column, read once per file per process."""
    key = (str(path), column)
    if key not in _CACHE:
        _CACHE[key] = sorted({row[column].strip() for row in read_tsv(path, (column,))
                              if row.get(column, "").strip()})
    return _CACHE[key]


def _id_names(path) -> dict[str, str]:
    key = (str(path), "names")
    if key not in _CACHE:
        names: dict[str, str] = {}
        for row in read_tsv(path, (GENE_COLUMN, "Gene name")):
            names.setdefault(row[GENE_COLUMN].strip(), row["Gene name"].strip())
        _CACHE[key] = names
    return _CACHE[key]



def consensus_partners(gene_id: str, path) -> dict[str, dict[str, Any]]:
    """Each partner of `gene_id` in HPA's consensus interaction file, by
    Ensembl ID: its name where the release gives one, and the datasets that
    saw the pair (IntAct, BioGRID, OpenCell, BioPlex) where it says."""
    columns = header_of(path)
    # HPA 25 names the columns ensembl_gene_id_1/2 and drops the gene
    # names; earlier releases had ensg_id_1/2 with names beside them.
    first, second = (("ensembl_gene_id_1", "ensembl_gene_id_2")
                     if "ensembl_gene_id_1" in columns else ("ensg_id_1", "ensg_id_2"))
    partners: dict[str, dict[str, Any]] = {}
    for row in read_tsv(path, (first, second)):
        one, two = row[first].strip(), row[second].strip()
        if gene_id not in (one, two):
            continue
        other_id = two if one == gene_id else one
        name = (row.get("gene_name_2", "") if one == gene_id else row.get("gene_name_1", "")).strip()
        found = partners.setdefault(other_id, {"name": name, "datasets": []})
        for dataset in row.get("datasets", "").strip().split("_"):
            if dataset and dataset not in found["datasets"]:
                found["datasets"].append(dataset)
    return partners


class Hpa(Source):
    key = "hpa"
    label = "Human Protein Atlas"
    needs = ()  # each file is checked in collect so one can be missing

    def collect(self, identity: Resolution, entry: MirrorEntry) -> dict[str, Any]:
        gene_id = identity.ensembl_gene_id.strip()
        if not gene_id:
            # HPA is keyed on Ensembl IDs only; without one there is nothing
            # to look up, and guessing by symbol would cross gene families.
            raise GeneNotInSource(
                f"HPA is keyed on Ensembl gene IDs and HGNC lists none for "
                f"{identity.symbol}"
            )

        fields: dict[str, Any] = {}
        fields.update(self._expression(gene_id, entry))
        fields.update(self._localization(gene_id, entry))
        fields.update(self._rna(gene_id, entry))
        for name in SINGLE_CELL_FIELDS:
            fields[name] = Absent(
                NullState.NOT_COVERED,
                "HPA's single-cell call and enriched cell types come from its API; "
                "no mirrored file carries them")
        fields.update(self._file_profiles(gene_id, entry))

        # Absent from every file is absence from HPA, reported once. A file
        # that could not be read is not absence, so it keeps its own reason.
        if all(
            isinstance(value, Absent) and value.state is NullState.NOT_FOUND
            for value in fields.values()
        ):
            raise GeneNotInSource(f"{gene_id} is not in HPA {entry.version}")
        return fields

    def locator(self, field_name: str, entry: MirrorEntry) -> str:
        if field_name == "hpa_protein_tissue_intensity" and "ms_tissue" in entry.files:
            file_key = "ms_tissue"
        elif field_name in FILE_ONLY or field_name == "hpa_interactions":
            file_key = FILE_ONLY.get(field_name, "interactions")
        elif field_name in RNA_FIELDS or field_name in SINGLE_CELL_FIELDS:
            file_key = "rna_tissue"
        elif field_name in EXPRESSION_FIELDS:
            file_key = "normal_tissue"
        else:
            file_key = "subcellular_location"
        return entry.files.get(file_key, "")

    def _missing_file(self, name: str, entry: MirrorEntry) -> str:
        """Why the file cannot be read, or "" if it can."""
        if name not in entry.files:
            return f"the mirror manifest declares no HPA {name} file"
        if not entry.path(name).exists():
            return f"{entry.files[name]} is not in {entry.root}"
        return ""

    def _expression(self, gene_id: str, entry: MirrorEntry) -> dict[str, Any]:
        problem = self._missing_file("normal_tissue", entry)
        if problem:
            return {
                name: Absent(NullState.FAILED, problem) for name in EXPRESSION_FIELDS
            }

        by_tissue: dict[str, str] = {}
        by_cell: dict[str, str] = {}
        reliabilities: list[str] = []
        required = (GENE_COLUMN, "Tissue", "Level")
        for row in rows_for(entry.path("normal_tissue"), GENE_COLUMN, gene_id, required):
            # HPA 25 capitalises tissues ("Adipose tissue"); its API and its
            # other files do not, and a record names a tissue one way.
            tissue = row.get("Tissue", "").strip().lower()
            level = stain_level(row.get("Level", ""))
            if not tissue or level.lower() not in LEVEL_RANK:
                continue
            # One tissue, several cell types. A triage call uses the
            # strongest staining in the tissue. Each cell type stays beside
            # it, so the view can open the tissue.
            current = by_tissue.get(tissue)
            if current is None or LEVEL_RANK[level.lower()] > LEVEL_RANK[current.lower()]:
                by_tissue[tissue] = level
            cell = row.get("Cell type", "").strip()
            if cell:
                # HPA 25 stains some tissues twice ("Skin 1", "Skin 2"); the
                # sample is kept for cell types, as the API keeps it.
                sample = (row.get("IHC tissue name", "") or "").strip().lower() or tissue
                key = f"{sample}{CELL_TYPE_KEY}{cell}"
                held = by_cell.get(key)
                if held is None or LEVEL_RANK[level.lower()] > LEVEL_RANK[held.lower()]:
                    by_cell[key] = level
            reliabilities.append(row.get("Reliability", "").strip())

        if not by_tissue:
            reason = f"HPA {entry.version} has no tissue staining for {gene_id}"
            return {
                name: Absent(NullState.NOT_FOUND, reason) for name in EXPRESSION_FIELDS
            }

        fields: dict[str, Any] = {
            "hpa_protein_tissue_level": by_tissue,
            "hpa_protein_tissue_intensity": Absent(
                NullState.NOT_COVERED,
                "normal_tissue.tsv is antibody staining; the mass-spectrometry "
                "intensities are a separate HPA download",
            ),
        }
        if by_cell:
            fields["hpa_protein_cell_type_level"] = by_cell
        best = strongest(reliabilities, RELIABILITY_RANK)
        if best:
            fields["hpa_protein_reliability"] = best
        return fields

    def _rna(self, gene_id: str, entry: MirrorEntry) -> dict[str, Any]:
        """Consensus RNA per tissue, from `rna_tissue_consensus.tsv`.

        The specificity call and the distribution are not in that file. HPA
        publishes them as separate summaries. They are thus `not_covered`
        here, not silently absent.
        """
        problem = self._missing_file("rna_tissue", entry)
        if problem:
            return {name: Absent(NullState.FAILED, problem) for name in RNA_FIELDS}

        profile: dict[str, float] = {}
        required = (GENE_COLUMN, "Tissue", "nTPM")
        for row in rows_for(entry.path("rna_tissue"), GENE_COLUMN, gene_id, required):
            tissue = row.get("Tissue", "").strip()
            try:
                value = round(float(row.get("nTPM", "")), 2)
            except ValueError:
                continue
            if tissue:
                profile[tissue] = value

        summary = Absent(
            NullState.NOT_COVERED,
            "rna_tissue_consensus.tsv carries the values, not HPA's "
            "specificity call; the API route has it",
        )
        if not profile:
            reason = f"HPA {entry.version} has no consensus RNA for {gene_id}"
            return {"hpa_rna_tissue_ntpm": Absent(NullState.NOT_FOUND, reason),
                    "hpa_rna_tissue_specificity": summary,
                    "hpa_rna_tissue_distribution": summary}
        return {"hpa_rna_tissue_ntpm": profile,
                "hpa_rna_tissue_specificity": summary,
                "hpa_rna_tissue_distribution": summary}

    def _file_profiles(self, gene_id: str, entry: MirrorEntry) -> dict[str, Any]:
        """The full single-cell atlas, cell types by tissue, and interaction
        partners: newer optional files, each read only if declared."""
        fields: dict[str, Any] = {}

        def absent(file_key: str) -> Absent:
            return Absent(NullState.NOT_COVERED,
                          f"the mirror declares no HPA {file_key} file")

        if self._missing_file("single_cell", entry):
            fields["hpa_single_cell_ncpm"] = absent("single_cell")
        else:
            profile: dict[str, float] = {}
            # HPA 25 reports single-cell levels as nCPM; earlier releases
            # called the same column nTPM.
            unit = _unit_column(entry.path("single_cell"))
            for row in rows_for(entry.path("single_cell"), GENE_COLUMN, gene_id,
                                (GENE_COLUMN, "Cell type", unit)):
                try:
                    profile[row["Cell type"].strip()] = round(float(row[unit]), 2)
                except ValueError:
                    continue
            fields["hpa_single_cell_ncpm"] = profile or Absent(
                NullState.NOT_FOUND, f"HPA {entry.version} has no single-cell profile for {gene_id}")

        if self._missing_file("brain_region", entry):
            fields["hpa_brain_region_ntpm"] = absent("brain_region")
        else:
            regions: dict[str, float] = {}
            for row in rows_for(entry.path("brain_region"), GENE_COLUMN, gene_id,
                                (GENE_COLUMN, "Brain region", "nTPM")):
                try:
                    regions[row["Brain region"].strip()] = round(float(row["nTPM"]), 2)
                except ValueError:
                    continue
            fields["hpa_brain_region_ntpm"] = regions or Absent(
                NullState.NOT_FOUND, f"HPA {entry.version} has no brain-region profile for {gene_id}")

        if self._missing_file("single_cell_tissue", entry):
            fields["hpa_single_cell_tissue"] = absent("single_cell_tissue")
        else:
            by_cell: dict[str, float] = {}
            unit = _unit_column(entry.path("single_cell_tissue"))
            required = (GENE_COLUMN, "Tissue", "Cell type", unit)
            for row in rows_for(entry.path("single_cell_tissue"), GENE_COLUMN, gene_id, required):
                try:
                    value = round(float(row[unit]), 2)
                except ValueError:
                    continue
                # Several clusters of one cell type in one tissue: the
                # highest, as everywhere else an organ is summarised.
                key = f"{row['Tissue'].strip()}{CELL_TYPE_KEY}{row['Cell type'].strip()}"
                by_cell[key] = max(value, by_cell.get(key, value))
            fields["hpa_single_cell_tissue"] = by_cell or Absent(
                NullState.NOT_FOUND, f"HPA {entry.version} has no tissue single-cell data for {gene_id}")

        if self._missing_file("interactions", entry):
            fields["hpa_interactors"] = absent("interactions")
            fields["hpa_interactions"] = absent("interactions")
        else:
            partners: list[str] = []
            names = None
            for other_id, found in consensus_partners(gene_id, entry.path("interactions")).items():
                name = found["name"]
                if not name:
                    if names is None:
                        names = self._gene_names(entry)
                    name = names.get(other_id, other_id)
                if name and name not in partners:
                    partners.append(name)
            if partners:
                fields["hpa_interactors"] = partners
                fields["hpa_interactions"] = len(partners)
            else:
                reason = (f"no partner for {gene_id} in the HPA {entry.version} consensus interaction "
                          f"file; the HPA API can count more, from single databases")
                fields["hpa_interactors"] = Absent(NullState.NOT_FOUND, reason)
                fields["hpa_interactions"] = Absent(NullState.NOT_FOUND, reason)
        if not self._missing_file("ms_tissue", entry):
            fields["hpa_protein_tissue_intensity"] = self._ms_tissue(gene_id, entry)
        return fields

    def _ms_tissue(self, gene_id: str, entry: MirrorEntry) -> Any:
        """Mass-spectrometry intensity per tissue, from the HPA ms_tissue file.

        The file lists only detections. Each tissue in the HPA run occurs in
        it for some gene. A tissue absent for this gene is thus "not
        detected" and recorded as 0, as on the API route.
        """
        path = entry.path("ms_tissue")
        assayed = _all_values(path, "Tissue")
        profile = {tissue: 0.0 for tissue in assayed}
        for row in rows_for(path, GENE_COLUMN, gene_id, (GENE_COLUMN, "Tissue", "Intensity")):
            try:
                profile[row["Tissue"].strip()] = round(float(row["Intensity"]), 2)
            except ValueError:
                continue
        if not any(profile.values()):
            return Absent(NullState.NOT_FOUND,
                          f"HPA's mass spectrometry found no peptide of this protein in any of "
                          f"its {len(assayed)} tissues")
        return profile

    def _gene_names(self, entry: MirrorEntry) -> dict[str, str]:
        """Ensembl ID to gene name, from the consensus RNA file every gene is in."""
        return _id_names(entry.path("rna_tissue"))

    def _localization(self, gene_id: str, entry: MirrorEntry) -> dict[str, Any]:
        problem = self._missing_file("subcellular_location", entry)
        if problem:
            return {
                name: Absent(NullState.FAILED, problem) for name in LOCALIZATION_FIELDS
            }

        row: dict[str, str] | None = None
        required = (GENE_COLUMN, "Main location")
        for candidate in rows_for(entry.path("subcellular_location"), GENE_COLUMN, gene_id, required):
            row = candidate
            break

        if row is None:
            reason = f"HPA {entry.version} has no imaging entry for {gene_id}"
            return {
                name: Absent(NullState.NOT_FOUND, reason)
                for name in LOCALIZATION_FIELDS
            }

        fields: dict[str, Any] = {}
        main = split_locations(row.get("Main location", ""))
        if main:
            fields["hpa_subcellular_main"] = main
        additional = split_locations(row.get("Additional location", ""))
        if additional:
            fields["hpa_subcellular_additional"] = additional
        reliability = row.get("Reliability", "").strip()
        if reliability:
            fields["hpa_subcellular_reliability"] = reliability
        return fields

    # -- the API ------------------------------------------------------------

    def fetch(self, identity: Resolution, live: Live) -> Fetched:
        if not identity.ensembl_gene_id:
            raise GeneNotInSource(
                f"HPA is keyed on Ensembl gene IDs and HGNC lists none for "
                f"{identity.symbol}"
            )
        url = f"{API}/{identity.ensembl_gene_id}.json"
        try:
            response = live.get_json(self.key, url)
        except NotFoundUpstream:
            raise GeneNotInSource(
                f"HPA has no entry for {identity.ensembl_gene_id}"
            ) from None

        payload = response.payload
        entry = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(entry, dict):
            raise SourceError("HPA answered with something other than an entry")

        fields: dict[str, Any] = {}

        # Only the tissues the protein is specific to: a fallback for when the
        # full mass-spectrometry profile below cannot be had.
        intensity = self._numbers(entry.get("Protein tissue specific Intensity"))
        if intensity:
            fields["hpa_protein_tissue_intensity"] = intensity
        for field_name, key in (
            ("hpa_protein_reliability", "Reliability (IH)"),
            ("hpa_subcellular_reliability", "Reliability (IF)"),
        ):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                fields[field_name] = value.strip()
        for field_name, key in (
            ("hpa_subcellular_main", "Subcellular main location"),
            ("hpa_subcellular_additional", "Subcellular additional location"),
        ):
            places = self._terms(entry.get(key))
            if places:
                fields[field_name] = places

        # The entry JSON carries only the tissues this gene is *specific*
        # to; the whole profiles come from the download API, one column per
        # tissue.
        fields.update(self._profiles(identity, live))
        for name, file_key in FILE_ONLY.items():
            fields.setdefault(name, Absent(
                NullState.NOT_COVERED,
                f"HPA's API does not carry this; mirror its {file_key} file"))

        # Its own release is not in the payload, so the fetch date carries it.
        return Fetched(fields, "API", response.fetched, url)

    def _profiles(self, identity: Resolution, live: Live) -> dict[str, Any]:
        """Every per-tissue profile HPA's download API has, in one request:
        consensus RNA, antibody staining by tissue and by cell type,
        mass-spectrometry intensity, and the single-cell call."""
        columns = ["g", "eg"]
        columns += [f"t_RNA_{tissue.replace(' ', '_')}" for tissue in CONSENSUS_TISSUES]
        columns += [f"t_APE_{tissue}" for tissue in STAINED_TISSUES]
        columns += [f"ct_APE_{tissue}" for tissue in STAINED_TISSUES]
        columns += [f"t_ms_{tissue}" for tissue in MS_TISSUES]
        columns += list(SUMMARY_COLUMNS) + ["rnascsm", "interactions"]
        url = (f"{DOWNLOAD}?search={identity.ensembl_gene_id}&format=json"
               f"&columns={','.join(columns)}&compress=no")
        try:
            response = live.get_json(self.key, url)
        except NotFoundUpstream:
            return profile_gap(NullState.NOT_FOUND, "HPA's download API has no row for this gene")
        except Exception as exc:
            # Losing the profiles costs their fields, not the source, and
            # each says it failed: a fetch error is not an absence.
            return profile_gap(NullState.FAILED, f"HPA's download API could not be read: {exc}")

        rows = response.payload if isinstance(response.payload, list) else []
        row = next((r for r in rows
                    if str(r.get("Ensembl", "")).strip() == identity.ensembl_gene_id),
                   None)
        if not isinstance(row, dict):
            return profile_gap(NullState.NOT_FOUND, "HPA's download API has no row for this gene")

        profile: dict[str, float] = {}
        for key, value in row.items():
            # "Tissue RNA - liver [nTPM]" -> "liver"
            if not key.startswith("Tissue RNA - ") or "[nTPM]" not in key:
                continue
            tissue = consensus_name(key[len("Tissue RNA - "):].split(" [")[0])
            try:
                profile[tissue] = round(float(value), 2)
            except (TypeError, ValueError):
                continue

        fields: dict[str, Any] = {}
        if profile:
            fields["hpa_rna_tissue_ntpm"] = profile
        for title, field_name in (("RNA tissue specificity",
                                   "hpa_rna_tissue_specificity"),
                                  ("RNA tissue distribution",
                                   "hpa_rna_tissue_distribution"),
                                  ("RNA single cell type specificity",
                                   "hpa_single_cell_specificity")):
            value = row.get(title)
            if isinstance(value, str) and value.strip():
                fields[field_name] = value.strip()
        fields.update(stain_profiles(row))
        fields.update(ms_profile(row))
        # The API's "Interactions" counts partners in every database HPA
        # draws on (926 for EGFR); the field is the consensus network, which
        # only the interaction_consensus file carries (187 for EGFR). A
        # different measure under the same name would not compare.
        fields["hpa_interactions"] = Absent(
            NullState.NOT_COVERED,
            "HPA's API counts partners across all its databases, not its consensus "
            "network; mirror interaction_consensus.tsv")

        enriched = self._numbers(row.get("RNA single cell type specific nCPM"))
        if enriched:
            fields["hpa_single_cell_enriched"] = enriched
        elif "hpa_single_cell_specificity" in fields:
            fields["hpa_single_cell_enriched"] = Absent(
                NullState.NOT_FOUND,
                f"HPA calls this gene {fields['hpa_single_cell_specificity'].lower()} "
                f"across cell types and enriches none")
        return fields

    @staticmethod
    def _terms(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return split_locations(str(value or ""))

    @staticmethod
    def _numbers(value: Any) -> dict[str, float]:
        """HPA sends its numbers as strings; anything unparseable is dropped
        rather than guessed at."""
        if not isinstance(value, dict):
            return {}
        numbers: dict[str, float] = {}
        for tissue, raw in value.items():
            try:
                numbers[str(tissue)] = round(float(raw), 2)
            except (TypeError, ValueError):
                continue
        return numbers
