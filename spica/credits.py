"""Who to credit for each source, and where a gene's own page is.

One table for the exported report's credits and for THIRD_PARTY_NOTICES.md
(`tools/notices.py`), so the two never say different things.
`docs/licences.md` records how each licence was checked.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Credit:
    name: str
    terms: str
    credit: str
    home: str
    #: The gene's page, filled with `symbol`, `ensembl`, `accession`, `hgnc`.
    page: str = ""

    def link(self, **ids: str) -> str:
        if not self.page:
            return self.home
        try:
            filled = self.page.format(**ids)
        except KeyError:
            return self.home
        # A page that needs an identifier the gene does not have is no page.
        return filled if all(ids.get(key) for key in _needs(self.page)) else self.home


def _needs(page: str) -> list[str]:
    import string

    return [name for _, name, _, _ in string.Formatter().parse(page) if name]


CREDITS: dict[str, Credit] = {
    "hgnc": Credit("HGNC", "No restrictions on use",
                   "HUGO Gene Nomenclature Committee (HGNC), www.genenames.org",
                   "https://www.genenames.org/",
                   "https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/{hgnc}"),
    "ensembl": Credit("Ensembl", "No restrictions on use", "Ensembl, EMBL-EBI, www.ensembl.org",
                      "https://www.ensembl.org/",
                      "https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={ensembl}"),
    "uniprot": Credit("UniProt", "CC BY 4.0", "The UniProt Consortium, www.uniprot.org",
                      "https://www.uniprot.org/",
                      "https://www.uniprot.org/uniprotkb/{accession}/entry"),
    "go": Credit("Gene Ontology (through UniProt)", "CC BY 4.0",
                 "Gene Ontology Consortium, geneontology.org, with the release used",
                 "https://geneontology.org/"),
    "gtex": Credit("GTEx (open-access summary data)", "Open access",
                   "The Genotype-Tissue Expression (GTEx) Project, gtexportal.org",
                   "https://gtexportal.org/", "https://gtexportal.org/home/gene/{symbol}"),
    "hpa": Credit("Human Protein Atlas", "CC BY 4.0",
                  "Human Protein Atlas, www.proteinatlas.org; Uhlén M et al., Tissue-based map "
                  "of the human proteome, Science 2015",
                  "https://www.proteinatlas.org/", "https://www.proteinatlas.org/{ensembl}"),
    "opentargets": Credit("Open Targets Platform", "CC0 1.0",
                          "Open Targets, platform.opentargets.org (credit customary)",
                          "https://platform.opentargets.org/",
                          "https://platform.opentargets.org/target/{ensembl}"),
    "clinvar": Credit("ClinVar, dbSNP",
                      "US government works, public domain; submitters may hold rights in their "
                      "own submissions",
                      "NCBI ClinVar, www.ncbi.nlm.nih.gov/clinvar",
                      "https://www.ncbi.nlm.nih.gov/clinvar/",
                      "https://www.ncbi.nlm.nih.gov/clinvar/?term={symbol}%5Bgene%5D"),
    "gwas": Credit("GWAS Catalog", "EMBL-EBI terms of use: no restriction added to the data "
                   "owners'; summary statistics CC0 unless stated",
                   "NHGRI-EBI GWAS Catalog, www.ebi.ac.uk/gwas (Cerezo M et al., Nucleic Acids "
                   "Research 2025)", "https://www.ebi.ac.uk/gwas/",
                   "https://www.ebi.ac.uk/gwas/genes/{symbol}"),
    "chembl": Credit("ChEMBL",
                     "CC BY-SA 3.0. Share-alike: material derived from ChEMBL values must carry "
                     "the same licence",
                     "ChEMBL, EMBL-EBI, www.ebi.ac.uk/chembl", "https://www.ebi.ac.uk/chembl/"),
    "alphafold": Credit("AlphaFold Protein Structure Database", "CC BY 4.0",
                        "AlphaFold DB, DeepMind and EMBL-EBI, alphafold.ebi.ac.uk",
                        "https://alphafold.ebi.ac.uk/",
                        "https://alphafold.ebi.ac.uk/entry/{accession}"),
    "depmap": Credit("DepMap (Broad Institute)", "CC BY 4.0",
                     "DepMap, Broad Institute: the DepMap Public release named in the report, "
                     "Figshare+; Chronos gene effect (Dempster JM et al., Genome Biology 2021)",
                     "https://depmap.org/portal/", "https://depmap.org/portal/gene/{symbol}"),
    "alphamissense": Credit("AlphaMissense (current release)", "CC BY 4.0",
                            "Cheng J et al., Science 2023; Google DeepMind",
                            "https://github.com/google-deepmind/alphamissense"),
    "pdb": Credit("RCSB PDB / wwPDB", "CC0 1.0", "RCSB Protein Data Bank, www.rcsb.org",
                  "https://www.rcsb.org/"),
    "ucsc": Credit("UCSC Genome Browser data", "Free for commercial use, per track",
                   "UCSC Genome Browser, genome.ucsc.edu, and each track's own provider",
                   "https://genome.ucsc.edu/"),
    "encode": Credit("ENCODE", "No restrictions on use",
                     "ENCODE Project Consortium, www.encodeproject.org",
                     "https://www.encodeproject.org/"),
    "string": Credit("STRING", "CC BY 4.0",
                     "STRING, string-db.org (Szklarczyk D et al.); physical subnetwork, mapped to "
                     "Ensembl genes by Spica", "https://string-db.org/",
                     "https://string-db.org/network/9606.{symbol}"),
    "omnipath": Credit("OmniPath",
                       "Per resource; Spica requests only records cleared for commercial use",
                       "OmniPath, omnipathdb.org, and the resource named on each record",
                       "https://omnipathdb.org/"),
    "epo": Credit("EPO Open Patent Services", "Under the licensee's own EPO account and terms",
                  "European Patent Office, OPS", "https://www.epo.org/"),
    "europepmc": Credit("Europe PMC", "Bibliographic metadata and links only; abstracts are not kept",
                        "Europe PMC, europepmc.org", "https://europepmc.org/"),
    "jaspar": Credit("JASPAR 2024", "CC BY 4.0",
                     "JASPAR 2024, CORE vertebrates non-redundant (Rauluseviciute I et al., Nucleic "
                     "Acids Res 2024), jaspar.elixir.no", "https://jaspar.elixir.no/"),
    "geo": Credit("NCBI GEO", "No restrictions from NCBI; submitters may hold rights in their data",
                  "NCBI Gene Expression Omnibus, and the series and sample named on each track or value",
                  "https://www.ncbi.nlm.nih.gov/geo/"),
}

#: Read through another source: GO terms and PDB entries come with UniProt,
#: AlphaMissense with the AlphaFold step.
CARRIED = {"uniprot": ("go", "pdb"), "alphafold": ("alphamissense",)}
