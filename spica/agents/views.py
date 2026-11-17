"""The report views, as tools: AI mode reaches all that the report reaches.

The report shows more than the record: the organ alignment, the glance
words, the structure along the sequence, isoforms by tissue, co-expressed
genes, shared regulators, the genome view and competitive intelligence.
Each one is a tool here and calls the same function as the screen. An
answer can thus use all data that a researcher can see.

Two rules come from the report.

*Never cut data.* A long answer comes one page at a time, with the call for
the next page. Nothing is dropped without a note. `field()` reads one full
field of the record; the record tool shows the first entries of a list.

*Each line is citable.* Each tool vouches for one citation per call
(`[organs:PCSK9]`, `[coexpressed:PCSK9]`). The verifier checks the numbers
of an answer against the tool output under that citation.

`tests/test_agents.py` holds a parity test: each view of the app maps to a
tool here. A view without its tool fails the suite.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from spica.agents.tools import Finding
from spica.live import LiveError, NotFoundUpstream

#: Entries per page, for anything long.
PAGE = 120
RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$|^from\s+(\d+)$")


def _page(items: list, spec: str, call: str) -> tuple[list, str]:
    """A page of `items` from a "51-100" or "from 51" spec, and a line that
    says what was shown and how to ask for more."""
    total = len(items)
    start, end = 1, min(PAGE, total)
    found = RANGE.match(spec.strip()) if spec else None
    if found:
        if found.group(3):
            start = int(found.group(3))
            end = min(start + PAGE - 1, total)
        else:
            start, end = int(found.group(1)), min(int(found.group(2)), total)
    start = max(1, start)
    shown = items[start - 1:end]
    if total <= len(shown) and start == 1:
        return shown, f"all {total}"
    note = f"{start}-{start + len(shown) - 1} of {total}"
    if start + len(shown) - 1 < total:
        nxt = start + len(shown)
        note += f"; the next page is {call} {nxt}-{min(nxt + PAGE - 1, total)}\")"
    return shown, note


def _split(argument: str) -> list[str]:
    return [part for part in re.split(r"\s+", argument.strip()) if part]


def _symbols(argument: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;/]|\s+and\s+|\s+", argument) if part.strip()]


class _Base:
    """Records built the deterministic way, the mirror and the live layer
    as the user has set them up."""

    def __init__(self, builder=None) -> None:
        self._build = builder

    def record(self, symbol: str):
        if self._build is None:
            from spica.build import build_record

            self._build = build_record
        return self._build(symbol)

    @staticmethod
    def mirror_and_live():
        from spica.live import Live
        from spica.mirror import Mirror

        mirror = Mirror.load()
        return mirror, Live.from_env(mirror.root)

    def resolved(self, symbol: str):
        if not symbol:
            return None, Finding("", problem=f"{self.key}() needs a gene symbol")
        record = self.record(symbol)
        if not record.resolution.resolved:
            return None, Finding("", problem=record.resolution.reason)
        return record, None


# -- one field, whole ---------------------------------------------------------


class Field(_Base):
    key = "field"
    label = "One field, whole"
    usage = ('field("<gene> <field name> [words to match | 51-100]") -> every entry of one '
             'record field, a page at a time')

    def status(self) -> str:
        return "any field of the record, unabbreviated"

    def run(self, argument: str) -> Finding:
        from spica.schema import FIELDS_BY_NAME

        parts = _split(argument)
        if len(parts) < 2:
            return Finding("", problem='field() needs a gene and a field name, '
                                      'like field("PCSK9 disease_associations")')
        symbol, name, rest = parts[0], parts[1], " ".join(parts[2:])
        if name not in FIELDS_BY_NAME:
            close = difflib.get_close_matches(name, list(FIELDS_BY_NAME), n=3)
            hint = f" Close matches: {', '.join(close)}." if close else ""
            return Finding("", problem=f"no field {name}.{hint}")
        record, problem = self.resolved(symbol)
        if problem:
            return problem
        spec, value = FIELDS_BY_NAME[name], record.fields[name]
        gene = record.resolution.symbol
        if not value.present:
            return Finding("", problem=f"{gene} {name} has no value "
                                       f"({value.state.value}: {value.reason})")
        raw = value.value
        unit = f" ({spec.unit})" if spec.unit else ""
        source = (f" (from {value.provenance.source} {value.provenance.version})"
                  if value.provenance else "")
        if isinstance(raw, dict):
            entries = list(raw.items())
            if all(isinstance(v, (int, float)) for v in raw.values()):
                entries.sort(key=lambda kv: (-kv[1], kv[0]))
            lines = [f"{key}: {item}" for key, item in entries]
        elif isinstance(raw, list):
            lines = [str(item) for item in raw]
        else:
            return Finding(f"[{name}] {gene} {spec.label}: {raw}{unit}{source}",
                           citations=[name], raw=f"{gene} {name}")
        if rest and not RANGE.match(rest):
            words = rest.lower().split()
            lines = [line for line in lines if all(word in line.lower() for word in words)]
            if not lines:
                return Finding("", problem=f"no entry of {gene} {name} matches {rest!r}")
            spec_range, label = "", f"matching {rest!r}, "
        else:
            spec_range, label = rest, ""
        shown, note = _page(lines, spec_range, f'field("{gene} {name}')
        text = (f"[{name}] {gene} {spec.label}{unit}{source}, {label}entries {note}:\n"
                + "\n".join(f"  {line}" for line in shown))
        return Finding(text, citations=[name], raw=f"{gene} {name}: {note}")


# -- the organ alignment --------------------------------------------------------


class Organs(_Base):
    key = "organs"
    label = "RNA and protein by organ"
    usage = 'organs("<gene>") -> transcript and protein, every source, on one organ axis'

    def status(self) -> str:
        return "GTEx, HPA RNA, single cell, antibody and mass spec, aligned by organ"

    def run(self, argument: str) -> Finding:
        from spica.dogma import align

        record, problem = self.resolved(argument.strip())
        if problem:
            return problem
        gene = record.resolution.symbol
        aligned = align(record)
        if not aligned.get("rows"):
            return Finding("", problem=aligned.get("summary") or f"{gene} has no per-tissue data")
        layers = {layer["key"]: layer for layer in aligned["layers"]}
        lines = [f"[organs:{gene}] {aligned['summary']}"]
        for row in aligned["rows"]:
            cells = []
            for key, cell in row["cells"].items():
                layer = layers.get(key, {})
                peak = f", highest in {cell['peak_tissue']}" if cell.get("merged", 1) > 1 else ""
                unit = f" {layer.get('unit')}" if layer.get("kind") == "number" else ""
                cells.append(f"{layer.get('label', key)} {cell['display']}{unit}{peak}")
            lines.append(f"  {row['organ']}: " + "; ".join(cells))
        if aligned.get("missing"):
            lines.append(f"  not measured here: {', '.join(map(str, aligned['missing']))}")
        pairs = [p for p in aligned.get("agreement") or [] if p["rho"] is not None]
        if pairs:
            lines.append("  agreement between sources (Pearson r of log(1 + value) over the "
                         "organs both measure):")
            lines += [f"    {layers[p['a']]['label']} against {layers[p['b']]['label']}: "
                      f"r={p['rho']} over {p['n']} organs" for p in pairs]
        return Finding("\n".join(lines), citations=[f"organs:{gene}"],
                       raw=f"{len(aligned['rows'])} organs for {gene}")


# -- the glance words -------------------------------------------------------------


class Glance(_Base):
    key = "glance"
    label = "At a glance"
    usage = ('glance("<gene> [function | disease] [51-100]") -> the words its GO terms and '
             'disease associations keep returning to, with their weights')

    def status(self) -> str:
        return "the words behind the report's word map, with the terms each comes from"

    def run(self, argument: str) -> Finding:
        from spica.glance import glance

        parts = _split(argument)
        record, problem = self.resolved(parts[0] if parts else "")
        if problem:
            return problem
        gene = record.resolution.symbol
        sides = [p for p in parts[1:] if p in ("function", "disease")] or ["function", "disease"]
        spec = " ".join(p for p in parts[1:] if p not in ("function", "disease"))
        result = glance(record)
        lines = [f"[glance:{gene}]"]
        for side in sides:
            block = result[side]
            if not block["words"]:
                lines.append(f"  {side}: {block['reason']}")
                continue
            how = ("weight = number of GO terms using the word" if side == "function" else
                   "weight = sum of squared association scores of the diseases using it")
            shown, note = _page(block["words"], spec, f'glance("{gene} {side}')
            lines.append(f"  {side} ({block['terms']} terms, {block['source']}; {how}), "
                         f"words {note}:")
            for word in shown:
                sources = word["from"][:3]
                example = "; ".join(s[0] if isinstance(s, list) else s for s in sources)
                lines.append(f"    {word['word']}: {word['weight']} ({word['count']} terms, "
                             f"e.g. {example})")
        return Finding("\n".join(lines), citations=[f"glance:{gene}"], raw=f"glance for {gene}")


# -- where the protein sits -----------------------------------------------------------


class Where(_Base):
    key = "where"
    label = "Where the protein sits"
    usage = ('where("<gene>") -> UniProt, HPA and GO locations on one set of compartments, '
             'and how many sources agree')

    def status(self) -> str:
        return "ten compartments, three sources"

    def run(self, argument: str) -> Finding:
        from spica.locations import compartments

        record, problem = self.resolved(argument.strip())
        if problem:
            return problem
        gene = record.resolution.symbol
        found = compartments(record)
        labels = {s["key"]: s["label"] for s in found["sources"]}
        reported = [s["label"] for s in found["sources"] if s["reported"]]
        if not reported:
            return Finding("", problem=f"no source places {gene}'s protein anywhere")
        lines = [f"[where:{gene}] sources reporting: {', '.join(reported)}"]
        for row in found["compartments"]:
            if not row["count"]:
                continue
            said = "; ".join(f"{labels[key]}: {', '.join(terms)}"
                             for key, terms in row["sources"].items())
            main = ", HPA's main location" if row["main"] else ""
            lines.append(f"  {row['name']}: {row['count']} of {len(reported)} sources{main} ({said})")
        if found["topology"]:
            lines.append(f"  membrane topology (UniProt): {', '.join(found['topology'])}")
        if found["unplaced"]:
            lines.append("  not a compartment: " + ", ".join(
                f"{u['term']} ({u['source']})" for u in found["unplaced"]))
        return Finding("\n".join(lines), citations=[f"where:{gene}"], raw=f"locations of {gene}")


# -- the protein along its sequence ----------------------------------------------------


def _stretches(points: list[list[float]], keep, minimum: int = 5) -> list[tuple[int, int]]:
    """Runs of at least `minimum` consecutive residues where keep(value)."""
    out, start, last = [], None, None
    for residue, value in points:
        residue = int(residue)
        if keep(value) and (last is None or residue == last + 1) and start is not None:
            last = residue
            continue
        if start is not None and last - start + 1 >= minimum:
            out.append((start, last))
        start, last = (residue, residue) if keep(value) else (None, None)
    if start is not None and last - start + 1 >= minimum:
        out.append((start, last))
    return out


class Structure(_Base):
    key = "structure"
    label = "Structure along the sequence"
    usage = ('structure("<gene>") -> PDB coverage, AlphaFold confidence and AlphaMissense '
             'tolerance along the protein')

    def status(self) -> str:
        return "PDB entries and chains; per-residue scores when online access is on"

    def run(self, argument: str) -> Finding:
        from spica import structure

        record, problem = self.resolved(argument.strip())
        if problem:
            return problem
        gene = record.resolution.symbol
        accession = record.resolution.uniprot_accession
        if not accession:
            return Finding("", problem=f"{gene} has no UniProt accession: no protein to describe")
        mirror, live = self.mirror_and_live()
        profile = structure.profile(accession, live, mirror)
        if profile.get("error"):
            return Finding("", problem=profile["error"])
        length = profile["length"]
        lines = [f"[structure:{gene}] {gene} ({accession}), {length} residues"]
        pdb = profile.get("pdb") or []
        if pdb:
            covered = set()
            for entry in pdb:
                for a, b in entry["ranges"]:
                    covered.update(range(a, b + 1))
            best = min((e["resolution"] for e in pdb if e["resolution"]), default=None)
            lines.append(f"  PDB: {len(pdb)} entries, {100 * len(covered) / length:.1f}% of the "
                         f"sequence covered" + (f", best resolution {best} A" if best else ""))
            for entry in sorted(pdb, key=lambda e: (e["resolution"] or 99, e["id"])):
                ranges = ", ".join(f"{a}-{b}" for a, b in entry["ranges"])
                resolution = f"{entry['resolution']} A" if entry["resolution"] else "no resolution"
                lines.append(f"    {entry['id']} {entry['method']} {resolution}: {ranges}")
        else:
            lines.append("  PDB: no experimental structure")
        plddt = profile.get("plddt") or []
        if plddt:
            mean = sum(v for _, v in plddt) / len(plddt)
            low = _stretches(plddt, lambda v: v < 50)
            lines.append(f"  AlphaFold (model v{profile.get('model_version')}): mean pLDDT "
                         f"{mean:.1f}; low-confidence stretches (pLDDT under 50, 5+ residues): "
                         + (", ".join(f"{a}-{b}" for a, b in low) or "none"))
        missense = profile.get("missense") or []
        if missense:
            mean = sum(v for _, v in missense) / len(missense)
            hot = _stretches(missense, lambda v: v >= 0.564)
            lines.append(f"  AlphaMissense: mean pathogenicity {mean:.3f}; intolerant stretches "
                         "(mean 0.564 or more, the likely-pathogenic cut-off, 5+ residues): "
                         + (", ".join(f"{a}-{b}" for a, b in hot) or "none"))
        for note in profile.get("notes") or []:
            lines.append(f"  note: {note}")
        return Finding("\n".join(lines), citations=[f"structure:{gene}"],
                       raw=f"structure of {accession}")


# -- transcripts by tissue ---------------------------------------------------------------


class Isoforms(_Base):
    key = "isoforms"
    label = "Isoforms by tissue"
    usage = 'isoforms("<gene>") -> every GTEx transcript, and which one leads in each tissue'

    def status(self) -> str:
        return "GTEx transcript expression; needs online access or an earlier fetch"

    def run(self, argument: str) -> Finding:
        from spica import isoforms

        record, problem = self.resolved(argument.strip())
        if problem:
            return problem
        gene = record.resolution.symbol
        mirror, live = self.mirror_and_live()
        table = isoforms.table(gene, record.resolution.ensembl_gene_id, live, mirror)
        if table.get("error"):
            return Finding("", problem=table["error"])
        lines = [f"[isoforms:{gene}] {len(table['transcripts'])} transcripts, "
                 f"{table['dataset']} ({table['unit']})"]
        for t in table["transcripts"]:
            lines.append(f"  {t['name']} ({t['id']}, {t['biotype']}"
                         f"{', canonical' if t.get('canonical') else ''}): expressed in "
                         f"{t['expressed_in']} tissues, total {t['total']}")
        names = {t["id"]: t["name"] for t in table["transcripts"]}
        lines.append("  leading transcript per tissue:")
        for tissue, lead in table["dominant"].items():
            lines.append(f"    {tissue}: {names.get(lead['transcript'], lead['transcript'])} "
                         f"{lead['share']}%")
        return Finding("\n".join(lines), citations=[f"isoforms:{gene}"],
                       raw=f"isoforms of {gene}")


# -- genes that move with this one -------------------------------------------------------


class Coexpressed(_Base):
    key = "coexpressed"
    label = "Co-expressed genes"
    usage = ('coexpressed("<gene> [51-100]") -> genes whose GTEx profile moves with this one, '
             'by Pearson r')

    def status(self) -> str:
        return "correlation across GTEx's 54 sites, from the local mirror"

    def run(self, argument: str) -> Finding:
        from spica import coexpression

        parts = _split(argument)
        record, problem = self.resolved(parts[0] if parts else "")
        if problem:
            return problem
        gene = record.resolution.symbol
        mirror, _ = self.mirror_and_live()
        found = coexpression.correlated(gene, record.resolution.ensembl_gene_id, mirror)
        if found.get("error"):
            return Finding("", problem=found["error"])
        shown, note = _page(found["genes"], " ".join(parts[1:]), f'coexpressed("{gene}')
        lines = [f"[coexpressed:{gene}] {found['method']}, {found['source']}, "
                 f"{found['tissues']} tissues; {found['left_out']} genes too low to correlate; "
                 f"genes {note}:"]
        lines += [f"  {g['symbol']} r={g['r']}" for g in shown]
        return Finding("\n".join(lines), citations=[f"coexpressed:{gene}"],
                       raw=f"co-expression for {gene}: {note}")


# -- disease against genetics -------------------------------------------------------------


class Genetics(_Base):
    key = "genetics"
    label = "Disease against genetics"
    usage = ('genetics("<gene> [51-100]") -> each disease\'s Open Targets association beside '
             'the ClinVar variants for it in the gene and its strongest GWAS association')

    def status(self) -> str:
        return ("Open Targets, ClinVar and the GWAS Catalog joined on disease identifiers, "
                "from the local data")

    def run(self, argument: str) -> Finding:
        from spica import genetics

        parts = _split(argument)
        record, problem = self.resolved(parts[0] if parts else "")
        if problem:
            return problem
        gene = record.resolution.symbol
        mirror, _ = self.mirror_and_live()
        found = genetics.evidence(gene, record.resolution.ensembl_gene_id, mirror)
        if found.get("error"):
            return Finding("", problem=found["error"])
        summary = found["summary"]
        shown, note = _page(found["rows"], " ".join(parts[1:]), f'genetics("{gene}')
        gwas = found.get("gwas")
        lines = [f"[genetics:{gene}] {found['sources']}: {summary['associations']} associated "
                 f"diseases, {summary['with_pathogenic']} with pathogenic or likely pathogenic "
                 f"variants in {gene}"
                 + (f", {summary['with_gwas']} with GWAS associations" if gwas else "")
                 + f"; diseases {note} (score; pathogenic of all records"
                 + ("; strongest GWAS -log10 p, 7.3 genome-wide" if gwas else "") + "):"]
        for row in shown:
            genetic = (f"{row['pathogenic']} of {row['records']} ClinVar records"
                       if row["records"] else "no ClinVar condition")
            if gwas:
                genetic += (f"; GWAS {row['gwas']:.1f} ({', '.join(row['gwas_traits'])})"
                            if row["gwas"] else "; no GWAS trait")
            lines.append(f"  {row['disease']}: {row['score']}; {genetic}")
        if found["clinvar_only"]:
            lines.append(f"  ClinVar conditions matching no associated disease "
                         f"({len(found['clinvar_only'])}):")
            for condition in found["clinvar_only"]:
                lines.append(f"    {condition['condition']}: {condition['pathogenic']} of "
                             f"{condition['records']} records pathogenic")
        if found.get("gwas_only"):
            lines.append(f"  GWAS traits matching no associated disease "
                         f"({len(found['gwas_only'])}), -log10 p:")
            for trait in found["gwas_only"]:
                lines.append(f"    {trait['trait']}: {trait['mlog10p']:.1f}, {trait['relation']}, "
                             f"{trait['variant']}")
        return Finding("\n".join(lines), citations=[f"genetics:{gene}"],
                       raw=f"disease genetics for {gene}")


# -- interaction partners --------------------------------------------------------------------


SIGNS = {"stimulates": "stimulates", "inhibits": "inhibits",
         "both": "stimulates and inhibits", "unsigned": "acts on"}


def _links(links: list[dict]) -> str:
    def one(link: dict) -> str:
        if link["direction"] == "none":
            return f"{link['from']} with {link['to']}, undirected"
        return f"{link['from']} {SIGNS[link['sign']]} {link['to']}"
    return "; ".join(one(link) for link in links)


class Interactions(_Base):
    key = "interactions"
    label = "Interaction partners"
    usage = ('interactions("<gene> [51-100]") -> its partners in HPA\'s experiments, STRING\'s '
             'physical network and OmniPath\'s curation, with the datasets, scores and papers')

    def status(self) -> str:
        return ("HPA's consensus network, STRING's physical network and OmniPath's curated one, "
                "joined on identifiers, from the local data")

    def run(self, argument: str) -> Finding:
        from spica import interactions

        parts = _split(argument)
        record, problem = self.resolved(parts[0] if parts else "")
        if problem:
            return problem
        gene = record.resolution.symbol
        mirror, _ = self.mirror_and_live()
        found = interactions.compare(gene, record.resolution.ensembl_gene_id, mirror)
        if found.get("error"):
            return Finding("", problem=found["error"])
        s = found["summary"]
        shown, note = _page(found["partners"], " ".join(parts[1:]), f'interactions("{gene}')
        sizes = ", ".join(f"{s[n]} in {n.replace('hpa', 'HPA').replace('omnipath', 'OmniPath').replace('string', 'STRING')}"
                          for n in s["networks"])
        combos = "; ".join(f"{'+'.join(c['networks'])}: {c['count']}" for c in s["combinations"])
        lines = [f"[interactions:{gene}] {found['sources']}: {s['union']} partners ({sizes}); "
                 f"by combination of networks, {combos}; partners {note}:"]
        for row in shown:
            hpa = f"HPA {'+'.join(row['hpa'])}" if row["hpa"] else "not in HPA"
            if "string" in s["networks"]:
                score = row["string"]
                hpa += (f"; STRING {score['score']:.3f}"
                        + ("" if score["medium"] else " (below medium confidence)")
                        if score else "; not in STRING")
            curated = row["omnipath"]
            if curated:
                papers = curated["references"]
                omni = (f"OmniPath {papers} paper{'' if papers == 1 else 's'}, "
                        f"{_links(curated['links'])}")
                if not curated["direct"]:
                    omni += ", only through a complex"
            else:
                omni = "not in OmniPath"
            lines.append(f"  {row['symbol']}: {hpa}; {omni}")
        return Finding("\n".join(lines), citations=[f"interactions:{gene}"],
                       raw=f"interaction partners for {gene}")


# -- regulators ------------------------------------------------------------------------------


class Regulators(_Base):
    key = "regulators"
    label = "Regulators"
    usage = ('regulators("<gene>, <gene>, ...") -> transcription factors regulating each gene '
             '(OmniPath, commercial records), and those they share')

    def status(self) -> str:
        return "OmniPath, from the local data when it holds it; else online access or an earlier fetch"

    def run(self, argument: str) -> Finding:
        from spica import regulators

        symbols = _symbols(argument)
        if not symbols:
            return Finding("", problem="regulators() needs at least one gene symbol")
        mirror, live = self.mirror_and_live()
        if len(symbols) == 1:
            one = regulators.single(symbols[0], live, mirror)
            if one.get("state") != "ok":
                return Finding("", problem=one.get("error") or "OmniPath could not be read")
            gene = one["gene"]
            lines = [f"[regulators:{gene}] {one['source']}",
                     f"  regulated by ({len(one['regulators'])}): "
                     + (", ".join(f"{tf} {e}" for tf, e in one["regulators"].items()) or "none recorded")]
            if one["targets"]:
                lines.append(f"  as a transcription factor, regulates ({len(one['targets'])}): "
                             + ", ".join(f"{t} {e}" for t, e in one["targets"].items()))
            return Finding("\n".join(lines), citations=[f"regulators:{gene}"],
                           raw=f"regulators of {gene}")
        found = regulators.compare(symbols, live, mirror)
        if found.get("state") != "ok":
            return Finding("", problem=found.get("reason") or "OmniPath could not be read")
        key = ",".join(found["genes"])
        lines = [f"[regulators:{key}] {found.get('source', 'OmniPath')}"]
        for gene, regs in found["regulators"].items():
            lines.append(f"  {gene} ({len(regs)}): {', '.join(regs)}")
        if len(found["genes"]) > 1:
            shared = found.get("shared") or []
            lines.append(f"  shared regulators ({len(shared)}):")
            for entry in shared:
                effects = ", ".join(f"{g} {e}" for g, e in entry.get("genes", {}).items())
                lines.append(f"    {entry['tf']} ({entry.get('targets', '?')} targets in all): "
                             f"{effects}")
        for link in found.get("links") or []:
            lines.append(f"  direct link: {link['source']} {link['effect']} {link['target']} "
                         f"({link.get('type', '')}, {link.get('references', 0)} references)")
        return Finding("\n".join(lines), citations=[f"regulators:{key}"],
                       raw=f"regulators of {key}")


class Promoter(_Base):
    key = "promoter"
    label = "Transcription factors at the promoter"
    usage = ('promoter("<gene>") -> its regulators, the JASPAR motif sites of each in the promoter '
             '(2,000 bases upstream to 500 in, p < 1e-4) and whether its own ChIP-seq peak covers them')

    def status(self) -> str:
        return "OmniPath, JASPAR 2024 and ENCODE; needs online access or an earlier fetch"

    def run(self, argument: str) -> Finding:
        from spica import tfscan

        parts = _split(argument)
        record, problem = self.resolved(parts[0] if parts else "")
        if problem:
            return problem
        gene = record.resolution.symbol
        mirror, live = self.mirror_and_live()
        found = tfscan.analyse(gene, record.resolution.ensembl_gene_id, live, mirror)
        if found.get("state") != "ok":
            return Finding("", problem=found.get("error") or "the promoter could not be scanned")
        s = found["summary"]
        lines = [f"[promoter:{gene}] {found['sources']['regulators']}; {found['sources']['motifs']}; "
                 f"{found['sources']['binding']}. TSS {found['chrom']}:{found['tss'] + 1} "
                 f"({found['tss_from']}), sites at p < {found['p_value']:g}.",
                 f"  {s['regulators']} regulators, {s['with_motif']} with a JASPAR motif, "
                 f"{s['with_sites']} with a site here ({s['sites']} sites), {s['supported']} with a "
                 f"site inside their own ChIP-seq peak ({s['supported_sites']} sites); "
                 f"{s['assayed']} assayed by ENCODE, {s['bound_here']} bound here."]
        for row in found["regulators"]:
            motif = row["motif"]
            chip = row["chip"]
            assayed = ("not checked" if chip["assayed"] is None else
                       f"{chip['experiments']} ENCODE experiments" if chip["assayed"] else "not assayed by ENCODE")
            sites = "; ".join(f"{h['offset']:+d} {h['site']} p {h['p']:g}"
                              f"{' in own peak' if h['in_peak'] else ''}" for h in row["hits"])
            lines.append(f"  {row['tf']} {row['effect']}"
                         f"{', DoRothEA ' + row['level'] if row['level'] else ''}, {row['references']} papers; "
                         + (f"motif {motif['id']} {motif['consensus']}: {len(row['hits'])} sites"
                            f"{' (' + sites + ')' if sites else ''}" if motif else row["motif_note"])
                         + f"; ChIP-seq {assayed}, {len(chip['peaks'])} peaks here")
        return Finding("\n".join(lines), citations=[f"promoter:{gene}"], raw=f"promoter scan of {gene}")


# -- the genome view ----------------------------------------------------------------------------


class Genome(_Base):
    key = "genome"
    label = "Genome view"
    usage = ('genome("<gene> [track ids | atlas dnase|h3k27ac|gtex_coverage | encode <organ> '
             '<assay>]") -> the locus and what the genome view holds over it')

    #: Tracks read by default: the ones the view opens with.
    DEFAULT = ("genes", "ccre", "clinvar", "cpg")

    def status(self) -> str:
        from spica.genome import tracks

        return (f"{len(tracks.CATALOG)} tracks (UCSC, ENCODE, Ensembl); needs online access "
                "or an earlier fetch")

    def run(self, argument: str) -> Finding:
        from spica.genome import locus as genome_locus, tracks

        parts = _split(argument)
        record, problem = self.resolved(parts[0] if parts else "")
        if problem:
            return problem
        gene = record.resolution.symbol
        mirror, live = self.mirror_and_live()
        try:
            locus = genome_locus.find(gene, record.resolution.ensembl_gene_id, live, mirror)
        except Exception as exc:
            return Finding("", problem=f"locus not found: {exc}")
        if len(parts) > 1 and parts[1] == "atlas":
            return self._atlas(gene, locus, live, parts[2] if len(parts) > 2 else "dnase")
        if len(parts) > 1 and parts[1] == "encode":
            return self._encode(gene, live, parts[2:])
        known = {track.id: track for track in tracks.CATALOG}
        wanted = [p for p in parts[1:] if p in known] or [t for t in self.DEFAULT if t in known]
        info = locus.to_dict()
        lines = [f"[genome:{gene}] {gene} {info['chrom']}:{info['start']}-{info['end']} "
                 f"({info['strand']}), {info['assembly']}; window "
                 f"{info['window']['start']}-{info['window']['end']}"]
        for track_id in wanted:
            loaded = tracks.load(track_id, locus, live)
            if loaded.get("state") != "ok":
                lines.append(f"  {known[track_id].label}: {loaded.get('reason', 'not read')}")
                continue
            names = sorted({str(f.get("name", "")) for f in loaded.get("features", [])
                            if f.get("name")})
            sample = f": {', '.join(names[:40])}" + (f" and {len(names) - 40} more"
                                                     if len(names) > 40 else "")
            lines.append(f"  {known[track_id].label}: {loaded.get('count', 0)} features in the "
                         f"window{sample if names else ''}")
        lines.append("  other tracks: " + ", ".join(t for t in known if t not in wanted))
        lines.append('  also: genome("<gene> atlas dnase|h3k27ac|gtex_coverage"), '
                     'genome("<gene> encode <organ> <assay>")')
        return Finding("\n".join(lines), citations=[f"genome:{gene}"], raw=f"genome of {gene}")

    @staticmethod
    def _atlas(gene: str, locus, live, family: str) -> Finding:
        """One assay across every tissue over the locus: the regulation atlas,
        each tissue's peak over the gene body and over the whole window."""
        from spica.genome import atlas

        found = atlas.atlas(family, locus, live)
        if found.get("error") or not found.get("rows"):
            return Finding("", problem=found.get("error") or f"no {family} atlas for {gene}")
        span = (found["end"] - found["start"]) / found["bins"]
        body = [at for at in range(found["bins"])
                if found["gene"]["start"] <= found["start"] + (at + 0.5) * span <= found["gene"]["end"]]
        rows = []
        for row in found["rows"]:
            values = [v or 0 for v in row["values"]]
            peak_at = max(range(len(values)), key=lambda at: values[at])
            rows.append((max((values[at] for at in body), default=0), max(values),
                         int(found["start"] + (peak_at + 0.5) * span), row["tissue"]))
        rows.sort(key=lambda r: (-r[0], r[3]))
        key = f"genome:{gene}:{family}"
        lines = [f"[{key}] {found['label']} ({found['unit']}) over {found['chrom']}:"
                 f"{found['start']}-{found['end']}, {len(rows)} tissues; the gene body is "
                 f"{found['gene']['start']}-{found['gene']['end']}. Per tissue: peak over the "
                 "gene body, peak over the window and where:"]
        lines += [f"  {tissue}: {body_peak:.2f}; {window_peak:.2f} at {where}"
                  for body_peak, window_peak, where, tissue in rows]
        if found.get("failed"):
            lines.append(f"  could not be read: {', '.join(map(str, found['failed']))}")
        return Finding("\n".join(lines), citations=[key], raw=f"{family} atlas for {gene}")

    @staticmethod
    def _encode(gene: str, live, words: list[str]) -> Finding:
        """ENCODE experiments of one assay in one organ."""
        from spica.genome import encode

        assay = next((w for w in words if w in encode.ASSAYS), "")
        organ = " ".join(w for w in words if w not in encode.ASSAYS)
        if not assay or organ not in encode.ORGANS:
            return Finding("", problem=(f"genome(\"{gene} encode <organ> <assay>\") needs an "
                                        f"assay ({', '.join(encode.ASSAYS)}) and an organ "
                                        f"({', '.join(encode.ORGANS)})"))
        found = encode.by_organ(live, organ, assay, True)
        if found.get("state") != "ok":
            return Finding("", problem=found.get("reason") or "ENCODE could not be read")
        key = f"genome:encode:{organ}:{assay}"
        items = found.get("items") or []
        lines = [f"[{key}] ENCODE {encode.ASSAYS[assay]['label']} in {organ}, adult: "
                 f"{len(items)} experiments"]
        for item in items:
            lines.append("  " + ", ".join(f"{k} {v}" for k, v in item.items()
                                          if k in ("accession", "biosample", "label", "lab",
                                                   "date", "replicates") and v))
        return Finding("\n".join(lines), citations=[key], raw=f"ENCODE {assay} in {organ}")


# -- competitive intelligence ------------------------------------------------------------------------


class Intel(_Base):
    key = "intel"
    label = "Papers, patents and trials"
    usage = ('intel("<topic>; trials 121-240") -> the latest check of a watched topic: papers, '
             'preprints, patents and clinical trials, what is new; a kind and a range pages one list')

    def status(self) -> str:
        from spica.intel.watch import Watches

        mirror, live = self.mirror_and_live()
        watches = Watches(mirror.root).list()
        new = "new checks need online access" if not live.allowed else "can check new topics"
        return f"{len(watches)} watched topics kept on this computer; {new}"

    def run(self, argument: str) -> Finding:
        from spica.intel import run_watch
        from spica.intel.patents import Credentials
        from spica.intel.terms import gene_lookup
        from spica.intel.watch import Watches, slug

        topic, _, paging = argument.partition(";")
        topic = topic.strip()
        wanted, _, spec = paging.strip().partition(" ")
        if not topic:
            return Finding("", problem="intel() needs a topic: a target, a modality, any terms")
        mirror, live = self.mirror_and_live()
        watches = Watches(mirror.root)
        found = watches.latest(slug(topic))
        if found is None:
            if not live.allowed:
                known = ", ".join(w["topic"] for w in watches.list()) or "none"
                return Finding("", problem=(f"no check of {topic!r} is kept, and online access is "
                                            f"off. Watched topics: {known}"))
            from spica import settings

            chosen = settings.load()
            found = run_watch(topic, live, watches,
                              Credentials(chosen["epo_key"], chosen["epo_secret"]),
                              lookup=gene_lookup(mirror, live))
            if found.get("error"):
                return Finding("", problem=found["error"])
        key = slug(topic)
        lines = [f"[intel:{key}] {found.get('topic', topic)}, checked {found.get('at', '')}"]
        for kind in ("papers", "patents", "trials"):
            if wanted and kind != wanted.lower():
                continue
            block = found.get(kind) or {}
            items = block.get("items") or []
            if not block:
                continue  # a check made before this source was asked
            if block.get("state") not in (None, "ok"):
                lines.append(f"  {kind}: {block.get('state')}: {block.get('reason', '')}")
                continue
            new = sum(1 for item in items if item.get("new"))
            shown, note = _page(items, spec if wanted else "", f'intel("{topic}; {kind}')
            lines.append(f"  {kind}: {block.get('total', len(items))} found, {new} new since the "
                         f"last check; newest first, {note}:"
                         + (f" ({block['credit']})" if block.get("credit") else ""))
            for item in shown:
                when = item.get("date", "")
                if kind == "trials":
                    who = f"{item.get('nct')}, {item.get('phase')}, {item.get('status')}, {item.get('sponsor')}"
                else:
                    who = item.get("venue") or ", ".join(item.get("applicants") or [])
                lines.append(f"    {when} {item.get('title', '')} ({who})"
                             f"{' NEW' if item.get('new') else ''} {item.get('link') or item.get('url', '')}")
        return Finding("\n".join(lines), citations=[f"intel:{key}"], raw=f"intel on {topic}")


# -- candidates: gene lists, the ranked table, the benchmark ------------------------------------


def _options(argument: str) -> tuple[str, dict[str, str]]:
    """'A, B, C; preset antibody; for lung cancer; missing zero' -> the first
    part, and the options after it."""
    parts = [part.strip() for part in argument.split(";")]
    options = {}
    for part in parts[1:]:
        word, _, rest = part.partition(" ")
        if word.lower() in ("preset", "for", "missing") and rest.strip():
            options[word.lower()] = rest.strip()
    return parts[0] if parts else "", options


class GeneList(_Base):
    key = "genelist"
    label = "Gene lists"
    usage = ('genelist("A, B, C") -> how each entry maps to a gene (exact, alias, renamed, '
             'ambiguous, not found, duplicate); genelist("saved") -> the saved lists; '
             'genelist("<list name>") -> one saved list\'s genes')

    def status(self) -> str:
        return "HGNC mapping, and the lists saved in Candidates"

    def run(self, argument: str) -> Finding:
        from spica import genelist

        text = argument.strip()
        if not text or text.lower() == "saved":
            lists = genelist.saved()
            if not lists:
                return Finding("[genelist:saved] No list has been saved yet.",
                               citations=["genelist:saved"], raw="saved lists")
            lines = ["[genelist:saved] Saved lists, newest first:"]
            lines += [f"  {item['name']}: {item['genes']} genes, updated {item['updated']}"
                      + (f", preset {item['preset']}" if item["preset"] else "") for item in lists]
            return Finding("\n".join(lines), citations=["genelist:saved"], raw="saved lists")
        found = genelist.load(text)
        if found:
            genes = ", ".join(g["symbol"] for g in found["genes"])
            return Finding(f"[genelist:{found['name']}] {len(found['genes'])} genes, confirmed "
                           f"{found['updated']}: {genes}", citations=[f"genelist:{found['name']}"],
                           raw=f"list {found['name']}")
        mapped = genelist.map_entries(genelist.parse(text))
        lines = [f"[genelist:mapping] {mapped['message']}"]
        for row in mapped["rows"]:
            target = row["symbol"] or ", ".join(c["symbol"] for c in row["candidates"]) or "nothing"
            lines.append(f"  {row['input']}: {row['status'].replace('_', ' ')}, {target}"
                         + (f" ({row['note']})" if row["note"] else ""))
        return Finding("\n".join(lines), citations=["genelist:mapping"], raw="list mapping")


class Candidates(_Base):
    key = "candidates"
    label = "Ranked candidates"
    usage = ('candidates("A, B, C; preset antibody; for lung cancer") or '
             'candidates("<list name>") -> the ranked table: each gene\'s score and each '
             'weighted criterion\'s score and value; candidates("criteria") -> the criteria '
             'and presets [51-100 after the genes pages the table]')

    def status(self) -> str:
        return "the ranked table, on weights the user or a preset sets, from the local data"

    def run(self, argument: str) -> Finding:
        from spica import genelist, ranking

        head, options = _options(argument)
        page = ""
        found_page = re.search(r"\s(\d+-\d+|from \d+)$", head)
        if found_page:
            page, head = found_page.group(1), head[:found_page.start()].strip()
        if head.lower() == "criteria":
            lines = ["[candidates:criteria] Criteria, each scored 0 to 1 from the record; weights 0 to 10:"]
            lines += [f"  {c.key} ({c.label}, {c.group}): {c.describe}"
                      + (f" Carries the benchmark label for {', '.join(c.leaks)}." if c.leaks else "")
                      for c in ranking.CRITERIA]
            for key, preset in ranking.presets().items():
                weighed = ", ".join(f"{k} {v:g}" for k, v in preset["weights"].items() if v)
                lines.append(f"  preset {key} ({preset['label']}): {weighed}")
            return Finding("\n".join(lines), citations=["candidates:criteria"], raw="criteria")
        saved = genelist.load(head)
        if saved:
            queries = [g["hgnc_id"] for g in saved["genes"]]
            weights = {k: float(v) for k, v in (saved.get("weights") or {}).items()} or \
                ranking.weights_for(saved.get("preset") or "antibody")
            indication = saved.get("indication", "")
            name = saved["name"]
        else:
            queries = _symbols(head)
            weights, indication, name = ranking.weights_for("antibody"), "", ", ".join(queries)
        if "preset" in options:
            if options["preset"] not in ranking.PRESETS:
                return Finding("", problem=f"No preset {options['preset']}: "
                                           f"{', '.join(ranking.PRESETS)}")
            weights = ranking.weights_for(options["preset"])
        indication = options.get("for", indication)
        if not queries:
            return Finding("", problem="candidates() needs genes or a saved list's name")
        mirror, live = self.mirror_and_live()
        records = [self.record(query) for query in queries]
        ranked = ranking.rank(records, weights, indication,
                              "zero" if options.get("missing") == "zero" else "skip", mirror)
        used = [c for c in ranking.CRITERIA if weights.get(c.key)]
        shown, note = _page(ranked["rows"], page, f'candidates("{head}')
        lines = [f"[candidates:{name}] {ranked['summary']}; weights "
                 + ", ".join(f"{c.key} {weights[c.key]:g}" for c in used) + f"; rows {note}:"]
        for row in shown:
            parts = "; ".join(
                f"{c.key} {row['parts'][c.key]['score']:.2f} ({row['parts'][c.key]['value']})"
                if row["parts"][c.key]["score"] is not None
                else f"{c.key} no data ({row['parts'][c.key]['value']})" for c in used)
            score = f"{row['score']:.3f}" if row["score"] is not None else "no data"
            lines.append(f"  {row['rank']}. {row['symbol']} {score}, data "
                         f"{round(100 * (row['coverage'] or 0))}%: {parts}")
        unresolved = [r.query for r in records if not r.resolution.resolved]
        if unresolved:
            lines.append(f"  not matched to a gene: {', '.join(unresolved)}")
        return Finding("\n".join(lines), citations=[f"candidates:{name}"], raw=f"ranking {name}")


class Benchmark(_Base):
    key = "benchmark"
    label = "Benchmark"
    usage = ('benchmark("antibody" or "small_molecule") -> the newest benchmark kept: how well '
             'the weights put known targets above decoys, and each criterion alone')

    def status(self) -> str:
        return "the benchmark results kept on this computer; a new run starts in Candidates"

    def run(self, argument: str) -> Finding:
        from spica import benchmark

        modality = argument.strip().lower().replace(" ", "_").replace("-", "_")
        found = benchmark.latest(modality if modality in benchmark.MODALITIES else "")
        if not found:
            return Finding("", problem=f"no benchmark run{' for ' + modality if modality else ''}; "
                                       "runs from the Candidates screen")
        top = found["top"]
        lines = [f"[benchmark:{found['modality']}] {found['when']}: {found['sets']} "
                 f"{found['positives']} positives, {found['decoys']} decoys. AUC {found['auc']} "
                 f"(0.5 is chance); the top {top['size']} hold {top['positives']} positives. "
                 f"Data coverage: positives {found['coverage']['positives']}, decoys "
                 f"{found['coverage']['decoys']}."
                 + (f" Left out as carrying the label: {', '.join(found['dropped'])}."
                    if found["dropped"] else "")]
        lines.append("  each criterion alone (AUC; weight in the run):")
        for c in sorted(found["criteria"], key=lambda c: -(c["auc"] or 0)):
            if c["auc"] is not None:
                lines.append(f"    {c['key']}: {c['auc']}, weight {c['weight']:g}"
                             + (" (carries the label)" if c["leaks"] else ""))
        return Finding("\n".join(lines), citations=[f"benchmark:{found['modality']}"],
                       raw=f"benchmark {found['modality']}")


# -- the digest: podcasts, trials and papers, searched --------------------------------------


class Datasets(_Base):
    key = "datasets"
    label = "GEO datasets"
    usage = ('datasets("<terms or GSE accession>; gene <symbol>; samples 41-80") -> GEO series for '
             'the terms (a gene\'s other names included), or one series: its samples in context, '
             'the files that can be drawn on a locus, and the gene\'s values in its table. '
             'datasets("<GSE>; de") lists its tables for differential expression; '
             'datasets("<GSE>; de <file>; contrast <fold column>") reads published results; '
             'datasets("<GSE>; de <file>; groups <variable>=<reference> vs <comparison>") runs DESeq2 '
             'on raw counts (about a minute)')

    def status(self) -> str:
        return "NCBI GEO through its public services; needs online access or an earlier fetch"

    def run(self, argument: str) -> Finding:
        from spica.geo import records, response, search
        from spica.intel.terms import gene_lookup

        head, *rest = [part.strip() for part in argument.split(";")]
        options = {part.split(" ", 1)[0].lower(): part.split(" ", 1)[1].strip()
                   for part in rest if " " in part}
        if not head:
            return Finding("", problem="datasets() needs terms or a GSE accession")
        mirror, live = self.mirror_and_live()
        if not records.ACCESSION.match(head.upper()):
            try:
                found = search.search(head, live, lookup=gene_lookup(mirror, live))
            except LiveError as exc:
                return Finding("", problem=f"GEO search failed: {exc}")
            if found.get("error"):
                return Finding("", problem=found["error"])
            lines = [f"[datasets:{head}] NCBI GEO, {found['total']} human series for "
                     f"{', '.join(found['terms'])}; the first {len(found['results'])}, best match first:"]
            for hit in found["results"]:
                lines.append(f"  {hit['accession']} ({hit['type']}, {hit['samples']} samples, {hit['date']}"
                             f"{', tracks' if hit['tracks'] else ''}): {hit['title']}")
            return Finding("\n".join(lines), citations=[f"datasets:{head}"], raw=f"GEO search for {head}")
        try:
            series = records.read(head, live)
        except (ValueError, NotFoundUpstream, LiveError) as exc:
            return Finding("", problem=f"GEO not read: {exc}")
        acc = series["accession"]
        shown, note = _page(series["samples"], options.get("samples", ""), f'datasets("{acc}; samples')
        lines = [f"[datasets:{acc}] {acc}: {series['title']}. {'; '.join(series['types'])}. "
                 f"{series['counts']['samples']} samples ({', '.join(series['organisms'])}), "
                 f"{series['counts']['tracks']} files drawable on a GRCh38 locus, "
                 f"{series['counts']['matrices']} tables. PubMed {', '.join(series['pubmed']) or 'none'}.",
                 f"  design: {series['design'] or series['summary'][:400]}"]
        for facet in series["facets"]:
            lines.append(f"  {facet['field']}: " + ", ".join(f"{v['value']} ({v['samples']})" for v in facet["values"]))
        lines.append(f"  samples, {note}:")
        for sample in shown:
            context = "; ".join(f"{k}: {v}" for k, v in sample["characteristics"].items())
            drawable = sum(1 for f in sample["files"] if f["track"])
            lines.append(f"    {sample['accession']} {sample['title']} ({sample['strategy']}; {context})"
                         f"{', ' + str(drawable) + ' tracks' if drawable else ''}")
        gene = options.get("gene", "")
        if gene:
            fields = gene_lookup(mirror, live)(gene) or {}
            symbol = str(fields.get("symbol") or gene)
            try:
                values = response.gene(series, symbol, str(fields.get("ensembl_gene_id") or ""), live)
            except LiveError as exc:
                values = {"state": "failed", "message": str(exc)}
            if values.get("state") != "ok":
                lines.append(f"  {symbol}: {values.get('message', 'not read')}")
            else:
                lines.append(f"  {symbol} in {values['file']} ({values['matched']} of {len(values['columns'])} "
                             f"columns matched to samples; the study's own processed values):")
                for group in values["groups"]:
                    lines.append(f"    by {group['field']}: " + ", ".join(
                        f"{g['value']} mean {g['mean']:g} (n={g['samples']})" for g in group["groups"]))
        flags = [part for part in rest if part.lower() == "de" or part.lower().startswith("de ")]
        if flags:
            lines += self._de(series, flags[0][2:].strip(), options, mirror, live)
        return Finding("\n".join(lines), citations=[f"datasets:{acc}"], raw=f"GEO series {acc}")

    @staticmethod
    def _de(series: dict, name: str, options: dict, mirror, live) -> list[str]:
        """Differential expression lines: the series' tables, or one table's result."""
        from spica.geo import de

        tables = de.tables(series)
        acc = series["accession"]
        if not tables:
            return ["  differential expression: no text or Excel table among the supplementary files"]
        if not name:
            out = [f'  differential expression tables (datasets("{acc}; de <file>") reads one):']
            for t in tables[:6]:
                try:
                    found = de.inspect(series, t["url"], live)
                except (de.DeError, LiveError) as exc:
                    out.append(f"    {t['name']}: not read ({exc})")
                    continue
                for tb in found["tables"]:
                    groups = sorted({k for c in tb["columns"] for k in c["context"]})
                    out.append(f"    {t['name']}{' sheet ' + tb['sheet'] if tb['sheet'] else ''}: {tb['kind']}; "
                               f"routes {', '.join(tb['routes']) or 'none'}"
                               + (f"; contrasts {', '.join(c['fold'] for c in tb['contrasts'])}" if tb["contrasts"] else "")
                               + (f"; group variables {', '.join(groups)}" if groups else "")
                               + (f"; count columns {', '.join(c['column'] for c in tb['columns'])}"
                                  if tb["columns"] and not groups else "")
                               + (f"; {tb['reason']}" if tb.get("reason") else ""))
            if len(tables) > 6:
                out.append(f"    and {len(tables) - 6} more tables")
            return out
        chosen = next((t for t in tables if t["name"] == name), None) or \
            next((t for t in tables if name.lower() in t["name"].lower()), None)
        if chosen is None:
            return [f"  no table {name} in {acc}"]
        sheet = options.get("sheet", "")
        try:
            if options.get("groups"):
                matched = re.match(r"(.+?)=(.+?)\s+vs\s+(.+)$", options["groups"])
                if not matched:
                    return ['  groups take the form "<variable>=<reference> vs <comparison>"']
                field, reference, comparison = (g.strip() for g in matched.groups())
                result = de.run(series, chosen["url"], sheet, live, mirror, "deseq2", "", field, reference,
                                comparison, options.get("covariate", ""))
            else:
                found = de.inspect(series, chosen["url"], live)
                table = next((t for t in found["tables"] if t["sheet"] == sheet),
                             found["tables"][0] if found["tables"] else None)
                if table is None or not table["contrasts"]:
                    return [f"  {chosen['name']}: no published results"
                            + (f"; {table['reason']}" if table and table.get("reason") else "")]
                contrast = options.get("contrast") or table["contrasts"][0]["fold"]
                result = de.run(series, chosen["url"], table["sheet"], live, mirror, "published", contrast)
        except (de.DeError, LiveError) as exc:
            return [f"  {chosen['name']}: {exc}"]
        points = result["points"]
        hits = [p for p in points if p[4] is not None and p[4] < 0.05 and abs(p[3]) >= 1]
        up = sorted((p for p in hits if p[3] > 0), key=lambda p: (p[4], -abs(p[3])))
        down = sorted((p for p in hits if p[3] < 0), key=lambda p: (p[4], -abs(p[3])))

        def fmt(p: list) -> str:
            return f"{p[0]} {p[3]:+g} ({p[4]:.2g})"

        return [f"  {chosen['name']}: {result['method']} {len(points):,} genes; {result['p_label']} < 0.05 "
                f"and fold change 2x or more: {len(up)} up, {len(down)} down.",
                "    up, strongest first: " + (", ".join(fmt(p) for p in up[:12]) or "none"),
                "    down, strongest first: " + (", ".join(fmt(p) for p in down[:12]) or "none")]


class DigestSearch(_Base):
    key = "digest"
    label = "Digest"
    usage = ('digest("query; gene ERBB2; kind podcast; since 2026-01-01; 26-50") -> passages from '
             'transcribed scientific podcasts, show notes, clinical trials and papers, best first, '
             'each with its source, date, time in the episode and link; digest("latest") -> what '
             'arrived most recently; kinds: podcast, notes, trial, paper')

    def status(self) -> str:
        return "podcasts transcribed on this computer, ClinicalTrials.gov and Europe PMC, as gathered"

    def run(self, argument: str) -> Finding:
        from spica.digest.service import Digest

        parts = [part.strip() for part in argument.split(";")]
        query, options, page = parts[0] if parts else "", {}, ""
        for part in parts[1:]:
            word, _, rest = part.partition(" ")
            if word.lower() in ("gene", "kind", "since") and rest.strip():
                options[word.lower()] = rest.strip()
            elif RANGE.match(part):
                page = part
        found = RANGE.match(page) if page else None
        start = int(found.group(1) or found.group(3)) if found else 1
        mirror, _ = self.mirror_and_live()
        digest = Digest(mirror=mirror)
        kinds = [k.strip() for k in options.get("kind", "").replace("+", ",").split(",") if k.strip()]
        if query.lower() in ("", "latest"):
            result = digest.latest(kinds, options.get("since", ""), limit=PAGE, offset=start - 1)
            heading = "most recent first"
        else:
            result = digest.search(query, kinds, options.get("gene", ""), options.get("since", ""),
                                   limit=PAGE, offset=start - 1)
            heading = (f"best first for {query!r}"
                       + (f", taken to name {', '.join(result['genes'])}" if result.get("genes") else ""))
            if result.get("genes") and not result.get("naming"):
                heading += (f"; none of them names {', '.join(result['genes'])}, they share words "
                            "with the query")
        rows = result["results"]
        if not rows:
            return Finding("", problem=f"no digest item for {query or 'that'}; the Digest screen fills it")
        end = start + len(rows) - 1
        note = f"{start}-{end} of {result['total']}"
        if end < result["total"]:
            note += f"; the next page is digest(\"{argument.split(';')[0]}; {end + 1}-{end + PAGE}\")"
        lines = [f"[digest] {result['total']} passages, {heading}; {note}:"]
        for row in rows:
            where = f", at {row['at']}" if row.get("at") else ""
            genes = f" [{', '.join(row['genes'])}]" if row.get("genes") else ""
            lines.append(f"  [digest:{row['id']}] {row['kind']}, {row['source']}, {row['date']}{where}: "
                         f"{row['title']}{genes}. \"{row['snippet']}\" ({row['link']})")
        return Finding("\n".join(lines), citations=[f"digest:{row['id']}" for row in rows],
                       raw=f"digest {query}")


#: Every view the app serves, and the tool that reaches the same data. The
#: parity test reads this: a view added to the app without a tool here
#: fails it. The methods left out are not data (settings, licence, the
#: mirror's upkeep, the agents themselves).
APP_VIEWS = {
    "build_report": "record",
    "build_comparison": "compare",
    "genome_locus": "genome",
    "genome_track": "genome",
    "genome_encode": "genome",
    "genome_regulators": "regulators",
    "tf_analysis": "promoter",
    "genome_atlas": "genome",
    "structure_profile": "structure",
    "isoform_table": "isoforms",
    "coexpressed": "coexpressed",
    "compare_regulators": "regulators",
    "disease_genetics": "genetics",
    "interaction_partners": "interactions",
    "candidates_criteria": "candidates",
    "digest_status": "digest",
    "digest_latest": "digest",
    "digest_search": "digest",
    "geo_search": "datasets",
    "geo_series": "datasets",
    "geo_gene": "datasets",
    "geo_de_inspect": "datasets",
    "geo_de_start": "datasets",
    "digest_transcript": "digest",
    "rank_start": "candidates",
    "genelist_map": "genelist",
    "genelists": "genelist",
    "genelist_open": "genelist",
    "benchmark_start": "benchmark",
    "benchmark_latest": "benchmark",
    "intel_status": "intel",
    "intel_watch": "intel",
    "intel_open": "intel",
}
NOT_VIEWS = {
    "licence_documents", "settings_status", "set_online",
    "set_theme", "export_report", "open_exported", "genelist_read_file", "genelist_save",
    "genelist_delete", "job_status", "export_ranked_start", "export_save", "exported_reports",
    "digest_set_feed", "digest_set_per_feed", "digest_add_feed", "digest_remove_feed",
    "digest_update_start", "speech_download_start", "digest_running", "job_stop", "set_thinking", "set_menu", "gene_locate",
    "mirror_status", "mirror_check", "mirror_update", "mirror_stop", "app_status",
    "intel_configure", "agents_status", "agents_ask", "agents_poll", "agents_cancel",
    "agents_rollback", "agents_resume",
}


def view_tools(builder=None) -> list:
    return [Field(builder), Organs(builder), Glance(builder), Where(builder), Structure(builder),
            Isoforms(builder), Coexpressed(builder), Genetics(builder), Interactions(builder),
            Regulators(builder), Promoter(builder),
            Genome(builder),
            Intel(builder), GeneList(builder), Candidates(builder), Benchmark(builder),
            DigestSearch(builder), Datasets(builder)]
