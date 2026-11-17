# Differential expression

Volcano plots for GEO series, on the Datasets screen, in the panel
"Differential expression" under an opened series. Code: `spica/geo/de.py`;
interface: `frontend/src/components/DiffExpression.tsx`, `Volcano.tsx`.

## Validated routes only

| Table in the series | Route | Result |
| --- | --- | --- |
| The authors' results (DESeq2, edgeR, limma column names) | Published results | Fold change and p-value as published. Not recomputed. |
| Raw integer read counts, gene by sample | DESeq2 | PyDESeq2 0.5.4, DESeq2 defaults: median-of-ratios size factors, parametric dispersion fit, Wald test, Benjamini-Hochberg adjustment, Cook's distance and independent filtering. |
| TPM, FPKM, CPM or other normalised values | None | Refused: no validated test on these values. |
| Columns not matched to samples, no counts | None | Refused: groups unknown. |

The fold change is log2 of comparison over reference. A table can hold
several contrasts (`KO_log2FoldChange`, `DKO_log2FoldChange`); each pairs with
the p-value column of the same name, else the next one to its right.

## Groups for DESeq2

- **By sample variable.** Any characteristic that splits the count columns
  into groups of two or more: treatment, genotype, cell type. Also "sample
  group (title)": the sample title without its replicate number ("shCTR-1",
  "shCTR-2" give "shCTR"). The titles must read as numbered replicates, 1 to n
  in each group; "Day 3" and "Day 10" never pool into "Day".
- **By column.** For count columns whose names match no sample (N1 to N4,
  T1 to T4). The groups are the user's choice; the test is still DESeq2.
- **Covariate.** An optional second variable in the design
  (`~covariate + condition`), for batches or paired samples. Refused when it
  is confounded with the groups or leaves no residual degrees of freedom.
- Two samples minimum per group.

Every gene in the table goes into the model, all-zero genes too: DESeq2's
independent filtering takes its thresholds over all genes, so dropping any
shifts the adjusted p-values (checked: removing the 30,655 all-zero genes of
GSE326551 raised the disagreements with the published calls from 7 to 19).

## Validation

GSE326551 publishes raw counts and the authors' DESeq2 results for the same
comparison (TRPM1 overexpression against control, four samples each). Spica's
run on the counts against the published table, over the 1,778 genes in both:

| Measure | Agreement |
| --- | --- |
| log2 fold change | Pearson r 1.000000; largest difference 0.0001 |
| -log10 adjusted p | Pearson r 0.9997 |
| Adjusted p < 0.05 | 1,771 of 1,778 calls agree; 7 genes near 0.05 are significant in the published table only |

The 7 discordant genes sit at the threshold, where PyDESeq2's independent
filtering differs slightly from R's. Run time: 46 s for 58,735 genes and 8
samples, one CPU core (one worker keeps the run inside the app's process).

## Files and cache

Tables are downloaded whole once (300 MB maximum) into
`data/cache/geo-files/`; results are kept in `data/cache/geo-de/`, keyed by
table, route and groups, and open offline afterwards. Text tables (`.txt`,
`.tsv`, `.csv`, gzipped or not) and Excel workbooks (`.xlsx`, one table per
sheet) are read; old Excel (`.xls`) is not.

## Not yet in

- Per-sample count files inside a series' `_RAW.tar`.
- Single-cell tables (no pseudobulk).
- Proteomics: GEO holds almost none (0 protein tables in 15 series sampled);
  the source is PRIDE, whose processed files depend on the software
  (MaxQuant `proteinGroups.txt`, DIA-NN `pg_matrix.tsv`).
