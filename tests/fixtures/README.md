# Test fixtures

`mirror/` is a complete but tiny stand-in for a real local mirror: the same
file formats and column titles as the releases, with three genes in them
(PCSK9, ADH1B, MALAT1) and one withdrawn HGNC entry.

They are not real data and must never be read as such:

- Protein sequences are truncated to about 50 residues, and each entry's
  `Length` column matches its truncated sequence rather than the real one.
- GTEx has five tissues instead of 68, and only two genes.
- HPA covers PCSK9 only.

The genes are chosen to exercise the record's null states: ADH1B is in HGNC,
Ensembl and UniProt but absent from the GTEx and HPA files (`not_found`),
and MALAT1 is a long non-coding RNA with no protein (`not_covered`).

Regenerate them with `python tests/make_fixtures.py` after changing a format.
