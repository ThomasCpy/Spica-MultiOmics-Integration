# Licences, and what they allow commercially

A record of what each source says about reuse, checked on 25 October 2026.
It is a working note for deciding what goes in, not legal advice, and the
terms change: re-read the pages before anything ships to a client.

The roadmap requires this check before a source is added. The short version:
**everything Spica reads today permits commercial use**, but three things
need watching, and they are set out at the bottom.

## What is in now

| Source | Terms | Commercial | Attribution |
| --- | --- | --- | --- |
| [HGNC](https://www.genenames.org/about/) | "No restrictions are imposed on access to, or use of, the data provided by the HGNC." No named licence | Yes | Requested: HUGO Gene Nomenclature Committee at the University of Cambridge, plus the URL |
| [Ensembl](https://www.ensembl.org/info/about/legal/disclaimer.html) | "Ensembl imposes no restrictions on access to, or use of, the data provided." Code is Apache 2.0 | Yes | Not required, customary |
| [UniProt](https://ftp.ebi.ac.uk/pub/databases/uniprot/LICENSE) | CC BY 4.0. "All databases and documents in the UniProt FTP directory may be copied and redistributed freely" | Yes | Required |
| [GTEx](https://gtexportal.org/home/faq) | Two tiers. The open tier, which is all Spica reads, is public summary data. Individual-level data is controlled through dbGaP and AnVIL | Yes, open tier | Citation customary |
| [Human Protein Atlas](https://www.proteinatlas.org/about/licence) | CC BY 4.0. "We encourage you to use our resource for your research and commercial purposes" | Yes, explicitly | Required, and strict: cite the publication, the site, and each specific image used |
| [Open Targets](https://platform-docs.opentargets.org/licence) | CC0 1.0 for the Platform itself | Yes | Not required, customary |
| [OmniPath](https://omnipathdb.org/info) | Licence varies by underlying resource, record by record. The service's `license=commercial` filter returns only records whose resources allow commercial use; the mirror is built with it and the API route always sends it, so no other record reaches Spica. OmniPath asks to be cited along with the resources each record came from, which every record names | Yes, filtered | Required per resource: OmniPath's paper, and the `sources` each record lists |
| [GWAS Catalog](https://www.ebi.ac.uk/gwas/docs/about) | The general [Terms of Use for EMBL-EBI Services](https://www.ebi.ac.uk/about/terms-of-use): "EMBL-EBI itself places no additional restrictions on the use or redistribution of the data" beyond the data owners'; attribution expected. Summary statistics CC0 unless stated; Spica reads the curated associations only | Yes, no restriction added | Expected: cite the Catalog |
| [STRING](https://string-db.org/cgi/access) | CC BY 4.0: "All data and download files in STRING are freely available", "including commercial use". Material STRING shows from other resources keeps its provider's terms; Spica reads STRING's own scored links | Yes | Required: cite STRING, and say what was changed (Spica maps proteins to Ensembl genes and keeps the physical subnetwork) |
| [DepMap](https://doi.org/10.25452/figshare.plus.27993248.v1) | CC BY 4.0, stated on the Figshare+ release record; DepMap-generated data only (the Achilles CRISPR files and the model table). Not the Sanger Cancer Dependency Map, which forbids commercial use without consent | Yes | Required: DepMap, Broad, the release and its DOI |
| [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/intro/) | Records written by NCBI are US government works, public domain. NCBI places no restrictions on use, but submitters do not assign rights to NCBI and may hold IP in their own submissions (NCBI's long-standing molecular data policy, via secondary sources; the current page sits behind a browser check). Spica keeps counts of classifications, not submission text | Yes | Requested: cite ClinVar |

## Genome view sources

Searched for the gene's window and cached, not mirrored. See `docs/genome.md`.

| Source | Terms | Commercial | In Spica |
| --- | --- | --- | --- |
| [UCSC Genome Browser data](https://genome.ucsc.edu/license/) | "The data displayed by the browser is freely available for both public and commercial use, with a few exceptions"; restrictions are per assembly and per track. The browser *software* needs a commercial licence; Spica uses the data API only, not the software | Yes, per track | GENCODE, cCREs, CpG islands, ClinVar, dbSNP, GTEx, phyloP, RepeatMasker, ENCODE DNase and H3K27ac |
| [ENCODE](https://www.encodeproject.org/about/data-use-policy/) | "External data users may freely download, analyze and publish results based on any ENCODE data without restrictions." API use is limited to 10 requests a second | Yes (no restriction stated) | cCREs, TF clusters, any released experiment |
| NCBI ClinVar, dbSNP | US government works, public domain | Yes | Variant tracks |
| [OmniPath](https://omnipathdb.org/) | As in the table above: only records cleared for commercial use, from the mirror or the API | Yes, filtered | A gene's regulators |
| [JASPAR](https://jaspar.elixir.no/about/) | JASPAR's own about page: "licensed under the Creative Commons Attribution 4.0 International License" (checked 30 Oct 2026; an older paper record said CC BY-NC, the site now settles it) | Yes, with attribution | The 2024 CORE vertebrates matrices for the promoter scan (`spica/tfscan.py`), and UCSC's JASPAR track |
| ENCORI (starBase) | Terms not found | **Unverified** | Off by default, marked on screen |
| [NCBI GEO](https://www.ncbi.nlm.nih.gov/geo/info/disclaimer.html) | "NCBI itself places no restrictions on the use or distribution of the GEO data. However, some submitters may claim patent, copyright, or other intellectual property rights in all or a portion of the data they have submitted." Read through NCBI's E-utilities and file server (checked 30 Oct 2026) | Yes from NCBI; a submitter's own rights travel with their files, so Spica names the series and sample on every track and value | Datasets: series, samples in context, tracks over a gene's window, a gene's row in a processed table (`spica/geo/`) |

Left out on purpose: OMIM and HGMD (licensed), GeneHancer (GeneCards,
commercial licence), ReMap (terms not found).

## Competitive intelligence sources

These are searched, not mirrored: a watch is about this month's filings.
See `docs/intelligence.md`.

| Source | Terms | Commercial | What Spica keeps |
| --- | --- | --- | --- |
| [EPO Open Patent Services](https://www.epo.org/en/service-support/ordering/ops-terms-and-conditions) | Registered users get a non-exclusive licence to use OPS data and include it in their own products and services; the data may not be made available to the public "as such" or redistributed on its own. Free up to 4 GB a week under the [fair-use charter](https://www.epo.org/en/service-support/ordering/fair-use) | Yes, inside a product, each user with their own key | Bibliographic data per family, in that user's own watch files |
| [ClinicalTrials.gov](https://www.nlm.nih.gov/databases/download/terms_and_conditions.html) | NLM's terms: no charge, no restriction on commercial use; credit "Courtesy of the U.S. National Library of Medicine", say a copy may not be current, imply no endorsement; the [registry's own terms](https://classic.clinicaltrials.gov/ct2/about-site/terms-conditions) add stating processing dates and changes | Yes | Each trial's registered fields and a link, with the credit and the currency note on screen |
| Europe PMC | Not verified. The terms page refused automated reading, and the abstracts' copyright sits with each publisher | Treated as unknown | Bibliographic metadata and a link only, no abstracts |

Two things to settle before selling this: whether showing OPS results to
a client inside Spica is "your own product" in the EPO's sense (the
plausible reading, not yet confirmed; patentdata@epo.org answers this),
and Europe PMC's terms for metadata reuse. Each user registering their own
OPS key keeps Spica out of redistributing EPO data in the meantime.

## The digest's podcasts

Checked on 2026-10-28 (`docs/digest.md`). No podcast publisher states terms for transcribing
its episodes; the machine-readable reservations were checked instead, as the EU's text and
data mining exception (Article 4 of Directive 2019/790) makes them the deciding signal.

| Publisher | Feeds | Reservation found | In Spica |
| --- | --- | --- | --- |
| ASCO | ASCO Daily News, JCO Podcast, JCO Precision Oncology | None (no TDMRep file on ascopubs.org; generic copyright line) | Transcribed here, kept here |
| NEJM Group | NEJM This Week | None (no TDMRep file on nejm.org) | Transcribed here, kept here |
| eLife, the Naked Scientists | The eLife Podcast | None found | Transcribed here, kept here |
| AACR | AACR Scientific Podcasts | None found | Transcribed here, kept here |
| Springer Nature | Nature Podcast | TDMRep `tdm-reservation: 1` on nature.com | Titles only |
| AAAS | Science Magazine Podcast | TDMRep on science.org | Titles only |
| Elsevier | The Lancet Oncology podcast; Cell Podcast | TDMRep on thelancet.com; `tdm-reservation` header on the Cell feed | Titles only; Cell left out |
| AMA | JAMA Oncology Author Interviews | Copyright line: "including those for text and data mining, AI training" | Titles only |

The check is not a one-off: every update repeats it for every feed (`spica/digest/feeds.py`).
Transcripts stay on the user's computer and are never put in a client report; the UK's
exception, for comparison, covers non-commercial research only, so a licensee outside the EU
should take advice before transcribing for commercial work.

Transcription runs with whisper.cpp (MIT) through pywhispercpp (MIT, its low-level bindings
only) and miniaudio (MIT); the speech models are OpenAI's Whisper weights, MIT, converted by
whisper.cpp's authors and downloaded by the user, not bundled.

## The three things to watch

**1. Open Targets is CC0 on the outside, mixed on the inside.** The
Platform marks its own output CC0, and says every source "agreed for their
data to be used without restriction". But its licence page then lists
constituent datasets under other terms: ChEMBL and the Human Protein Atlas
as CC BY-SA 3.0, Europe PMC content as possibly CC BY-NC depending on the
publication, ClinVar, GWAS Catalog, IntAct, Gene2Phenotype and Signor under
EMBL-EBI terms of use, and FinnGen summary statistics behind a request
form. Cancer Gene Census, PanelApp and Project Score are listed only as
"Commercial use for Open Targets", with nothing further.

This matters for Spica because `tractability` is partly ChEMBL-derived.
Taking the aggregate as CC0 and stopping there would be a mistake: the
field-level provenance Spica already records is what makes it answerable,
and the honest position is that a client report quoting tractability may be
quoting share-alike data.

**2. Share-alike is the most restrictive term.** CC BY-SA requires
derivative works to carry the same licence. A client report built partly on
ChEMBL-derived values may be a derivative. Non-commercial terms (the Europe
PMC subset) would be worse, and are the one category to keep out of a
commercial path entirely.

There is a discrepancy worth resolving: HPA's own licence page says CC BY
4.0 and encourages commercial use, while Open Targets lists HPA as CC BY-SA
3.0. Most likely HPA relicensed and the aggregator's page is stale, but
that is a guess. Ask HPA before relying on either reading.

**3. "Third-party constraints" is a real clause, not boilerplate.** Both
Ensembl and HGNC disclaim restrictions on their own data while noting that
some included data may carry third-party terms, and that the user is
"solely responsible for establishing the nature of and complying with any
such restrictions". Neither enumerates them.

## Added with the MultiOmics import

| Source | Terms | Commercial | In Spica |
| --- | --- | --- | --- |
| [RCSB PDB](https://www.rcsb.org/pages/policies) | wwPDB archive data under CC0 1.0, "freely available to all PDB Users including commercial users". Data RCSB integrates from third parties (DrugBank, CC BY-NC) keeps its own terms; Spica takes none of it | Yes | Structure counts, resolution, coverage, read from UniProt's cross-references |
| [AlphaFold DB](https://alphafold.ebi.ac.uk/download) | CC BY 4.0 (checked below) | Yes | Model confidence, per-residue pLDDT |
| [AlphaMissense](https://github.com/google-deepmind/alphamissense) | The official repository now states CC BY 4.0 for the predictions; an earlier release carried a non-commercial licence, so check which version a mirror holds | Yes, current release | Mean pathogenicity, pathogenic share, per-residue profile |
| [Gene Ontology](https://geneontology.org/docs/go-citation-policy/) | CC BY 4.0; name the release used | Yes | GO terms, read from UniProt |
| ChEMBL | CC BY-SA 3.0 (checked below). Share-alike reaches anything derived from these values | Yes, share-alike | Target, drugs and phase, activity count |

Checked and left out, terms not found or not cleared: **DGIdb** (aggregates
41 sources; no data licence found), **miRTarBase** (no terms found),
**ProteomicsDB** (no terms found), **IntAct** (old papers say CC BY; the
current site states none). HPA's interaction partners cover what IntAct
would have, under HPA's CC BY 4.0.

## Differential expression (software)

PyDESeq2 0.5.4 (MIT; Muzellec et al., Bioinformatics 2023) runs DESeq2 on GEO
count tables (`spica/geo/de.py`). Checked 2026-11-08, with the package
metadata of every distribution a DESeq2 run imports:

| Licence | Packages |
| --- | --- |
| MIT | pydeseq2, formulaic, interface_meta, narwhals, natsort, numcodecs, zarr, donfig, pydantic, pydantic-core, pydantic-settings, annotated-types, typing-inspection, pyparsing, fonttools, PyYAML |
| BSD | anndata, h5py, pandas, scipy, scikit-learn, joblib, cloudpickle, threadpoolctl, msgspec, python-dateutil, python-dotenv, scverse-misc, formulaic-contrasts, contourpy, cycler, kiwisolver, wrapt, psutil |
| Apache-2.0 | google-crc32c, tzdata |
| Matplotlib licence (PSF-based, permissive) | matplotlib |
| **MPL-2.0** | **legacy-api-wrap** (imported by anndata) |

MPL-2.0 is file-level copyleft, not GPL: unmodified, it requires its licence
text and a pointer to its source, and places no condition on Spica's own
code. It is weaker than the rule "permissive only" reads, so it is recorded
here for a decision. `session-info2` (also MPL-2.0) is installed with anndata
but never imported; the exe leaves it out (`tools/build_exe.py`).

## Before adding the next sources

Checked:

- **AlphaFold DB:** CC BY 4.0, [academic and commercial use](https://alphafold.ebi.ac.uk/download),
  with attribution to DeepMind and third-party copyright holders. Two
  caveats: the data is "not approved for any clinical use", and AlphaFold 3
  (generating *new* predictions rather than reading the database) is
  non-commercial under separate terms. Reading the database is the safe one.
  Checked again on 2026-10-28, after the question was raised that AlphaFold is
  forbidden commercially: the download page still says "Data is available for
  academic and commercial use, under a CC-BY-4.0 licence", and the AlphaMissense
  repository says its predictions are "licensed under the Creative Commons
  Attribution 4.0 International License (CC BY 4.0)". What is non-commercial
  is the AlphaFold Server (its terms also bar using its output for docking or
  screening) and the AlphaFold 3 code and weights. Spica uses neither: it never
  runs a model, it reads the published database. The owner decides whether to
  keep AlphaFold in a release; until then the per-residue download is not run.
- **ChEMBL:** [CC BY-SA 3.0](https://chembl.gitbook.io/chembl-interface-documentation/about).
  Commercial use permitted, share-alike applies. Worth having; worth
  recording as share-alike wherever it lands in a record.

Checked on 2026-10-28, for the last of milestone 2:

- **DepMap (Broad):** CC BY 4.0, stated on the release record itself:
  [DepMap 24Q4 Public on Figshare+](https://doi.org/10.25452/figshare.plus.27993248.v1)
  carries `CC BY 4.0`, and the DepMap team's
  [forum answer](https://forum.depmap.org/t/license-for-data-found-in-the-depmap-portal/130)
  says data DepMap generates is CC BY 4.0 while other projects hosted on the
  portal may differ. Spica reads only the Achilles CRISPR files (gene
  effect, dependency probability, common essentials) and the model table,
  all DepMap's own. Credit: "DepMap, Broad (2024): DepMap 24Q4 Public.
  Figshare+. Dataset", with the DOI. Two cautions. The portal now sits
  behind a browser check, so the mirror reads the Figshare+ deposit, and
  24Q4 is the newest release deposited there; later releases are on the
  portal only. And the *Sanger* Cancer Dependency Map
  ([depmap.sanger.ac.uk](https://depmap.sanger.ac.uk/documentation/data-usage-policy/))
  is a different resource that forbids commercial use without consent:
  Spica does not read it.
- **STRING:** CC BY 4.0, from STRING's own
  [access page](https://string-db.org/cgi/access): "All data and download
  files in STRING are freely available under a 'Creative Commons BY 4.0'
  license", "including commercial use". Cite STRING and say what was changed;
  material STRING displays from other resources keeps its provider's terms.
  Current version 12.5.
- **GWAS Catalog:** under the general
  [Terms of Use for EMBL-EBI Services](https://www.ebi.ac.uk/about/terms-of-use)
  ([about](https://www.ebi.ac.uk/gwas/docs/about)): "EMBL-EBI itself places no
  additional restrictions on the use or redistribution of the data ... other
  than those provided by the original data owners", and attribution is
  expected. Summary statistics are CC0 unless a study says otherwise; Spica
  reads the curated associations, not summary statistics. The terms do not
  name commercial use either way, and add no restriction: cleared, with the
  Catalog cited.

## How this is recorded

The `license` field in `data/mirror.json` is where the answer goes for each
mirrored source: a note of what was checked, not something Spica
asserts. The live routes carry no such field, which is a gap worth closing
if fetched values ever reach a client report.
