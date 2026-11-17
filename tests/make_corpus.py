"""Regenerate the fixture corpus in `tests/fixtures/corpus`.

    python tests/make_corpus.py

One file of each format that Spica reads, written with the same libraries
that read them back. The tests thus use real files, not strings that
pretend to be files. Needs the document readers: `./run.sh --agents`.

Each fixture has one thing that the extractor must get right:

    memo.pdf        a word hyphenated across a line break
    deck.pptx       a native chart, whose numbers must become text
    assays.xlsx     two sheets, each needing its header row
    rationale.docx  a table as well as paragraphs
    notes.md        plain prose
    readings.csv    rows that only mean anything under their columns
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent / "fixtures" / "corpus"


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)

    (ROOT / "notes.md").write_text(
        "# Screen notes\n\nThe LDLR knockdown screen ran in triplicate.\n"
        "PCSK9 inhibition raised surface LDLR by 2.4 fold in hepatocytes.\n"
        "Vehicle controls were unchanged.\n", encoding="utf-8")

    (ROOT / "readings.csv").write_text(
        "gene,tissue,fold_change,n\n"
        "PCSK9,liver,2.41,3\n"
        "LDLR,liver,0.88,3\n"
        "CLDN18,stomach,5.02,3\n", encoding="utf-8")

    from openpyxl import Workbook

    workbook = Workbook()
    binding = workbook.active
    binding.title = "binding"
    binding.append(["compound", "target", "Kd_nM", "assay"])
    binding.append(["SPC-101", "PCSK9", 12.4, "SPR"])
    binding.append(["SPC-102", "PCSK9", 340.0, "SPR"])
    cytotox = workbook.create_sheet("cytotox")
    cytotox.append(["compound", "line", "IC50_uM"])
    cytotox.append(["SPC-101", "HepG2", 48.2])
    workbook.save(ROOT / "assays.xlsx")

    import docx

    document = docx.Document()
    document.add_paragraph("Target rationale: PCSK9")
    document.add_paragraph(
        "Liver-dominant expression makes hepatocyte delivery the obvious route.")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "modality"
    table.rows[0].cells[1].text = "status"
    table.rows[1].cells[0].text = "siRNA"
    table.rows[1].cells[1].text = "approved"
    document.save(ROOT / "rationale.docx")

    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Expression by tissue"
    data = CategoryChartData()
    data.categories = ["liver", "kidney", "brain"]
    data.add_series("median TPM", (77.41, 9.82, 1.44))
    slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                           Inches(1), Inches(2), Inches(6), Inches(4), data)
    deck.save(ROOT / "deck.pptx")

    (ROOT / "memo.pdf").write_bytes(minimal_pdf([
        (72, 100, 16, "Spica internal memo"),
        (72, 140, 11, "Hepatocyte delivery remains the bottleneck for this"),
        (72, 154, 11, "programme. The dereduc-"),
        (72, 168, 11, "tase assay was repeated."),
    ]))

    print(f"[spica] wrote {len(list(ROOT.iterdir()))} fixtures to {ROOT}")
    return 0


def minimal_pdf(lines: list[tuple[float, float, float, str]]) -> bytes:
    """A one-page PDF with lines of Helvetica, written by hand.

    Enough for a reader to find text with coordinates, and no PDF library
    needed to make it: the one this used to use is AGPL. `lines` are
    (x, y-from-top, size, text) on a US Letter page.
    """
    height = 792
    content = []
    for x, y, size, text in lines:
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.append(f"BT /F1 {size} Tf {x} {height - y} Td ({safe}) Tj ET")
    stream = "\n".join(content).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


if __name__ == "__main__":
    raise SystemExit(main())
