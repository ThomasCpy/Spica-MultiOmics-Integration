# Candidates: lists, the ranked table, the benchmark

Milestone 3. A gene list goes in, a ranked table comes out, and a benchmark says how far
the weights can be trusted. Code: `spica/genelist.py`, `spica/ranking.py`,
`spica/benchmark.py`; screen: Candidates.

## A list, mapped and confirmed

Paste the list or open a file (.txt, .csv, .tsv, or .xlsx with the document readers). A line
with tabs is a spreadsheet row and its first cell is the gene; otherwise commas, semicolons
and spaces separate. A column title on the first line is dropped.

Every entry is resolved through HGNC, as a single report resolves its query, and the mapping
report says how each one matched:

| Match | Meaning | What to do |
| --- | --- | --- |
| exact | An approved symbol, or an HGNC, Ensembl, UniProt or Entrez ID | Nothing |
| renamed | A previous symbol; the gene is now called something else | Glance at it |
| alias | Another name of the gene; where lists most often go wrong | Glance at it |
| pick one | A name several genes share, or a number that is both an HGNC number and an Entrez ID (1956 is CHRNA2's HGNC number and EGFR's Entrez ID) | Pick the gene, or drop the entry |
| not found | Nothing matches | Correct the list, or let it drop |
| duplicate | A second entry for a gene already in the list | Nothing; it is kept once |

Nothing is ranked until the mapping is confirmed. A confirmed list is saved in
`data/lists/` with its entries, the mapping, the choices made, and later its weights and
indication, so it opens again on the same genes.

## The ranked table

Each criterion reads the record and gives a score between 0 and 1. The total is the
weighted mean of the scores, so each criterion's contribution reads straight off the row.

- **A gene's score depends on its own record only.** No criterion is normalised against
  the other genes, so a gene scores the same in any list and adding a gene never moves
  another one's score.
- **Missing data is left out**, and the share of the weight a gene had data for is shown
  beside its score ("Data"). Or, if asked, missing data counts as zero. A not-found value
  that is an answer (no ortholog, no drug, no safety liability on record) is scored as such,
  not treated as missing.
- **An indication** focuses two criteria: disease association takes the strongest disease
  whose name matches, and human genetics looks only at those diseases.

| Criterion | Asks | Reads | Score |
| --- | --- | --- | --- |
| RNA specificity | Expression | GTEx tau | tau |
| Cell-type specificity | Expression | HPA single-cell tau | tau |
| Peak over typical tissue | Expression | fold over median | log10(fold) / 3, at most 1 |
| At the cell surface | Expression | UniProt, HPA, GO locations | sources placing it at the plasma membrane or outside, out of 3 |
| Antibody, small-molecule, PROTAC tractability | Druggability | Open Targets tractability | share of the modality's predictive buckets (clinical buckets are precedent, scored apart) |
| Experimental structure | Druggability | PDB coverage | share of the sequence covered |
| Predicted fold confidence | Druggability | AlphaFold mean pLDDT | pLDDT / 100 |
| Clinical precedent | Precedent | ChEMBL highest phase | phase / 4 |
| Disease association | Disease relevance | Open Targets scores | the strongest (matching) score |
| Human genetics | Disease relevance | ClinVar, GWAS Catalog | half for pathogenic variants, half for a genome-wide GWAS association |
| Selective dependency | Disease relevance | DepMap | top lineage's dependent share times the share of all lines that do not depend on it; 0 for a common essential |
| Healthy cells spared | Safety | DepMap | 1 less the dependent share; 0 for a common essential |
| Knockout tolerated | Safety | mouse knockout phenotypes | 0 if any is lethal, else 1 |
| Few safety liabilities | Safety | Open Targets safety | 1 / (1 + liabilities) |
| Cynomolgus, mouse identity | Translation | Ensembl Compara | identity / 100 |

Presets set starting weights (0 to 10) for an antibody or ADC, a small molecule, a CAR-T or
cell therapy, and an oncology dependency. They are where the user starts; every weight
stays theirs. The screen re-ranks as a weight moves, with the same arithmetic as
`spica/ranking.py`, since every criterion's score comes back whatever its weight.

"Export report" on the ranked table writes the client report the art direction describes:
the ranked table on page one with the weights and what each criterion reads, then a profile
for the top 10, the top 25 or every gene.

## The benchmark

For one modality: the positives are targets with an approved drug of that modality (Open
Targets' tractability, "Approved Drug"); the decoys are protein-coding genes with no drug of
any modality in the clinic, three per positive, drawn by a fixed hash so every run picks the
same ones. Both are scored with the weights on screen, and the result is the area under the
ROC curve, the curve, how many positives the top of the list holds, and each criterion on
its own.

What keeps it honest:

- Criteria that carry the label are left out of the run and named: clinical precedent is
  the label itself, and Open Targets' association score counts drug evidence.
- Data coverage is reported for each group. Approved targets are better studied, and a
  criterion that rewards being studied shows up there.
- Results are kept in `data/benchmarks/`, with the weights and the releases they ran on.

First runs, on the default presets and the releases of 2026-10-28:

| Modality | Positives, decoys | AUC | Top of the list | Best single criteria |
| --- | --- | --- | --- | --- |
| Antibody | 68, 204 | 0.861 | 39 of the top 68 are approved targets (chance: 17) | antibody tractability 0.91, cell surface 0.82 |
| Small molecule | 200, 600 | 0.869 | 130 of the top 200 (chance: 50) | small-molecule tractability 0.93, structure 0.76 |

What the runs say about the presets: cynomolgus identity scores below chance for antibody
targets (0.41), because many approved antibodies act on immune genes that diverge between
species, and a liability on record goes with being an approved target (0.38), because the
records come from trials. Both are reasons to weigh those criteria for what they are
(translation and safety risks to manage), not as signs a target will work.
