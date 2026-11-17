# The local mirror

A finished Spica answers entirely from databases already on the machine.
This describes how those files are built, where they go and how Spica is told
what they are.

Building them is a deliberate step: from Settings or the Databases page
("Local data"), or from the command line. Spica is offline by default; with
"Online access" switched on in Settings, a source not mirrored yet is fetched
from its public API instead (see "Before a source is mirrored" below).

## Building it

In the app, "Check for new releases" asks each source for its newest
release (one small request each, about ten seconds for all nine) and
"Update" rebuilds the ones that moved, in a process of its own: the window
stays responsive, reports keep reading the old release of a source until its
new one is complete, and the panel follows the download. The exe does the
same by starting itself again with `--build-mirror`, so a client's copy
updates its own data without Python or this repository.

```sh
./runtime/Scripts/python.exe tools/build_mirror.py --check      # what is newer upstream
./runtime/Scripts/python.exe tools/build_mirror.py              # every source
./runtime/Scripts/python.exe tools/build_mirror.py hpa clinvar  # some of them
./runtime/Scripts/python.exe tools/build_mirror.py gtex --refresh   # download again
```

(`runtime/bin/python` on macOS and Linux.) Each source is built on its own and
written to the manifest the moment it is done, so a failure costs that source
only, and running the command again resumes: files already on disk are not
downloaded again unless `--refresh` is given. Open Targets needs pyarrow, which
is in `requirements.txt` and bundled in the exe for that reason.

| Source | What is downloaded | On disk | Time |
| --- | --- | --- | --- |
| HGNC | The complete set | 16 MB | seconds |
| Ensembl | A BioMart gene export, release from the REST API, and every gene's mouse and cynomolgus orthologs (Compara) | 13 MB | about a minute |
| UniProt | Reviewed human entries, REST stream, with the full PDB column | 49 MB | 30 s |
| GTEx | The newest release's median-TPM matrix (found from the bucket listing), and GTEx's tissue names | 10 MB | seconds |
| HPA | Seven release files, unzipped | 1.7 GB | a few minutes |
| ClinVar | `variant_summary.txt.gz`, reduced to GRCh38 single-gene rows sorted by gene; the raw file is deleted | 180 MB | a few minutes |
| Open Targets | Parquet (targets, direct associations, diseases, mouse phenotypes, tractability, safety), converted to one JSON line per target; the parquet is deleted | 660 MB | about 7 min |
| ChEMBL | Targets, mechanisms, molecules and activity counts, from the API | 1 MB | about 5 min |
| AlphaFold | AlphaMissense's substitution table (1.2 GB), averaged per protein, and AFDB's confidence per entry | 1 MB kept | about 10 min |
| OmniPath | The curated network and transcription factor regulation, each requested with `license=commercial` | 41 MB | under a minute |
| GWAS Catalog | The full associations download with ontology annotations (73 MB zipped, 1.2 million associations), reduced to one row per gene and trait; the download then deleted | 111 MB kept | under a minute |
| STRING | The human physical subnetwork (detailed scores) and the alias table, the version from STRING's API; links mapped to Ensembl genes, the downloads then deleted | 59 MB kept | seconds |
| DepMap | The newest "DepMap NNQN Public" deposit on Figshare+ (its licence checked on the record): the two Chronos matrices (850 MB) reduced to one row per gene, then deleted | 57 MB kept | about 3 min |

About 2.6 GB in all, and half an hour on a good connection. The log goes to
the terminal; `data/mirror-build.log` holds the last full run.

## Where it lives

`data/` next to `app.py` when running from source, beside `Spica.exe` for the
built program, or anywhere if `SPICA_DATA_DIR` points there. To give the exe
a mirror, copy the folder: `dist/Spica.exe` with `dist/data/` beside it, or set
`SPICA_DATA_DIR`. The whole directory is outside version control: it is large
and specific to one machine.

    data/
      mirror.json
      hgnc/hgnc_complete_set.txt
      ensembl/genes.tsv
      uniprot/entries.tsv
      gtex/median_tpm.gct.gz
      gtex/tissues.tsv
      hpa/normal_ihc_data.tsv
      hpa/rna_tissue_consensus.tsv
      hpa/subcellular_location.tsv
      hpa/rna_single_cell_type.tsv
      hpa/rna_single_cell_cluster.tsv
      hpa/interaction_consensus.tsv
      hpa/ms_tissue.tsv
      clinvar/variant_summary.tsv
      clinvar/conditions.tsv
      opentargets/targets.jsonl
      opentargets/disease_xrefs.tsv
      chembl/targets.jsonl
      alphafold/summary.tsv
      omnipath/interactions.tsv
      omnipath/regulation.tsv
      string/physical.tsv
      gwas/traits.tsv
      depmap/genes.tsv
      depmap/Model.csv
      cache/            API answers, and the indexes below

Check what Spica can see with:

    python -m spica.cli --mirror

## Large files

HPA's single-cell cluster table is 1.5 GB, its staining table 95 MB, ClinVar's
reduced summary 180 MB. Scanning them for each record would make a report from
the mirror slower than one from the APIs, so each large plain file gets a byte
index the first time it is read (`spica/sources/index.py`): for every gene,
where its rows start and end. The release files are grouped by gene, so a gene
is one or two byte ranges, and the index of a 1.5 GB file is a few hundred
kilobytes. Indexes are kept under `data/cache/index/` and rebuilt only when
the file changes. The first report after a build takes ten seconds or so
while they are made; after that a report reads in about a second.

Gzipped files cannot be seeked into and are scanned; that is why the builder
unpacks HPA and keeps ClinVar's reduced table plain.

## mirror.json

The manifest is the only statement of what is mirrored. `version` and
`retrieved` land on the provenance of every value built from that source, so
both are required; a source that cannot name its release is skipped rather
than reported without one.

```json
{
  "mirror_version": "1",
  "sources": {
    "hgnc": {
      "label": "HGNC",
      "version": "2026-10-16",
      "retrieved": "2026-10-25",
      "license": "No restrictions",
      "files": { "complete_set": "hgnc/hgnc_complete_set.txt" }
    }
  }
}
```

| Key | Meaning |
| --- | --- |
| `label` | How the source is named in the report |
| `version` | The release, exactly as the source labels it (`v11`, `116`, `2026_03`, `25.1`) |
| `retrieved` | ISO date this copy was downloaded |
| `license` | Note of the terms checked before mirroring |
| `files` | Named paths, relative to the mirror root (absolute also works) |

Anything else in a source's object is passed through to its adapter; Ensembl
reads `assembly` that way, because the assembly is not in the export itself.

## What each source expects

The builder produces all of this; the table is for building a file another
way. Paths are free; the file *keys* and the column titles are what
the adapters read. Columns are matched by name, so a release that adds or
reorders columns still reads. Files may be gzipped: a `.gz` suffix is enough.

| Source | File key | Format and columns read |
| --- | --- | --- |
| `hgnc` | `complete_set` | `hgnc_complete_set.txt`: `hgnc_id`, `symbol`, `name`, `status`, `locus_type`, `location`, `alias_symbol`, `prev_symbol`, `entrez_id`, `ensembl_gene_id`, `uniprot_ids` |
| `ensembl` | `orthologs_mouse`, `orthologs_cyno` (optional) | BioMart exports, one per species, with BioMart's titles naming the species: `Gene stable ID`, `Mouse gene stable ID` (or `Crab-eating macaque ...`), `... gene name`, `... homology type`, `%id. target ... gene identical to query gene` (the share of the human protein identical in the ortholog, whatever the title suggests), `... orthology confidence [0 low, 1 high]`. Downloaded with BioMart's completion stamp, so a cut-off export is retried rather than kept |
| `ensembl` | `transcripts` (optional) | BioMart export: `Gene stable ID`, `Transcript stable ID`, `Transcript name`, `Transcript type`, `Ensembl Canonical`. The isoform view's names, biotypes and canonical flags |
| `ensembl` | `genes` | BioMart gene export: `Gene stable ID`, `Gene name`, `Gene type`, `Chromosome/scaffold name`, `Gene start (bp)`, `Gene end (bp)`, `Strand`. Add `"assembly"` to the manifest entry |
| `uniprot` | `entries` | UniProtKB TSV export: `Entry`, `Reviewed`, `Protein names`, `Gene Names`, `Length`, `Sequence`, `Subcellular location [CC]`; optionally `Function [CC]`, the three `Gene Ontology (...)` columns, `PDB` and `Alternative products (isoforms)`. Export `PDB` as `xref_pdb_full` (method, resolution and chains per entry) for resolution and coverage; with `xref_pdb` (IDs only) the count alone is filled |
| `gtex` | `median_tpm` | A release's median-TPM GCT matrix, gzipped or not |
| `gtex` | `tissues` (optional) | `tissueSiteDetailId`, `tissueSiteDetail`: the names GTEx prints, from its API. Without it, IDs are shown with spaces for underscores. Microdissected samples (v10 on) are named after their site, "Liver (Hepatocyte)", and kept in their own field so tau and the median count each tissue once |
| `hpa` | `normal_tissue` | `normal_ihc_data.tsv` (HPA 25; `normal_tissue.tsv` before): `Gene`, `Tissue`, `Cell type`, `Level`, `Reliability`, and `IHC tissue name` where HPA stained a tissue twice ("Skin 1", "Skin 2"): the strongest level per tissue, and every cell type within each sample |
| `hpa` | `rna_tissue` | `rna_tissue_consensus.tsv`: `Gene`, `Gene name`, `Tissue`, `nTPM`: the full consensus profile. Also names interaction partners when the interaction file carries IDs only |
| `hpa` | `subcellular_location` | `Gene`, `Reliability`, `Main location`, `Additional location` |
| `hpa` | `single_cell` (optional) | `rna_single_cell_type.tsv`: `Gene`, `Cell type`, and `nCPM` (HPA 25) or `nTPM` (before): the single-cell atlas, and the cell-type tau derived from it |
| `hpa` | `single_cell_tissue` (optional) | `rna_single_cell_cluster.tsv` (HPA 25; `rna_single_cell_type_tissue.tsv` before): `Gene`, `Tissue`, `Cell type`, `nCPM` or `nTPM`: cell types within tissues, the highest cluster kept; the organ view folds them by tissue |
| `hpa` | `interactions` (optional) | `interaction_consensus.tsv`: `ensembl_gene_id_1`, `ensembl_gene_id_2` (HPA 25), or `ensg_id_1`, `gene_name_1`, `ensg_id_2`, `gene_name_2` (before). The consensus file is a subset: HPA's API can count more partners than it lists |
| `hpa` | `brain_region` (optional) | `rna_brain_region_hpa.tsv`: `Gene`, `Brain region`, `nTPM`: HPA's brain atlas, one row per gene and region |
| `hpa` | `transcripts` (optional) | A table Spica defines from HPA's `transcript_rna_tissue` file (one TPM column per sample): `ensgid`, `enstid`, then the median TPM in each tissue. Sorted by gene. What the isoform view reads |
| `hpa` | `ms_tissue` (optional) | `ms_tissue.tsv`: `Gene`, `Tissue`, `Intensity`, detections only. Every tissue the file names for any gene was assayed, so a tissue absent for this gene reads 0 (not detected), as on the API route |
| `alphafold` | `plddt_residues`, `missense_residues` (optional) | Tables Spica defines: `accession`, `start`, `plddt` (comma-separated, one per residue, from each model's confidence file); `accession`, `means` (the mean AlphaMissense score of the 19 substitutions at each position, position 1 first). What the structure plot reads |
| `alphafold` | `summary` | A table Spica defines: `accession`, `mean_plddt`, `very_high`, `confident`, `low`, `very_low` (fractions), `am_mean`, `am_pathogenic_share` |
| `chembl` | `targets` | JSON Lines Spica defines, one per UniProt accession: `{"accession", "target", "activities", "drugs": [{"name", "phase", "action"}]}`. ChEMBL ships SQL dumps, which Spica does not read |
| `clinvar` | `conditions` (optional) | Built from the same download: `GeneSymbol`, `Condition`, `IDs` (MONDO, MedGen, OMIM, Orphanet), `Pathogenic`, `Records`, one row per gene and condition. What the disease-against-genetics view joins to Open Targets |
| `clinvar` | `variant_summary` | NCBI's `variant_summary`: `GeneSymbol`, `ClinicalSignificance`, `Assembly`, `VariationID`. GRCh38 rows only, single-gene rows only, one count per variation. Sorted by gene, so the index finds a gene in one range |
| `opentargets` | `disease_xrefs` (optional) | Built from the release's disease table: `id`, `name`, `xrefs` (OMIM, Orphanet, UMLS, MeSH and others, `|`-separated). The identifiers a disease is matched to ClinVar's conditions on |
| `omnipath` | `interactions` | OmniPath's `interactions` endpoint, dataset `omnipath`, with gene symbols and the fields `references`, `curation_effort`, `sources`, `type`: `source`, `target` (UniProt accessions, or `COMPLEX:` and the members' accessions joined by `_`), `source_genesymbol`, `target_genesymbol`, `is_directed`, `is_stimulation`, `is_inhibition`. Only records cleared for commercial use. What the interaction-partner view compares to HPA |
| `omnipath` | `regulation` | The same endpoint and columns for the datasets `dorothea`, `collectri` and `tf_target`: transcription factor to target. What shared regulation and the genome view's regulators read. A live service with no numbered releases, so the copy is dated |
| `gwas` | `traits` | A table Spica defines from the Catalog's associations: `gene_id` (the Catalog's own Ensembl mapping: the gene a variant is in, else the nearest gene on either side), `relation` (`in the gene` when any association has the variant inside it, else `nearest gene`), `trait` (the mapped trait), `trait_uris` (EFO, MONDO), `associations`, `studies`, and the strongest association's `mlog10p`, `p_value`, `risk_allele`, `or_beta`, `context`, `study`, `pubmed`. Sorted by gene, strongest first |
| `string` | `physical` | A table Spica defines from STRING's physical subnetwork: `gene_a`, `gene_b` (Ensembl genes, through STRING's `Ensembl_gene` aliases), `experimental`, `database`, `textmining`, `combined_score` (0 to 1000). Every link at every score, both directions, sorted by `gene_a`; the interaction view applies STRING's medium confidence (400) only to partners STRING alone names |
| `depmap` | `genes` | A table Spica defines, one row per gene, from CRISPRGeneEffect and CRISPRGeneDependency: `hgnc_id` (through the Entrez ID in DepMap's column names), `symbol`, `entrez`, `depmap_symbol`, `lines`, `mean_effect`, `median_effect`, `min_effect`, `dependent` (lines with dependency probability above 0.5), `dependent_share`, `common_essential` (in CRISPRInferredCommonEssentials), `lineages` (JSON: lineage to lines, dependent lines, mean effect), `histogram` (40 counts, 0.1-wide bins from -3 to 1, the ends open), `dependent_lines` (`ModelID:effect`, most dependent first) |
| `depmap` | `models` | The release's `Model.csv`: `ModelID`, `CellLineName`, `OncotreeLineage` |
| `opentargets` | `targets` | JSON Lines, one object per target keyed by `ensemblId`, in the shape the platform API returns (see `spica/sources/opentargets.py`). Built from the release parquet; from 26.09 tractability and safety come from their own datasets, which the builder reads |

HPA's files are independent: with one present and another not, the fields
from the missing file report `failed` and the rest are built.

## What the mirror does not hold

The record's fields all come from the mirror. The structure plot and the isoform view
read the mirror too, once it holds their per-residue and per-transcript
files (AlphaFold, HPA and Ensembl steps); without them they fall back to the
APIs, cached. What still reads an API, because its data is per region of
the genome and no release file is mirrored:

- the genome view's tracks (UCSC, ENCODE); its regulators come from the
  OmniPath copy when there is one;
- competitive intelligence (Europe PMC, EPO), which is new by nature.

With `SPICA_OFFLINE=1` these say what they could not reach instead of showing
an empty panel.

## When something is not there

Nothing in the mirror is required for a record to be produced. A source that
is absent, out of date or unreadable costs its own fields and nothing else,
and each of those fields says which of the three it was:

- `failed`: the mirror is missing, the manifest does not list it, or the
  file could not be read. Infrastructure, not biology.
- `not_found`: the file was read and has nothing for this gene or field.
- `not_covered`: the source does not cover this field for this gene, such
  as a UniProt accession for a long non-coding RNA.

HGNC is the exception worth knowing: it resolves what the user typed into the
identifiers every other source is looked up by, so without it nothing
resolves and the whole record is `failed`.

## Before a source is mirrored

A source with no files yet is fetched from its public API instead, so the
app works from the first run. This is scaffolding for the build-out: the
mirror is what a client runs on.

| Source | API |
| --- | --- |
| HGNC | `rest.genenames.org/fetch/<field>/<value>` |
| Ensembl | `rest.ensembl.org/lookup` |
| UniProt | `rest.uniprot.org/uniprotkb` |
| GTEx | `gtexportal.org/api/v2` |
| HPA | `proteinatlas.org/<ensembl id>.json`, and `api/search_download.php` for per-tissue RNA, antibody staining by tissue and cell type, mass spectrometry and the single-cell call |
| Open Targets | `api.platform.opentargets.org` (GraphQL), every disease association, page by page |
| ClinVar | NCBI E-utilities `esearch`, one count per classification, paced at three requests a second |
| AlphaFold DB | `alphafold.ebi.ac.uk/api/prediction/<accession>` and the AlphaMissense table it links |
| ChEMBL | `ebi.ac.uk/chembl/api/data`: target by accession, mechanisms, molecules, activity count |

What to know about it:

- **The mirror always wins.** A mirrored source is never fetched, whatever
  the network is doing.
- **Fetched values are marked.** The source is stamped `fetched` instead of
  `read`, and the value's provenance locator is the URL rather than a file.
- **Responses are cached** under `data/cache/`, so a rebuilt record does not
  drift and a second look sends no request. The retrieval date is the
  date of the fetch, not of the rebuild. `--refresh` fetches again.
- **It is off by default.** "Online access" in Settings turns it on;
  `SPICA_OFFLINE=1` keeps it off whatever Settings say.
- **The APIs are not the same data.** GTEx's API serves v10 (pinned to
  GENCODE v39, which is why the gene identifier has to come from GTEx rather
  than from HGNC), where the mirror takes the newest release files (v11).
  HPA's API summarises staining instead of listing it by tissue, and gives a
  single-cell call and a specificity call that no release file carries, so
  those two fields are `not_covered` from the mirror. Each value says which
  release it came from, so the difference is visible in the record rather
  than hidden in it.

Where the two routes once disagreed, and which one the field follows (each
checked gene by gene, `tests/test_route_agreement.py`):

| Field | Mirror | API | The record follows |
| --- | --- | --- | --- |
| ClinVar counts | Records whose gene list is this gene alone | ClinVar's `single_gene`, which also drops variants in an overlapping antisense or readthrough transcript (INS: 14, not 194) | The mirror; the API route undercounts such genes |
| Disease associations | Every direct association, less terms that are only measurements | The same, filtered by the platform | Both, now identical |
| HPA interactions | The consensus network (`interaction_consensus.tsv`) | A count over every database (EGFR: 926, against 187 in the consensus) | The mirror; the API route says `not_covered` rather than give the other count |
| HPA staining by tissue | Strongest cell type in the tissue | Now the same rule | Both |
| GTEx profile | v11's 54 sites; its 14 microdissected samples in their own field | v10's 54 sites | Both; values differ by release |

## Licenses

`docs/licences.md` records what each source's terms say, checked
rather than assumed, and the ones that need watching.

The `license` field is a place to record what was checked, not something
Spica verifies or asserts. Check each source's terms for local mirroring,
for API use, and for commercial use before relying on it, as the roadmap
requires. GTEx separates open-access summary files (all Spica reads) from
protected individual-level data; ChEMBL's share-alike terms reach material
derived from its values; HPA and UniProt ask for credit in what is handed to a
client.
