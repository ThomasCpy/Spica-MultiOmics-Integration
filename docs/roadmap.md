# Spica roadmap

Spica builds an extensive, sourced record for one gene, then compares many genes by
projecting the same records into a ranked table. The per-gene record comes first.

## Principles

- **Deterministic.** The same gene and the same database versions always give the same record.
- **Offline.** Databases are mirrored locally, and Spica is offline by default: nothing is
  fetched at report time. "Online access" in Settings is the switch for filling gaps from
  public APIs (cached, marked as fetched on the record); updating the mirror is a separate,
  explicit action in the same screen.
- **Three layers.** Raw downloads (kept unchanged) → normalized gene record → views
  (single-gene report, multi-gene table).
- **Fixed schema.** Every gene record has the same typed fields, so records stack into a table.
- **Provenance on every value.** Source, database version, retrieval date.
- **Explicit nulls.** Missing data says why: `not_found` (queried, nothing there),
  `not_covered` (source does not cover this), or `failed` (query error). Never a silent blank.
- **The LLM only reads the record.** It never fetches. Every claim it writes cites a field,
  and the citation is checked.
- **Licenses.** Check each source's terms for local mirroring and commercial use before adding it.
  Done for the six that are in, and recorded in `docs/licences.md`.

## Milestone 1: one gene, three sources

- Gene record schema: fields, types, provenance, null states. Room for derived metrics.
- Identity: HGNC, Ensembl, UniProt (symbol resolution, aliases, ID mapping).
- Expression: GTEx tissue RNA, Human Protein Atlas protein.
- Localization: UniProt and HPA subcellular data.
- Wire `Api.build_report` in `app.py` to build the record and show a first report screen.

## Milestone 2: about eight sources and a real report

*Done, but the run on real thesis candidates.* Thirteen sources are mirrored: HGNC,
Ensembl (with mouse and cynomolgus orthologs), UniProt, GTEx, HPA, Open Targets, ClinVar,
ChEMBL, AlphaFold DB, OmniPath, DepMap, STRING and the GWAS Catalog. The record is grouped
as identity, genomics, transcriptomics, proteomics, essentiality, clinical and predictive
insights, and the last of those is the point: tau, fold over median, RNA/protein
concordance, protein identity in the model species and the dependency reading are
comparable between genes in a way a raw peak value is not. IntAct is covered through HPA's
consensus network (its own site states no licence). The report screen and the exportable
client report are in.

- Add orthologs (mouse, cynomolgus), tractability (Open Targets, ChEMBL), safety signals
  (knockout phenotypes, DepMap essentiality), structure (PDB, AlphaFold DB), interactions
  (STRING, IntAct), disease genetics (Open Targets, ClinVar, GWAS Catalog).
- Single-gene report screen and an exportable HTML report in the Spica style.
- Run it on real thesis candidates.

## Milestone 3: many genes

*Done* (`docs/candidates.md`). Records build in under a tenth of a second from the mirror
(HGNC and GTEx read once per process, smaller files indexed), so a list of a thousand
genes ranks in about a minute.

- Upload a gene list, harmonize IDs with a mapping report the user confirms.
- Ranked table built from the records, with transparent, adjustable criteria weights.
- Benchmark: known clinical targets versus decoys for one modality.

## Later

- Derived, biologically meaningful metrics (therapeutic window, extracellular-domain
  conservation, RNA-protein concordance).
- Local LLM summary over the record, every claim cited. *Built early, ahead of the
  milestones: `spica/agents/` and `docs/agents.md`. Plan, read and draft run on a local
  Qwen; the citation check is code, not a model.*
- Outcome feedback: record which candidates held up at the bench.

## Added out of order: competitive intelligence

Asked for directly, ahead of the milestones above: papers, preprints and
patents on a topic, checked as a watch with "new since the last check".
Europe PMC and EPO OPS. It is the one feature that cannot follow the
offline principle (new filings are by definition not in a mirror), so it
uses the live layer with the offline switch, and keeps every check on disk.
Still to do: verify the OPS parser against a live response, isoform-aware
patent queries, and settling the EPO and Europe PMC terms for client use
(`docs/licences.md`).

## Added out of order: the digest

Asked for directly: scientific discussion, not hype, as it happens. Podcasts from journals and
learned societies, transcribed locally with whisper.cpp, searchable with the clinical trials
the watches now also find (ClinicalTrials.gov), from a Digest screen and from AI mode. Like
Intelligence it needs the network by nature, goes through the live layer and keeps everything
appended. Publishers that reserve text and data mining are listed by title only
(`docs/digest.md`, `docs/licences.md`).

## Added out of order: the genome view

Asked for directly: the MultiOmics integrator's IGV view with its databases.
In the report's Genomics section, with the tracks fetched by Python and the
interface kept off the network. What else comes over from the integrator, and
in what order, is in `docs/multiomics-import.md`.

## The MultiOmics import

First pass: genome view and regulation atlas, HPA staining by tissue and
cell type, mass spectrometry, single-cell, interactions, ClinVar,
structures and AlphaFold, AlphaMissense, ChEMBL, GO, isoforms,
co-expression, and shared regulation in Compare.

Second pass, asked for directly (30 Oct 2026), *done*: Datasets, any GEO
series searched or opened by accession, its samples in context, their
tracks on a gene's locus and a gene's values in its table (`spica/geo/`);
and Transcription factors at the promoter, the regulators' JASPAR motifs
scanned and crossed with their own ChIP-seq (`spica/tfscan.py`), JASPAR's
licence confirmed first. What is still left out, and why, is in
`docs/multiomics-import.md`.

## Added out of order: AI mode, faster

Asked for directly, *done*: a thinking switch on the Ask screen; reasoning
only where it pays (the first plan, the answer) and capped, closed and
acted on when the cap is reached; several tool calls in one move, run side
by side and returned as one package, short outputs kept as they are
(`docs/agents.md`). The digest gained Process all, which builds the whole
corpus in the background with an estimate, a stop and a resume
(`docs/digest.md`). The main menu can be floating cards on a home screen
instead of the sidebar (Settings, Appearance, Main menu; the sidebar stays
the default): the cards turn slowly under the centred logo, a card unfolds
its submenu, a still row of every screen, the keys 1 to 9, typing a name
and double-clicking each go straight in, and inside a screen a slim bar
replaces the sidebar.

## Finishing the product

In this order. Each item names what "done" means.

1. **Offline by default, data updated in the app.** *Done.* Online access is a switch in
   Settings, off unless turned on. The local data panel (Settings, Databases) checks each
   source for a newer release and rebuilds what moved, in a process of its own; the exe
   does it too, without Python.
2. **AI mode reaches what the report reaches.** *Done.* A tool for every view beside the record
   (organ alignment, the glance words, structure, isoforms, co-expression, regulators,
   genome tracks, competitive intelligence); a tool that reads any one field whole rather
   than its first eight entries; compare on every comparable field with no gene limit;
   empty fields shown with their reasons; citations to tool output checked like citations
   to the record. A test fails when a view is added without its tool.
3. **Comparisons across databases, each with a plot.** *Done.* Agreement between every two
   expression sources (log-scale correlation) with a scatter per pair; Open Targets diseases
   against ClinVar genetics, joined on identifiers; tractability as Open Targets' whole
   framework; drugs by phase; where the protein sits (UniProt, HPA, GO) as one cell diagram;
   interaction partners in HPA's experiments against OmniPath's curation, joined through
   HGNC, as an overlap bar and an evidence matrix. OmniPath is mirrored, so regulators read
   offline too.
4. **Milestone 2's remainder.** The exportable client report the art direction describes
   (*done*: "Export report" on the report and the comparison, `spica/export.py`); orthologs
   (*done*: mouse and cynomolgus from Ensembl Compara, mirrored, with protein identity as a
   comparable figure); DepMap essentiality (*done*: an Essentiality section from the newest
   Figshare+ release, lineage chart, gene-effect histogram, and a derived reading of common
   essential, selective or rare); STRING (*done*: the physical subnetwork, a third network in
   the interaction comparison, shown as combinations of networks); GWAS Catalog (*done*: traits,
   lead variants and genome-wide counts in the record, and common variants as a third column
   in disease against genetics, joined on EFO and MONDO terms). *Step done.* Each source
   licence-checked first (`docs/licences.md`).
5. **Milestone 3.** *Done.* Gene lists with an ID mapping the user confirms (exact, alias,
   renamed, ambiguous, not found, duplicate; numbers that are both an HGNC number and an
   Entrez ID are asked about); the ranked table with adjustable weights and modality presets
   (the Candidates screen), re-ranked live, exported with the ranked table on page one; the
   benchmark of approved targets against decoys, with the criteria that carry the label left
   out (antibody AUC 0.86, small molecule 0.87). AI mode reads all three (`genelist`,
   `candidates`, `benchmark`).
6. **Ready to sell.** Brain-region data on clear terms (*done*: HPA's brain atlas, CC BY
   4.0, as a field and a chart; the Allen atlases stay out, needing the Institute's written
   permission for commercial use); the per-transcript view reads the mirror (*done*: HPA
   transcript medians per tissue, with Ensembl's names). The per-residue view reads the
   mirror (*done for AlphaMissense*, all 20,516 proteins; AlphaFold confidence per residue
   for 7,100 of 20,431 models so far: AlphaFold DB's file server began refusing the bulk
   fetch with HTTP 403, so the step now asks four at a time, keeps what it has and reports
   what it lacks; for the rest the view asks AlphaFold DB for that one protein, cached).
   AlphaFold stays in (the owner's decision; both are CC BY 4.0 as published). Left
   for the owner: code signing (the build signs when a certificate is
   configured, `docs/licensing.md`).
