"""Competitive intelligence: what was filed and published on a topic.

The question is narrow: *whether a new paper, patent or trial appeared on
the target, modality or sequence since the last check.* That is a watch,
not a report, and the design follows:

- **A topic is a set of terms** that the user types. When a term is a
  gene, its HGNC names and aliases join in: a paper about "claudin 18" is
  also about CLDN18.
- **Separate sources.** Papers and preprints from Europe PMC. Patents from
  the EPO Open Patent Services, which cover EP, WO, US, CN, JP and most
  other offices. Each source states what it could not do, in the three
  states of the record, and does not return an empty list instead.
- **Each check stays.** Runs are appended, never rewritten. A watch can
  thus show what is new since the last check, and it reads offline.

It is not a freedom-to-operate opinion. That needs a patent attorney to
read the claims of each patent against the product. This finds what they
must read, and finds it early.

Unlike the gene record, this needs the network by nature: a watch on last
month's filings cannot run from last year's mirror. It uses the same
cached, switchable live layer (`SPICA_OFFLINE=1` stops it), and past checks
stay readable without a connection.
"""

from spica.intel.watch import Watches, run_watch

__all__ = ["Watches", "run_watch"]
