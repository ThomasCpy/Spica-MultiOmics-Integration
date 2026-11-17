# Competitive intelligence

Papers, preprints and patents on a topic, and what is new since the last
look. Built for the question a preclinical team asks every few weeks: *whether
another group works on the same target, modality or concept, and whether the IP is
still clear.*

It is a watch, not a freedom-to-operate opinion. Whether a patent stands in
the way depends on its claims, its family's legal status in each country and
the product, read by a patent attorney. This finds what they should read,
and finds it early.

## Using it

Open **Intelligence**, type terms separated by commas, pick a window, press
**Check now**:

```
CLDN18, zolbetuximab, claudin 18.2 CAR-T
```

- A term that names a gene is widened with its HGNC symbol, approved name,
  aliases and previous symbols (aliases under four characters are skipped:
  they match too much). Widened terms are shown dashed, each with where it
  came from. Untick *Widen gene symbols* to search only the typed terms.
- Every check is kept. The next check of the same topic marks what no
  earlier check had seen. The first check marks nothing new.
- If the terms or the window changed since the last check, the screen says
  so: some of what is marked new is then older work the wider search reaches.

## Sources

| What | Source | Key | Coverage |
| --- | --- | --- | --- |
| Papers | Europe PMC (`SRC:MED`) | none | PubMed and more |
| Preprints | Europe PMC (`SRC:PPR`) | none | bioRxiv, medRxiv, Research Square and others |
| Patents | EPO Open Patent Services 3.2 | user's own, free | EP, WO, US, CN, JP, KR and most other offices (DOCDB) |
| Clinical trials | ClinicalTrials.gov API v2 | none | Every registered study, registered or updated inside the window; a symbol ending in a digit also searches its isoforms (`docs/digest.md`) |

Europe PMC also indexes patents, but its patent index stops around 2012, so
it is no use for new filings. PatentsView (USPTO) did not resolve at all
when this was built, consistent with reports that it shut down in 2026, and
covered only the US anyway.

### EPO key for patents

Register for OPS on the EPO's developer portal (free), create an app, and
paste its consumer key and secret into **Add key** on the Intelligence
screen. Spica gets a token once to check they work before saving them. They
are kept in `data/settings.json` on this computer, sent only to
`ops.epo.org`, and never handed back to the interface. Tokens are never
written to the cache.

Without a key the patent panel says *not configured*, which is a different
statement from "no patents".

## How matching works, and the trap it avoids

Search is on title and abstract, inside a first-publication window.

Europe PMC indexes `CLDN18.2` as one token, so a search for `CLDN18` misses
every paper about the isoform: 15 hits against 67 in one quarter, measured.
A gene symbol therefore also matches its dotted forms (`CLDN18.*`). A bare
`CLDN18*` would be wrong the other way (`IL1*` is IL10, IL17 and the rest
of the family), while `IL1.*` matches nothing it should not.

For patents, the query is OPS's CQL: `ta="term"` for each term (title and
abstract), joined with `or`, and `pd within "from to"` for the window. The
isoform form is not applied there yet: type the isoform name.

Patents are grouped by DOCDB family, because one invention is published
several times (WO, then EP, US, CN) and a competitor's invention is one row.
The family's date is its latest publication inside the window.

## Limits, said plainly

- One check fetches up to 1,000 papers and 1,000 preprints, and up to 500
  patent publications. Past that the screen says how many more match and
  links to the same search on the source's own site.
- Only bibliographic metadata is kept for papers: title, authors, venue,
  date, identifiers. Abstracts stay at the source behind a link: their
  copyright sits with each publisher.
- **The OPS parser has been tested against OPS's documented response shape,
  not yet against a live response**: `epo.org` did not resolve from the
  network this was built on. The first real check with a key is the test.
  If it fails, the patent panel says why rather than showing an empty list.

## Offline

A watch on last month's filings cannot run from last year's mirror, so this
is the one part of Spica that needs the network by nature. It goes through
the same live layer as everything else: cached per day (the same check twice
in one day agrees with itself), stopped by `SPICA_OFFLINE=1`, and every past
check stays readable offline from `data/intel/<topic>.jsonl`, one line per
check, appended, never rewritten.

## Code

```
spica/intel/terms.py        typed terms, widened with HGNC names
spica/intel/literature.py   Europe PMC: papers and preprints
spica/intel/patents.py      EPO OPS: token, CQL, parsing, family grouping
spica/intel/watch.py        the append-only history and "new since"
frontend/src/components/Intel.tsx
tests/test_intel.py         stub transport, no network
```
