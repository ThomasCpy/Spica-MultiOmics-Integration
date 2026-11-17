"""The tracks of a locus, their sources, and how they are drawn.

Python fetches each track for the full window. The live layer caches it.
The interface gets it as igv.js features. Three routes:

- **The UCSC data API** for tracks that UCSC hosts: GENCODE genes, ENCODE
  cCREs and TF clusters, ClinVar, dbSNP, GTEx eQTLs and RNA coverage,
  per-tissue DNase and H3K27ac, conservation, CpG islands, repeats, JASPAR.
- **Ensembl** for its Regulatory Build, **ENCORI** for miRNA binding sites
  and **OmniPath** for the regulators of a gene.
- **ENCODE files**, read by byte range (`bigfile.py`), for experiments that
  the user selects.

Colours follow the art direction: azure for data, orange only where a
signed or flagged value needs a second pole, slate and ink for the rest.
Red and green are never a pair. A label always carries identity too.

No track is cut to a top few. Two tracks have a narrow definition, and say
so. JASPAR (782,453 motif hits in one 135 kb window) shows only the motifs
of the gene's own regulators near its promoter. GTEx eQTLs show only those
that act on this gene.
"""

from __future__ import annotations

import csv
import html
import io
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

from spica.genome import encode
from spica.genome.bigfile import BigFile, BigFileError, Ranged
from spica.genome.locus import Locus
from spica.live import Live, LiveError, NotFoundUpstream, OFF

UCSC = "https://api.genome.ucsc.edu/getData/track"
ENSEMBL = "https://rest.ensembl.org"
OMNIPATH = "https://omnipathdb.org/interactions"
ENCORI = "https://rnasysu.com/encori/api/miRNATarget/"

#: Signal tracks are binned to this many points over the window: enough to
#: read a 135 kb locus at about 35 bases a bin, small enough to send.
WIG_BINS = 4000
#: JASPAR's own browser default: a motif score of 400 is p < 1e-4.
JASPAR_MIN_SCORE = 400
#: The promoter window JASPAR motifs are read in, either side of the TSS.
PROMOTER = 2000

INK, SLATE = "#0B1B2B", "#5B6B7C"
AZURE, AZURE_DEEP, AZURE_MID, AZURE_LOW = "#00B2FF", "#0077CC", "#4DC9FF", "#99DEFF"
ORANGE = "#F97316"


class TrackError(Exception):
    pass


@dataclass(frozen=True)
class Track:
    id: str
    label: str
    group: str
    source: str
    licence: str
    verified: bool  # licence checked and allows commercial use
    default: bool
    kind: str  # "annotation" | "wig"
    description: str
    fetch: Callable[[Locus, Live, str], list[dict[str, Any]]] = field(repr=False)
    tissues: tuple[str, ...] = ()  # for per-tissue families: the choices
    display: str = "EXPANDED"
    color: str = AZURE_DEEP
    alt_color: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "group": self.group,
                "source": self.source, "licence": self.licence,
                "verified": self.verified, "default": self.default,
                "kind": self.kind, "description": self.description,
                "tissues": list(self.tissues)}


# -- helpers ------------------------------------------------------------------


def _text(value: Any) -> str:
    """Plain, escaped text for a popup. igv.js inserts popup values as HTML.
    All remote text is thus escaped here. Embedded HTML from some sources
    (ClinVar star ratings, links) becomes plain text."""
    plain = re.sub(r"<[^>]*>", " ", html.unescape(str(value)))
    return html.escape(" ".join(plain.split()))


def ucsc_rows(live: Live, track: str, locus: Locus, start: int | None = None,
              end: int | None = None) -> list[dict[str, Any]]:
    lo = locus.window_start if start is None else start
    hi = locus.window_end if end is None else end
    url = f"{UCSC}?genome=hg38;track={track};chrom={locus.chrom};start={lo};end={hi}"
    payload = live.get_json("ucsc", url).payload or {}
    rows = payload.get(track)
    if isinstance(rows, dict):
        rows = rows.get(locus.chrom)
    return [row for row in rows or [] if isinstance(row, dict)]


def binned(rows: list[tuple[int, int, float]], start: int, end: int,
           bins: int = WIG_BINS) -> list[tuple[int, int, float]]:
    """Mean value per bin, weighted by the bases each row covers.

    Bins with no data are left out. A gap is not a zero, and drawing one as
    zero would claim a measurement that was not made.
    """
    bins = max(1, min(bins, end - start))
    width = (end - start) / bins
    total = [0.0] * bins
    covered = [0.0] * bins
    for s, e, value in rows:
        s, e = max(s, start), min(e, end)
        if e <= s:
            continue
        first = int((s - start) / width)
        last = min(bins - 1, int((e - 1 - start) / width))
        for b in range(first, last + 1):
            lo = start + b * width
            overlap = min(e, lo + width) - max(s, lo)
            if overlap > 0:
                total[b] += value * overlap
                covered[b] += overlap
    out = []
    for b in range(bins):
        if covered[b]:
            lo = int(start + b * width)
            out.append((lo, max(int(start + (b + 1) * width), lo + 1), total[b] / covered[b]))
    return out


def _wig(locus: Locus, rows: list[tuple[int, int, float]]) -> list[dict[str, Any]]:
    return [{"chr": locus.chrom, "start": s, "end": e, "value": round(v, 4)}
            for s, e, v in rows]


def ucsc_wig(live: Live, track: str, locus: Locus) -> list[dict[str, Any]]:
    """A UCSC-hosted signal, binned before it is cached: the raw per-base
    answer runs to megabytes, the binned one to a few kilobytes."""
    key = f"{UCSC}?track={track};{locus.chrom}:{locus.window_start}-{locus.window_end};bins={WIG_BINS}"

    def produce() -> list[list[float]]:
        import json
        url = (f"{UCSC}?genome=hg38;track={track};chrom={locus.chrom};"
               f"start={locus.window_start};end={locus.window_end}")
        payload = json.loads(live.raw(url))
        rows = payload.get(track)
        if isinstance(rows, dict):
            rows = rows.get(locus.chrom)
        points = [(int(r["start"]), int(r["end"]), float(r["value"]))
                  for r in rows or [] if isinstance(r, dict) and "value" in r]
        return [list(b) for b in binned(points, locus.window_start, locus.window_end)]

    rows = live.remember("ucsc", key, produce).payload or []
    return _wig(locus, [(int(s), int(e), float(v)) for s, e, v in rows])


def find_utrs(exons: list[dict[str, Any]], cd_start: int, cd_end: int) -> None:
    """The igv.js rule for coding exon parts. A feature built here thus draws
    exactly as the same transcript from a BED file."""
    for exon in exons:
        if exon["end"] < cd_start or exon["start"] > cd_end:
            exon["utr"] = True
        else:
            if exon["start"] <= cd_start <= exon["end"]:
                exon["cdStart"] = cd_start
            if exon["start"] <= cd_end <= exon["end"]:
                exon["cdEnd"] = cd_end


def _blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    start = int(row["chromStart"])
    sizes = [int(x) for x in str(row.get("blockSizes", "")).strip(",").split(",") if x]
    starts = [int(x) for x in str(row.get("chromStarts", "")).strip(",").split(",") if x]
    return [{"start": start + s, "end": start + s + z} for s, z in zip(starts, sizes)]


# -- converters (pure: rows in, features out) ---------------------------------


def gene_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        exons = _blocks(row)
        cd_start, cd_end = int(row.get("thickStart", 0)), int(row.get("thickEnd", 0))
        coding = cd_end > cd_start
        if coding:
            find_utrs(exons, cd_start, cd_end)
        else:
            for exon in exons:
                exon["utr"] = True
        feature = {
            "chr": chrom, "start": int(row["chromStart"]), "end": int(row["chromEnd"]),
            "strand": row.get("strand", "+"),
            "name": _text(row.get("geneName") or row.get("name", "")),
            "transcript": _text(row.get("name", "")),
            "type": _text(row.get("transcriptType") or row.get("geneType") or ""),
            "tags": _text(str(row.get("tag", "")).replace(",", ", ")),
            "exons": exons,
        }
        if coding:
            feature["cdStart"], feature["cdEnd"] = cd_start, cd_end
        out.append(feature)
    return out


REGULATORY = {"promoter": AZURE_DEEP, "enhancer": AZURE, "ctcf binding site": INK,
              "open chromatin region": SLATE, "open chromatin": SLATE,
              "tf binding site": AZURE_MID, "promoter flanking region": AZURE_LOW}


def regulatory_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        kind = str(row.get("description") or "regulatory feature").lower()
        out.append({"chr": chrom, "start": int(row["start"]) - 1, "end": int(row["end"]),
                    "name": _text(kind.capitalize()), "id": _text(row.get("id", "")),
                    "color": REGULATORY.get(kind, SLATE)})
    return out


CCRE = {"PLS": AZURE_DEEP, "pELS": AZURE, "dELS": AZURE_MID, "CTCF-only": INK,
        "DNase-H3K4me3": SLATE}


def ccre_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        label = str(row.get("ccre") or row.get("encodeLabel") or "")
        out.append({"chr": chrom, "start": int(row["chromStart"]), "end": int(row["chromEnd"]),
                    "name": _text(label), "accession": _text(row.get("name", "")),
                    "description": _text(row.get("description", "")),
                    "zScore": row.get("zScore"), "color": CCRE.get(label, SLATE)})
    return out


def cpg_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    return [{"chr": chrom, "start": int(r["chromStart"]), "end": int(r["chromEnd"]),
             "name": _text(r.get("name", "CpG island")), "cpgCount": r.get("cpgNum"),
             "gcPercent": r.get("perGc"), "observedOverExpected": r.get("obsExp")}
            for r in rows]


def _significance_colour(significance: str) -> str:
    text = significance.lower()
    if "pathogenic" in text and "conflicting" not in text:
        return ORANGE
    if "benign" in text and "conflicting" not in text:
        return AZURE_DEEP
    return SLATE


def clinvar_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        original = str(row.get("origName", ""))
        change = original.split(" : ", 1)[1] if " : " in original else original
        protein = re.search(r"\((p\.[^)]+)\)", change)
        significance = _text(row.get("clinSign", ""))
        stars = html.unescape(str(row.get("reviewStatus", ""))).count("★")
        out.append({
            "chr": chrom, "start": int(row["chromStart"]), "end": int(row["chromEnd"]),
            "name": _text(protein.group(1) if protein else row.get("name", "")),
            "significance": significance,
            "review": f"{stars} of 4 stars, {_text(row.get('reviewStatus', ''))}",
            "consequence": _text(row.get("molConseq", "")),
            "condition": _text(row.get("phenotypeList", "")),
            "variant": _text(change),
            "type": _text(row.get("type", "")),
            "dbSNP": _text(row.get("snpId", "")),
            "clinvar": _text(row.get("name", "")),
            "color": _significance_colour(significance),
        })
    return out


def snp_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        freqs = [f for f in str(row.get("minorAlleleFreq", "")).split(",") if f and f != "-inf"]
        try:
            maf = max(float(f) for f in freqs) if freqs else None
        except ValueError:
            maf = None
        out.append({"chr": chrom, "start": int(row["chromStart"]), "end": int(row["chromEnd"]),
                    "name": _text(row.get("name", "")), "ref": _text(row.get("ref", "")),
                    "alt": _text(str(row.get("alts", "")).strip(",")),
                    "highestMinorAlleleFrequency": maf, "color": SLATE})
    return out


def eqtl_features(rows: list[dict[str, Any]], chrom: str, symbol: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if str(row.get("geneName", "")).upper() != symbol.upper():
            continue
        start = int(row.get("thickStart", row["chromStart"]))
        out.append({"chr": chrom, "start": start, "end": start + 1,
                    "name": _text(row.get("eqtlName", "")),
                    "tissue": _text(str(row.get("tissue", "")).replace("_", " ")),
                    "posteriorInclusionProbability": _text(row.get("pip", "")),
                    "gene": _text(row.get("geneName", "")), "color": AZURE_DEEP})
    return out


def tf_cluster_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    return [{"chr": chrom, "start": int(r["chromStart"]), "end": int(r["chromEnd"]),
             "name": _text(r.get("name", "")), "score": r.get("score"),
             "cellTypes": r.get("sourceCount"), "color": AZURE_DEEP}
            for r in rows]


def repeat_features(rows: list[dict[str, Any]], chrom: str) -> list[dict[str, Any]]:
    return [{"chr": chrom, "start": int(r["genoStart"]), "end": int(r["genoEnd"]),
             "strand": r.get("strand", "+"), "name": _text(r.get("repName", "")),
             "class": _text(f"{r.get('repClass', '')} / {r.get('repFamily', '')}"),
             "color": SLATE}
            for r in rows]


def jaspar_features(rows: list[dict[str, Any]], chrom: str, regulators: set[str]) -> list[dict[str, Any]]:
    wanted = {name.upper() for name in regulators}
    out = []
    for row in rows:
        names = {part.upper() for part in re.split(r"::|_", str(row.get("TFName", "")))}
        if not names & wanted or int(row.get("score", 0)) < JASPAR_MIN_SCORE:
            continue
        out.append({"chr": chrom, "start": int(row["chromStart"]), "end": int(row["chromEnd"]),
                    "strand": row.get("strand", "+"), "name": _text(row.get("TFName", "")),
                    "matrix": _text(row.get("name", "")), "score": row.get("score"),
                    "color": AZURE_DEEP})
    return out


def encori_features(table: str, chrom: str) -> list[dict[str, Any]]:
    lines = [line for line in table.splitlines() if line and not line.startswith("#")]
    if len(lines) < 2:
        return []
    out = []
    for row in csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t"):
        try:
            start, end = int(row.get("narrowStart") or 0), int(row.get("narrowEnd") or 0)
        except ValueError:
            continue
        if not end:
            continue
        clip = int(float(row.get("clipExpNum") or 0))
        degradome = int(float(row.get("degraExpNum") or 0))
        evidence = ("cleavage (degradome)" if degradome else
                    "AGO-CLIP" if clip else "predicted")
        out.append({"chr": chrom, "start": start, "end": end,
                    "strand": "-" if str(row.get("strand")) in ("-", "-1") else "+",
                    "name": _text(row.get("miRNAname", "")), "evidence": evidence,
                    "clipExperiments": clip, "degradomeExperiments": degradome,
                    "color": ORANGE if degradome else AZURE_DEEP if clip else SLATE})
    return out


def methylation_features(records: list[tuple[int, int, list[str]]], chrom: str) -> list[dict[str, Any]]:
    """bedMethyl rows as a signal: percent methylated at each CpG."""
    out = []
    for start, end, rest in records:
        try:
            percent = float(rest[-1])
        except (ValueError, IndexError):
            continue
        out.append({"chr": chrom, "start": start, "end": end, "value": percent})
    return out


def bed_features(records: list[tuple[int, int, list[str]]], chrom: str,
                 assay: str) -> list[dict[str, Any]]:
    out = []
    for start, end, rest in records:
        name = rest[0] if rest else ""
        feature: dict[str, Any] = {"chr": chrom, "start": start, "end": end,
                                   "name": _text(name if name not in (".", "") else assay),
                                   "color": AZURE_DEEP}
        # narrowPeak: name, score, strand, signalValue, pValue, qValue, peak.
        if len(rest) >= 7 and ("ChIP-seq" in assay or assay in ("ATAC-seq", "DNase-seq")):
            try:
                feature["signalValue"] = float(rest[3])
                feature["minusLog10P"] = float(rest[4])
            except (ValueError, IndexError):
                pass
        if assay.startswith("Chromatin states"):
            label = name.lower()
            feature["color"] = (AZURE_DEEP if "tss" in label or "promoter" in label else
                                AZURE if "enh" in label else
                                AZURE_LOW if "tx" in label or "transcri" in label else
                                INK if "repress" in label or "polycomb" in label else SLATE)
        out.append(feature)
    return out


# -- fetchers -----------------------------------------------------------------


def _genes(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
    return gene_features(ucsc_rows(live, "knownGene", locus), locus.chrom)


def _regulatory(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
    url = (f"{ENSEMBL}/overlap/region/human/{locus.ensembl_chrom}:{locus.window_start + 1}-"
           f"{locus.window_end}?feature=regulatory;content-type=application/json")
    try:
        rows = live.get_json("ensembl", url).payload or []
    except NotFoundUpstream:
        rows = []
    return regulatory_features([r for r in rows if isinstance(r, dict)], locus.chrom)


def _tf_scan(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
    """The regulators' motif sites scanned in the promoter (`spica/tfscan.py`)."""
    from spica import tfscan

    found = tfscan.analyse(locus.symbol, locus.ensembl_id, live)
    if found.get("state") != "ok":
        raise TrackError(found.get("error") or "the scan could not run")
    return tfscan.features(found, locus.chrom)


def _ucsc(track: str, convert: Callable[[list[dict[str, Any]], str], list[dict[str, Any]]]):
    def fetch(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
        return convert(ucsc_rows(live, track, locus), locus.chrom)
    return fetch


def _eqtls(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
    return eqtl_features(ucsc_rows(live, "gtexEqtlDapg", locus), locus.chrom, locus.symbol)


def _signal(prefix: str):
    def fetch(locus: Locus, live: Live, tissue: str) -> list[dict[str, Any]]:
        if not tissue:
            raise TrackError("choose a tissue for this track")
        return ucsc_wig(live, f"{prefix}{tissue}", locus)
    return fetch


def _conservation(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
    return ucsc_wig(live, "phyloP100way", locus)


def regulators(locus: Locus, live: Live, mirror=None) -> list[str]:
    """The gene's transcriptional regulators, commercially usable records only:
    from the local OmniPath copy when there is one."""
    from spica import omnipath

    if mirror is not None and omnipath.available(mirror):
        return sorted({row["source_genesymbol"] for row in omnipath.regulators_of(locus.symbol, mirror)
                       if row.get("source_genesymbol")})
    query = urllib.parse.urlencode({
        "targets": locus.symbol, "genesymbols": 1, "datasets": "dorothea,collectri,tf_target",
        "license": "commercial", "format": "json"})
    try:
        rows = live.get_json("omnipath", f"{OMNIPATH}?{query}").payload or []
    except NotFoundUpstream:
        rows = []
    return sorted({str(r.get("source_genesymbol")) for r in rows
                   if isinstance(r, dict) and r.get("source_genesymbol")})


def _jaspar(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
    tfs = regulators(locus, live)
    if not tfs:
        return []
    tss = locus.start if locus.strand == "+" else locus.end
    rows = ucsc_rows(live, "jaspar2024", locus, max(0, tss - PROMOTER), tss + PROMOTER)
    names = {part for tf in tfs for part in tf.split("_")}
    return jaspar_features(rows, locus.chrom, names)


def _encori(locus: Locus, live: Live, _: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({
        "assembly": "hg38", "geneType": "mRNA", "miRNA": "all", "clipExpNum": 1,
        "degraExpNum": 0, "pancancerNum": 0, "programNum": 1, "program": "None",
        "target": locus.symbol, "cellType": "all"})
    table = live.get_text("encori", f"{ENCORI}?{query}").payload or ""
    return encori_features(str(table), locus.chrom)


def encode_file(locus: Locus, live: Live, accession: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One ENCODE file's records in the window, read by byte range."""
    info = encode.file_info(live, accession)
    label = " ".join(x for x in (info["assay"], info["target"], info["biosample"]) if x)
    key = f"{info['url']}#{locus.chrom}:{locus.window_start}-{locus.window_end};bins={WIG_BINS}"

    def produce() -> dict[str, Any]:
        if not live.allowed:
            raise LiveError(OFF)
        try:
            big = BigFile(Ranged(info["url"]))
            if big.kind == "bigwig":
                rows = big.wig(locus.chrom, locus.window_start, locus.window_end, WIG_BINS)
                return {"kind": "wig", "rows": [list(r) for r in rows]}
            return {"kind": "bed", "rows": [[s, e, rest] for s, e, rest in
                                             big.bed(locus.chrom, locus.window_start, locus.window_end)]}
        except BigFileError as exc:
            raise LiveError(str(exc)) from None

    data = live.remember("encode", key, produce).payload or {}
    if data.get("kind") == "wig":
        features = _wig(locus, [(int(s), int(e), float(v)) for s, e, v in data.get("rows", [])])
        return features, {"kind": "wig", "label": label, "info": info}
    records = [(int(s), int(e), list(rest)) for s, e, rest in data.get("rows", [])]
    if "methylation state" in info["output"]:
        return methylation_features(records, locus.chrom), {"kind": "wig", "label": label, "info": info}
    return bed_features(records, locus.chrom, info["assay"] or "ENCODE"), \
        {"kind": "annotation", "label": label, "info": info}


# -- the catalog ----------------------------------------------------------------

UCSC_DATA = "UCSC data, free for public and commercial use (per-track exceptions)"

DNASE_TISSUES = (
    "Adipose", "AdrenalGland", "Blood", "BloodVessel", "Bone", "BoneMarrow", "Brain",
    "Breast", "ConnectiveTissue", "Embryo", "Epithelium", "Esophagus", "Eye", "Gallbladder",
    "Heart", "Kidney", "LargeIntestine", "Limb", "Liver", "Lung", "Mouth", "Muscle", "Nerve",
    "Nose", "Ovary", "Pancreas", "Penis", "Placenta", "Prostate", "Skin", "SmallIntestine",
    "SpinalCord", "Spleen", "Stomach", "Testis", "Thymus", "Thyroid", "UrinaryBladder",
    "Uterus", "Vagina")
H3K27AC_TISSUES = tuple(t for t in DNASE_TISSUES if t not in ("Gallbladder", "Limb", "Nose")) + (
    "ParaythroidGland",)  # sic: UCSC's own spelling of the track name
GTEX_TISSUES = (
    "AdiposeSubcutaneous", "AdiposeVisceralOmentum", "AdrenalGland", "ArteryAorta",
    "ArteryCoronary", "ArteryTibial", "Bladder", "BrainAmygdala",
    "BrainAnteriorcingulatecortexBA24", "BrainCaudatebasalganglia",
    "BrainCerebellarHemisphere", "BrainCerebellum", "BrainCortex", "BrainFrontalCortexBA9",
    "BrainHippocampus", "BrainHypothalamus", "BrainNucleusaccumbensbasalganglia",
    "BrainPutamenbasalganglia", "BrainSpinalcordcervicalc-1", "BrainSubstantianigra",
    "BreastMammaryTissue", "CellsCulturedfibroblasts", "CellsEBV-transformedlymphocytes",
    "CervixEctocervix", "CervixEndocervix", "ColonSigmoid", "ColonTransverse",
    "EsophagusGastroesophagealJunction", "EsophagusMucosa", "EsophagusMuscularis",
    "FallopianTube", "HeartAtrialAppendage", "HeartLeftVentricle", "KidneyCortex",
    "KidneyMedulla", "Liver", "Lung", "MinorSalivaryGland", "MuscleSkeletal", "NerveTibial",
    "Ovary", "Pancreas", "Pituitary", "Prostate", "SkinNotSunExposedSuprapubic",
    "SkinSunExposedLowerleg", "SmallIntestineTerminalIleum", "Spleen", "Stomach", "Testis",
    "Thyroid", "Uterus", "Vagina", "WholeBlood")

CATALOG: tuple[Track, ...] = (
    Track("genes", "Genes (GENCODE)", "Genes", "GENCODE via UCSC", UCSC_DATA, True, True,
          "annotation", "All transcripts in the window; coding parts thick.",
          _genes, color=INK),
    Track("ensembl_regulatory", "Regulatory Build (Ensembl)", "Regulation", "Ensembl",
          "Ensembl: no restrictions on use", True, True, "annotation",
          "Promoters, enhancers, CTCF sites, open chromatin; all tissues pooled.",
          _regulatory),
    Track("ccre", "Candidate cis-regulatory elements (ENCODE)", "Regulation", "ENCODE via UCSC",
          "ENCODE: data usable without restriction", True, True, "annotation",
          "PLS promoter-like, pELS/dELS enhancer-like, CTCF-only.", _ucsc("encodeCcreCombined", ccre_features)),
    Track("cpg", "CpG islands", "Regulation", "UCSC", UCSC_DATA, True, True, "annotation",
          "CpG islands, a promoter proxy.", _ucsc("cpgIslandExt", cpg_features), color=SLATE),
    Track("tf_clusters", "TF ChIP-seq clusters (ENCODE, 340 factors)", "TF binding",
          "ENCODE via UCSC", "ENCODE: data usable without restriction", True, False, "annotation",
          "ENCODE binding of 340 TFs, cell types pooled.",
          _ucsc("encRegTfbsClustered", tf_cluster_features), display="SQUISHED"),
    Track("tf_scan", "Regulator motif sites, with their ChIP-seq (scanned here)", "TF binding",
          "JASPAR 2024, OmniPath, ENCODE", "JASPAR: CC BY 4.0 (checked on its site)", True, False,
          "annotation",
          "Regulator JASPAR motifs, -2,000 to +500 bp of the TSS, p < 1e-4. Deep azure: site in "
          "the factor's own ChIP-seq peak; slate: motif only.", _tf_scan, color=AZURE_DEEP),
    Track("jaspar", "Regulator motifs near the promoter (JASPAR 2024)", "TF binding",
          "JASPAR via UCSC, regulators from OmniPath",
          "JASPAR: CC BY 4.0 (checked on its site)", True, False,
          "annotation",
          f"UCSC genome-wide JASPAR scan: OmniPath regulators of this gene, within "
          f"{PROMOTER:,} bp of the TSS, score {JASPAR_MIN_SCORE} or more.", _jaspar),
    Track("mirna", "miRNA binding sites (ENCORI)", "miRNA", "ENCORI (starBase)",
          "ENCORI: terms not found; check before commercial use", False, False, "annotation",
          "Orange: degradome cleavage; azure: AGO-CLIP binding; slate: predicted only.", _encori),
    Track("clinvar", "ClinVar variants", "Variants", "NCBI ClinVar via UCSC",
          "NCBI: public domain", True, True, "annotation",
          "Orange: pathogenic; azure: benign; slate: uncertain or conflicting.",
          _ucsc("clinvarMain", clinvar_features), display="SQUISHED"),
    Track("dbsnp", "Common variants (dbSNP 155)", "Variants", "NCBI dbSNP via UCSC",
          "NCBI: public domain", True, False, "annotation",
          "Minor allele frequency 1% or more.",
          _ucsc("dbSnp155Common", snp_features), display="SQUISHED"),
    Track("eqtl", "eQTLs for this gene (GTEx)", "Variants", "GTEx via UCSC",
          "GTEx open-access tier", True, False, "annotation",
          "Fine-mapped (DAP-G) eQTLs of this gene, per tissue.", _eqtls,
          display="SQUISHED"),
    Track("conservation", "Conservation (phyloP, 100 vertebrates)", "Conservation",
          "UCSC", UCSC_DATA, True, True, "wig",
          "Positive: conserved; negative: faster than neutral.", _conservation,
          color=ORANGE, alt_color=AZURE_DEEP),
    Track("repeats", "Repeats (RepeatMasker)", "Conservation", "UCSC", UCSC_DATA, True, False,
          "annotation", "Interspersed repeats and low-complexity sequence.",
          _ucsc("rmsk", repeat_features), color=SLATE, display="SQUISHED"),
    Track("dnase", "Open chromatin by tissue (ENCODE DNase)", "By tissue", "ENCODE via UCSC",
          "ENCODE: data usable without restriction", True, False, "wig",
          "DNase-seq signal pooled per tissue.", _signal("wgEncodeReg4DnaseAll"),
          tissues=DNASE_TISSUES, color=AZURE),
    Track("h3k27ac", "Active chromatin by tissue (ENCODE H3K27ac)", "By tissue",
          "ENCODE via UCSC", "ENCODE: data usable without restriction", True, False, "wig",
          "H3K27ac signal pooled per tissue: active promoters and enhancers.",
          _signal("wgEncodeReg4MarkH3k27acAll"), tissues=H3K27AC_TISSUES, color=AZURE),
    Track("gtex_coverage", "RNA-seq coverage by tissue (GTEx)", "By tissue", "GTEx via UCSC",
          "GTEx open-access tier", True, False, "wig",
          "Median RNA-seq read coverage per tissue: exon use.",
          _signal("gtexCov"), tissues=GTEX_TISSUES, color=AZURE_DEEP),
)

BY_ID = {track.id: track for track in CATALOG}


def igv_config(track: Track | None, label: str, kind: str, tissue: str = "") -> dict[str, Any]:
    name = f"{label}, {tissue}" if tissue else label
    if kind == "wig":
        config: dict[str, Any] = {"type": "wig", "name": name, "autoscale": True, "height": 60,
                                  "color": track.color if track else AZURE}
        if track and track.alt_color:
            config["altColor"] = track.alt_color
        return config
    return {"type": "annotation", "name": name,
            "displayMode": track.display if track else "EXPANDED",
            "color": track.color if track else AZURE_DEEP, "searchable": False}


def load(track_id: str, locus: Locus, live: Live) -> dict[str, Any]:
    """One track's features for the locus window, or why there are none.

    `track_id` is a catalog id, `<family>:<tissue>` for a per-tissue track,
    `encode:<file accession>`, or `geo:<sample>|<build>|<file url>` for a
    file from a GEO series.
    """
    family, _, param = track_id.partition(":")
    try:
        if family == "encode":
            features, meta = encode_file(locus, live, param)
            config = igv_config(None, meta["label"], meta["kind"])
            source, licence = "ENCODE", "ENCODE: data usable without restriction"
        elif family == "geo":
            from spica.geo import tracks as geo_tracks

            owner, _, rest = param.partition("|")
            hint, _, url = rest.partition("|")
            if not url.startswith("https://ftp.ncbi.nlm.nih.gov/geo/"):
                return {"id": track_id, "state": "failed", "reason": "not a GEO file address"}
            try:
                features, meta = geo_tracks.read(url, locus, live, hint)
            except geo_tracks.GeoTrackError as exc:
                raise TrackError(str(exc)) from None
            label = meta["name"] if not owner or meta["name"].startswith(owner) else f"{owner} {meta['name']}"
            if meta["mapped"]:
                label += " (GRCh37, mapped)"
            config = igv_config(None, label, meta["kind"])
            source = "NCBI GEO"
            licence = "NCBI places no restriction; submitters may hold rights in their data"
        else:
            track = BY_ID.get(family)
            if track is None:
                return {"id": track_id, "state": "failed", "reason": f"no track called {track_id}"}
            if track.tissues and param not in track.tissues:
                return {"id": track_id, "state": "failed",
                        "reason": f"{track.label} has no tissue called {param or 'that'}"}
            features = track.fetch(locus, live, param)
            config = igv_config(track, track.label, track.kind, _tissue_label(param))
            source, licence = track.source, track.licence
    except LiveError as exc:
        state = "offline" if OFF in str(exc) else "failed"
        return {"id": track_id, "state": state, "reason": str(exc)}
    except (TrackError, NotFoundUpstream) as exc:
        return {"id": track_id, "state": "failed", "reason": str(exc)}
    except Exception as exc:  # a broken converter costs its track, never the view
        return {"id": track_id, "state": "failed", "reason": f"not read: {exc}"}
    if config.get("type") == "annotation" and any("color" in f for f in features):
        # In igv.js a track colour overrides the colour of each feature.
        # A track with features coloured by class (cCRE type, ClinVar
        # significance) must thus not have one.
        config.pop("color", None)
    return {"id": track_id, "state": "ok", "config": config, "features": features,
            "count": len(features), "source": source, "licence": licence}


def _tissue_label(name: str) -> str:
    """`SmallIntestineTerminalIleum` -> `Small Intestine Terminal Ileum`."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def gtex_labels(live: Live) -> dict[str, str]:
    """UCSC's GTEx track suffixes to the names GTEx prints.

    UCSC builds `gtexCovCellsCulturedfibroblasts` from GTEx's
    `Cells_Cultured_fibroblasts` by dropping the underscores, which splitting
    on capitals cannot undo ("Culturedfibroblasts"). GTEx's own label map,
    already cached for the record, can.
    """
    from spica.sources.gtex import Gtex

    try:
        labels = Gtex()._labels(live)
    except Exception:
        return {}
    return {re.sub(r"[^A-Za-z0-9-]", "", key): name for key, name in labels.items()}


#: Spica organ -> the per-tissue track names that best stand for it, so the
#: view can open on the tissue where the gene is highest.
ORGAN_TISSUES: dict[str, tuple[str, str, str]] = {
    # organ: (DNase / H3K27ac tissue, GTEx coverage tissue, ENCODE organ slim)
    "liver": ("Liver", "Liver", "liver"),
    "stomach": ("Stomach", "Stomach", "stomach"),
    "lung": ("Lung", "Lung", "lung"),
    "brain": ("Brain", "BrainCortex", "brain"),
    "heart": ("Heart", "HeartLeftVentricle", "heart"),
    "kidney": ("Kidney", "KidneyCortex", "kidney"),
    "pancreas": ("Pancreas", "Pancreas", "pancreas"),
    "intestine": ("LargeIntestine", "ColonTransverse", "large intestine"),
    "esophagus": ("Esophagus", "EsophagusMucosa", "esophagus"),
    "skin": ("Skin", "SkinSunExposedLowerleg", "skin of body"),
    "muscle": ("Muscle", "MuscleSkeletal", "musculature of body"),
    "blood": ("Blood", "WholeBlood", "blood"),
    "spleen": ("Spleen", "Spleen", "spleen"),
    "thyroid": ("Thyroid", "Thyroid", "thyroid gland"),
    "adrenal": ("AdrenalGland", "AdrenalGland", "adrenal gland"),
    "breast": ("Breast", "BreastMammaryTissue", "breast"),
    "prostate": ("Prostate", "Prostate", "prostate gland"),
    "testis": ("Testis", "Testis", "testis"),
    "ovary": ("Ovary", "Ovary", "ovary"),
    "uterus": ("Uterus", "Uterus", "uterus"),
    "adipose": ("Adipose", "AdiposeSubcutaneous", "adipose tissue"),
    "nerve": ("Nerve", "NerveTibial", "nerve"),
    "vessel": ("BloodVessel", "ArteryTibial", "blood vessel"),
    "vagina": ("Vagina", "Vagina", "vagina"),
}


def tissue_hint(top_tissue: str) -> dict[str, str]:
    """Which tissue each per-tissue track should open on, from the gene's peak."""
    from spica import metrics

    for organ in sorted(metrics.organs(top_tissue or "")):
        if organ in ORGAN_TISSUES:
            dnase, gtex, slim = ORGAN_TISSUES[organ]
            return {"organ": organ, "dnase": dnase, "h3k27ac": dnase if dnase in H3K27AC_TISSUES else "",
                    "gtex_coverage": gtex, "encode": slim}
    return {}
