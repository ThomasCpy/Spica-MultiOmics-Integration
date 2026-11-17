"""Build the local data mirror: download the release of each source, convert
where needed, and write `data/mirror.json`.

    python tools/build_mirror.py                  # every source
    python tools/build_mirror.py hpa clinvar      # these sources only
    python tools/build_mirror.py --refresh gtex   # download again even if present
    python tools/build_mirror.py --check          # which sources have a newer release

The app runs the same code from Settings ("Local data") as a separate
process. A build of half an hour thus never blocks the window. It reports
its progress through `mirror-status.json` beside the mirror.

Each source is independent. A failed source affects only its own entry, and
it stays on its public API until it builds. A source goes into the manifest
only after its files are complete, so a half-finished run never makes the
app read half a file.

Spica reads most source files as they are. Four sources need a conversion
into the formats in `docs/data-mirror.md`:

- HPA ships zips: extracted to plain TSV.
- ClinVar ships 450 MB: reduced to GRCh38 single-gene rows and the four
  columns that the record counts.
- Open Targets ships Parquet: converted to JSON Lines in the shape of its
  API. Needs pyarrow, installed into `runtime/` (never system-wide).
- ChEMBL and AlphaFold DB ship no small per-protein file: assembled from
  their APIs, a few thousand calls each, in parallel.

All files go into the data folder (`spica.paths.data_dir`): `data/` from
source, `data/` beside the exe for the built program.

Files are replaced, never rewritten in place. Each one is written beside
its final name and swapped in whole. A report built during a refresh thus
reads the old file or the new one, never half of either.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

from spica.paths import data_dir, frozen

ROOT = Path(__file__).resolve().parent.parent
DATA = data_dir()
MANIFEST = DATA / "mirror.json"
STATUS = DATA / "mirror-status.json"
LOG = DATA / "mirror-build.log"
LATEST = DATA / "mirror-latest.json"
AGENT = {"User-Agent": "Spica/0.1 (mirror build)"}
TODAY = date.today().isoformat()

csv.field_size_limit(1 << 30)  # UniProt sequences and HPA lists run long

#: What a running build is doing, for the app to show. Written to STATUS.
STATE: dict = {"running": False, "pid": 0, "started": "", "finished": "", "sources": [],
               "current": "", "done": [], "failed": {}, "file": None, "log": []}
_last_write = 0.0


def _write_status(force: bool = False) -> None:
    global _last_write
    if not force and time.time() - _last_write < 1:
        return
    _last_write = time.time()
    try:
        temporary = STATUS.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(STATE), encoding="utf-8")
        os.replace(temporary, STATUS)
    except OSError:
        pass  # the status is a courtesy; the build goes on without it


def say(message: str) -> None:
    line = f"[mirror] {message}"
    if sys.stdout is not None:  # the windowed exe has no console
        print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    STATE["log"] = (STATE["log"] + [message])[-60:]
    _write_status()


# -- plumbing -------------------------------------------------------------------


def fetch(url: str, dest: Path, refresh: bool = False, tries: int = 3) -> dict[str, str]:
    """Download `url` to `dest` (via a .part file), returning the headers."""
    if dest.exists() and not refresh:
        say(f"  have {dest.relative_to(DATA)}")
        return {}
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, tries + 1):
        try:
            request = urllib.request.Request(url, headers=AGENT)
            with urllib.request.urlopen(request, timeout=120) as response, open(part, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                done, last = 0, time.time()
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    STATE["file"] = {"name": dest.name, "done": done, "total": total}
                    _write_status()
                    if time.time() - last > 5:
                        share = f" ({100 * done / total:.0f}%)" if total else ""
                        say(f"  {dest.name}: {done / 1e6:.0f} MB{share}")
                        last = time.time()
                headers = dict(response.headers)
            os.replace(part, dest)
            STATE["file"] = None
            say(f"  got {dest.relative_to(DATA)} ({dest.stat().st_size / 1e6:.1f} MB)")
            return headers
        except Exception as exc:  # network trouble is retried, then reported
            say(f"  attempt {attempt} for {url} failed: {exc}")
            time.sleep(3 * attempt)
    raise RuntimeError(f"could not download {url}")


def get_json(url: str, tries: int = 4) -> object:
    for attempt in range(1, tries + 1):
        try:
            request = urllib.request.Request(url, headers={**AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == tries:
                raise
        except Exception:
            if attempt == tries:
                raise
        time.sleep(1.5 * attempt)
    return None


def day(headers: dict[str, str]) -> str:
    """A release date from Last-Modified, or today."""
    stamp = headers.get("Last-Modified") or headers.get("last-modified")
    try:
        return parsedate_to_datetime(stamp).date().isoformat() if stamp else TODAY
    except (TypeError, ValueError):
        return TODAY


def unzip_one(archive: Path, dest: Path) -> None:
    part = dest.with_suffix(dest.suffix + ".part")
    with zipfile.ZipFile(archive) as bundle:
        member = next(n for n in bundle.namelist() if not n.endswith("/"))
        with bundle.open(member) as source, open(part, "wb") as out:
            shutil.copyfileobj(source, out, 1 << 20)
    os.replace(part, dest)


def write_atomic(dest: Path, text: str) -> None:
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, dest)


def record(key: str, entry: dict) -> None:
    """Add one source to the manifest, atomically."""
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {"mirror_version": "1", "sources": {}}
    manifest.setdefault("sources", {})[key] = entry
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, MANIFEST)
    say(f"{key}: in the manifest ({entry['version']})")


def header_of(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return handle.readline().rstrip("\n").split("\t")


# -- sources --------------------------------------------------------------------


def hgnc(refresh: bool) -> None:
    dest = DATA / "hgnc" / "hgnc_complete_set.txt"
    headers = fetch("https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/"
                    "hgnc_complete_set.txt", dest, refresh)
    record("hgnc", {"label": "HGNC", "version": day(headers) if headers else _kept("hgnc"),
                    "retrieved": TODAY, "license": "No restrictions (HGNC)",
                    "files": {"complete_set": "hgnc/hgnc_complete_set.txt"}})


def ensembl(refresh: bool) -> None:
    dest = DATA / "ensembl" / "genes.tsv"
    release = (get_json("https://rest.ensembl.org/info/data?content-type=application/json")
               or {}).get("releases", ["?"])[0]
    if refresh or not dest.exists():
        query = (
            '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE Query>'
            '<Query virtualSchemaName="default" formatter="TSV" header="1" uniqueRows="1" '
            'datasetConfigVersion="0.6"><Dataset name="hsapiens_gene_ensembl" interface="default">'
            '<Attribute name="ensembl_gene_id"/><Attribute name="external_gene_name"/>'
            '<Attribute name="gene_biotype"/><Attribute name="chromosome_name"/>'
            '<Attribute name="start_position"/><Attribute name="end_position"/>'
            '<Attribute name="strand"/></Dataset></Query>')
        url = "https://www.ensembl.org/biomart/martservice?" + urllib.parse.urlencode({"query": query})
        fetch(url, dest, refresh=True)
        if "Gene stable ID" not in header_of(dest):
            raise RuntimeError(f"BioMart answered without the expected header: {header_of(dest)[:4]}")
    files = {"genes": "ensembl/genes.tsv"}
    for key, (prefix, title) in ORTHOLOG_SPECIES.items():
        files[key] = _orthologs(key, prefix, title, refresh)
    files["transcripts"] = _biomart(
        "transcripts", ["ensembl_gene_id", "ensembl_transcript_id", "external_transcript_name",
                        "transcript_biotype", "transcript_is_canonical"],
        "Transcript stable ID", "transcript", refresh)
    record("ensembl", {"label": "Ensembl", "version": str(release), "assembly": "GRCh38",
                       "retrieved": TODAY, "license": "No restrictions (Ensembl)",
                       "files": files})


#: Mirror file key: BioMart's attribute prefix for the species, and how its
#: column titles name it.
ORTHOLOG_SPECIES = {"orthologs_mouse": ("mmusculus", "Mouse"),
                    "orthologs_cyno": ("mfascicularis", "Crab-eating macaque")}
ORTHOLOG_ATTRIBUTES = ("ensembl_gene", "associated_gene_name", "orthology_type", "perc_id",
                       "perc_id_r1", "goc_score", "wga_coverage", "orthology_confidence")


def _orthologs(key: str, prefix: str, title: str, refresh: bool) -> str:
    """Every human gene's orthologs in one species, from Ensembl Compara."""
    return _biomart(key, ["ensembl_gene_id"] + [f"{prefix}_homolog_{a}" for a in ORTHOLOG_ATTRIBUTES],
                    f"{title} gene stable ID", f"{title} ortholog", refresh)


def _biomart(key: str, names: list[str], expect: str, what: str, refresh: bool) -> str:
    """One BioMart export of human genes into `ensembl/<key>.tsv`.

    Asked with BioMart's completion stamp: a long export can stop part way
    and still answer 200, and so can Ensembl's "service unavailable" page;
    the stamp is how a whole export says so. Either is asked again."""
    dest = DATA / "ensembl" / f"{key}.tsv"
    if dest.exists() and not refresh:
        say(f"  have {dest.relative_to(DATA)}")
        return f"ensembl/{key}.tsv"
    attributes = "".join(f'<Attribute name="{name}"/>' for name in names)
    query = (
        '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE Query>'
        '<Query virtualSchemaName="default" formatter="TSV" header="1" uniqueRows="1" '
        'completionStamp="1" datasetConfigVersion="0.6">'
        f'<Dataset name="hsapiens_gene_ensembl" interface="default">{attributes}</Dataset></Query>')
    url = "https://www.ensembl.org/biomart/martservice?" + urllib.parse.urlencode({"query": query})
    for attempt in range(1, 4):
        fetch(url, dest, refresh=True)
        text = dest.read_text(encoding="utf-8").rstrip("\n")
        body, _, last = text.rpartition("\n")
        if last.strip() == "[success]" and expect in header_of_text(body):
            write_atomic(dest, body + "\n")
            return f"ensembl/{key}.tsv"
        dest.unlink()
        what = ("a web page (Ensembl busy or down)" if text.lstrip().lower().startswith("<")
                else "an export that stopped part way")
        say(f"  BioMart answered with {what}; try {attempt} of 3")
        time.sleep(10 * attempt)
    raise RuntimeError(f"BioMart did not give the whole {what} table after three tries; "
                       "run the step again later")


def header_of_text(text: str) -> list[str]:
    return text.split("\n", 1)[0].split("\t")


UNIPROT_FIELDS = ("accession,reviewed,protein_name,gene_names,length,sequence,"
                  "cc_subcellular_location,cc_function,go_p,go_f,go_c,xref_pdb_full,"
                  "cc_alternative_products")


def uniprot(refresh: bool) -> None:
    dest = DATA / "uniprot" / "entries.tsv"
    query = urllib.parse.urlencode({"query": "organism_id:9606 AND reviewed:true",
                                    "format": "tsv", "fields": UNIPROT_FIELDS})
    headers = fetch(f"https://rest.uniprot.org/uniprotkb/stream?{query}", dest, refresh)
    version = headers.get("X-UniProt-Release") or _kept("uniprot") or TODAY
    record("uniprot", {"label": "UniProt", "version": version, "retrieved": TODAY,
                       "license": "CC BY 4.0", "files": {"entries": "uniprot/entries.tsv"}})


GTEX_BUCKET = "https://storage.googleapis.com/adult-gtex"


def _gtex_latest() -> tuple[str, str]:
    """The newest release folder and its median-TPM matrix, from the bucket
    listing: file names change between releases (v11's carries a date)."""
    listing = urllib.request.urlopen(f"{GTEX_BUCKET}?prefix=bulk-gex/&delimiter=/",
                                     timeout=60).read().decode()
    releases = sorted({int(n) for n in re.findall(r"<Prefix>bulk-gex/v(\d+)/</Prefix>", listing)})
    for number in reversed(releases):
        keys = urllib.request.urlopen(f"{GTEX_BUCKET}?prefix=bulk-gex/v{number}/rna-seq/",
                                      timeout=60).read().decode()
        found = re.findall(r"<Key>([^<]*_gene_median_tpm\.gct\.gz)</Key>", keys)
        if found:
            return f"v{number}", sorted(found)[-1]
    raise RuntimeError("no GTEx median-TPM matrix found in the bucket listing")


def gtex(refresh: bool) -> None:
    dest = DATA / "gtex" / "median_tpm.gct.gz"
    if refresh or not dest.exists():
        release, key = _gtex_latest()
        say(f"  GTEx {release}: {key.rsplit('/', 1)[-1]}")
        fetch(f"{GTEX_BUCKET}/{key}", dest, True)
    else:
        release = _kept("gtex")
    # The matrix is keyed on tissue IDs; the names GTEx prints come from its
    # API, saved here so the mirror route shows the same names offline.
    names = DATA / "gtex" / "tissues.tsv"
    if refresh or not names.exists():
        sites = get_json("https://gtexportal.org/api/v2/dataset/tissueSiteDetail?itemsPerPage=200")
        rows = sorted((row["tissueSiteDetailId"], row["tissueSiteDetail"])
                      for row in (sites or {}).get("data") or []
                      if row.get("tissueSiteDetailId") and row.get("tissueSiteDetail"))
        write_atomic(names, "tissueSiteDetailId\ttissueSiteDetail\n"
                     + "".join(f"{key}\t{name}\n" for key, name in rows))
        say(f"  {len(rows)} tissue names")
    record("gtex", {"label": "GTEx", "version": release, "retrieved": TODAY,
                    "license": "Open tier public; protected tier via dbGaP",
                    "files": {"median_tpm": "gtex/median_tpm.gct.gz",
                              "tissues": "gtex/tissues.tsv"}})


#: HPA file key -> the name HPA 25 publishes it under.
HPA_FILES = {
    "normal_tissue": "normal_ihc_data",
    "rna_tissue": "rna_tissue_consensus",
    "subcellular_location": "subcellular_location",
    "single_cell": "rna_single_cell_type",
    "single_cell_tissue": "rna_single_cell_cluster",
    "interactions": "interaction_consensus",
    "ms_tissue": "ms_tissue",
    # Brain regions: HPA's own, CC BY 4.0 like the rest (the Allen atlases
    # need the Institute's written permission for commercial use).
    "brain_region": "rna_brain_region_hpa",
}


def hpa(refresh: bool) -> None:
    files = {}
    for key, name in HPA_FILES.items():
        tsv = DATA / "hpa" / f"{name}.tsv"
        if refresh or not tsv.exists():
            archive = DATA / "hpa" / f"{name}.tsv.zip"
            fetch(f"https://www.proteinatlas.org/download/tsv/{name}.tsv.zip", archive, True)
            unzip_one(archive, tsv)
            archive.unlink()
            say(f"  unpacked {tsv.name} ({tsv.stat().st_size / 1e6:.0f} MB): {header_of(tsv)[:8]}")
        files[key] = f"hpa/{name}.tsv"
    files["transcripts"] = _hpa_transcripts(refresh)
    page = urllib.request.urlopen(urllib.request.Request(
        "https://www.proteinatlas.org/about/download", headers=AGENT), timeout=60).read().decode(
        "utf-8", "replace")
    found = re.search(r"[Vv]ersion\s*(\d+\.\d+)", page)
    record("hpa", {"label": "Human Protein Atlas", "version": found.group(1) if found else TODAY,
                   "retrieved": TODAY, "license": "CC BY 4.0", "files": files})


def _hpa_transcripts(refresh: bool) -> str:
    """HPA's tissue RNA-seq per transcript, reduced from one column per
    sample to the median TPM per tissue: what the isoform view reads.
    Sorted by gene, so the index finds a gene's transcripts in one range."""
    import statistics

    dest = DATA / "hpa" / "transcript_tissue_median.tsv"
    if dest.exists() and not refresh:
        say(f"  have {dest.relative_to(DATA)}")
        return "hpa/transcript_tissue_median.tsv"
    archive = DATA / "hpa" / "transcript_rna_tissue.tsv.zip"
    fetch("https://www.proteinatlas.org/download/tsv/transcript_rna_tissue.tsv.zip", archive, True)
    say("  medians per tissue, transcript by transcript")
    rows = []
    with zipfile.ZipFile(archive) as bundle:
        member = next(n for n in bundle.namelist() if not n.endswith("/"))
        with bundle.open(member) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            head = text.readline().rstrip("\n").split("\t")
            # "TPM.adipose tissue.86": the tissue between the dots, one column
            # per sample; the est_counts columns are not read.
            groups: dict[str, list[int]] = {}
            for index, column in enumerate(head):
                if column.startswith("TPM."):
                    tissue = column[4:].rsplit(".", 1)[0]
                    groups.setdefault(tissue, []).append(index)
            tissues = sorted(groups)
            for line in text:
                cells = line.rstrip("\n").split("\t")
                if len(cells) < len(head):
                    continue
                medians = []
                for tissue in tissues:
                    values = []
                    for index in groups[tissue]:
                        try:
                            values.append(float(cells[index]))
                        except ValueError:
                            pass
                    medians.append(f"{statistics.median(values):.2f}" if values else "")
                rows.append((cells[0], cells[1], medians))
    rows.sort()
    write_atomic(dest, "\t".join(["ensgid", "enstid", *tissues]) + "\n"
                 + "".join("\t".join([gene, transcript, *medians]) + "\n"
                           for gene, transcript, medians in rows))
    archive.unlink()
    say(f"  {len(rows):,} transcripts over {len(tissues)} tissues")
    return "hpa/transcript_tissue_median.tsv"


def clinvar(refresh: bool) -> None:
    dest = DATA / "clinvar" / "variant_summary.tsv"
    raw = DATA / "clinvar" / "variant_summary.txt.gz"
    headers = {}
    if refresh or not dest.exists():
        headers = fetch("https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/"
                        "variant_summary.txt.gz", raw, refresh=True)
        say("  reducing to GRCh38, single-gene rows")
        kept = 0
        conditions: dict[tuple[str, str], list] = {}
        with gzip.open(raw, "rt", encoding="utf-8", newline="") as source, \
                open(dest.with_suffix(".part"), "w", encoding="utf-8", newline="") as out:
            reader = csv.reader(source, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = [h.lstrip("#") for h in next(reader)]
            significance = "ClinicalSignificance" if "ClinicalSignificance" in header \
                else next(h for h in header if "Classification" in h)
            at = {name: header.index(name) for name in ("GeneSymbol", "Assembly", "VariationID")}
            at["ClinicalSignificance"] = header.index(significance)
            names_at = header.index("PhenotypeList") if "PhenotypeList" in header else None
            ids_at = header.index("PhenotypeIDS") if "PhenotypeIDS" in header else None
            out.write("GeneSymbol\tClinicalSignificance\tAssembly\tVariationID\n")
            for row in reader:
                if len(row) <= max(at.values()):
                    continue
                gene = row[at["GeneSymbol"]]
                if row[at["Assembly"]] != "GRCh38" or not gene or ";" in gene or gene == "-":
                    continue
                out.write(f"{gene}\t{row[at['ClinicalSignificance']]}\tGRCh38\t{row[at['VariationID']]}\n")
                kept += 1
                if names_at is not None and ids_at is not None:
                    _count_conditions(conditions, gene, row[names_at], row[ids_at],
                                      row[at["ClinicalSignificance"]])
        # Grouped by gene, so each gene is one byte range for the index
        # rather than thousands scattered through the file.
        with open(dest.with_suffix(".part"), encoding="utf-8") as handle:
            header = handle.readline()
            lines = handle.readlines()
        lines.sort(key=lambda line: line.split("\t", 1)[0])
        with open(dest.with_suffix(".part"), "w", encoding="utf-8", newline="") as out:
            out.write(header)
            out.writelines(lines)
        del lines
        os.replace(dest.with_suffix(".part"), dest)
        raw.unlink()
        say(f"  kept {kept:,} rows, grouped by gene")
        write_atomic(DATA / "clinvar" / "conditions.tsv",
                     "GeneSymbol\tCondition\tIDs\tPathogenic\tRecords\n" + "".join(
                         f"{gene}\t{name}\t{ids}\t{pathogenic}\t{records}\n"
                         for (gene, name), (ids, pathogenic, records) in sorted(conditions.items())))
        say(f"  {len(conditions):,} gene-condition pairs")
    files = {"variant_summary": "clinvar/variant_summary.tsv"}
    if (DATA / "clinvar" / "conditions.tsv").exists():
        files["conditions"] = "clinvar/conditions.tsv"
    record("clinvar", {"label": "ClinVar", "version": day(headers) if headers else _kept("clinvar"),
                       "retrieved": TODAY, "license": "Public domain (NCBI)", "files": files})


#: Conditions that name nothing.
VAGUE = {"not provided", "not specified", "see cases", "", "-"}


def _count_conditions(conditions: dict, gene: str, names: str, ids: str, significance: str) -> None:
    """Count one record under each condition it names, with that
    condition's identifiers (MONDO, MedGen, OMIM, Orphanet), which is what
    Open Targets' diseases are matched on. Conditions are separated by "|"
    and, within a group, by ";", in names and identifiers alike and in the
    same order."""
    from spica.sources.clinvar import classes_of

    pathogenic = bool(classes_of(significance) & {"Pathogenic", "Likely pathogenic"})
    for name_group, id_group in zip(names.split("|"), ids.split("|")):
        name_parts, id_parts = name_group.split(";"), id_group.split(";")
        if len(id_parts) != len(name_parts):
            id_parts = [id_group] * len(name_parts)  # misaligned: every name keeps them all
        for name, group in zip(name_parts, id_parts):
            name = name.strip()
            if name.lower() in VAGUE:
                continue
            entry = conditions.setdefault((gene, name), [group.strip(), 0, 0])
            entry[1] += pathogenic
            entry[2] += 1


OT = "https://ftp.ebi.ac.uk/pub/databases/opentargets/platform"


def _pyarrow():
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        if frozen():
            raise RuntimeError("this build of Spica has no Parquet reader, so Open Targets "
                               "cannot be built; it keeps using its API") from None
        runtime = (ROOT / "runtime").resolve()
        if not str(Path(sys.prefix).resolve()).startswith(str(runtime)):
            raise RuntimeError("pyarrow is needed for Open Targets; run this with runtime's "
                               "python so it can be installed there, never system-wide")
        say("  installing pyarrow into runtime/")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r",
                        str(ROOT / "requirements.txt")], check=True)
        import importlib
        importlib.invalidate_caches()  # this process must see what pip added
    import pyarrow.parquet as pq
    return pq


def _parquet_dir(release: str, dataset: str, refresh: bool) -> Path:
    folder = DATA / "opentargets" / "parquet" / dataset
    listing = urllib.request.urlopen(f"{OT}/{release}/output/{dataset}/", timeout=60).read().decode()
    parts = sorted(set(re.findall(r'href="([^"]+\.parquet)"', listing)))
    for part in parts:
        fetch(f"{OT}/{release}/output/{dataset}/{part}", folder / part, refresh)
    return folder


def opentargets(refresh: bool) -> None:
    listing = urllib.request.urlopen(f"{OT}/", timeout=60).read().decode()
    release = sorted(re.findall(r'href="(\d{2}\.\d{2})/"', listing))[-1]
    dest = DATA / "opentargets" / "targets.jsonl"
    if refresh or not dest.exists():
        pq = _pyarrow()
        # From 26.09, tractability and safety are datasets of their own
        # rather than columns of the target table; either layout is read.
        offered = set(re.findall(r'href="([a-z_]+)/"', urllib.request.urlopen(
            f"{OT}/{release}/output/", timeout=60).read().decode()))
        wanted = ["target", "association_overall_direct", "disease", "mouse_phenotype"]
        wanted += [name for name in ("target_tractability", "target_safety_event") if name in offered]
        folders = {name: _parquet_dir(release, name, refresh) for name in wanted}
        read = lambda name, columns: pq.read_table(folders[name], columns=columns).to_pylist()

        say("  reading diseases")
        diseases = read("disease", ["id", "name", "therapeuticAreas", "dbXRefs"])
        write_atomic(DATA / "opentargets" / "disease_xrefs.tsv",
                     "id\tname\txrefs\n" + "".join(
                         f"{row['id']}\t{row['name']}\t{'|'.join(row.get('dbXRefs') or [])}\n"
                         for row in sorted(diseases, key=lambda r: r["id"])))
        names = {row["id"]: row["name"] for row in diseases}
        # The platform's API leaves out terms whose only therapeutic area is
        # "measurement" (HbA1c, waist circumference, "Adult onset"); so does
        # the mirror, so both routes mean the same by a disease association.
        measurement_only = {row["id"] for row in diseases
                            if set(row.get("therapeuticAreas") or []) == {"EFO_0001444"}}
        say(f"  {len(measurement_only):,} measurement terms left out")
        say("  reading associations")
        associated: dict[str, list] = {}
        # Releases from 25.12 call the score associationScore and add an
        # aggregation column; only the overall aggregation is the API's score.
        schema = pq.read_schema(next(folders["association_overall_direct"].glob("*.parquet")))
        score = "associationScore" if "associationScore" in schema.names else "score"
        columns = ["targetId", "diseaseId", score]
        if "aggregationType" in schema.names:
            columns.append("aggregationType")
        for row in read("association_overall_direct", columns):
            if row.get("aggregationType", "overall") != "overall":
                continue
            if row["diseaseId"] in measurement_only:
                continue
            associated.setdefault(row["targetId"], []).append(
                {"score": row[score], "disease": {"id": row["diseaseId"],
                                                  "name": names.get(row["diseaseId"], row["diseaseId"])}})
        say("  reading mouse phenotypes")
        phenotypes: dict[str, list] = {}
        for row in read("mouse_phenotype", ["targetFromSourceId", "modelPhenotypeLabel"]):
            phenotypes.setdefault(row["targetFromSourceId"], []).append(
                {"modelPhenotypeLabel": row["modelPhenotypeLabel"]})
        tractable: dict[str, list] = {}
        if "target_tractability" in folders:
            say("  reading tractability")
            for row in read("target_tractability", ["targetId", "modality", "category", "value"]):
                tractable.setdefault(row["targetId"], []).append(
                    {"modality": row["modality"], "label": row["category"], "value": row["value"]})
        hazards: dict[str, list] = {}
        if "target_safety_event" in folders:
            say("  reading safety events")
            for row in read("target_safety_event", ["targetId", "event", "datasource"]):
                hazards.setdefault(row["targetId"], []).append(
                    {"event": row["event"], "datasource": row["datasource"]})
        say("  reading targets")
        schema = pq.read_schema(next(folders["target"].glob("*.parquet")))
        columns = [c for c in ("id", "approvedSymbol", "tractability", "safetyLiabilities")
                   if c in schema.names]
        part = dest.with_suffix(".part")
        written = 0
        with open(part, "w", encoding="utf-8") as out:
            for row in read("target", columns):
                rows = sorted(associated.get(row["id"], []), key=lambda r: -r["score"])
                tractability = [{"modality": t.get("modality"), "label": t.get("id") or t.get("label"),
                                 "value": t.get("value")} for t in row.get("tractability") or []]
                tractability = tractability or tractable.get(row["id"], [])
                safety = [{"event": s.get("event"), "datasource": s.get("datasource")}
                          for s in row.get("safetyLiabilities") or []]
                safety = safety or hazards.get(row["id"], [])
                out.write(json.dumps({
                    "ensemblId": row["id"], "approvedSymbol": row.get("approvedSymbol"),
                    "tractability": tractability, "safetyLiabilities": safety,
                    "associatedDiseases": {"count": len(rows), "rows": rows},
                    "mousePhenotypes": phenotypes.get(row["id"], []),
                }) + "\n")
                written += 1
        os.replace(part, dest)
        shutil.rmtree(DATA / "opentargets" / "parquet", ignore_errors=True)
        say(f"  wrote {written:,} targets")
    record("opentargets", {"label": "Open Targets", "version": release, "retrieved": TODAY,
                           "license": "CC0 1.0 (some constituent data CC BY-SA)",
                           "files": {"targets": "opentargets/targets.jsonl",
                                     "disease_xrefs": "opentargets/disease_xrefs.tsv"}})


CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"


def _chembl_all(path: str, key: str, **query) -> list[dict]:
    out, offset = [], 0
    while True:
        page = get_json(f"{CHEMBL}/{path}?" + urllib.parse.urlencode(
            {**query, "limit": 1000, "offset": offset, "format": "json"})) or {}
        items = page.get(key) or []
        out.extend(items)
        offset += len(items)
        total = (page.get("page_meta") or {}).get("total_count") or 0
        if not items or offset >= total:
            return out


def chembl(refresh: bool) -> None:
    dest = DATA / "chembl" / "targets.jsonl"
    status = get_json(f"{CHEMBL}/status.json") or {}
    version = str(status.get("chembl_db_version") or "ChEMBL").replace("ChEMBL_", "")
    if refresh or not dest.exists():
        say("  human single-protein targets")
        targets = _chembl_all("target.json", "targets", target_type="SINGLE PROTEIN",
                              organism="Homo sapiens")
        accession_of = {}
        for target in targets:
            for component in target.get("target_components") or []:
                if component.get("accession"):
                    accession_of.setdefault(target["target_chembl_id"], component["accession"])
        say(f"  {len(accession_of):,} targets; every mechanism")
        mechanisms = _chembl_all("mechanism.json", "mechanisms")
        ids = sorted({m["molecule_chembl_id"] for m in mechanisms
                      if m.get("target_chembl_id") in accession_of and m.get("molecule_chembl_id")})
        say(f"  {len(ids):,} molecules")
        names = {}
        batches = [ids[i:i + 50] for i in range(0, len(ids), 50)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            for molecules in pool.map(lambda batch: _chembl_all(
                    "molecule.json", "molecules", molecule_chembl_id__in=",".join(batch)), batches):
                names.update({m["molecule_chembl_id"]: m.get("pref_name") or m["molecule_chembl_id"]
                              for m in molecules})
        say("  activity counts, one per target")

        def count(target: str) -> tuple[str, int]:
            page = get_json(f"{CHEMBL}/activity.json?target_chembl_id={target}&limit=1&format=json") or {}
            return target, int((page.get("page_meta") or {}).get("total_count") or 0)

        with ThreadPoolExecutor(max_workers=8) as pool:
            activities = dict(pool.map(count, sorted(accession_of)))
        drugs: dict[str, dict] = {}
        for m in mechanisms:
            target, molecule = m.get("target_chembl_id"), m.get("molecule_chembl_id")
            if target not in accession_of or not molecule:
                continue
            phase = m.get("max_phase")
            try:
                phase = float(phase) if phase is not None else None
            except (TypeError, ValueError):
                phase = None
            held = drugs.setdefault(target, {}).get(molecule)
            if held is None or (phase or 0) > (held["phase"] or 0):
                drugs[target][molecule] = {"name": names.get(molecule, molecule), "phase": phase,
                                           "action": m.get("action_type")}
        part = dest.with_suffix(".part")
        part.parent.mkdir(parents=True, exist_ok=True)
        with open(part, "w", encoding="utf-8") as out:
            for target, accession in sorted(accession_of.items(), key=lambda kv: kv[1]):
                out.write(json.dumps({"accession": accession, "target": target,
                                      "activities": activities.get(target, 0),
                                      "drugs": list(drugs.get(target, {}).values())}) + "\n")
        os.replace(part, dest)
    record("chembl", {"label": "ChEMBL", "version": version, "retrieved": TODAY,
                      "license": "CC BY-SA 3.0", "files": {"targets": "chembl/targets.jsonl"}})


def alphafold(refresh: bool) -> None:
    dest = DATA / "alphafold" / "summary.tsv"
    if refresh or not dest.exists():
        entries = DATA / "uniprot" / "entries.tsv"
        if not entries.exists():
            raise RuntimeError("build uniprot first: its accessions are the list to fetch")
        with open(entries, encoding="utf-8") as handle:
            accessions = [line.split("\t", 1)[0] for line in handle][1:]
        raw = DATA / "alphafold" / "AlphaMissense_aa_substitutions.tsv.gz"
        fetch("https://storage.googleapis.com/dm_alphamissense/AlphaMissense_aa_substitutions.tsv.gz",
              raw, refresh)
        say("  averaging AlphaMissense per protein and per residue")
        sums: dict[str, list[float]] = {}
        residues = DATA / "alphafold" / "missense_residues.tsv"
        with gzip.open(raw, "rt", encoding="utf-8") as handle, \
                open(residues.with_suffix(".part"), "w", encoding="utf-8") as out:
            out.write("accession" + "\t" + "means" + "\n")
            current, positions = None, {}

            def flush() -> None:
                # The mean of the 19 substitutions at each position, position 1
                # first; an empty cell where the table has none.
                if current and positions:
                    last = max(positions)
                    out.write(current + "\t" + ",".join(
                        f"{sum(positions[p]) / len(positions[p]):.3f}" if p in positions else ""
                        for p in range(1, last + 1)) + "\n")

            for line in handle:
                if line.startswith("#") or line.startswith("uniprot_id"):
                    continue
                accession, variant, score, klass = line.rstrip("\n").split("\t")[:4]
                totals = sums.setdefault(accession, [0.0, 0.0, 0.0])
                totals[0] += float(score)
                totals[1] += 1
                # The bulk file names the class "pathogenic", "benign" or
                # "ambiguous"; the per-protein files AlphaFold DB serves say
                # "likely_pathogenic" for the same call.
                totals[2] += klass in ("pathogenic", "likely_pathogenic")
                if accession != current:
                    flush()
                    current, positions = accession, {}
                try:
                    positions.setdefault(int(variant[1:-1]), []).append(float(score))
                except ValueError:
                    pass
            flush()
        os.replace(residues.with_suffix(".part"), residues)
        say(f"  {len(sums):,} proteins scored; AlphaFold confidence for {len(accessions):,} entries")

        # Per-residue confidence already kept from an earlier run stays, so a
        # rerun asks only for what is missing.
        kept: dict[str, tuple[str, str]] = {}
        residues_path = DATA / "alphafold" / "plddt_residues.tsv"
        if residues_path.exists():
            for line in residues_path.read_text(encoding="utf-8").splitlines()[1:]:
                parts = line.split("	")
                if len(parts) == 3 and parts[2]:
                    kept[parts[0]] = (parts[1], parts[2])
        failures: list[str] = []

        def model(accession: str) -> tuple[str, dict | None]:
            found = get_json(f"https://alphafold.ebi.ac.uk/api/prediction/{accession}")
            if not isinstance(found, list) or not found:
                return accession, None
            chosen = next((m for m in found if m.get("uniprotStart") == 1), found[0])
            if accession in kept:
                chosen["_plddt"] = kept[accession][1]
                return accession, chosen
            # The per-residue confidence, for the structure plot: one more
            # small file per model, read in the same pass.
            doc = chosen.get("plddtDocUrl")
            if doc:
                try:
                    confidence = get_json(doc) or {}
                    chosen["_plddt"] = ",".join(
                        f"{float(c):.1f}" for c in confidence.get("confidenceScore", []))
                except Exception as exc:  # counted and said, never swallowed
                    chosen["_plddt"] = ""
                    failures.append(f"{accession}: {exc}")
            return accession, chosen

        # Four at a time: the file server refuses a client that asks faster.
        with ThreadPoolExecutor(max_workers=4) as pool:
            models = dict(pool.map(model, accessions))
        with_residues = sum(1 for m in models.values() if m and m.get("_plddt"))
        say(f"  per-residue confidence for {with_residues:,} of "
            f"{sum(1 for m in models.values() if m):,} models"
            + (f"; {len(failures):,} could not be read (first: {failures[0]}). A rerun asks "
               "only for those" if failures else ""))
        write_atomic(DATA / "alphafold" / "plddt_residues.tsv",
                     "accession" + "\t" + "start" + "\t" + "plddt" + "\n" + "".join(
                         f"{accession}" + "\t" + f"{m.get('uniprotStart') or 1}" + "\t"
                         + m["_plddt"] + "\n"
                         for accession, m in sorted(models.items()) if m and m.get("_plddt")))
        part = dest.with_suffix(".part")
        with open(part, "w", encoding="utf-8") as out:
            out.write("accession\tmean_plddt\tvery_high\tconfident\tlow\tvery_low\tam_mean\t"
                      "am_pathogenic_share\n")
            for accession in accessions:
                m = models.get(accession)
                if not m or m.get("globalMetricValue") is None:
                    continue
                am = sums.get(accession)
                am_mean = f"{am[0] / am[1]:.3f}" if am and am[1] else ""
                am_share = f"{100 * am[2] / am[1]:.1f}" if am and am[1] else ""
                out.write("\t".join([accession, f"{m['globalMetricValue']:.2f}",
                                     *(str(m.get(k, "")) for k in ("fractionPlddtVeryHigh",
                                       "fractionPlddtConfident", "fractionPlddtLow",
                                       "fractionPlddtVeryLow")), am_mean, am_share]) + "\n")
        os.replace(part, dest)
        raw.unlink()
        versions = [m.get("latestVersion") for m in models.values() if m and m.get("latestVersion")]
        if versions:
            write_atomic(DATA / "alphafold" / "version.txt", f"v{max(versions)}\n")
    try:
        version = (DATA / "alphafold" / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        version = _kept("alphafold") if MANIFEST.exists() else "v6"
    record("alphafold", {"label": "AlphaFold DB", "version": version, "retrieved": TODAY,
                         "license": "CC BY 4.0 (AlphaFold DB and AlphaMissense)",
                         "files": {"summary": "alphafold/summary.tsv",
                                   **{key: f"alphafold/{key}.tsv" for key in
                                      ("plddt_residues", "missense_residues")
                                      if (DATA / "alphafold" / f"{key}.tsv").exists()}}})


def _kept(key: str) -> str:
    """The version already in the manifest, when nothing was downloaded."""
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"][key]["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        return TODAY


OMNIPATH = "https://omnipathdb.org/interactions"
OMNIPATH_FIELDS = "references,curation_effort,sources,type"
#: The two sets Spica reads: the curated network (protein interactions and
#: signalling) and transcription factor to target regulation.
OMNIPATH_SETS = {"interactions": "omnipath", "regulation": "dorothea,collectri,tf_target"}


def omnipath(refresh: bool) -> None:
    """OmniPath, whole, with its own commercial filter on every request: the
    records of each upstream resource whose licence allows commercial use,
    and nothing else (`docs/licences.md`)."""
    files, downloaded = {}, False
    for key, datasets in OMNIPATH_SETS.items():
        dest = DATA / "omnipath" / f"{key}.tsv"
        query = urllib.parse.urlencode({"datasets": datasets, "genesymbols": 1,
                                        "license": "commercial", "format": "tsv",
                                        "fields": OMNIPATH_FIELDS})
        headers = fetch(f"{OMNIPATH}?{query}", dest, refresh)
        downloaded = downloaded or bool(headers)
        if headers:
            header = header_of(dest)
            if "source_genesymbol" not in header:
                raise RuntimeError(f"OmniPath answered without gene symbols: {header[:4]}")
        files[key] = f"omnipath/{key}.tsv"
    # A live service without numbered releases: the copy is dated, by the
    # day it was downloaded.
    version = TODAY if downloaded else _kept("omnipath")
    record("omnipath", {"label": "OmniPath", "version": version, "retrieved": TODAY,
                        "license": "Per resource; only records cleared for commercial use",
                        "files": files})


FIGSHARE = "https://api.figshare.com/v2"
#: DepMap's releases are deposited on Figshare+ as "DepMap 24Q4 Public"; the
#: portal itself now sits behind a browser check a build cannot pass.
DEPMAP_TITLE = re.compile(r"^DepMap (\d\dQ\d) Public$")
DEPMAP_FALLBACK = (27993248, "24Q4")
DEPMAP_FILES = ("Model.csv", "CRISPRInferredCommonEssentials.csv", "CRISPRGeneEffect.csv",
                "CRISPRGeneDependency.csv")
#: Edges of the gene-effect distribution: 0.1 wide from -3 to 1, the two end
#: bins open, so every line is counted somewhere.
EFFECT_EDGES = [round(-3 + 0.1 * i, 1) for i in range(41)]
DEPENDENT = 0.5  # dependency probability above which a line counts as dependent


def _depmap_latest() -> tuple[int, str]:
    """The newest "DepMap NNQN Public" deposit on Figshare, by release."""
    found: dict[str, int] = {}
    try:
        request = urllib.request.Request(
            f"{FIGSHARE}/articles/search", headers={**AGENT, "Content-Type": "application/json"},
            data=json.dumps({"search_for": "DepMap Public", "page_size": 100}).encode())
        with urllib.request.urlopen(request, timeout=60) as response:
            for article in json.load(response):
                match = DEPMAP_TITLE.match(str(article.get("title", "")).strip())
                if match:
                    found[match.group(1)] = int(article["id"])
    except Exception as exc:
        say(f"  Figshare search failed ({exc}); using DepMap {DEPMAP_FALLBACK[1]}")
    if not found:
        return DEPMAP_FALLBACK
    release = max(found)  # "24Q4" > "24Q2" > "23Q4": year, then quarter
    return found[release], release


def _gene_label(label: str) -> tuple[str, str]:
    """DepMap names a gene column "SYMBOL (Entrez)"."""
    match = re.match(r"^(.*) \((\d+)\)$", label.strip())
    return (match.group(1), match.group(2)) if match else (label.strip(), "")


def _matrix(path: Path) -> tuple[list[str], list[str], list]:
    """A DepMap model-by-gene CSV as (models, gene labels, one float array per
    gene), NaN where a model was not screened. Arrays, not lists: twenty
    million floats as Python objects would not fit."""
    from array import array

    nan = float("nan")
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        genes = next(reader)[1:]
        columns = [array("f") for _ in genes]
        models = []
        for row in reader:
            models.append(row[0])
            for index, cell in enumerate(row[1:len(genes) + 1]):
                columns[index].append(float(cell) if cell else nan)
    return models, genes, columns


def _depmap_summary(raw: Path, dest: Path) -> int:
    """One row per gene from the two Chronos matrices: how much cells need
    it, how many depend on it, by lineage, and every dependent line."""
    import math

    lineage: dict[str, tuple[str, str]] = {}
    with open(raw / "Model.csv", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            lineage[row["ModelID"]] = (row.get("CellLineName", ""), row.get("OncotreeLineage", "") or "Unknown")
    essentials = set()
    for line in (raw / "CRISPRInferredCommonEssentials.csv").read_text(encoding="utf-8").splitlines():
        if "(" in line:
            essentials.add(line.strip().strip('"'))
    hgnc: dict[str, tuple[str, str]] = {}
    hgnc_file = DATA / "hgnc" / "hgnc_complete_set.txt"
    if hgnc_file.exists():
        with open(hgnc_file, encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            at = {name: header.index(name) for name in ("hgnc_id", "symbol", "entrez_id")}
            for line in handle:
                cells = line.rstrip("\n").split("\t")
                entrez = cells[at["entrez_id"]].strip().strip('"') if len(cells) > at["entrez_id"] else ""
                if entrez:
                    hgnc[entrez] = (cells[at["hgnc_id"]].strip('"'), cells[at["symbol"]].strip('"'))

    say("  reading gene effect")
    models, genes, effects = _matrix(raw / "CRISPRGeneEffect.csv")
    say("  reading dependency probability")
    dep_models, dep_genes, probabilities = _matrix(raw / "CRISPRGeneDependency.csv")
    dep_row = {model: index for index, model in enumerate(dep_models)}
    dep_col = {label: index for index, label in enumerate(dep_genes)}

    columns = ["hgnc_id", "symbol", "entrez", "depmap_symbol", "lines", "mean_effect",
               "median_effect", "min_effect", "dependent", "dependent_share", "common_essential",
               "lineages", "histogram", "dependent_lines"]
    out = [columns]
    for label, values in zip(genes, effects):
        symbol, entrez = _gene_label(label)
        hgnc_id, current = hgnc.get(entrez, ("", symbol))
        probs = probabilities[dep_col[label]] if label in dep_col else None
        scored, per_lineage, dependent_lines = [], {}, []
        bins = [0] * (len(EFFECT_EDGES) - 1)
        dependent = judged = 0
        for row_index, value in enumerate(values):
            if math.isnan(value):
                continue
            model = models[row_index]
            name, line_lineage = lineage.get(model, (model, "Unknown"))
            scored.append(value)
            at = min(max(int((value - EFFECT_EDGES[0]) / 0.1), 0), len(bins) - 1)
            bins[at] += 1
            stats = per_lineage.setdefault(line_lineage, [0, 0, 0.0])
            stats[0] += 1
            stats[2] += value
            prob = float("nan")
            if probs is not None and model in dep_row:
                prob = probs[dep_row[model]]
            if not math.isnan(prob):
                judged += 1
                if prob > DEPENDENT:
                    dependent += 1
                    stats[1] += 1
                    dependent_lines.append((value, model))
        if not scored:
            continue
        scored.sort()
        middle = len(scored) // 2
        median = scored[middle] if len(scored) % 2 else (scored[middle - 1] + scored[middle]) / 2
        lineages = {name: [n, dep, round(total / n, 3)] for name, (n, dep, total) in sorted(per_lineage.items())}
        dependent_lines.sort()
        out.append([hgnc_id, current, entrez, symbol, str(len(scored)),
                    f"{sum(scored) / len(scored):.4f}", f"{median:.4f}", f"{scored[0]:.4f}",
                    str(dependent), f"{100 * dependent / judged:.2f}" if judged else "",
                    "1" if label in essentials else "0",
                    json.dumps(lineages, separators=(",", ":")), ",".join(map(str, bins)),
                    "|".join(f"{model}:{value:.3f}" for value, model in dependent_lines)])
    write_atomic(dest, "".join("\t".join(row) + "\n" for row in out))
    return len(out) - 1


def depmap(refresh: bool) -> None:
    """DepMap's CRISPR screens, reduced to one row per gene; the two
    matrices they come from (about 850 MB) are deleted once read."""
    folder = DATA / "depmap"
    summary = folder / "genes.tsv"
    if refresh or not summary.exists():
        article, release = _depmap_latest()
        meta = get_json(f"{FIGSHARE}/articles/{article}") or {}
        urls = {f["name"]: f["download_url"] for f in meta.get("files", [])}
        missing = [name for name in DEPMAP_FILES if name not in urls]
        if missing:
            raise RuntimeError(f"DepMap {release} on Figshare has no {', '.join(missing)}")
        licence = (meta.get("license") or {}).get("name", "")
        if licence != "CC BY 4.0":
            raise RuntimeError(f"DepMap {release} is deposited under {licence or 'no stated licence'}, "
                               "not CC BY 4.0: check it before mirroring (docs/licences.md)")
        raw = folder / "raw"
        for name in DEPMAP_FILES:
            fetch(urls[name], raw / name, refresh)
        say(f"  {_depmap_summary(raw, summary):,} genes summarised")
        os.replace(raw / "Model.csv", folder / "Model.csv")
        for name in DEPMAP_FILES:
            (raw / name).unlink(missing_ok=True)
        raw.rmdir()
        version, doi = release, str(meta.get("doi") or "")
    else:
        version, doi = _kept("depmap") or DEPMAP_FALLBACK[1], ""
        try:
            doi = json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"]["depmap"].get("doi", "")
        except Exception:
            pass
    record("depmap", {"label": "DepMap", "version": version, "retrieved": TODAY,
                      "license": "CC BY 4.0 (DepMap, Broad Institute; Figshare+ deposit)",
                      "doi": doi, "files": {"genes": "depmap/genes.tsv", "models": "depmap/Model.csv"}})


STRING_API = "https://string-db.org/api/json/version"
STRING_FILES = "https://stringdb-downloads.org/download"


def _string_version() -> str:
    answer = get_json(STRING_API) or []
    return str(answer[0].get("string_version", "")) if answer else ""


def string(refresh: bool) -> None:
    """STRING's physical subnetwork for human, every link with its evidence
    channels, mapped from STRING's protein IDs to Ensembl genes through
    STRING's own alias table. Both directions, sorted by the first gene, so
    the index finds a gene's partners in one range."""
    folder = DATA / "string"
    dest = folder / "physical.tsv"
    if refresh or not dest.exists():
        version = _string_version() or "12.5"
        raw = folder / "raw"
        names = {"aliases": "protein.aliases", "links": "protein.physical.links.detailed"}
        for key, name in names.items():
            fetch(f"{STRING_FILES}/{name}.v{version}/9606.{name}.v{version}.txt.gz",
                  raw / f"{key}.txt.gz", refresh)
        gene: dict[str, str] = {}
        with gzip.open(raw / "aliases.txt.gz", "rt", encoding="utf-8") as handle:
            for line in handle:
                protein, alias, source = (line.rstrip("\n").split("\t") + ["", ""])[:3]
                if source == "Ensembl_gene":
                    gene.setdefault(protein, alias)
        rows, unmapped = [], 0
        with gzip.open(raw / "links.txt.gz", "rt", encoding="utf-8") as handle:
            header = handle.readline().split()
            at = {name: header.index(name) for name in
                  ("protein1", "protein2", "experimental", "database", "textmining", "combined_score")}
            for line in handle:
                cells = line.split()
                one, two = gene.get(cells[at["protein1"]]), gene.get(cells[at["protein2"]])
                if not one or not two:
                    unmapped += 1
                    continue
                rows.append((one, two, cells[at["experimental"]], cells[at["database"]],
                             cells[at["textmining"]], cells[at["combined_score"]]))
        rows.sort()
        write_atomic(dest, "gene_a" + "\t" + "gene_b" + "\t" + "experimental" + "\t" + "database"
                     + "\t" + "textmining" + "\t" + "combined_score" + "\n"
                     + "".join("\t".join(row) + "\n" for row in rows))
        say(f"  {len(rows):,} links kept, {unmapped:,} without an Ensembl gene")
        for key in names:
            (raw / f"{key}.txt.gz").unlink(missing_ok=True)
        raw.rmdir()
    else:
        version = _kept("string") or "12.5"
    record("string", {"label": "STRING", "version": version, "retrieved": TODAY,
                      "license": "CC BY 4.0 (STRING)", "network": "physical subnetwork",
                      "files": {"physical": "string/physical.tsv"}})


GWAS_ZIP = ("https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/"
            "gwas-catalog-associations_ontology-annotated-full.zip")
GWAS_COLUMNS = ("gene_id", "relation", "trait", "trait_uris", "associations", "studies",
                "mlog10p", "p_value", "risk_allele", "or_beta", "context", "study", "pubmed")


def _ids(cell: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", cell or "") if part.strip().startswith("ENSG")]


def gwas(refresh: bool) -> None:
    """The GWAS Catalog associations, reduced to one row per gene and trait:
    the strongest association with its variant, the association count, and
    whether the variant is in the gene or only near it. The genes come from
    the Ensembl mapping of the Catalog."""
    folder = DATA / "gwas"
    dest = folder / "traits.tsv"
    if refresh or not dest.exists():
        raw = folder / "associations.zip"
        headers = fetch(GWAS_ZIP, raw, refresh=True)
        best: dict[tuple[str, str], dict] = {}
        counts: dict[tuple[str, str], list] = {}
        with zipfile.ZipFile(raw) as archive:
            member = archive.infolist()[0]
            with archive.open(member) as handle:
                text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
                head = text.readline().rstrip("\n").split("\t")
                at = {name: head.index(name) for name in (
                    "SNP_GENE_IDS", "UPSTREAM_GENE_ID", "DOWNSTREAM_GENE_ID", "MAPPED_TRAIT",
                    "MAPPED_TRAIT_URI", "DISEASE/TRAIT", "PVALUE_MLOG", "P-VALUE",
                    "STRONGEST SNP-RISK ALLELE", "OR or BETA", "CONTEXT", "STUDY ACCESSION",
                    "PUBMEDID")}
                for line in text:
                    cells = line.rstrip("\n").split("\t")
                    if len(cells) < len(head):
                        continue
                    trait = cells[at["MAPPED_TRAIT"]].strip() or cells[at["DISEASE/TRAIT"]].strip()
                    try:
                        strength = float(cells[at["PVALUE_MLOG"]])
                    except ValueError:
                        continue
                    inside = _ids(cells[at["SNP_GENE_IDS"]])
                    nearest = [g for g in _ids(cells[at["UPSTREAM_GENE_ID"]])
                               + _ids(cells[at["DOWNSTREAM_GENE_ID"]]) if g not in inside]
                    for gene_id, relation in [(g, "in the gene") for g in inside] + \
                            [(g, "nearest gene") for g in nearest]:
                        key = (gene_id, trait)
                        tally = counts.setdefault(key, [0, set(), False])
                        tally[0] += 1
                        tally[1].add(cells[at["STUDY ACCESSION"]])
                        tally[2] = tally[2] or relation == "in the gene"
                        if key not in best or strength > best[key]["mlog10p"]:
                            best[key] = {"mlog10p": strength, "relation": relation,
                                         "uris": cells[at["MAPPED_TRAIT_URI"]].strip(),
                                         "p": cells[at["P-VALUE"]].strip(),
                                         "allele": cells[at["STRONGEST SNP-RISK ALLELE"]].strip(),
                                         "effect": cells[at["OR or BETA"]].strip(),
                                         "context": cells[at["CONTEXT"]].strip(),
                                         "study": cells[at["STUDY ACCESSION"]].strip(),
                                         "pubmed": cells[at["PUBMEDID"]].strip()}
        rows = []
        for (gene_id, trait), found in best.items():
            n, studies, any_inside = counts[(gene_id, trait)]
            rows.append((gene_id, -found["mlog10p"], trait, [
                gene_id, "in the gene" if any_inside else "nearest gene", trait, found["uris"],
                str(n), str(len(studies)), f"{found['mlog10p']:.2f}", found["p"], found["allele"],
                found["effect"], found["context"], found["study"], found["pubmed"]]))
        rows.sort()
        write_atomic(dest, "\t".join(GWAS_COLUMNS) + "\n"
                     + "".join("\t".join(c.replace("\t", " ") for c in row[3]) + "\n" for row in rows))
        say(f"  {len(rows):,} gene and trait pairs")
        raw.unlink(missing_ok=True)
        version = day(headers)
    else:
        version = _kept("gwas") or TODAY
    record("gwas", {"label": "GWAS Catalog", "version": version, "retrieved": TODAY,
                    "license": "EMBL-EBI terms of use; summary statistics CC0 unless stated",
                    "files": {"traits": "gwas/traits.tsv"}})


STEPS = {"hgnc": hgnc, "ensembl": ensembl, "uniprot": uniprot, "gtex": gtex, "hpa": hpa,
         "clinvar": clinvar, "opentargets": opentargets, "chembl": chembl, "alphafold": alphafold,
         "omnipath": omnipath, "depmap": depmap, "string": string, "gwas": gwas}

#: How the local data panel names each step.
LABELS = {"hgnc": "HGNC", "ensembl": "Ensembl", "uniprot": "UniProt", "gtex": "GTEx",
          "hpa": "Human Protein Atlas", "clinvar": "ClinVar", "opentargets": "Open Targets",
          "chembl": "ChEMBL", "alphafold": "AlphaFold DB", "omnipath": "OmniPath",
          "depmap": "DepMap", "string": "STRING", "gwas": "GWAS Catalog"}


# -- newer releases -------------------------------------------------------------


def _head(url: str) -> dict[str, str]:
    request = urllib.request.Request(url, headers=AGENT, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        return dict(response.headers)


def _hpa_version() -> str:
    page = urllib.request.urlopen(urllib.request.Request(
        "https://www.proteinatlas.org/about/download", headers=AGENT), timeout=30).read().decode(
        "utf-8", "replace")
    found = re.search(r"[Vv]ersion\s*(\d+\.\d+)", page)
    if not found:
        raise RuntimeError("the HPA download page names no version")
    return found.group(1)


def _ot_version() -> str:
    listing = urllib.request.urlopen(f"{OT}/", timeout=30).read().decode()
    return sorted(re.findall(r'href="(\d{2}\.\d{2})/"', listing))[-1]


def _uniprot_version() -> str:
    request = urllib.request.Request(
        "https://rest.uniprot.org/uniprotkb/search?query=accession:P04637&fields=accession"
        "&format=tsv&size=1", headers=AGENT)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.headers.get("X-UniProt-Release", "")


def _alphafold_version() -> str:
    found = get_json("https://alphafold.ebi.ac.uk/api/prediction/P04637") or []
    return f"v{max(m.get('latestVersion', 0) for m in found)}" if found else ""


#: How to ask each source for its newest release, in the form its manifest
#: entry records it, so the two compare as strings. One small request each.
PROBES = {
    "hgnc": lambda: day(_head("https://storage.googleapis.com/public-download-files/hgnc/tsv/"
                              "tsv/hgnc_complete_set.txt")),
    "ensembl": lambda: str((get_json("https://rest.ensembl.org/info/data?content-type="
                                     "application/json") or {}).get("releases", [""])[0]),
    "uniprot": _uniprot_version,
    "gtex": lambda: _gtex_latest()[0],
    "hpa": _hpa_version,
    "clinvar": lambda: day(_head("https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/"
                                 "variant_summary.txt.gz")),
    "opentargets": _ot_version,
    "chembl": lambda: str((get_json(f"{CHEMBL}/status.json") or {}).get(
        "chembl_db_version", "")).replace("ChEMBL_", ""),
    "alphafold": _alphafold_version,
    "depmap": lambda: _depmap_latest()[1],
    "string": _string_version,
    "gwas": lambda: day(_head(GWAS_ZIP)),
    # No releases to ask about: the copy is as fresh as its date.
    "omnipath": lambda: "",
}


def has_parquet() -> bool:
    """Whether this copy reads Parquet, which the Open Targets build needs."""
    try:
        import pyarrow.parquet  # noqa: F401
        return True
    except ImportError:
        return False


def latest() -> dict:
    """Each source's newest release upstream, or why it could not be asked.

    Kept in `mirror-latest.json` with the date it was asked, so the app can
    say "checked today" without asking again.
    """
    def probe(item):
        key, ask = item
        try:
            return key, {"version": ask() or "", "error": ""}
        except Exception as exc:  # a source that cannot be asked says so
            return key, {"version": "", "error": str(exc)[:200]}

    with ThreadPoolExecutor(max_workers=len(PROBES)) as pool:
        found = dict(pool.map(probe, PROBES.items()))
    result = {"checked": date.today().isoformat(), "sources": found, "parquet": has_parquet()}
    try:
        temporary = LATEST.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, indent=1), encoding="utf-8")
        os.replace(temporary, LATEST)
    except OSError:
        pass
    return result


def use(root: Path) -> None:
    """Build into another folder than the app's (the tests do)."""
    global DATA, MANIFEST, STATUS, LOG, LATEST
    DATA = Path(root)
    MANIFEST, STATUS = DATA / "mirror.json", DATA / "mirror-status.json"
    LOG, LATEST = DATA / "mirror-build.log", DATA / "mirror-latest.json"


def _heartbeat() -> None:
    """Some steps run for minutes without a word (sorting ClinVar, averaging
    AlphaMissense). The beat tells the app the build is alive, not stuck."""
    while STATE["running"]:
        STATE["beat"] = time.time()
        _write_status(force=True)
        time.sleep(10)


def build(chosen: list[str], refresh: bool) -> int:
    """Build the chosen sources in order, reporting through STATE."""
    import threading

    DATA.mkdir(parents=True, exist_ok=True)
    STATE.update({"running": True, "pid": os.getpid(), "started": time.strftime("%Y-%m-%d %H:%M"),
                  "finished": "", "sources": chosen, "current": "", "done": [], "failed": {},
                  "file": None, "log": [], "beat": time.time()})
    threading.Thread(target=_heartbeat, daemon=True).start()
    say(f"building {', '.join(chosen)} into {DATA}")
    for name in chosen:
        STATE["current"] = name
        say(f"{name}: start")
        started = time.time()
        try:
            STEPS[name](refresh)
            STATE["done"].append(name)
            say(f"{name}: done in {time.time() - started:.0f}s")
        except Exception as exc:
            STATE["failed"][name] = str(exc)[:300]
            say(f"{name}: FAILED, it keeps using its API: {exc}")
    failed = list(STATE["failed"])
    STATE.update({"running": False, "current": "", "file": None,
                  "finished": time.strftime("%Y-%m-%d %H:%M")})
    say("finished" + (f"; failed: {', '.join(failed)}" if failed else ", every source local"))
    _write_status(force=True)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sources", nargs="*", help=f"any of: {', '.join(STEPS)} (default: all)")
    parser.add_argument("--refresh", action="store_true", help="download again")
    parser.add_argument("--check", action="store_true",
                        help="ask each source for its newest release, and build nothing")
    args = parser.parse_args(argv)
    unknown = [name for name in args.sources if name not in STEPS]
    if unknown:
        parser.error(f"no source called {', '.join(unknown)}; choose from {', '.join(STEPS)}")
    if args.check:
        result = latest()
        if sys.stdout is None:  # the windowed exe: the answer is in mirror-latest.json
            return 0
        try:
            local = json.loads(MANIFEST.read_text(encoding="utf-8")).get("sources", {})
        except (OSError, json.JSONDecodeError):
            local = {}
        for key, found in result["sources"].items():
            have = (local.get(key) or {}).get("version", "not built")
            now = found["version"] or f"unknown ({found['error']})"
            mark = "" if have == found["version"] else "  <- newer" if found["version"] else ""
            print(f"{key:12} {have:12} {now}{mark}")
        return 0
    return build(args.sources or list(STEPS), args.refresh)


if __name__ == "__main__":
    sys.exit(main())
