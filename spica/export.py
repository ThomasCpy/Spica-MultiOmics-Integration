"""The client report: one gene, or several, as one HTML file.

What most clients will see of Spica, so it follows the art direction
closely (`docs/art-direction.md`, "Voice and the client report"): the
app's palette and fonts on white, so it prints; a cover with the star, the
project, the date and every data version; then the record section by
section, each value beside its source and release, with a chart wherever
the data makes one. Every bar keeps its figure, so a grayscale print reads.

Deterministic, like the record: built from the record and the views
derived from it, with no model anywhere. The same genes against the same
releases give the same report, bar the date on the cover.

One file, nothing fetched: the fonts are embedded, the charts are HTML,
and a Content-Security-Policy keeps it that way wherever it is opened. The
only links go to each source's own page for the gene, for a reader who
wants to check a value. Long lists show their first rows and keep the rest
one click away: abbreviated, never cut.
"""

from __future__ import annotations

import base64
import html
from datetime import date
from pathlib import Path
from typing import Any, Callable

from spica.credits import CARRIED, CREDITS
from spica.record import GeneRecord, Value
from spica.schema import FIELDS, SCHEMA_VERSION, SECTIONS, FieldSpec

FONTS = Path(__file__).resolve().parent / "assets" / "fonts"

#: Rows a long list shows before "show the rest".
FIRST = 25

#: HPA's staining levels as bar lengths; the word stays beside each bar.
LEVELS = {"not detected": 0, "low": 1, "medium": 2, "high": 3}

#: HPA's consensus datasets as their owners write them.
DATASETS = {"intact": "IntAct", "biogrid": "BioGRID", "opencell": "OpenCell", "bioplex": "BioPlex",
            "consensus": "Consensus"}

#: Maps whose keys are an axis, drawn in key order as a histogram.
ORDERED_MAPS = {"depmap_effect_distribution"}

STATE_LABEL = {"not_found": "not found", "not_covered": "not covered", "failed": "failed"}

#: The view sources the record does not stamp, by the mirror key that holds them.
VIEW_SOURCES = ("omnipath", "string")

STAR = ("M11 6C10.3 11 6 15.3 1 16C6 16.7 10.3 21 11 26C11.7 21 14.6 16.9 18 16.55L31 16"
        "L18 15.45C14.6 15.1 11.7 11 11 6Z")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def number(value: Any) -> str:
    """A figure as the report prints it: grouped thousands, sensible places."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):,}"
    size = abs(value)
    if size >= 1000:
        return f"{value:,.0f}"
    if size >= 10:
        return f"{value:.1f}"
    if size >= 0.01:
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:.2g}"


def long_date(day: date) -> str:
    return f"{day.day} {day.strftime('%B')} {day.year}"


# -- building blocks ---------------------------------------------------------------------------


def _rest(items: list[str], noun: str, wrap: Callable[[str], str] = lambda inner: inner) -> str:
    """The first rows, and the others behind one click."""
    shown = "".join(items[:FIRST])
    if len(items) <= FIRST:
        return wrap(shown)
    more = len(items) - FIRST
    return (wrap(shown) + f'<details><summary>Show the other {more:,} {esc(noun)}</summary>'
            + wrap("".join(items[FIRST:])) + "</details>")


def bars(rows: list[tuple[str, float, str]], caption: str, note: str = "",
         noun: str = "rows", mono: bool = False, highlight: str = "") -> str:
    """A horizontal bar chart: label, bar, figure. Linear, from zero."""
    if not rows:
        return ""
    top = max((value for _, value, _ in rows), default=0) or 1
    items = []
    for label, value, shown in rows:
        width = max(0.0, min(100.0, 100 * value / top))
        strong = " strong" if highlight and label == highlight else ""
        items.append(
            f'<div class="bar{strong}"><span class="label{" mono" if mono else ""}">{esc(label)}</span>'
            f'<span class="track"><span class="fill" style="width:{width:.1f}%"></span></span>'
            f'<span class="num">{esc(shown)}</span></div>')
    head = f'<figcaption>{esc(caption)}'
    head += f' <span>{esc(note)}</span>' if note else ""
    head += "</figcaption>"
    return f'<figure class="chart">{head}' + _rest(items, noun, lambda inner: f'<div class="bars">{inner}</div>') + "</figure>"


def histogram(spec: FieldSpec, data: dict) -> str:
    """Counts over ordered bins: columns in key order, the peak count named,
    0 and -1 marked (DepMap's no effect and common essential median)."""
    bins = sorted(((float(key), int(count)) for key, count in data.items()), key=lambda b: b[0])
    top = max((count for _, count in bins), default=0) or 1
    columns = "".join(
        f'<span class="col{" mark" if edge in (0.0, -1.0) else ""}" title="{edge:.1f} to '
        f'{edge + 0.1:.1f}: {count} lines"><span style="height:{100 * count / top:.1f}%"></span></span>'
        for edge, count in bins)
    ticks = "".join(f'<span style="left:{100 * i / len(bins):.2f}%">{edge:g}</span>'
                    for i, (edge, _) in enumerate(bins) if abs(edge - round(edge)) < 1e-9)
    total = sum(count for _, count in bins)
    return (f'<figure class="chart"><figcaption>{esc(spec.label)} <span>{total:,} lines, '
            f'tallest bar {top:,}; dashed: 0 (no effect) and -1 (common essential median)</span>'
            f'</figcaption><div class="hist">{columns}</div><div class="ticks">{ticks}</div></figure>')


def table(head: list[str], rows: list[list[str]], noun: str = "rows", classes: str = "",
          whole: bool = False) -> str:
    """Cells are HTML already; a long table keeps its other rows behind a
    click, unless it is `whole`: the ranked table is what the reader came
    for, and prints every row."""
    top = "".join(f"<th>{cell}</th>" for cell in head)
    body = [f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows]

    def wrap(inner: str) -> str:
        return f'<table class="grid {classes}"><thead><tr>{top}</tr></thead><tbody>{inner}</tbody></table>'

    return wrap("".join(body)) if whole else _rest(body, noun, wrap)


def meter(value: float, top: float, shown: str) -> str:
    """A bar in a table cell, figure beside it."""
    width = max(0.0, min(100.0, 100 * value / top)) if top else 0.0
    return (f'<span class="meter"><span class="track"><span class="fill" style="width:{width:.1f}%">'
            f'</span></span><span class="num">{esc(shown)}</span></span>')


def missing(value: Value | None) -> str:
    if value is None:
        return '<span class="null">not built</span>'
    state = value.state.value if value.state else "not_found"
    reason = f' <span class="why">{esc(value.reason)}</span>' if value.reason else ""
    return f'<span class="null">{STATE_LABEL.get(state, state)}</span>{reason}'


# -- one field ---------------------------------------------------------------------------------


class Profile:
    """One gene's record and the views derived from it, as report sections."""

    def __init__(self, record: GeneRecord, views: dict[str, Any]) -> None:
        self.record = record
        self.views = views
        res = record.resolution
        self.symbol = res.symbol or record.query
        self.ids = {"symbol": self.symbol, "ensembl": res.ensembl_gene_id,
                    "accession": res.uniprot_accession, "hgnc": res.hgnc_id}

    def source(self, spec: FieldSpec, value: Value) -> str:
        if spec.derived:
            names = [field.label for field in FIELDS if field.name in spec.derived_from]
            return f'<span class="derived">Derived{": " + esc(", ".join(names)) if names else ""}</span>'
        provenance = value.provenance
        if provenance is None:
            return ""
        credit = CREDITS.get(spec.source)
        text = esc(f"{provenance.source} {provenance.version}".strip())
        if credit:
            return f'<a href="{esc(credit.link(**self.ids))}">{text}</a>'
        return text

    def value(self, spec: FieldSpec, value: Value) -> str:
        data = value.value
        unit = f" {esc(spec.unit)}" if spec.unit else ""
        mono = ' class="mono"' if spec.mono else ""
        if spec.type == "sequence" and isinstance(data, str):
            return (f'<span class="mono">{len(data):,} residues</span><details><summary>Show the '
                    f'sequence</summary><p class="sequence mono">{esc(data)}</p></details>')
        if spec.type == "text_list" and isinstance(data, list):
            items = [f"<li{mono}>{esc(item)}</li>" for item in data]
            return _rest(items, "entries", lambda inner: f'<ul class="list">{inner}</ul>')
        if spec.type in ("number_map", "text_map") and isinstance(data, dict):
            return self.map_summary(spec, data)
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return f'<span class="mono">{number(data)}</span>{unit}'
        return f"<span{mono}>{esc(data)}</span>{unit}"

    def map_summary(self, spec: FieldSpec, data: dict) -> str:
        if not data:
            return "none"
        if spec.type == "number_map":
            name, top = max(data.items(), key=lambda kv: kv[1])
            return (f'{len(data):,} entries; highest {esc(name)} '
                    f'<span class="mono">{number(top)}</span>{" " + esc(spec.unit) if spec.unit else ""}'
                    f'. Chart below.')
        return f"{len(data):,} entries. Chart below."

    def chart(self, spec: FieldSpec, value: Value) -> str:
        data = value.value
        if not isinstance(data, dict) or not data:
            return ""
        if spec.name in ORDERED_MAPS:
            return histogram(spec, data)
        if spec.type == "number_map":
            rows = sorted(((str(k), float(v), number(v)) for k, v in data.items()
                           if isinstance(v, (int, float))), key=lambda row: (-row[1], row[0]))
            peak = self.record.fields.get("gtex_max_tissue")
            return bars(rows, spec.label, f"{spec.unit}, {len(rows):,} entries" if spec.unit
                        else f"{len(rows):,} entries", noun="entries",
                        highlight=str(peak.value) if peak and peak.present else "")
        levels = {str(k): LEVELS.get(str(v).strip().lower()) for k, v in data.items()}
        if all(level is not None for level in levels.values()):
            rows = sorted(((k, float(levels[k]), str(data[k])) for k in data),
                          key=lambda row: (-row[1], row[0]))
            return bars(rows, spec.label, "staining level, not detected to high", noun="entries")
        items = [f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in data.items()]
        return _rest(items, "entries", lambda inner: f'<table class="grid">{inner}</table>')

    # -- sections ------------------------------------------------------------------------------

    def fields(self, section: str) -> str:
        rows, charts = [], []
        for spec in FIELDS:
            if spec.section != section:
                continue
            value = self.record.fields.get(spec.name)
            label = esc(spec.label)
            if spec.derived and spec.description:
                label += f'<span class="desc">{esc(spec.description)}</span>'
            if value is None or not value.present:
                rows.append(f'<tr><th>{label}</th><td colspan="2">{missing(value)}</td></tr>')
                continue
            rows.append(f'<tr><th>{label}</th><td>{self.value(spec, value)}</td>'
                        f'<td class="src">{self.source(spec, value)}</td></tr>')
            if spec.type in ("number_map", "text_map"):
                charts.append(self.chart(spec, value))
        body = f'<table class="fields"><tbody>{"".join(rows)}</tbody></table>'
        return body + "".join(charts)

    def summary(self) -> str:
        from spica.build import summarize

        parts = [f'<p class="lead">{esc(summarize(self.record))}</p>']
        glance = self.views.get("glance") or {}
        for key, title in (("function", "What it does"), ("disease", "What it is linked to")):
            words = (glance.get(key) or {}).get("words") or []
            rows = [(w["word"], float(w["weight"]), number(w["weight"])) for w in words]
            parts.append(bars(rows, f"At a glance: {title.lower()}",
                              "how often each word recurs across its "
                              + ("GO terms" if key == "function" else "disease associations"),
                              noun="words"))
        return "".join(parts)

    def organs(self) -> str:
        dogma = self.views.get("dogma")
        if not dogma or not dogma.get("rows"):
            return ""
        layers = dogma["layers"]
        tops = {layer["key"]: max((row["cells"][layer["key"]]["value"] for row in dogma["rows"]
                                   if layer["key"] in row["cells"]
                                   and isinstance(row["cells"][layer["key"]].get("value"), (int, float))),
                                  default=0) for layer in layers}
        head = ["Organ"] + [f'{esc(layer["label"])}<span class="unit">{esc(layer["unit"])}</span>'
                            for layer in layers]
        rows = []
        for row in dogma["rows"]:
            cells = [esc(row["organ"].capitalize())]
            for layer in layers:
                cell = row["cells"].get(layer["key"])
                if not cell:
                    cells.append('<span class="null">not measured</span>')
                elif isinstance(cell.get("value"), (int, float)) and layer.get("kind") == "number":
                    cells.append(meter(cell["value"], tops[layer["key"]], cell["display"]))
                else:
                    cells.append(esc(cell.get("display", "")))
            rows.append(cells)
        agreement = [pair for pair in dogma.get("agreement", []) if pair.get("rho") is not None]
        names = {layer["key"]: layer["label"] for layer in layers}
        pairs = "".join(
            f'<li>{esc(names.get(p["a"], p["a"]))} against {esc(names.get(p["b"], p["b"]))}: '
            f'<span class="mono">r = {p["rho"]:.2f}</span> over {p["n"]} organs</li>' for p in agreement)
        return (f'<h3>Expression by organ</h3><p class="note">{esc(dogma.get("summary", ""))} Each '
                f'source on its own scale; bars compare organs within a column, never across.</p>'
                + table(head, rows, noun="organs", classes="organs")
                + (f'<h4>Agreement between sources</h4><p class="note">Correlation of log-scaled '
                   f'values over the organs both measured.</p><ul class="plain">{pairs}</ul>'
                   if pairs else ""))

    def compartments(self) -> str:
        found = self.views.get("locations")
        if not found or not found.get("compartments"):
            return ""
        labels = {"uniprot": "UniProt", "hpa": "HPA", "go": "GO"}
        rows = []
        for row in found["compartments"]:
            terms = "; ".join(f"{labels.get(k, k)}: {', '.join(v)}" for k, v in row["sources"].items())
            rows.append([esc(row["name"]) + (' <span class="tag">main</span>' if row.get("main") else ""),
                         meter(row["count"], 3, f'{row["count"]} of 3'),
                         f'<span class="why">{esc(terms) or "none"}</span>'])
        return ('<h3>Where the protein sits</h3><p class="note">UniProt, HPA and GO placed on '
                'ten compartments; the bar counts how many of the three agree.</p>'
                + table(["Compartment", "Sources agreeing", "Terms"], rows, noun="compartments"))

    def interactions(self) -> str:
        found = self.views.get("interactions")
        if not found:
            return ""
        if found.get("error"):
            return f'<h3>Interaction partners</h3><p class="note">{esc(found["error"])}</p>'
        s = found["summary"]
        head = (f'<h3>Interaction partners</h3><p class="note">HPA\'s experiments, STRING\'s '
                f'physical network and OmniPath\'s curation, matched on identifiers; a partner only '
                f'STRING names counts from its medium confidence, 0.4. {esc(found["sources"])}.</p>')
        if not s["union"]:
            return head + "<p>Neither network records a partner.</p>"
        names = {"hpa": "HPA", "omnipath": "OmniPath", "string": "STRING"}
        overlap = bars([(" and ".join(names[n] for n in c["networks"])
                         + (" only" if len(c["networks"]) < len(s["networks"]) else ""),
                         c["count"], number(c["count"])) for c in s["combinations"]],
                       "Partners by the networks that name them", f"{s['union']:,} in all")
        with_string = "string" in s["networks"]
        top = max((row["omnipath"]["references"] for row in found["partners"] if row["omnipath"]),
                  default=1)
        signs = {"stimulates": "stimulates", "inhibits": "inhibits",
                 "both": "stimulates and inhibits", "unsigned": "acts on"}
        rows = []
        for row in found["partners"]:
            curated = row["omnipath"]
            effects = "; ".join(f'{link["from"]} with {link["to"]}, undirected' if link["direction"] == "none"
                                else f'{link["from"]} {signs[link["sign"]]} {link["to"]}'
                                for link in (curated or {}).get("links", []))
            string = row.get("string")
            rows.append([f'<span class="mono">{esc(row["symbol"])}</span>',
                         f'<span class="nowrap">{esc(", ".join(DATASETS.get(d, d) for d in row["hpa"]))}</span>'
                         if row["hpa"] else '<span class="null">not in HPA</span>']
                        + ([meter(string["score"], 1, f'{string["score"]:.3f}'
                                  + ("" if string["medium"] else " (low)"))
                            if string else '<span class="null">not in STRING</span>']
                           if with_string else [])
                        + [
                         meter(curated["references"], top, str(curated["references"])) if curated
                         else '<span class="null">not in OmniPath</span>',
                         f'<span class="why">{esc(effects)}</span>'])
        return head + overlap + table(["Partner", "HPA datasets"]
                                      + (["STRING score"] if with_string else [])
                                      + ["Papers (OmniPath)", "Effect (OmniPath)"],
                                      rows, noun="partners")

    def genetics(self) -> str:
        found = self.views.get("genetics")
        if not found:
            return ""
        if found.get("error"):
            return f'<h3>Disease against genetics</h3><p class="note">{esc(found["error"])}</p>'
        s = found["summary"]
        top_score = max((row["score"] for row in found["rows"]), default=1) or 1
        top_path = max((row["pathogenic"] for row in found["rows"]), default=1) or 1
        gwas = found.get("gwas")
        top_gwas = max([row.get("gwas", 0) for row in found["rows"]] + [1])
        rows = [[esc(row["disease"]), meter(row["score"], top_score, f'{row["score"]:.3f}'),
                 meter(row["pathogenic"], top_path, f'{row["pathogenic"]} of {row["records"]}')
                 if row["records"] else '<span class="null">no ClinVar condition</span>']
                + ([meter(row["gwas"], top_gwas, f'{row["gwas"]:.1f}') if row.get("gwas")
                    else '<span class="null">no GWAS trait</span>'] if gwas else [])
                for row in found["rows"]]
        out = (f'<h3>Disease against genetics</h3><p class="note">Open Targets\' association beside '
               f'ClinVar\'s pathogenic or likely pathogenic variants, matched on disease '
               f'identifiers. {esc(found["sources"])}.</p>'
               f'<p>{s["with_pathogenic"]:,} of {s["associations"]:,} associated diseases have '
               f'pathogenic variants in the gene'
               + (f'; the strongest of them is {esc(s["top_supported"])}' if s.get("top_supported") else "")
               + ".</p>"
               + table(["Disease", "Association (0 to 1)", "Pathogenic variants"]
                       + (["GWAS, strongest (-log10 p)"] if gwas else []), rows, noun="diseases"))
        if found.get("clinvar_only"):
            items = [f'<li>{esc(c["condition"])} <span class="mono">{c["pathogenic"]} of {c["records"]}</span></li>'
                     for c in found["clinvar_only"]]
            out += (f'<h4>ClinVar conditions with no associated disease to match '
                    f'({len(items):,})</h4>' + _rest(items, "conditions",
                                                     lambda inner: f'<ul class="list cols">{inner}</ul>'))
        if found.get("gwas_only"):
            traits = [(t["trait"], t["mlog10p"], f'{t["mlog10p"]:.1f}') for t in found["gwas_only"]]
            out += bars(traits, f"GWAS traits with no associated disease to match ({len(traits):,})",
                        "strongest association as -log10 p; 7.3 is genome-wide significance",
                        noun="traits")
        return out

    def regulators(self) -> str:
        found = self.views.get("regulators")
        if not found or found.get("state") != "ok":
            return ""
        items = [f'<li><span class="mono">{esc(tf)}</span> {esc(effect)}</li>'
                 for tf, effect in found["regulators"].items()]
        out = (f'<h3>Transcriptional regulators</h3><p class="note">{esc(found["source"])}.</p>'
               + (_rest(items, "regulators", lambda inner: f'<ul class="list cols">{inner}</ul>')
                  if items else "<p>None recorded.</p>"))
        if found["targets"]:
            out += (f'<p>As a transcription factor, it is recorded regulating '
                    f'{len(found["targets"]):,} genes.</p>')
        return out

    def body(self) -> str:
        """Every section, in the record's order, with its views."""
        views = {"genomics": [self.regulators], "transcriptomics": [self.organs],
                 "proteomics": [self.compartments, self.interactions], "clinical": [self.genetics]}
        res = self.record.resolution
        name = self.record.fields.get("name")
        out = [f'<section class="gene" id="{esc(self.symbol)}"><header class="gene-head">'
               f'<h2><span class="mono">{esc(self.symbol)}</span></h2>'
               f'<p>{esc(name.value) if name and name.present else ""}</p>'
               f'<p class="ids mono">{esc(res.hgnc_id)} · {esc(res.ensembl_gene_id)}'
               f'{" · " + esc(res.uniprot_accession) if res.uniprot_accession else ""}</p>'
               + '<nav class="contents">' + "".join(
                   f'<a href="#{esc(self.symbol)}-{key}">{esc(SECTIONS[key])}</a>'
                   for key in ["insights"] + [k for k in SECTIONS if k != "insights"]) + '</nav>'
               + '</header>',
               f'<div class="block">{self.summary()}</div>']
        order = ["insights"] + [key for key in SECTIONS if key != "insights"]
        for key in order:
            extra = "".join(view() for view in views.get(key, []))
            out.append(f'<section class="block" id="{esc(self.symbol)}-{key}">'
                       f'<h3 class="section">{esc(SECTIONS[key])}</h3>'
                       f'{self.fields(key)}{extra}</section>')
        out.append(f'<p class="fingerprint">Record fingerprint <span class="mono">'
                   f'{self.record.fingerprint()}</span>: the same gene against the same releases '
                   f'gives the same fingerprint.</p></section>')
        return "".join(out)


# -- the document ------------------------------------------------------------------------------


def _font(name: str, family: str, weight: int) -> str:
    path = FONTS / name
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return (f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');}}")


STYLE = """
:root{--azure:#00B2FF;--deep:#0077CC;--mist:#EAF7FF;--frost:#F5FAFF;--ink:#0B1B2B;
--slate:#5B6B7C;--line:#E3EBF3;--edge:#C9D7E5}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:#fff;color:var(--ink);font:13px/1.5 Sora,ui-sans-serif,system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 32px 64px}
.mono{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:.95em}
a{color:var(--deep);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:30px;font-weight:600;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:24px;font-weight:600;margin:0}
h3{font-size:15px;font-weight:600;margin:28px 0 6px}
h3.section{font-size:18px;margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h4{font-size:13px;font-weight:600;margin:18px 0 6px}
p{margin:6px 0}.note,.why,.desc,.unit{color:var(--slate)}.note{font-size:12px}
.why{font-size:11.5px}.desc{display:block;font-weight:400;font-size:11px;margin-top:2px}
.unit{display:block;font-weight:400;font-size:10.5px}
.lead{font-size:15px;margin:0 0 14px}
.null{color:var(--slate);font-style:italic}
.tag{font-size:10.5px;border:1px solid var(--edge);border-radius:999px;padding:0 6px;color:var(--slate)}
.cover{min-height:900px;display:flex;flex-direction:column;justify-content:space-between;
padding:24px 0 8px;border-bottom:1px solid var(--line);margin-bottom:40px}
.cover .star{width:64px;height:64px}
.kicker{text-transform:uppercase;letter-spacing:.14em;font-size:11px;color:var(--slate);margin:28px 0 8px}
.genes{font-size:22px;margin:4px 0 2px}.cover .meta{color:var(--slate);margin-top:10px}
.versions{margin-top:32px}.cover .fine{font-size:11px;color:var(--slate);max-width:620px}
.gene-head{padding:4px 0 14px;border-bottom:2px solid var(--ink);margin-bottom:18px}
.gene-head p{margin:2px 0}.ids{color:var(--slate);font-size:12px}
.block{margin:0 0 30px}
table{border-collapse:collapse;width:100%}
.fields th{text-align:left;font-weight:600;width:30%;padding:7px 12px 7px 0;vertical-align:top}
.fields td{padding:7px 12px 7px 0;vertical-align:top;border-top:1px solid var(--line)}
.fields th{border-top:1px solid var(--line)}
.fields td.src{width:19%;font-size:11.5px;text-align:right;padding-right:0;white-space:nowrap}
.derived{color:var(--slate);white-space:normal}
.grid{font-size:12px;margin:8px 0}
.grid th{text-align:left;font-weight:600;color:var(--slate);font-size:11px;padding:4px 10px 4px 0;
border-bottom:1px solid var(--line);vertical-align:bottom}
.grid td{padding:4px 10px 4px 0;border-bottom:1px solid var(--line);vertical-align:top}
.list{margin:0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:2px 14px}
.list.cols{display:block;columns:2;column-gap:28px}.list.cols li{break-inside:avoid}
.plain{margin:4px 0;padding-left:18px}
.chart{margin:16px 0 22px}
figcaption{font-weight:600;font-size:12.5px;margin-bottom:6px}
figcaption span{font-weight:400;color:var(--slate)}
.bars{display:grid;gap:3px}
.bar{display:grid;grid-template-columns:minmax(0,34%) 1fr 76px;align-items:center;gap:10px;font-size:12px}
.bar .label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar.strong .label,.bar.strong .num{font-weight:600}
.track{display:block;height:14px;background:var(--mist)}
.fill{display:block;height:100%;background:var(--azure);border-radius:0 4px 4px 0}
.num{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11.5px;text-align:right;
font-variant-numeric:tabular-nums}
.meter{display:grid;grid-template-columns:minmax(60px,1fr) auto;align-items:center;gap:8px}
.meter .track{height:7px;border-radius:0 4px 4px 0}.meter .num{min-width:44px}
.organs td{min-width:90px}
.hist{display:flex;align-items:flex-end;gap:2px;height:110px;border-bottom:1px solid var(--line)}
.hist .col{flex:1;height:100%;display:flex;align-items:flex-end;position:relative}
.hist .col span{display:block;width:100%;background:var(--azure);border-radius:2px 2px 0 0}
.hist .col.mark{border-left:1px dashed var(--slate)}
.ticks{position:relative;height:16px;font:11px 'JetBrains Mono',monospace;color:var(--slate);
margin-top:4px}.ticks span{position:absolute;transform:translateX(-50%)}
details{margin:4px 0 10px}
summary{cursor:pointer;color:var(--deep);font-size:12px;margin:6px 0}
.sequence{word-break:break-all;font-size:11px;line-height:1.6;color:var(--slate)}
.fingerprint{font-size:11px;color:var(--slate);border-top:1px solid var(--line);padding-top:10px;
word-break:break-all}
.nowrap{white-space:nowrap}
.compare{table-layout:fixed}.compare th:first-child,.compare td:first-child{width:22%}.compare .high{font-weight:600}
.compare .high::after{content:" highest";font-size:10px;font-weight:400;color:var(--slate)}
.credits td:first-child{font-weight:600;white-space:nowrap}
.ranked{font-size:11px}.ranked td{min-width:64px}.ranked .meter{grid-template-columns:minmax(40px,1fr) auto}
.ranked .why{display:block;font-size:10px}
.tools{position:absolute;top:16px;right:16px;display:flex;gap:8px}
.contents{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;margin:8px 0 0}
.tools button{font:inherit;font-size:12px;border:1px solid var(--line);background:#fff;
color:var(--deep);border-radius:999px;padding:4px 12px;cursor:pointer}
@page{size:A4;margin:16mm 14mm 18mm;
@bottom-left{content:"Spica, " string(subject);font:9px Sora,sans-serif;color:#5B6B7C}
@bottom-right{content:counter(page) " of " counter(pages);font:9px Sora,sans-serif;color:#5B6B7C}}
@page wide{size:A4 landscape}
.wide{page:wide;width:min(1320px,96vw);position:relative;left:50%;transform:translateX(-50%)}
.cover h1{string-set:subject content()}
@media print{
main{max-width:none;padding:0}.tools{display:none}
.wide{width:auto;left:auto;transform:none}
.cover{min-height:250mm;border:0;margin:0}
.cover,.gene,.after{break-after:page}
.block{break-inside:auto}h3,h4,figcaption{break-after:avoid}.bar,tr{break-inside:avoid}
a{color:var(--ink)}
}
"""

SCRIPT = """
document.getElementById('expand').addEventListener('click', function () {
  var all = document.querySelectorAll('details');
  var open = Array.prototype.some.call(all, function (d) { return !d.open; });
  all.forEach(function (d) { d.open = open; });
  this.textContent = open ? 'Collapse long lists' : 'Expand every list';
});
document.getElementById('print').addEventListener('click', function () { window.print(); });
"""


def _versions(records: list[GeneRecord], mirror) -> list[tuple[str, str, str, str]]:
    """(key, label, release, retrieved) for every source the report reads."""
    seen: dict[str, tuple[str, str, str, str]] = {}
    for record in records:
        for stamp in record.sources:
            if stamp.status == "read" and stamp.key not in seen:
                seen[stamp.key] = (stamp.key, stamp.label, stamp.version, stamp.retrieved)
    if mirror is not None:
        for key in VIEW_SOURCES:
            entry = mirror.entry(key)
            if entry is not None and not entry.missing_files():
                seen.setdefault(key, (key, entry.label, entry.version, entry.retrieved))
    return list(seen.values())


def _credits(versions: list[tuple[str, str, str, str]]) -> str:
    keys = []
    for key, *_ in versions:
        keys += [key, *CARRIED.get(key, ())]
    rows = [[esc(CREDITS[key].name), esc(CREDITS[key].terms), esc(CREDITS[key].credit)]
            for key in dict.fromkeys(keys) if key in CREDITS]
    return ('<section class="block after"><h3 class="section">Sources and credits</h3>'
            '<p class="note">Every value in this report names its source and release. Material '
            'shared outside your organisation should keep these credits.</p>'
            + table(["Source", "Terms", "Credit"], rows, classes="credits")
            + '<h3>How to read this report</h3><ul class="plain">'
            '<li>Values are read from the releases on the cover, as each source published them; '
            'nothing in this report was written by a model.</li>'
            '<li>An empty value says which kind of gap it is: <em>not found</em> (the source has '
            'no entry for the gene), <em>not covered</em> (the source does not measure it), '
            '<em>failed</em> (it could not be read when the report was built).</li>'
            '<li>Derived measures (the insights) are computed from the values beside them: tau '
            'runs from 0 (expressed everywhere alike) to 1 (one tissue only).</li>'
            '<li>Bars start at zero and are linear; each keeps its figure, so the report reads in '
            'grayscale.</li>'
            '<li>Long lists show their first rows in print; the HTML file holds every row.</li>'
            '</ul></section>')


def document(profiles: list[Profile], project: str, mirror=None, today: date | None = None,
             comparison: dict[str, Any] | None = None, ranked: dict[str, Any] | None = None,
             records: list[GeneRecord] | None = None) -> str:
    """The whole file: cover, then the ranked table or the comparison when
    there is one, each gene's profile, and the credits."""
    today = today or date.today()
    symbols = [profile.symbol for profile in profiles]
    versions = _versions(records or [profile.record for profile in profiles], mirror)
    kind = ("Ranked candidates" if ranked else
            "Target comparison" if len(profiles) > 1 else "Target report")
    if ranked:
        everyone = [row["symbol"] for row in ranked["rows"]]
        title = project.strip() or "Ranked candidates"
        genes_line = (f'<p class="genes mono">{esc(", ".join(everyone[:12]))}'
                      f'{esc(f", and {len(everyone) - 12} more") if len(everyone) > 12 else ""}</p>')
        subtitle = esc(ranked["summary"]) + "."
    else:
        # Without a project name the genes are the title, said once.
        title = project.strip() or ", ".join(symbols)
        genes_line = f'<p class="genes mono">{esc(", ".join(symbols))}</p>' if project.strip() else ""
        names = [profile.record.fields.get("name") for profile in profiles]
        subtitle = (esc(names[0].value) if len(profiles) == 1 and names[0] and names[0].present
                    else f"{len(profiles)} genes, side by side")
    version_rows = [[esc(label), f'<span class="mono">{esc(release)}</span>', esc(retrieved)]
                    for _, label, release, retrieved in versions]
    cover = (f'<section class="cover"><div><svg class="star" viewBox="0 0 32 32" role="img" '
             f'aria-label="Spica"><path fill="#00B2FF" d="{STAR}"/></svg>'
             f'<p class="kicker">{kind}</p><h1{"" if project.strip() else ' class="mono"'}>'
             f'{esc(title)}</h1>{genes_line}<p>{subtitle}</p>'
             f'<p class="meta">{long_date(today)}. Prepared with Spica, record schema '
             f'{SCHEMA_VERSION}.</p></div>'
             f'<div class="versions"><h4>Data versions</h4>'
             + table(["Source", "Release", "Retrieved"], version_rows)
             + '<p class="fine">Values are read from these releases as published. The report is '
               'deterministic: the same genes against the same releases give the same report.</p>'
               '</div></section>')
    parts = [cover]
    if ranked:
        parts.append(ranked_table(ranked, len(profiles)))
    elif comparison:
        parts.append(comparison_table(comparison))
    parts += [profile.body() for profile in profiles]
    parts.append(_credits(versions))
    fonts = (_font("sora-latin-400-normal.woff2", "Sora", 400)
             + _font("sora-latin-600-normal.woff2", "Sora", 600)
             + _font("jetbrains-mono-latin-400-normal.woff2", "JetBrains Mono", 400))
    policy = ("default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; "
              "script-src 'unsafe-inline'")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(kind)}: {esc(title)}</title><style>{fonts}{STYLE}</style></head><body>"
            '<div class="tools"><button id="expand" type="button">Expand every list</button>'
            '<button id="print" type="button">Print</button></div>'
            f"<main>{''.join(parts)}</main><script>{SCRIPT}</script></body></html>")


def ranked_table(ranked: dict[str, Any], profiled: int) -> str:
    """Page one of a ranked report: every gene, its score and each weighted
    criterion's own score with the value behind it; then the weights."""
    used = [c for c in ranked["criteria"] if c["weight"]]
    head = ["Rank", "Gene", "Score", "Data"] + [
        f'{esc(c["label"])}<span class="unit">weight {c["weight"]:g}</span>' for c in used]
    rows = []
    for row in ranked["rows"]:
        cells = [f'<span class="mono">{row["rank"]}</span>',
                 f'<span class="mono">{esc(row["symbol"])}</span>',
                 meter(row["score"], 1, f'{row["score"]:.3f}') if row["score"] is not None
                 else '<span class="null">no data</span>',
                 f'<span class="mono">{round(100 * (row["coverage"] or 0))}%</span>']
        for c in used:
            part = row["parts"][c["key"]]
            cells.append(f'<span title="{esc(part["value"])}">'
                         + (meter(part["score"], 1, f'{part["score"]:.2f}') if part["score"] is not None
                            else '<span class="null">no data</span>')
                         + f'<span class="why"> {esc(part["value"])}</span></span>')
        rows.append(cells)
    weights = [[esc(c["label"]), f'<span class="mono">{c["weight"]:g}</span>', esc(c["group"]),
                f'<span class="why">{esc(c["describe"])}</span>'] for c in used]
    unweighted = [c["label"] for c in ranked["criteria"] if not c["weight"]]
    return ('<section class="block wide after"><h3 class="section">Ranked candidates</h3>'
            f'<p class="note">{esc(ranked["summary"])}. The score is the weighted mean of the '
            'criteria below, each between 0 and 1; "Data" is the share of the weight a gene had '
            'data for. A gene scores the same in any list: no score depends on the other genes. '
            + (f'Profiles follow for the top {profiled}.' if profiled < len(ranked["rows"])
               else 'Every gene\'s profile follows.') + '</p>'
            + table(head, rows, classes="ranked", whole=True)
            + '<h3>Weights</h3>'
            + table(["Criterion", "Weight, 0 to 10", "Group", "Scoring"], weights, whole=True)
            + (f'<p class="note">Not weighed: {esc(", ".join(unweighted))}.</p>' if unweighted else "")
            + "</section>")


def comparison_table(table_data: dict[str, Any]) -> str:
    """The comparison, comparable measures first, the highest marked in words."""
    genes = table_data["genes"]
    head = ["Field"] + [f'<span class="mono">{esc(g["symbol"])}</span>' for g in genes]
    blocks = []
    for section in table_data["sections"]:
        rows = []
        for row in section["rows"]:
            cells = [esc(row["label"])]
            for cell in row["cells"]:
                if cell["state"]:
                    cells.append(f'<span class="null">{STATE_LABEL.get(cell["state"], cell["state"])}</span>')
                else:
                    mark = ' class="high"' if cell.get("notable") else ""
                    cells.append(f'<span{mark}>{esc(cell["display"])}</span>')
            rows.append(cells)
        blocks.append(f'<h3>{esc(section["label"])}</h3>' + table(head, rows, noun="fields",
                                                                   classes="compare"))
    return ('<section class="block wide after"><h3 class="section">Side by side</h3>'
            '<p class="note">Every field for every gene. Where a higher value means something '
            '(specificity, clinical phase, structural coverage) the highest is marked; Spica does '
            'not rank the genes, since that depends on the modality and the indication. Long lists '
            'and tissue profiles are shortened here and given whole in the profiles that follow.</p>'
            + "".join(blocks) + "</section>")


# -- entry points ------------------------------------------------------------------------------


def views_for(record: GeneRecord, mirror, live) -> dict[str, Any]:
    """The derived views the report shows beside the record, each on its own."""
    from spica import genetics, interactions, regulators
    from spica.dogma import align
    from spica.glance import glance
    from spica.locations import compartments

    symbol = record.resolution.symbol
    ensembl = record.resolution.ensembl_gene_id
    makers = {
        "glance": lambda: glance(record),
        "dogma": lambda: align(record),
        "locations": lambda: compartments(record),
        "genetics": lambda: genetics.evidence(symbol, ensembl, mirror),
        "interactions": lambda: interactions.compare(symbol, ensembl, mirror),
        "regulators": lambda: regulators.single(symbol, live, mirror),
    }
    views: dict[str, Any] = {}
    for key, make in makers.items():
        try:
            views[key] = make()
        except Exception as exc:  # one view failing never costs the report
            views[key] = {"error": f"not built: {exc}"}
    return views


def report(queries: list[str], project: str = "", mirror=None, live=None,
           today: date | None = None) -> dict[str, Any]:
    """Build the report for one gene or several. Returns the HTML and a file name,
    or an error that says what to fix."""
    from spica.build import build_record
    from spica.compare import compare
    from spica.live import Live
    from spica.mirror import Mirror

    mirror = Mirror.load() if mirror is None else mirror
    live = Live.from_env(mirror.root) if live is None else live
    queries = [q.strip() for q in queries if q and q.strip()]
    if not queries:
        return {"error": "No gene entered."}
    records = [build_record(query, mirror, live) for query in queries]
    unresolved = [record.query for record in records if not record.resolution.resolved]
    if unresolved:
        return {"error": f"No gene match: {', '.join(unresolved)}."}
    profiles = [Profile(record, views_for(record, mirror, live)) for record in records]
    table_data = compare(queries, records) if len(records) > 1 else None
    day = today or date.today()
    content = document(profiles, project, mirror, day, table_data)
    stem = "-".join(profile.symbol for profile in profiles[:4])
    if len(profiles) > 4:
        stem += f"-and-{len(profiles) - 4}-more"
    return {"html": content, "filename": f"Spica {stem} {day.isoformat()}.html",
            "genes": [profile.symbol for profile in profiles]}


def ranked_report(queries: list[str], weights: dict[str, float], indication: str = "",
                  missing: str = "skip", project: str = "", profiles: int | None = 10,
                  mirror=None, live=None, today: date | None = None,
                  progress=None) -> dict[str, Any]:
    """The client report for a ranked list: the ranked table on page one,
    then a profile for each of the top `profiles` genes (every gene when
    None). The table always holds every gene."""
    from spica import ranking
    from spica.build import build_record
    from spica.live import Live
    from spica.mirror import Mirror

    mirror = Mirror.load() if mirror is None else mirror
    live = Live.from_env(mirror.root) if live is None else live
    records = []
    for done, query in enumerate(queries, start=1):
        records.append(build_record(query, mirror, live))
        if progress:
            progress(done, len(queries))
    resolved = [record for record in records if record.resolution.resolved]
    if not resolved:
        return {"error": "No gene in the list could be matched."}
    ranked = ranking.rank(resolved, weights, indication, missing, mirror)
    order = {row["hgnc_id"]: row["rank"] for row in ranked["rows"]}
    top = sorted(resolved, key=lambda record: order.get(record.resolution.hgnc_id, 10 ** 6))
    top = top if profiles is None else top[:max(0, int(profiles))]
    chosen = [Profile(record, views_for(record, mirror, live)) for record in top]
    day = today or date.today()
    content = document(chosen, project, mirror, day, ranked=ranked, records=resolved)
    stem = (project.strip() or "ranked candidates").replace("/", "-")[:60]
    return {"html": content, "filename": f"Spica {stem} {day.isoformat()}.html",
            "genes": [row["symbol"] for row in ranked["rows"]]}
