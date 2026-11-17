# Genome view

A gene's locus in igv.js, inside the report's Genomics section, with every
track Spica can put on it. Adapted from the MultiOmics integrator's IGV
reports (`plotter.py`, `modules/regulation.py`), rebuilt so the interface
never touches the network.

## How it works

1. Opening Genomics asks Python for the locus: the gene's coordinates
   (Ensembl), a window of the gene plus 50 kb either side, and that window's
   GRCh38 sequence (UCSC, Ensembl as fallback).
2. The sequence becomes igv.js's reference, named `chr3:FROM-TO @len=N` so
   igv.js places it at its real coordinates. The ruler reads GRCh38 positions.
3. Each track is fetched by Python for the whole window, cached, and handed to
   igv.js as plain features. Panning inside the window costs nothing.
4. igv.js is told not to load its genome list or search service, and the page
   carries a Content-Security-Policy that refuses any network request from the
   interface. Whatever a bundled library tries, the webview blocks it.

## Tracks

On by default: GENCODE genes, Ensembl Regulatory Build, ENCODE cCREs, CpG
islands, ClinVar, phyloP conservation. Everything else is one click away.

| Group | Track | Source | Terms |
| --- | --- | --- | --- |
| Genes | GENCODE transcripts | UCSC | free, public and commercial |
| Regulation | Regulatory Build | Ensembl | no restrictions |
| Regulation | Candidate cis-regulatory elements | ENCODE via UCSC | unrestricted |
| Regulation | CpG islands | UCSC | free |
| TF binding | ChIP-seq clusters, 340 factors | ENCODE via UCSC | unrestricted |
| TF binding | Regulator motif sites, with their ChIP-seq (scanned here) | JASPAR 2024, OmniPath, ENCODE | CC BY 4.0, off by default |
| TF binding | Regulator motifs near the promoter | JASPAR 2024 via UCSC | CC BY 4.0, off by default |
| miRNA | Binding sites | ENCORI | **unverified**, off by default |
| Variants | ClinVar | NCBI via UCSC | public domain |
| Variants | Common variants | dbSNP 155 via UCSC | public domain |
| Variants | eQTLs acting on this gene | GTEx via UCSC | open tier |
| Conservation | phyloP, 100 vertebrates | UCSC | free |
| Conservation | Repeats | RepeatMasker via UCSC | free |
| By tissue | Open chromatin (DNase), 40 tissues | ENCODE via UCSC | unrestricted |
| By tissue | Active chromatin (H3K27ac), 38 tissues | ENCODE via UCSC | unrestricted |
| By tissue | RNA-seq coverage, 54 tissues | GTEx via UCSC | open tier |
| ENCODE | Any released experiment: ATAC-seq, DNase-seq, H3K27ac, WGBS, ChromHMM | ENCODE files | unrestricted |
| Regulators | Each regulator's measured ChIP-seq peaks | OmniPath (commercial records) + ENCODE | per record |
| GEO | Any GEO series' bigWig, bigBed, peak and signal files | NCBI GEO | no restriction from NCBI; submitters' rights travel with their files |

Per-tissue tracks open on the tissue where the gene's GTEx expression peaks,
and several tissues can be added side by side to compare them.

Two tracks are defined narrowly on purpose, and say so on screen:

- **JASPAR** returned 782,453 motif hits in one 135 kb window. The track shows
  only motifs of the gene's own OmniPath regulators, within 2 kb of the TSS,
  at a score of 400 or more (JASPAR's own default, p < 1e-4).
- **GTEx eQTLs** in a window include those acting on neighbouring genes. The
  track keeps the ones acting on this gene.

Signal tracks are binned to 4,000 points over the window (about 35 bases a bin
for a 135 kb window). A bin with no data is left out, never drawn as zero.

## Regulation atlas

Below the track list, the integrator's regulation atlas: one assay (open
chromatin, H3K27ac, or GTEx RNA coverage) in every tissue across the window,
one row per tissue. Rows share one scale because every row is the same
assay, so tissues compare directly. Each row carries its peak figure, the
hover gives any cell's value, and the scale is printed. Rows come from the
same cached signals as the per-tissue tracks.

## Transcription factors at the promoter

Above the genome view, the integrator's transcription-factor menu, crossed
the way it was heading (`spica/tfscan.py`):

1. The gene's regulators from OmniPath, commercial records only, with each
   edge's sign, DoRothEA's confidence letter and the papers behind it.
2. Each regulator's JASPAR 2024 matrix (CORE, vertebrates, non-redundant;
   a factor without its own matrix takes a dimer it belongs to, and says
   so), its IUPAC consensus and a sequence logo.
3. A scan of the promoter on both strands, 2,000 bases upstream of the
   canonical TSS to 500 into the gene by default (1,000 to 10,000 and 200
   to 1,000 can be chosen). A site counts at p < 1e-4, JASPAR's own cut-off,
   with the p-value computed exactly from the matrix under a uniform
   background (the score distribution convolved column by column), not as
   a share of the best score. A palindrome is one site, not two.
4. ENCODE's clustered TF ChIP-seq peaks (UCSC, 340 factors, 2019) over the
   same bases, factor by factor, and whether ENCODE assayed the factor at
   all. A motif site inside a peak of the same factor carries both kinds of
   evidence, the strongest case for direct regulation public data makes.

The map puts every site and every own peak on one axis, TSS at zero:
filled for a site in its factor's own peak, outlined for motif only, so it
reads in grey. "Show the sites in the genome view" loads the same scan as a
track. Checked on PCSK9: SREBF2's sterol response element at -51 inside
SREBF2's own peak, HNF1A's site 39 bases upstream of it, the pair the
literature describes.

## Tracks from GEO

Any GEO series can put its samples' files on the locus (`spica/geo/`).
The genome view's "Tracks from GEO" panel takes an accession; the Datasets
screen searches GEO, shows every sample in context and opens a gene's
report at Genomics with the chosen tracks already loaded.

- bigWig and bigBed are read by byte range, like ENCODE files. Their
  chromosome lengths settle the build (chr1 is 248,956,422 bases in GRCh38,
  249,250,621 in GRCh37).
- BED, narrowPeak, broadPeak, bedGraph and WIG text files have no index:
  they are streamed once, up to 400 MB compressed, keeping only the window.
- A GRCh37 file is read over the stretch Ensembl maps the window to, and
  each record is carried back onto GRCh38; the track says "GRCh37, mapped".
  NCBI36 (hg18) and mouse files are listed but not drawn.
- What a file is, and its build, come from its name and its sample's
  processing notes; contact details in GEO's records are never read.

## Reading ENCODE files

ENCODE publishes peaks, signal and methylation as bigBed and bigWig files of
hundreds of megabytes. `spica/genome/bigfile.py` reads only the window: the
header, two index walks and the compressed blocks that overlap it, by HTTP
range request. It is the format as UCSC documents it, in `struct` and `zlib`,
so the portable runtime and the exe need no compiled extension (the
integrator used `pybigtools`).

Checked against ground truth: reading UCSC's own cCRE bigBed gives exactly the
25 records UCSC's API gives for the same region; the phyloP bigWig aligns base
for base (the API serves an 8-bit quantised copy, so its values differ in the
second decimal). Following ENCODE's download redirect once and merging
neighbouring blocks into one request took an ATAC-seq read from 142 s and 65
requests to about 9 s and 7.

## Colours

Azure for data. Orange only as a second pole: pathogenic ClinVar variants,
cleavage-validated miRNA sites, conserved bases in phyloP. Slate and ink for
the rest. The bases themselves avoid igv.js's red and green. Identity is
always carried by a label as well as a colour.

## Code

```
spica/genome/locus.py      window, coordinates, reference slice
spica/genome/tracks.py     catalog, converters, fetchers
spica/genome/encode.py     ENCODE experiment search
spica/genome/bigfile.py    bigBed / bigWig region reader
spica/tfscan.py            regulators, JASPAR scan, ChIP-seq crossing
spica/geo/                 GEO series, samples, tracks, a gene's table row
frontend/src/components/GenomeView.tsx
tests/test_genome.py       files built byte by byte, stub transport
```
