"""Readable text from the files in the input folder.

One function per extension, in a registry. Each returns a list of numbered
units: pages for a PDF, slides for a deck, sheets for a workbook, blocks for
plain text. A hit can thus cite "deck.pptx, slide 12", not a file offset.

Adapted from `utils/corpus.py` in Betelgeuse. It solves three problems that
make answers worse without any error:

*Column order.* A simple extraction of a two-column paper mixes the
columns, and the text reads as two half-sentences joined together. Blocks
are grouped into columns by horizontal position and sorted column first.

*Hyphenation.* PDFs break words across lines ("dereduc-\\ntase"). Without a
fix, this breaks the technical terms that retrieval needs.

*Running heads.* Journal name, DOI and page items repeat on each page. As
chunks, they are noise that weakly matches every query. Blocks that repeat
across most pages of a document are thus dropped.

Not included: figure captions. Betelgeuse can describe embedded images with
a vision model. Here, a chart pasted as a picture is indexed by the text
around it only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator, Sequence

#: Formats without intrinsic pages are cut into blocks of this size, purely
#: so a citation can point at something smaller than the whole file.
PSEUDO_PAGE_CHARS = 2500


class ExtractionError(RuntimeError):
    """The file could not be read, with a sentence saying what is missing."""


def _need(module: str, package: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise ExtractionError(
            f"{package} is needed to read this format. "
            f"Run `./run.sh --agents` to add it."
        ) from exc


# -- cleaning ---------------------------------------------------------------


def dehyphenate(text: str) -> str:
    """Rejoin words split across a line break, keeping real hyphens intact."""
    # Only join when a lowercase letter precedes the hyphen and a letter
    # follows: that spares "NAD(P)H-\ndependent" compounds far more often
    # than not.
    return re.sub(r"([a-z])-\s*\n\s*([a-z])", r"\1\2", text)


def normalise(text: str) -> str:
    text = text.replace("­", "")  # soft hyphen
    text = dehyphenate(text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def paginate(text: str, size: int = PSEUDO_PAGE_CHARS) -> list[str]:
    text = normalise(text)
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), size)]


def columns(blocks: Sequence[tuple], page_width: float) -> list[tuple]:
    """Order text blocks the way a person reads them.

    Whether the page has one column or two is decided from the blocks
    rather than assumed: a two-column paper has left edges clustering into
    two groups, neither spanning the page. Full-width blocks (titles, wide
    tables) keep their place above the columns they precede.
    """
    if not blocks:
        return []

    mid = page_width / 2
    wide = [b for b in blocks
            if b[0] < mid < b[2] and (b[2] - b[0]) > page_width * 0.55]
    narrow = [b for b in blocks if b not in wide]
    left = [b for b in narrow if b[0] < mid]
    right = [b for b in narrow if b[0] >= mid]

    # Single column unless both sides carry real weight, else a one-column
    # paper with a marginal note gets shredded.
    if not left or not right or min(len(left), len(right)) < 2:
        return sorted(blocks, key=lambda b: (round(b[1], 1), round(b[0], 1)))

    return (sorted(wide, key=lambda b: b[1])
            + sorted(left, key=lambda b: b[1])
            + sorted(right, key=lambda b: b[1]))


# -- the formats ------------------------------------------------------------


def extract_pdf(path: Path) -> list[str]:
    """One reading-ordered string per page."""
    from collections import Counter

    # pdfminer.six (MIT), not PyMuPDF: PyMuPDF is AGPL unless licensed from
    # Artifex, which a closed commercial product cannot ship. pdfminer gives
    # the same thing the column ordering needs, text boxes with coordinates.
    _need("pdfminer", "pdfminer.six")
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextContainer

    raw: list[list[str]] = []
    for page in extract_pages(str(path), laparams=LAParams()):
        # pdfminer's origin is the bottom left; columns() reads from the
        # top, as the page is read. b = (x0, top, x1, bottom, text).
        blocks = [(el.x0, page.height - el.y1, el.x1, page.height - el.y0,
                   el.get_text(), index, 0)
                  for index, el in enumerate(page)
                  if isinstance(el, LTTextContainer) and el.get_text().strip()]
        raw.append([b[4].strip() for b in columns(blocks, page.width)])

    counts: Counter = Counter()
    for blocks_on_page in raw:
        for block in set(blocks_on_page):
            counts[re.sub(r"\d+", "#", block.strip())[:80]] += 1
    threshold = max(3, int(len(raw) * 0.6))
    furniture = {key for key, n in counts.items()
                 if n >= threshold and len(key) < 80}

    return [
        normalise("\n\n".join(
            b for b in blocks_on_page
            if re.sub(r"\d+", "#", b.strip())[:80] not in furniture
        ))
        for blocks_on_page in raw
    ]


def extract_xlsx(path: Path) -> list[str]:
    """One string per worksheet, rows rendered as pipe-separated lines.

    The header row travels with every chunk of its sheet, because a row of
    bare numbers retrieves nothing: what makes it findable is the column it
    sits under.
    """
    openpyxl = _need("openpyxl", "openpyxl")
    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        sheets: list[str] = []
        for worksheet in workbook.worksheets:
            rows = []
            for row in worksheet.iter_rows(values_only=True):
                cells = ["" if value is None else str(value) for value in row]
                if any(cell.strip() for cell in cells):
                    rows.append(" | ".join(cells))
            header = f"Sheet: {worksheet.title}"
            sheets.append(normalise(header + "\n" + "\n".join(rows)) if rows
                          else header)
        return sheets
    finally:
        workbook.close()


def extract_docx(path: Path) -> list[str]:
    docx = _need("docx", "python-docx")
    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return paginate("\n\n".join(parts))


def _shapes(container) -> Iterator:
    """Every shape, including those nested inside groups."""
    for shape in container:
        if getattr(shape, "shape_type", None) is not None and hasattr(shape, "shapes"):
            yield from _shapes(shape.shapes)
        else:
            yield shape


def extract_pptx(path: Path) -> list[str]:
    """One string per slide, with native chart data rendered as text.

    A chart built in PowerPoint stores its categories and series as numbers,
    so the plot itself becomes searchable. A chart pasted as a picture
    carries no data at all and is indexed only by the text around it.
    """
    _need("pptx", "python-pptx")
    from pptx import Presentation

    deck = Presentation(str(path))
    slides: list[str] = []
    for slide in deck.slides:
        parts: list[str] = []
        for shape in _shapes(slide.shapes):
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
            if getattr(shape, "has_chart", False):
                parts.append(_chart_text(shape.chart))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"Notes: {notes}")
        slides.append(normalise("\n\n".join(p for p in parts if p)))
    return slides


def _chart_text(chart) -> str:
    """A native chart's own numbers, as readable lines."""
    lines = ["Chart:"]
    try:
        categories = [str(c) for c in chart.plots[0].categories]
    except (IndexError, AttributeError, ValueError):
        categories = []
    try:
        for series in chart.series:
            values = [("" if v is None else str(round(v, 4) if isinstance(v, float) else v))
                      for v in series.values]
            pairs = ", ".join(
                f"{category} {value}"
                for category, value in zip(categories or [""] * len(values), values)
            )
            lines.append(f"{series.name}: {pairs}")
    except (AttributeError, ValueError):
        return ""
    return "\n".join(lines) if len(lines) > 1 else ""


def extract_text(path: Path) -> list[str]:
    return paginate(path.read_text(encoding="utf-8", errors="replace"))


#: Extension to extractor. Adding a format means adding one function here.
EXTRACTORS: dict[str, Callable[[Path], list[str]]] = {
    ".pdf": extract_pdf,
    ".xlsx": extract_xlsx,
    ".xlsm": extract_xlsx,
    ".docx": extract_docx,
    ".pptx": extract_pptx,
    ".txt": extract_text,
    ".md": extract_text,
    ".csv": extract_text,
    ".tsv": extract_text,
    ".json": extract_text,
}

SUPPORTED = tuple(sorted(EXTRACTORS))

#: Formats whose units stand alone, so a chunk must not span two of them.
#: Running slides together produces chunks citing "slides 1-6", which points
#: at a whole deck and is no use for checking a claim.
DISCRETE = {".pptx", ".xlsx", ".xlsm"}


def extract(path: Path) -> list[str]:
    """The text of one file as numbered units, or raise ExtractionError."""
    reader = EXTRACTORS.get(path.suffix.lower())
    if reader is None:
        raise ExtractionError(f"{path.suffix} is not a format Spica reads")
    try:
        return [unit for unit in reader(path)]
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"{type(exc).__name__}: {exc}") from exc


def unit_name(suffix: str) -> str:
    """What one unit of this format is called, for a citation."""
    return {".pptx": "slide", ".xlsx": "sheet", ".xlsm": "sheet",
            ".pdf": "p"}.get(suffix.lower(), "block")
