"""The sources a record is built from, in the order they are read.

HGNC is first and is not optional: it resolves what the user typed into the
identifiers every other source is looked up by. The rest are independent of
each other, so one missing mirror costs its own fields and nothing else.
"""

from __future__ import annotations

from spica.sources.base import Absent, GeneNotInSource, Source, SourceError
from spica.sources.alphafold import AlphaFold
from spica.sources.chembl import ChEMBL
from spica.sources.clinvar import ClinVar
from spica.sources.depmap import DepMap
from spica.sources.ensembl import Ensembl
from spica.sources.gtex import Gtex
from spica.sources.gwas import Gwas
from spica.sources.hgnc import Hgnc
from spica.sources.hpa import Hpa
from spica.sources.opentargets import OpenTargets
from spica.sources.uniprot import UniProt

RESOLVER = Hgnc()

SOURCES: tuple[Source, ...] = (RESOLVER, Ensembl(), UniProt(), Gtex(), Hpa(),
                               OpenTargets(), ClinVar(), AlphaFold(), ChEMBL(), DepMap(),
                               Gwas())

SOURCES_BY_KEY: dict[str, Source] = {source.key: source for source in SOURCES}

__all__ = [
    "Absent",
    "GeneNotInSource",
    "RESOLVER",
    "SOURCES",
    "SOURCES_BY_KEY",
    "Source",
    "SourceError",
]
