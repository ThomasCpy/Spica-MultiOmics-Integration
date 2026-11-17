"""The genome view: a gene locus, with all tracks that Spica can put on it.

Adapted from the IGV reports of the MultiOmics integrator, with these
changes for Spica:

- **The interface streams nothing.** The integrator gave igv.js remote
  URLs. Here Python fetches each track for the gene window and caches it.
  The interface gets plain features through the bridge. The bundled igv.js
  never makes a request (the CSP of the page would block it).
- **The reference is a slice.** Only the sequence of the window loads,
  named with its real coordinates, so the ruler shows GRCh38 positions.
- **Each track states its origin and its terms.** Tracks with unverified
  terms stay off until the user turns them on.

`locus.py` finds the window and its sequence. `tracks.py` holds the catalog
and the converters. `encode.py` searches ENCODE experiments. `bigfile.py`
reads a region from a remote bigBed or bigWig file.
"""
