"""Regenerate the fixture mirror in `tests/fixtures/mirror`.

Run after changing a file format an adapter reads:

    python tests/make_fixtures.py

See `tests/fixtures/README.md` for what the fixtures are and are not.
"""

from __future__ import annotations

import gzip
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent / "fixtures" / "mirror"


def tsv(path: str, header: list[str], rows: list[list[str]]) -> None:
    lines = ["\t".join(header)] + ["\t".join(row) for row in rows]
    (ROOT / path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    for sub in ("hgnc", "ensembl", "uniprot", "gtex", "hpa"):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)

    # -- HGNC ---------------------------------------------------------------
    tsv(
        "hgnc/hgnc_complete_set.txt",
        ["hgnc_id", "symbol", "name", "locus_group", "locus_type", "status",
         "location", "alias_symbol", "prev_symbol", "entrez_id",
         "ensembl_gene_id", "uniprot_ids"],
        [
            ["HGNC:20001", "PCSK9", "proprotein convertase subtilisin/kexin type 9",
             "protein-coding gene", "gene with protein product", "Approved", "1p32.3",
             "NARC1|HCHOLA3", "NARC1", "255738", "ENSG00000169174", "Q8NBP7"],
            ["HGNC:250", "ADH1B", "alcohol dehydrogenase 1B (class I), beta polypeptide",
             "protein-coding gene", "gene with protein product", "Approved", "4q23",
             "", "ADH2", "125", "ENSG00000196616", "P00325"],
            ["HGNC:29665", "MALAT1",
             "metastasis associated lung adenocarcinoma transcript 1",
             "non-coding RNA", "RNA, long non-coding", "Approved", "11q13.1",
             "NEAT2|PRO2853", "LINC00047", "378938", "ENSG00000251562", ""],
            ["HGNC:99999", "WITHDRAWNX", "withdrawn example", "other", "unknown",
             "Entry Withdrawn", "", "", "", "", "", ""],
        ],
    )

    # -- Ensembl (BioMart export) -------------------------------------------
    tsv(
        "ensembl/genes.tsv",
        ["Gene stable ID", "Gene name", "Gene type", "Chromosome/scaffold name",
         "Gene start (bp)", "Gene end (bp)", "Strand"],
        [
            ["ENSG00000169174", "PCSK9", "protein_coding", "1",
             "55039447", "55064852", "1"],
            ["ENSG00000196616", "ADH1B", "protein_coding", "4",
             "99304971", "99321659", "-1"],
            ["ENSG00000251562", "MALAT1", "lncRNA", "11",
             "65497688", "65508073", "1"],
        ],
    )

    # -- UniProt (TSV export; sequences truncated, Length matches the stub) --
    pcsk9 = "MGTVSSRRSWWPLPLLLLLLLLLGPAGARAQEDEDGDYEELVLALRSEE"
    adh1b = "MSTAGKVIKCKAAVLWEVKKPFSIEDVEVAPPKAYEVRIKMVAVGICHT"
    tsv(
        "uniprot/entries.tsv",
        ["Entry", "Reviewed", "Protein names", "Gene Names", "Length", "Sequence",
         "Subcellular location [CC]", "Function [CC]",
         "Gene Ontology (biological process)", "Gene Ontology (molecular function)",
         "Gene Ontology (cellular component)", "PDB", "Alternative products (isoforms)"],
        [
            ["Q8NBP7", "reviewed",
             "Proprotein convertase subtilisin/kexin type 9 (EC 3.4.21.-)",
             "PCSK9 NARC1", str(len(pcsk9)), pcsk9,
             "SUBCELLULAR LOCATION: Secreted {ECO:0000269|PubMed:14703719}; "
             "Endoplasmic reticulum lumen. Note=Autocatalytic cleavage is required.",
             "FUNCTION: Crucial player in the regulation of plasma cholesterol "
             "homeostasis {ECO:0000269|PubMed:17461796}.",
             "cholesterol homeostasis [GO:0042632]; lipoprotein metabolic process [GO:0042157]",
             "serine-type endopeptidase activity [GO:0004252]",
             "cell surface [GO:0009986]",
             "2P4E;2PMW;3BPS;",
             "ALTERNATIVE PRODUCTS: Event=Alternative splicing; Named isoforms=2;"],
            ["P00325", "reviewed",
             "All-trans-retinol dehydrogenase [NAD(+)] ADH1B (EC 1.1.1.105)",
             "ADH1B ADH2", str(len(adh1b)), adh1b, "SUBCELLULAR LOCATION: Cytoplasm.",
             "", "", "", "", "", ""],
            ["A0A0A0PCSK9", "unreviewed", "PCSK9 fragment", "PCSK9", "31",
             "MGTVSSRRSWWPLPLLLLLLLLLGPAGARA", "", "", "", "", "", "", ""],
        ],
    )

    # -- GTEx (GCT matrix, gzipped as the release ships it) ------------------
    tissues = ["Liver", "Kidney_Cortex", "Small_Intestine_Terminal_Ileum",
               "Whole_Blood", "Brain_Cortex"]
    rows = [
        ["ENSG00000169174.11", "PCSK9", "77.41", "9.82", "12.05", "0.31", "1.44"],
        ["ENSG00000251562.9", "MALAT1", "1204.00", "988.30", "1450.12",
         "320.55", "2100.80"],
    ]
    lines = ["#1.2", f"{len(rows)}\t{len(tissues)}",
             "\t".join(["Name", "Description"] + tissues)]
    lines += ["\t".join(row) for row in rows]
    with gzip.open(ROOT / "gtex/median_tpm.gct.gz", "wt",
                   encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")

    # -- HPA -----------------------------------------------------------------
    tsv(
        "hpa/normal_tissue.tsv",
        ["Gene", "Gene name", "Tissue", "Cell type", "Level", "Reliability"],
        [
            ["ENSG00000169174", "PCSK9", "liver", "hepatocytes", "High", "Enhanced"],
            ["ENSG00000169174", "PCSK9", "liver", "bile duct cells", "Low", "Enhanced"],
            ["ENSG00000169174", "PCSK9", "kidney", "cells in tubules", "Medium",
             "Approved"],
            ["ENSG00000169174", "PCSK9", "cerebral cortex", "neuronal cells",
             "Not detected", "Approved"],
            ["ENSG00000251562", "MALAT1", "liver", "hepatocytes", "Ascending",
             "Uncertain"],
        ],
    )
    tsv(
        "hpa/rna_tissue_consensus.tsv",
        ["Gene", "Gene name", "Tissue", "nTPM"],
        [["ENSG00000169174", "PCSK9", "liver", "47.5"],
         ["ENSG00000169174", "PCSK9", "kidney", "6.1"],
         ["ENSG00000169174", "PCSK9", "lung", "0.9"],
         ["ENSG00000251562", "MALAT1", "liver", "612.0"]],
    )
    tsv(
        "hpa/rna_single_cell_type.tsv",
        ["Gene", "Gene name", "Cell type", "nTPM"],
        [["ENSG00000169174", "PCSK9", "hepatocytes", "120.4"],
         ["ENSG00000169174", "PCSK9", "Kupffer cells", "2.1"],
         ["ENSG00000169174", "PCSK9", "T-cells", "0.0"],
         ["ENSG00000169174", "PCSK9", "proximal tubular cells", "8.6"],
         ["ENSG00000169174", "PCSK9", "alveolar cells type 2", "1.0"]],
    )
    tsv(
        "hpa/rna_single_cell_type_tissue.tsv",
        ["Gene", "Gene name", "Tissue", "Cluster", "Cell type", "Read count", "nTPM"],
        [["ENSG00000169174", "PCSK9", "liver", "c-0", "hepatocytes", "900", "118.0"],
         ["ENSG00000169174", "PCSK9", "liver", "c-3", "hepatocytes", "950", "131.5"],
         ["ENSG00000169174", "PCSK9", "liver", "c-5", "Kupffer cells", "10", "2.1"],
         ["ENSG00000169174", "PCSK9", "kidney", "c-1", "proximal tubular cells", "60", "8.6"]],
    )
    tsv(
        "hpa/interaction_consensus.tsv",
        ["ensg_id_1", "gene_name_1", "ensg_id_2", "gene_name_2", "interaction_type",
         "evidence_count"],
        [["ENSG00000169174", "PCSK9", "ENSG00000130164", "LDLR", "physical", "12"],
         ["ENSG00000073060", "SCARB1", "ENSG00000169174", "PCSK9", "physical", "2"],
         ["ENSG00000130164", "LDLR", "ENSG00000105855", "ITGB8", "physical", "1"]],
    )
    tsv(
        "hpa/subcellular_location.tsv",
        ["Gene", "Gene name", "Reliability", "Main location", "Additional location"],
        [["ENSG00000169174", "PCSK9", "Supported", "Golgi apparatus;Vesicles",
          "Nucleoplasm"]],
    )

    # -- Open Targets (JSON Lines, one target per line) ----------------------
    (ROOT / "opentargets").mkdir(parents=True, exist_ok=True)
    targets = [
        {
            "ensemblId": "ENSG00000169174",
            "approvedSymbol": "PCSK9",
            "tractability": [
                {"modality": "SM", "label": "High-Quality Pocket", "value": True},
                {"modality": "AB", "label": "Approved Drug", "value": True},
                {"modality": "PR", "label": "Half-life <24h", "value": False},
            ],
            "safetyLiabilities": [],
            "associatedDiseases": {
                "count": 926,
                "rows": [
                    {"score": 0.856, "disease": {"name": "familial hypercholesterolemia"}},
                    {"score": 0.732, "disease": {"name": "coronary artery disorder"}},
                ],
            },
            "mousePhenotypes": [
                {"modelPhenotypeLabel": "abnormal cholesterol homeostasis"},
                {"modelPhenotypeLabel": "increased bile salt level"},
            ],
        },
        {
            "ensemblId": "ENSG00000196616",
            "approvedSymbol": "ADH1B",
            "tractability": [],
            "safetyLiabilities": [{"event": "hepatotoxicity", "datasource": "literature"}],
            "associatedDiseases": {"count": 3, "rows": []},
            "mousePhenotypes": [],
        },
    ]
    (ROOT / "opentargets" / "targets.jsonl").write_text(
        "\n".join(json.dumps(target) for target in targets) + "\n", encoding="utf-8")

    # -- ClinVar (variant_summary, one row per variant per assembly) ----------
    (ROOT / "clinvar").mkdir(parents=True, exist_ok=True)
    tsv(
        "clinvar/variant_summary.txt",
        ["#AlleleID", "Type", "Name", "GeneSymbol", "ClinicalSignificance",
         "Assembly", "VariationID"],
        [
            ["1", "single nucleotide variant", "c.1A>G", "PCSK9", "Pathogenic",
             "GRCh38", "100"],
            ["1", "single nucleotide variant", "c.1A>G", "PCSK9", "Pathogenic",
             "GRCh37", "100"],  # the same variant on the old assembly
            ["2", "single nucleotide variant", "c.2C>T", "PCSK9",
             "Pathogenic/Likely pathogenic", "GRCh38", "101"],
            ["3", "single nucleotide variant", "c.3G>A", "PCSK9",
             "Uncertain significance", "GRCh38", "102"],
            ["4", "single nucleotide variant", "c.4T>C", "PCSK9",
             "Conflicting classifications of pathogenicity", "GRCh38", "103"],
            ["5", "copy number loss", "del", "PCSK9;USP24", "Pathogenic",
             "GRCh38", "104"],  # several genes: not this gene's alone
            ["6", "single nucleotide variant", "c.6A>T", "PCSK9", "not provided",
             "GRCh38", "105"],
        ],
    )

    # -- AlphaFold DB (summary table Spica defines) ---------------------------
    (ROOT / "alphafold").mkdir(parents=True, exist_ok=True)
    tsv(
        "alphafold/summary.tsv",
        ["accession", "mean_plddt", "very_high", "confident", "low", "very_low",
         "am_mean", "am_pathogenic_share"],
        [["Q8NBP7", "85.19", "0.669", "0.147", "0.048", "0.136", "0.376", "27.2"],
         ["P00325", "96.10", "0.950", "0.040", "0.005", "0.005", "", ""]],
    )

    # -- DepMap (the summary the mirror builder writes) -------------------------
    # Two genes, and the model table that names the lines. PCSK9 is needed
    # by one myeloid line.
    (ROOT / "depmap").mkdir(parents=True, exist_ok=True)
    (ROOT / "depmap" / "Model.csv").write_text(
        "ModelID,CellLineName,OncotreeLineage\n"
        "ACH-000001,LINE-A,Lung\nACH-000002,LINE-B,Myeloid\n", encoding="utf-8")
    bins = ["0"] * 40
    bins[28], bins[30] = "1", "1"
    tsv("depmap/genes.tsv",
        ["hgnc_id", "symbol", "entrez", "depmap_symbol", "lines", "mean_effect", "median_effect",
         "min_effect", "dependent", "dependent_share", "common_essential", "lineages",
         "histogram", "dependent_lines"],
        [["HGNC:20001", "PCSK9", "255738", "PCSK9", "2", "-0.1500", "-0.1500", "-0.2000", "1",
          "50.00", "0", '{"Lung":[1,0,-0.1],"Myeloid":[1,1,-0.2]}', ",".join(bins),
          "ACH-000002:-0.200"],
         ["HGNC:250", "ADH1B", "125", "ADH1B", "2", "0.0200", "0.0200", "0.0000", "0", "0.00",
          "0", '{"Lung":[1,0,0.0],"Myeloid":[1,0,0.04]}', ",".join(bins), ""]])

    # -- GWAS Catalog (the traits summary the mirror builder writes) -----------
    # One trait per kind of match: a MONDO disease, an EFO disease Open
    # Targets uses as its own ID, and a measurement that matches no disease.
    (ROOT / "gwas").mkdir(parents=True, exist_ok=True)
    tsv("gwas/traits.tsv",
        ["gene_id", "relation", "trait", "trait_uris", "associations", "studies", "mlog10p",
         "p_value", "risk_allele", "or_beta", "context", "study", "pubmed"],
        [["ENSG00000169174", "in the gene", "low density lipoprotein cholesterol measurement",
          "http://www.ebi.ac.uk/efo/EFO_0004611", "10", "5", "120.00", "1E-120", "rs11591147-T",
          "-0.3", "missense_variant", "GCST000002", "23456"],
         ["ENSG00000169174", "in the gene", "familial hypercholesterolemia",
          "http://purl.obolibrary.org/obo/MONDO_0005439", "3", "2", "45.20", "6E-46",
          "rs11591147-T", "0.5", "missense_variant", "GCST000001", "12345"],
         ["ENSG00000169174", "nearest gene", "coronary artery disease",
          "http://www.ebi.ac.uk/efo/EFO_0001645", "1", "1", "6.00", "1E-6", "rs1234-A", "1.1",
          "intergenic_variant", "GCST000003", "34567"]])

    # -- ChEMBL (JSON Lines Spica defines) -------------------------------------
    (ROOT / "chembl").mkdir(parents=True, exist_ok=True)
    chembl = [
        {"accession": "Q8NBP7", "target": "CHEMBL2929", "activities": 2460,
         "drugs": [{"name": "EVOLOCUMAB", "phase": 4, "action": "INHIBITOR"},
                   {"name": "BOCOCIZUMAB", "phase": 3, "action": "INHIBITOR"},
                   {"name": "ALIROCUMAB", "phase": 4, "action": "INHIBITOR"}]},
        {"accession": "P00325", "target": "CHEMBL3284", "activities": 512, "drugs": []},
    ]
    (ROOT / "chembl" / "targets.jsonl").write_text(
        "\n".join(json.dumps(row) for row in chembl) + "\n", encoding="utf-8")

    # -- manifest ------------------------------------------------------------
    manifest = {
        "mirror_version": "1",
        "sources": {
            "hgnc": {
                "label": "HGNC", "version": "2026-09-01", "retrieved": "2026-10-20",
                "license": "No restrictions (HGNC)",
                "files": {"complete_set": "hgnc/hgnc_complete_set.txt"},
            },
            "ensembl": {
                "label": "Ensembl", "version": "115", "assembly": "GRCh38.p14",
                "retrieved": "2026-10-20", "license": "No restrictions (Ensembl)",
                "files": {"genes": "ensembl/genes.tsv"},
            },
            "uniprot": {
                "label": "UniProt", "version": "2026_04", "retrieved": "2026-10-21",
                "license": "CC BY 4.0",
                "files": {"entries": "uniprot/entries.tsv"},
            },
            "gtex": {
                "label": "GTEx", "version": "v11", "retrieved": "2026-10-21",
                "license": "Open tier public; protected tier via dbGaP",
                "files": {"median_tpm": "gtex/median_tpm.gct.gz"},
            },
            "hpa": {
                "label": "Human Protein Atlas", "version": "24.0",
                "retrieved": "2026-10-22", "license": "CC BY 4.0",
                "files": {"normal_tissue": "hpa/normal_tissue.tsv",
                          "rna_tissue": "hpa/rna_tissue_consensus.tsv",
                          "subcellular_location": "hpa/subcellular_location.tsv",
                          "single_cell": "hpa/rna_single_cell_type.tsv",
                          "single_cell_tissue": "hpa/rna_single_cell_type_tissue.tsv",
                          "interactions": "hpa/interaction_consensus.tsv"},
            },
            "opentargets": {
                "label": "Open Targets", "version": "25.06",
                "retrieved": "2026-10-23",
                "license": "CC0 1.0 (some constituent data CC BY-SA)",
                "files": {"targets": "opentargets/targets.jsonl"},
            },
            "alphafold": {
                "label": "AlphaFold DB", "version": "v6", "retrieved": "2026-10-25",
                "license": "CC BY 4.0",
                "files": {"summary": "alphafold/summary.tsv"},
            },
            "chembl": {
                "label": "ChEMBL", "version": "36", "retrieved": "2026-10-25",
                "license": "CC BY-SA 3.0",
                "files": {"targets": "chembl/targets.jsonl"},
            },
            "gwas": {
                "label": "GWAS Catalog", "version": "2026-10-22", "retrieved": "2026-10-28",
                "license": "EMBL-EBI terms of use",
                "files": {"traits": "gwas/traits.tsv"},
            },
            "depmap": {
                "label": "DepMap", "version": "24Q4", "retrieved": "2026-10-28",
                "license": "CC BY 4.0",
                "files": {"genes": "depmap/genes.tsv", "models": "depmap/Model.csv"},
            },
            "clinvar": {
                "label": "ClinVar", "version": "2026-10",
                "retrieved": "2026-10-25", "license": "Public domain (NCBI)",
                "files": {"variant_summary": "clinvar/variant_summary.txt"},
            },
        },
    }
    (ROOT / "mirror.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"fixtures written to {ROOT}")


if __name__ == "__main__":
    main()
