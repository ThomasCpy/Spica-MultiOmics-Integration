"""The fixed gene-record schema.

Each record has exactly these fields, in this order, whatever the gene and
the mirror. Records thus stack into the multi-gene table with no special
case per gene.

Each field names the one source that owns it, by design. Two sources can
hold the same value (HGNC and Ensembl both know an Ensembl gene ID). A fixed
owner keeps the record deterministic. It does not depend on which source
answers first.

`mono` marks the fields that use JetBrains Mono, as the art direction
requires (IDs, scores, sequences). The flag lives here, so the interface
needs no separate list of data fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "1"

#: The groups of the record, in reading order. First the identity of the
#: gene, then its genome position, its RNA, its protein, its disease links.
#: The judgement comes last, because each judgement derives from the data
#: before it.
SECTIONS: dict[str, str] = {
    "identity": "Identity",
    "genomics": "Genomics",
    "transcriptomics": "Transcriptomics",
    "proteomics": "Proteomics",
    "essentiality": "Essentiality",
    "clinical": "Clinical",
    "insights": "Predictive insights",
}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    section: str
    label: str
    type: str
    source: str  # source key, or "derived"
    unit: str = ""
    mono: bool = False
    derived_from: tuple[str, ...] = ()
    description: str = ""

    @property
    def derived(self) -> bool:
        return self.source == "derived"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "section": self.section,
            "label": self.label,
            "type": self.type,
            "source": self.source,
            "unit": self.unit,
            "mono": self.mono,
            "derived_from": list(self.derived_from),
            "description": self.description,
        }


def check_type(spec: FieldSpec, value: Any) -> str:
    """Return "" if `value` fits the field's type, else why it does not.

    Adapters are the likeliest place for a quiet mistake (a column read as
    text where the schema promises a number). Checking here turns that into
    a `failed` field with a readable reason rather than a corrupt record.
    """
    kind = spec.type
    if kind in ("text", "sequence"):
        if not isinstance(value, str) or not value:
            return f"expected non-empty text, got {type(value).__name__}"
    elif kind == "text_list":
        if not isinstance(value, list) or not value:
            return f"expected a non-empty list, got {type(value).__name__}"
        if not all(isinstance(item, str) and item for item in value):
            return "expected a list of non-empty strings"
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"expected an integer, got {type(value).__name__}"
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"expected a number, got {type(value).__name__}"
    elif kind == "number_map":
        if not isinstance(value, dict) or not value:
            return f"expected a non-empty mapping, got {type(value).__name__}"
        for key, item in value.items():
            if not isinstance(key, str):
                return "expected text keys"
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                return f"expected numeric values, got {type(item).__name__} for {key}"
    elif kind == "text_map":
        if not isinstance(value, dict) or not value:
            return f"expected a non-empty mapping, got {type(value).__name__}"
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            return "expected text keys and values"
    else:  # pragma: no cover - a typo in the schema itself
        return f"unknown field type {kind}"
    return ""


FIELDS: tuple[FieldSpec, ...] = (
    # Identity -------------------------------------------------------------
    FieldSpec("hgnc_id", "identity", "HGNC ID", "text", "hgnc", mono=True,
              description="Stable HGNC identifier for the gene."),
    FieldSpec("symbol", "identity", "Approved symbol", "text", "hgnc", mono=True,
              description="HGNC approved gene symbol."),
    FieldSpec("name", "identity", "Approved name", "text", "hgnc",
              description="HGNC approved gene name."),
    FieldSpec("aliases", "identity", "Alias symbols", "text_list", "hgnc", mono=True,
              description="Other symbols in use for this gene."),
    FieldSpec("previous_symbols", "identity", "Previous symbols", "text_list", "hgnc",
              mono=True, description="Symbols this gene was approved under before."),
    FieldSpec("locus_type", "identity", "Locus type", "text", "hgnc",
              description="HGNC locus type, e.g. gene with protein product."),
    FieldSpec("chromosomal_location", "identity", "Cytogenetic location", "text", "hgnc",
              mono=True, description="Cytogenetic band, e.g. 1q42.13."),
    FieldSpec("entrez_id", "identity", "Entrez ID", "text", "hgnc", mono=True,
              description="NCBI Entrez Gene identifier, from the HGNC cross-reference."),
    FieldSpec("ensembl_gene_id", "identity", "Ensembl gene ID", "text", "hgnc", mono=True,
              description="Ensembl gene identifier, from the HGNC cross-reference."),
    FieldSpec("uniprot_accession", "identity", "UniProt accession", "text", "hgnc",
              mono=True,
              description="Reviewed UniProt accession, from the HGNC cross-reference."),
    FieldSpec("gene_biotype", "genomics", "Gene biotype", "text", "ensembl",
              description="Ensembl biotype, e.g. protein coding."),
    FieldSpec("genomic_location", "genomics", "Genomic location", "text", "ensembl",
              mono=True, description="Assembly, chromosome, span and strand."),
    FieldSpec("mouse_orthologs", "genomics", "Mouse orthologs", "text_list", "ensembl",
              mono=True,
              description="The mouse genes Ensembl Compara calls orthologs, closest first."),
    FieldSpec("mouse_orthology", "genomics", "Mouse orthology", "text", "ensembl",
              description="One-to-one when one mouse gene matches the one human gene, the "
                          "case a mouse model reads most directly; with Ensembl's confidence "
                          "call where the local data has it."),
    FieldSpec("mouse_protein_identity", "genomics", "Protein identity, mouse", "number",
              "ensembl", unit="%", mono=True,
              description="Share of the human protein's residues identical in the closest "
                          "mouse ortholog (Ensembl Compara). Comparable between genes: how "
                          "far a mouse result speaks for the human protein."),
    FieldSpec("cyno_orthologs", "genomics", "Cynomolgus orthologs", "text_list", "ensembl",
              mono=True,
              description="The cynomolgus macaque (Macaca fascicularis) genes Ensembl Compara "
                          "calls orthologs, closest first."),
    FieldSpec("cyno_orthology", "genomics", "Cynomolgus orthology", "text", "ensembl",
              description="One-to-one, one-to-many or many-to-many, as for mouse. Cynomolgus is "
                          "the usual species for non-clinical safety studies."),
    FieldSpec("cyno_protein_identity", "genomics", "Protein identity, cynomolgus", "number",
              "ensembl", unit="%", mono=True,
              description="Share of the human protein's residues identical in the closest "
                          "cynomolgus ortholog. Where a biologic's epitope has to cross-react "
                          "for a toxicology study, this is the first figure to read."),
    FieldSpec("protein_name", "proteomics", "Protein name", "text", "uniprot",
              description="UniProt recommended protein name."),
    FieldSpec("protein_length", "proteomics", "Protein length", "integer", "uniprot",
              unit="aa", mono=True,
              description="Length of the canonical sequence in amino acids."),
    FieldSpec("protein_sequence", "proteomics", "Canonical sequence", "sequence", "uniprot",
              mono=True, description="Canonical amino-acid sequence."),

    # Transcriptomics -----------------------------------------------------------
    FieldSpec("gtex_tissue_tpm", "transcriptomics", "RNA by tissue", "number_map", "gtex",
              unit="median TPM", mono=True,
              description="Median bulk RNA expression per GTEx tissue."),
    FieldSpec("gtex_microdissected_tpm", "transcriptomics", "RNA in microdissected samples",
              "number_map", "gtex", unit="median TPM", mono=True,
              description="GTEx v11 adds laser-capture microdissected samples of some tissues "
                          "(hepatocytes, colon mucosa, pancreatic islets). They are parts of "
                          "tissues already in the profile, so they are kept apart from it: "
                          "the specificity measures count each tissue once."),
    FieldSpec("gtex_median_across_tissues", "transcriptomics", "Median across tissues",
              "number", "gtex", unit="median TPM", mono=True,
              description="Median of the per-tissue medians."),
    FieldSpec("gtex_max_tissue", "transcriptomics", "Highest tissue", "text", "derived",
              derived_from=("gtex_tissue_tpm",),
              description="Tissue with the highest median TPM."),
    FieldSpec("hpa_rna_tissue_ntpm", "transcriptomics", "RNA by tissue (HPA)",
              "number_map", "hpa", unit="nTPM", mono=True,
              description="Consensus RNA expression across HPA's 51 tissues. A "
                          "second, independently processed read on the same "
                          "question GTEx answers."),
    FieldSpec("hpa_rna_tissue_specificity", "transcriptomics", "HPA specificity call",
              "text", "hpa",
              description="HPA's own classification: tissue enriched, group "
                          "enriched, enhanced, or low specificity."),
    FieldSpec("hpa_rna_tissue_distribution", "transcriptomics", "HPA distribution",
              "text", "hpa",
              description="How widely HPA detects it: in all, in many, in some, "
                          "in a single tissue."),
    FieldSpec("hpa_single_cell_specificity", "transcriptomics",
              "Single-cell specificity call", "text", "hpa",
              description="HPA's classification across its single-cell type atlas: "
                          "cell type enriched, group enriched, enhanced, or low "
                          "specificity."),
    FieldSpec("hpa_single_cell_ncpm", "transcriptomics", "Single-cell RNA, every cell type",
              "number_map", "hpa", unit="nCPM", mono=True,
              description="HPA's single-cell atlas across all its cell types. From the "
                          "mirrored rna_single_cell_type file: the API lists only the "
                          "enriched ones."),
    FieldSpec("hpa_brain_region_ntpm", "transcriptomics", "RNA across brain regions",
              "number_map", "hpa", unit="nTPM", mono=True,
              description="HPA's brain atlas: RNA in each region of the human brain, from "
                          "the mirrored rna_brain_region_hpa file. CC BY 4.0, where the Allen "
                          "atlases need the Institute's written permission for commercial use."),
    FieldSpec("hpa_single_cell_tissue", "transcriptomics",
              "Single-cell RNA by tissue and cell type", "number_map", "hpa",
              unit="nCPM", mono=True,
              description="Each cell type within each tissue HPA profiled, keyed "
                          "`tissue / cell type`. The organ view folds these into their "
                          "organ. From the mirrored rna_single_cell_type_tissue file."),
    FieldSpec("hpa_single_cell_enriched", "transcriptomics",
              "Enriched cell types (single-cell RNA)", "number_map", "hpa",
              unit="nCPM", mono=True,
              description="The cell types HPA calls enriched or enhanced for this gene, "
                          "with their single-cell RNA level. Only those cell types: the "
                          "API does not list the rest."),
    FieldSpec("hpa_protein_tissue_level", "proteomics", "Protein by tissue (antibody)",
              "text_map", "hpa",
              description="HPA antibody staining per tissue: the strongest level any "
                          "cell type in the tissue reaches."),
    FieldSpec("hpa_protein_cell_type_level", "proteomics",
              "Protein by cell type (antibody)", "text_map", "hpa",
              description="HPA antibody staining for each cell type HPA scores within "
                          "each tissue, keyed `tissue / cell type`. The organ view folds "
                          "these into their organ and opens on click."),
    FieldSpec("hpa_protein_tissue_intensity", "proteomics",
              "Protein by mass spectrometry", "number_map", "hpa", unit="intensity",
              mono=True,
              description="HPA tissue proteomics: mass-spectrometry intensity in each of "
                          "the 20 tissues HPA ran. 0 means the protein was not detected "
                          "in that tissue."),
    FieldSpec("hpa_interactions", "proteomics", "Interaction partners", "integer", "hpa",
              mono=True,
              description="Protein interaction partners in HPA's consensus network "
                          "(IntAct, BioGRID, OpenCell, BioPlex)."),
    FieldSpec("hpa_interactors", "proteomics", "Interaction partners, named", "text_list",
              "hpa",
              description="The partners themselves, from the mirrored "
                          "interaction_consensus file; the API gives only the count."),
    FieldSpec("hpa_protein_reliability", "proteomics", "Staining reliability", "text",
              "hpa", description="HPA reliability score for the protein expression data."),

    FieldSpec("uniprot_function", "proteomics", "Function", "text", "uniprot",
              description="UniProt's curated statement of what the protein does, "
                          "evidence tags removed."),
    FieldSpec("uniprot_isoforms", "proteomics", "Isoforms", "integer", "uniprot",
              mono=True, description="Protein isoforms UniProt describes for the gene."),

    # Proteomics: structure -------------------------------------------------------------
    FieldSpec("pdb_structures", "proteomics", "Experimental structures", "integer",
              "uniprot", mono=True,
              description="PDB entries that contain this protein, from UniProt's "
                          "cross-references."),
    FieldSpec("pdb_best_resolution", "proteomics", "Best resolution", "number",
              "uniprot", unit="Å", mono=True,
              description="The finest resolution among those entries (X-ray and "
                          "cryo-EM). Lower is sharper."),
    FieldSpec("pdb_coverage", "proteomics", "Sequence covered by structures", "number",
              "uniprot", unit="%", mono=True,
              description="Share of the canonical sequence that at least one PDB "
                          "chain spans: how much of the protein has been seen."),
    FieldSpec("alphafold_mean_plddt", "proteomics", "AlphaFold confidence", "number",
              "alphafold", mono=True,
              description="Mean pLDDT of the AlphaFold model, 0 to 100. Above 90 is "
                          "very high, below 50 usually disordered."),
    FieldSpec("alphafold_confidence_bands", "proteomics", "AlphaFold confidence bands",
              "number_map", "alphafold", unit="% of residues", mono=True,
              description="Share of residues in each of AlphaFold's confidence bands."),
    FieldSpec("alphamissense_mean", "proteomics", "Missense pathogenicity (mean)",
              "number", "alphafold", mono=True,
              description="Mean AlphaMissense pathogenicity over every possible amino "
                          "acid substitution, 0 to 1. Higher means the protein "
                          "tolerates change less: a constraint read, comparable between "
                          "genes."),
    FieldSpec("alphamissense_pathogenic_share", "proteomics",
              "Substitutions called likely pathogenic", "number", "alphafold", unit="%",
              mono=True,
              description="Share of all possible substitutions AlphaMissense classes as "
                          "likely pathogenic."),

    # Proteomics: what it does, by ontology ---------------------------------------------
    FieldSpec("go_process", "proteomics", "GO biological process", "text_list", "uniprot",
              description="Gene Ontology processes annotated in UniProt."),
    FieldSpec("go_function", "proteomics", "GO molecular function", "text_list", "uniprot",
              description="Gene Ontology molecular functions annotated in UniProt."),
    FieldSpec("go_component", "proteomics", "GO cellular component", "text_list", "uniprot",
              description="Gene Ontology cellular components annotated in UniProt."),

    # Proteomics: where it sits ---------------------------------------------------------
    FieldSpec("uniprot_subcellular_locations", "proteomics", "UniProt locations",
              "text_list", "uniprot",
              description="Subcellular locations annotated in UniProt."),
    FieldSpec("hpa_subcellular_main", "proteomics", "HPA main locations", "text_list",
              "hpa", description="Main subcellular locations from HPA imaging."),
    FieldSpec("hpa_subcellular_additional", "proteomics", "HPA additional locations",
              "text_list", "hpa",
              description="Additional subcellular locations from HPA imaging."),
    FieldSpec("hpa_subcellular_reliability", "proteomics", "Imaging reliability", "text",
              "hpa", description="HPA reliability score for the localization data."),

    # Clinical --------------------------------------------------------------
    FieldSpec("depmap_lines", "essentiality", "Cell lines screened", "integer", "depmap",
              mono=True,
              description="Cancer cell lines in which DepMap knocked the gene out by CRISPR."),
    FieldSpec("depmap_mean_effect", "essentiality", "Mean gene effect", "number", "depmap",
              mono=True,
              description="Chronos gene effect averaged over the lines: 0 is no effect, -1 the "
                          "median of the genes every line needs. More negative, more needed."),
    FieldSpec("depmap_dependent_share", "essentiality", "Lines that depend on it", "number",
              "depmap", unit="%", mono=True,
              description="Share of the lines with a dependency probability above 0.5. "
                          "Comparable between genes."),
    FieldSpec("depmap_common_essential", "essentiality", "Common essential", "text", "depmap",
              description="Whether DepMap infers the gene is needed across all lines."),
    FieldSpec("depmap_lineage_dependency", "essentiality", "Dependent lines by lineage",
              "number_map", "depmap", unit="% of lines",
              description="Within each lineage, the share of its lines that depend on the gene; "
                          "each lineage named with how many lines it has, since a share from a "
                          "few lines is a weak one."),
    FieldSpec("depmap_effect_distribution", "essentiality", "Gene effect across lines",
              "number_map", "depmap", unit="lines",
              description="How many lines fall in each 0.1-wide band of gene effect, from -3 to "
                          "1; the two end bands also hold everything beyond them."),
    FieldSpec("depmap_dependent_lines", "essentiality", "Dependent cell lines", "text_list",
              "depmap",
              description="Every line with a dependency probability above 0.5, with its "
                          "lineage and gene effect, most dependent first."),
    FieldSpec("clinvar_variants", "clinical", "ClinVar records", "integer", "clinvar",
              mono=True,
              description="ClinVar records that name this gene alone. Variants spanning "
                          "several genes are left out, so a large deletion is not "
                          "counted against every gene it covers."),
    FieldSpec("clinvar_pathogenic", "clinical", "Pathogenic or likely pathogenic",
              "integer", "clinvar", mono=True,
              description="ClinVar records classified pathogenic or likely pathogenic, "
                          "each counted once. Human genetic evidence that the gene "
                          "matters, and a safety signal at the same time."),
    FieldSpec("clinvar_classifications", "clinical", "ClinVar by classification",
              "number_map", "clinvar", unit="records", mono=True,
              description="Records per classification. Classes overlap as ClinVar's "
                          "own filters do: a Pathogenic/Likely pathogenic record "
                          "counts under both."),
    FieldSpec("gwas_associations", "clinical", "GWAS associations", "integer", "gwas",
              mono=True,
              description="Associations the GWAS Catalog maps to the gene, with the variant "
                          "inside it or the gene the nearest to it."),
    FieldSpec("gwas_genome_wide_traits", "clinical", "Traits at genome-wide significance",
              "integer", "gwas", mono=True,
              description="Traits whose strongest association reaches p below 5e-8."),
    FieldSpec("gwas_traits", "clinical", "GWAS traits", "number_map", "gwas", unit="-log10 p",
              description="Every trait, with its strongest association as -log10 p: 7.3 is the "
                          "genome-wide threshold (5e-8)."),
    FieldSpec("gwas_lead_variants", "clinical", "GWAS lead variants", "text_list", "gwas",
              description="For each trait, the strongest association's variant and risk allele, "
                          "p-value, effect, consequence, and whether the variant is in the gene "
                          "or the gene is only the nearest one; strongest first."),
    FieldSpec("chembl_target", "clinical", "ChEMBL target", "text", "chembl", mono=True,
              description="The ChEMBL single-protein target for this protein."),
    FieldSpec("chembl_max_phase", "clinical", "Highest clinical phase", "number", "chembl",
              mono=True,
              description="The furthest any drug or candidate acting on it has gone: 4 is "
                          "approved."),
    FieldSpec("chembl_drugs", "clinical", "Drugs and candidates", "text_list", "chembl",
              description="Every molecule ChEMBL records with a mechanism on this target, "
                          "furthest phase first."),
    FieldSpec("chembl_activities", "clinical", "Bioactivity measurements", "integer",
              "chembl", mono=True,
              description="Measured bioactivities against the target in ChEMBL: how much "
                          "chemistry has been done on it."),
    FieldSpec("disease_associations", "clinical", "Disease associations",
              "number_map", "opentargets", unit="association score", mono=True,
              description="Diseases this gene is implicated in, each scored 0 to "
                          "1 from genetics, expression, literature and clinical "
                          "evidence. The score is what makes two genes "
                          "comparable; a list of names is not."),
    FieldSpec("disease_association_count", "clinical", "Diseases implicated",
              "integer", "opentargets", mono=True,
              description="How many diseases Open Targets associates at all."),
    FieldSpec("tractability", "clinical", "Tractability", "text_list",
              "opentargets",
              description="What evidence there is that each modality could work "
                          "on this target: a co-crystallised ligand, an approved "
                          "antibody, a usable pocket."),
    FieldSpec("mouse_phenotypes", "clinical", "Mouse knockout phenotypes",
              "text_list", "opentargets",
              description="What happens when the gene is removed in mouse. The "
                          "cheapest read on what losing it costs."),
    FieldSpec("safety_liabilities", "clinical", "Safety liabilities", "text_list",
              "opentargets",
              description="Adverse events curated from literature and trials. "
                          "Usually empty, and worth seeing when it is not."),

    # Predictive insights ---------------------------------------------------
    # Derived, and the reason to read a record rather than a database page:
    # a raw peak value cannot be compared between genes, and these can.
    FieldSpec("rna_specificity_tau", "insights", "RNA specificity (tau)", "number",
              "derived", mono=True, derived_from=("gtex_tissue_tpm",),
              description="Yanai specificity index over the GTEx profile. 0 is "
                          "uniform across tissues, 1 is one tissue only. "
                          "Comparable between genes; a peak value is not."),
    FieldSpec("single_cell_tau", "insights", "Cell-type specificity (tau)", "number",
              "derived", mono=True, derived_from=("hpa_single_cell_ncpm",),
              description="Tau over HPA's full single-cell atlas: 0 in every cell type "
                          "alike, 1 in one cell type only. Comparable between genes."),
    FieldSpec("rna_specificity_class", "insights", "RNA specificity", "text",
              "derived", derived_from=("gtex_tissue_tpm",),
              description="The band that index falls in, from ubiquitous to "
                          "highly specific."),
    FieldSpec("rna_fold_over_median", "insights", "Peak over typical tissue",
              "number", "derived", unit="x", mono=True,
              derived_from=("gtex_tissue_tpm",),
              description="How far the highest tissue stands above the median "
                          "one. Where the median is zero, above the median of "
                          "the tissues where it is detected at all."),
    FieldSpec("rna_protein_concordance", "insights", "RNA against protein", "text",
              "derived",
              derived_from=("gtex_tissue_tpm", "hpa_protein_tissue_level"),
              description="Whether the RNA profile and the antibody profile "
                          "peak in the same organ. Discordance means the RNA "
                          "number is the weaker evidence for where it acts."),
    FieldSpec("rna_source_agreement", "insights", "GTEx against HPA", "text",
              "derived",
              derived_from=("gtex_tissue_tpm", "hpa_rna_tissue_ntpm"),
              description="Whether two independently processed RNA atlases "
                          "peak in the same organ. Agreement is the strongest "
                          "evidence a profile is real rather than a batch "
                          "effect; disagreement is worth knowing before a "
                          "programme is built on one of them."),
    FieldSpec("dependency_profile", "insights", "Dependency in cancer cell lines", "text",
              "derived", derived_from=("depmap_dependent_share", "depmap_common_essential",
                                       "depmap_lineage_dependency"),
              description="Common essential, selective or rarely needed, from DepMap's CRISPR "
                          "screens. Common essential is a safety question for any inhibitor; "
                          "selective, gathered in one lineage, is the shape an oncology target "
                          "wants."),
    FieldSpec("top_disease", "insights", "Strongest disease link", "text",
              "derived", derived_from=("disease_associations",),
              description="The highest-scoring association, with its score."),
    FieldSpec("druggable_modalities", "insights", "Modalities with evidence",
              "text_list", "derived", derived_from=("tractability",),
              description="Which modalities the tractability evidence covers, "
                          "collapsed from the individual findings."),
)

FIELDS_BY_NAME: dict[str, FieldSpec] = {spec.name: spec for spec in FIELDS}

FIELD_NAMES: tuple[str, ...] = tuple(spec.name for spec in FIELDS)


def fields_for_source(key: str) -> tuple[FieldSpec, ...]:
    """The fields that `key` owns. The registry and the schema agree by
    construction: a source never declares its own field list."""
    return tuple(spec for spec in FIELDS if spec.source == key)


def schema_to_dict() -> dict[str, Any]:
    """The schema as data, so the interface can render a record without
    being taught the field names twice."""
    return {
        "schema_version": SCHEMA_VERSION,
        "sections": SECTIONS,
        "fields": [spec.to_dict() for spec in FIELDS],
    }
