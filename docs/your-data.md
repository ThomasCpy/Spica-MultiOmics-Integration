# User documents

Everything dropped into `data/input/` is read, cut into passages, embedded
locally and made searchable. This is the retrieval half of AI mode.

It has nothing to do with the gene report. A report is deterministic and
built from mirrored databases; an answer is synthesised from whatever the
agents find, the user's documents included. The two never mix.

## Indexing

```bash
python -m spica.ingest --dry-run   # what would be indexed, without embedding
python -m spica.ingest             # build it
python -m spica.ingest --stats     # what is in the index now
```

Run `--dry-run` first on a corpus not indexed before. Embedding is
the expensive step and it comes last, so a scanned PDF with no text layer, a
duplicate under a second name or a workbook that will not parse would
otherwise surface after a long wait, or not at all. The dry run costs a
minute and answers all three.

Re-running rebuilds from scratch. That is deliberate: an incremental path
that silently disagrees with the files on disk is a worse problem than the
wait, and the manifest is only worth trusting if it was written by the run
that produced the vectors beside it.

## What gets read

| Format | One unit is | What it costs to read |
| --- | --- | --- |
| `.pdf` | a page | reading order rebuilt from block geometry |
| `.xlsx`, `.xlsm` | a worksheet | every row carries its header |
| `.pptx` | a slide | native chart data rendered as numbers |
| `.docx` | a block | tables included |
| `.txt`, `.md`, `.csv`, `.tsv`, `.json` | a block | as written |

Anything else is listed as skipped rather than ignored silently.

Three problems are solved during extraction, each of which otherwise
degrades answers quietly rather than raising:

- **Column order.** A two-column paper read naively interleaves its
  columns, giving text that reads as two half-sentences spliced together.
  Blocks are grouped into columns by horizontal position and sorted
  column-first, but only when both sides carry real weight, so a
  one-column page with a marginal note is not shredded.
- **Hyphenation.** PDFs hard-wrap words across lines (`dereduc-\ntase`),
  fragmenting exactly the technical terms retrieval depends on. Line-break
  hyphens are rejoined; real ones (`NAD(P)H-dependent`) are not.
- **Running heads.** Journal name, DOI and page furniture repeat on every
  page and match everything weakly. Blocks recurring across most pages of a
  document are dropped.

**On plots.** A chart *built* in PowerPoint stores its categories and series
as numbers, and those are rendered as text, so the plot's data becomes
searchable. A chart *pasted as a picture* (a screenshot from Prism or a
paper) carries no data at all, and nothing short of a vision model can
recover it. Such slides are indexed by their surrounding text.

## Passages and citations

Text is cut into ~1200-character passages with 200 characters of overlap,
preferring a paragraph break, then a sentence end, then whitespace, so a
passage rarely begins mid-word. A passage keeps where it came from, and the
unit is named for the format, because "p7" means nothing for a deck:

    memo.pdf, p1
    deck.pptx, slide 3
    assays.xlsx, sheet 2
    notes.md, block 1

Pages are merged before cutting, so a passage can span a page break, which
is exactly where a paper splits a sentence. Slides and worksheets are not:
running them together produces chunks citing "slides 1-6", which points at a
whole deck and is no use for checking a claim, and blends unrelated content
into one embedding.

A file too short to make a full passage is still indexed whole. Dropping a
fragment is housekeeping; dropping an entire file is data loss, and a real
corpus is full of short notes.

## The embedding model

Put a `.gguf` embedding model in `data/models/embeddings/`, or choose one in
the menu. Qwen3-Embedding-0.6B is a good default and what this was built
against.

Two details decide whether retrieval works at all:

- **Pooling.** Families differ: Qwen3-Embedding takes the last token,
  BERT-style models take the mean. The wrong mode still yields vectors,
  plausible-looking and quietly useless. llama.cpp reads the right mode
  from the GGUF metadata, so it is left to.
- **Asymmetry.** Instruction-tuned retrieval models expect a query wrapped
  in an instruction while documents are embedded bare. Embedding both sides
  identically measurably degrades recall, so queries and documents go
  through separate methods rather than one method with a flag.

## The index on disk

Three plain files under `data/index/`, so it can be inspected with ordinary
tools:

    chunks.jsonl   one passage per line, with its source and location
    vectors.npy    the matrix, one unit-length row per passage
    manifest.json  every file ingested, its digest, and what it produced

Search is a brute-force dot product over the matrix. For a corpus of this
size that is not a compromise (a few thousand vectors is well under a
millisecond), and it avoids an approximate-nearest-neighbour dependency
that would have to be vendored, tuned and trusted.

An index whose two halves disagree refuses to load rather than answering
with the wrong citation.
