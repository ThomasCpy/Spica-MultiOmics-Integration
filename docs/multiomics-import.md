# Port from the MultiOmics integrator

The integrator, an earlier project by the same author, is a terminal app with twelve
gene modules, fifteen cross-module pipelines and four large-dataset explorers.
This sorts all of it into Spica's five categories and records where each
piece ended up. Code was copied and adapted, never imported from the integrator.

The first pass left out two things the integrator did well: opening any
GEO series and putting its samples' tracks on the locus, and the
transcription-factor menu (regulators, their JASPAR consensus, measured
ChIP-seq). A second pass (30 Oct 2026) brought both in, after JASPAR's
licence was confirmed on its own site. Each item still left out says why.

## Genomics

| Integrator | What it does | In Spica |
| --- | --- | --- |
| `regulation.py`, `plotter.py` | IGV locus view: Ensembl regulatory features, ENCORI miRNA sites, OmniPath regulators, ENCODE explorer, regulators' ChIP-seq, JASPAR | **In**: the genome view (`docs/genome.md`), plus GENCODE, cCREs, ClinVar, dbSNP, eQTLs, conservation, repeats, per-tissue DNase, H3K27ac and RNA coverage. The TF menu is **in** as Transcription factors at the promoter (`spica/tfscan.py`): regulators, JASPAR consensus and logo, a scan of the promoter at p < 1e-4, crossed with each factor's own ChIP-seq peaks. ENCORI stays off by default (terms not found) |
| `pipelines/regulation_atlas.py`, `core/regulation_signal.py` | One assay across many tissues over the locus | **In**: "Regulation atlas" in the genome view |
| `regulation.py`, GC and CpG counts | GC percent and CpG count over the gene | **In** as the CpG island track; the raw counts were not carried over, the islands say more |
| `genomics.py` | Ensembl biotype and ID | **In** |
| `core/mirtarbase.py`, `pipelines/regulatory_circuit.py` | Validated miRNA targets; miRNA and TF circuits | **Left out**: miRTarBase's terms could not be found, and the circuit depends on it |

## Transcriptomics

| Integrator | What it does | In Spica |
| --- | --- | --- |
| `transcriptomics.py` | GTEx per tissue, specificity, isoform expression | **In**: GTEx (v11 from the mirror, v10 from the API) and HPA per tissue, tau, fold over median, and the isoform table (every transcript in every tissue, the leading one per tissue) |
| `single_cell.py` | HPA single-cell types | **In**: HPA's call and enriched cell types from the API; the full atlas, cell types by tissue and the cell-type tau from HPA's files once mirrored. The integrator scraped a web page for the full atlas; Spica does not |
| `pipelines/coexpression.py`, `databases/coexpression.py` | Genome-wide tissue co-expression | **In**, from the GTEx matrix the mirror already holds; without the mirror it says so |
| `pipelines/tissue_regulators.py` | Which regulators are active in a tissue | **In** in another form: the genome view lists the gene's regulators with their measured ChIP-seq per biosample, and the atlas shows which tissues open the locus |
| `databases/allen_brain.py`, `aging_tbi.py`, `anndata_backend.py`, `bulk_backend.py` | Brain single-cell and bulk datasets the user downloads | **Left out**: tens of gigabytes for one research question, outside target triage |

## Proteomics

| Integrator | What it does | In Spica |
| --- | --- | --- |
| `proteomics.py` | HPA staining, mass spec, UniProt, ProteomicsDB | **In**: HPA staining by tissue and by cell type, HPA mass spectrometry in its 20 tissues, UniProt function, GO terms and isoforms. **ProteomicsDB left out**: terms not found |
| `pipelines/multiomic_atlas.py` | Gene to mRNA to protein across tissues | **In**: RNA and protein by organ, organs opening into cell types |
| `structural.py` | PDB structures, predicted models | **In**: PDB count, best resolution, coverage, AlphaFold confidence, and the structure plot along the sequence |
| `interactomics.py`, `pipelines/context_interactome.py` | HPA consensus interactions | **In**: partner count from the API, named partners from HPA's file once mirrored. IntAct directly was **left out** (current terms not stated) |
| `pipelines/isoform_divergence.py`, `isoform_variant_map.py` | Domains and variants by isoform | **In** in part: isoform counts and per-tissue isoform use; the domain-by-isoform map was **left out**, it needs per-isoform feature alignment the sources do not serve |
| `pipelines/glycine_scan.py`, `variant_structure.py`, `core/structure.py`, `core/docking.py` | Residue scans, ESMFold shifts, LightDock | **Left out**: compute-heavy modelling, a design step rather than triage |

## Clinical

| Integrator | What it does | In Spica |
| --- | --- | --- |
| `clinical.py` | ClinVar variants and significance | **In**: record fields with a chart, and the genome track |
| `pipelines/variant_effect.py` | AlphaMissense and VEP | **In**: AlphaMissense mean and pathogenic share, per residue on the structure plot. Per-variant VEP calls were **left out**: AlphaMissense already scores every possible substitution |
| `pipelines/druggability.py` | ChEMBL, DGIdb, localisation | **In**: ChEMBL target, drugs and phase, activities, beside Open Targets tractability. **DGIdb left out**: no data licence found |
| `perturbation.py` | GEO search, a series' design, a gene's values in its processed table | **In** as Datasets (`spica/geo/`): any GEO series searched or opened by accession, every sample in context with facets, its bigWig, bigBed, peak and signal files on a gene's locus (GRCh37 mapped onto GRCh38), and a gene's row matched to the samples and grouped by any field. Differential expression: published results or DESeq2 on raw counts, as a volcano plot (docs/differential-expression.md). ArrayExpress, Expression Atlas and PRIDE are not yet in |

## Predictive insights

| Integrator | What it does | In Spica |
| --- | --- | --- |
| `core/analysis.py` | Cross-module synthesis | **In**: tau, fold over median, cell-type tau, RNA/protein concordance, GTEx/HPA agreement, top disease, modalities; and in Compare, the measures where higher means further along are marked |
| `pipelines/shared_regulators.py`, `directed_link.py` | Shared regulators by selectivity; directed links | **In**: the Shared regulation panel in Compare |
| `genecard.py`, `ontology.py` | MyGene summaries, GO | **In** from UniProt (function, GO) rather than MyGene, whose aggregated sources carry mixed terms |

## Rules carried over

- The integrator's limits are all off (`limits.py` sets them to `None`): lists
  are never cut. Spica keeps that; where a track is defined narrowly it says
  so on screen.
- Adult ENCODE samples only by default for tissue experiments, as in
  `core/lifestage.py`; TF ChIP-seq allows cell lines.
- Absence of a ChIP-seq experiment means "not assayed", never "does not bind".
