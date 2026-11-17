"""NCBI GEO: any series, its samples in context, and their tracks.

From the perturbation search (`modules/perturbation.py`) and the ENCODE
explorer of the integrator, which fed IGV. Find a series, read what each
sample is (cell type, treatment, antibody, assay), select the relevant
samples, and put their tracks on the gene locus.

- `records.py` reads a series and its samples from the GEO text records. It
  sorts their files into tracks, matrices and other files.
- `search.py` finds series through the NCBI E-utilities, with the other
  names of a gene.
- `tracks.py` reads the file of a sample over the gene window. bigWig and
  bigBed use byte ranges; peak and signal text files are streamed. GRCh37
  files map onto GRCh38.
- `response.py` reads the row of one gene from the processed table of a
  series. It puts the samples side by side, treated against control where
  the labels say which is which.
- `de.py` gives differential expression for a volcano plot.

All of it goes through `spica/live.py`, respects `SPICA_OFFLINE` and caches
what it reads. A series opened once thus opens again offline.

GEO terms: NCBI places no restriction on use or distribution. Submitters
can hold rights in their data (`docs/licences.md`).
"""
