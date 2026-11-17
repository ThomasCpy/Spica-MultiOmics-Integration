"""Reading the input folder, cutting it up, indexing and searching it.

The fixture corpus holds one file of every format Spica reads, written by
`tests/make_corpus.py` with the same libraries that read them back. No test
loads an embedding model: `Fake` returns deterministic vectors, which is
enough to test everything except the quality of the embeddings themselves.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spica.corpus import Index, chunk_units, extract
from spica.corpus.chunks import Chunk
from spica.corpus.extract import ExtractionError, columns, dehyphenate, normalise
from spica.corpus.index import discover, read_file

CORPUS = Path(__file__).resolve().parent / "fixtures" / "corpus"


def readers_installed() -> bool:
    """Whether the document libraries are in this runtime.

    They are optional, like the model: Spica builds records without them.
    So the tests that need them skip rather than fail, and the suite stays
    green on a machine that has only run `./run.sh`.
    """
    try:
        import docx  # noqa: F401
        import openpyxl  # noqa: F401
        import pptx  # noqa: F401
        import pdfminer  # noqa: F401
    except ImportError:
        return False
    return True


NEEDS_READERS = unittest.skipUnless(
    readers_installed(),
    "the document readers are not installed; run ./run.sh --agents",
)


class Fake:
    """An embedder with no model: a vector per text, stable and comparable.

    Three dimensions carrying word overlap with three probe terms, so a
    search still orders results in a way a test can assert on.
    """

    dimension = 3
    PROBES = ("pcsk9", "hepatocyte", "kd")

    def _vector(self, text: str):
        import numpy as np

        lowered = text.lower()
        raw = np.asarray([float(lowered.count(p)) for p in self.PROBES],
                         dtype="float32")
        norm = float(np.linalg.norm(raw))
        return raw / norm if norm else raw

    def documents(self, texts):
        import numpy as np

        return np.asarray([self._vector(t) for t in texts], dtype="float32")

    def query(self, text: str):
        return self._vector(text)


class TestCleaning(unittest.TestCase):
    def test_a_word_split_across_a_line_is_rejoined(self):
        self.assertEqual(dehyphenate("dereduc-\ntase"), "dereductase")

    def test_a_real_hyphen_survives(self):
        # The compound terms retrieval depends on must not be welded shut.
        self.assertEqual(dehyphenate("NAD(P)H-\ndependent"), "NAD(P)H-\ndependent")

    def test_soft_hyphens_and_runs_of_space_go(self):
        self.assertEqual(normalise("a­b   c\n\n\n\nd"), "ab c\n\nd")


class TestColumns(unittest.TestCase):
    def block(self, x0, y0, x1, y1):
        return (x0, y0, x1, y1, "text", 0, 0)

    def test_two_columns_are_read_down_then_across(self):
        blocks = [
            self.block(300, 100, 560, 200),  # right, top
            self.block(40, 100, 300, 200),   # left, top
            self.block(40, 220, 300, 320),   # left, lower
            self.block(300, 220, 560, 320),  # right, lower
        ]
        ordered = columns(blocks, 600)
        self.assertEqual([b[0] for b in ordered], [40, 40, 300, 300])

    def test_a_single_column_page_keeps_reading_order(self):
        blocks = [self.block(40, 300, 560, 400), self.block(40, 100, 560, 200)]
        ordered = columns(blocks, 600)
        self.assertEqual([b[1] for b in ordered], [100, 300])

    def test_a_full_width_title_stays_above_the_columns(self):
        blocks = [
            self.block(40, 200, 300, 300), self.block(40, 320, 300, 400),
            self.block(310, 200, 560, 300), self.block(310, 320, 560, 400),
            self.block(40, 50, 560, 120),  # the title
        ]
        ordered = columns(blocks, 600)
        self.assertEqual(ordered[0][1], 50)


@NEEDS_READERS
class TestExtractors(unittest.TestCase):
    """One of each format, from the fixture corpus."""

    def test_a_workbook_gives_one_unit_per_sheet_with_its_header(self):
        units = extract(CORPUS / "assays.xlsx")
        self.assertEqual(len(units), 2)
        self.assertIn("Sheet: binding", units[0])
        # The header travels with the rows: a row of bare numbers retrieves
        # nothing without the column it sits under.
        self.assertIn("compound | target | Kd_nM", units[0])
        self.assertIn("SPC-101 | PCSK9 | 12.4", units[0])

    def test_a_deck_renders_native_chart_data_as_text(self):
        # A chart built in PowerPoint stores its numbers; this is what makes
        # the plot itself searchable rather than only its title.
        units = extract(CORPUS / "deck.pptx")
        self.assertIn("median TPM", units[0])
        self.assertIn("liver 77.41", units[0])

    def test_a_pdf_comes_back_dehyphenated(self):
        units = extract(CORPUS / "memo.pdf")
        self.assertIn("dereductase", units[0])
        self.assertNotIn("dereduc-", units[0])

    def test_a_word_document_includes_its_tables(self):
        units = extract(CORPUS / "rationale.docx")
        self.assertIn("siRNA | approved", "\n".join(units))

    def test_plain_text_is_read_as_is(self):
        self.assertIn("triplicate", extract(CORPUS / "notes.md")[0])

    def test_an_unknown_format_is_refused_by_name(self):
        with self.assertRaises(ExtractionError) as caught:
            extract(Path("something.xyz"))
        self.assertIn(".xyz", str(caught.exception))


class TestChunking(unittest.TestCase):
    def test_pages_are_merged_so_a_passage_can_span_a_break(self):
        units = ["a" * 700, "b" * 700]
        chunks = chunk_units(units, "paper.pdf", merge=True)
        self.assertTrue(any(c.unit_start != c.unit_end for c in chunks))

    def test_standalone_units_are_never_merged(self):
        # "slides 1-6" points at a whole deck and is no use for checking.
        units = ["slide one text", "slide two text", "slide three text"]
        chunks = chunk_units(units, "deck.pptx", merge=False)
        self.assertEqual(len(chunks), 3)
        for chunk in chunks:
            self.assertEqual(chunk.unit_start, chunk.unit_end)

    def test_a_file_shorter_than_the_floor_is_still_indexed(self):
        # Dropping a fragment is housekeeping; dropping a whole file is
        # data loss, and a corpus is full of short notes.
        chunks = chunk_units(["tiny note"], "note.txt")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "tiny note")

    def test_an_empty_file_produces_nothing(self):
        self.assertEqual(chunk_units(["   "], "blank.txt"), [])

    def test_passages_overlap_so_a_claim_is_not_cut_in_half(self):
        chunks = chunk_units(["word " * 800], "long.txt")
        self.assertGreater(len(chunks), 1)
        tail = chunks[0].text[-80:]
        self.assertTrue(any(part in chunks[1].text for part in tail.split()[:3]))


class TestCitations(unittest.TestCase):
    def citation(self, source: str, start: int, end: int) -> str:
        return Chunk("text", source, start, end).citation

    def test_the_unit_is_named_for_the_format(self):
        self.assertEqual(self.citation("paper.pdf", 7, 7), "paper.pdf, p7")
        self.assertEqual(self.citation("deck.pptx", 3, 3), "deck.pptx, slide 3")
        self.assertEqual(self.citation("book.xlsx", 2, 2), "book.xlsx, sheet 2")
        self.assertEqual(self.citation("notes.md", 1, 1), "notes.md, block 1")

    def test_a_span_reads_as_a_span(self):
        self.assertEqual(self.citation("paper.pdf", 4, 5), "paper.pdf, pp4-5")
        self.assertEqual(self.citation("deck.pptx", 2, 4), "deck.pptx, slides 2-4")


@NEEDS_READERS
class TestDiscovery(unittest.TestCase):
    def test_it_finds_every_supported_file(self):
        files, skipped = discover(CORPUS)
        self.assertEqual(len(files), 6)
        self.assertEqual(skipped, [])

    def test_documents_are_named_by_their_path_not_their_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("one", "two"):
                (root / folder).mkdir()
                (root / folder / "notes.md").write_text("text", encoding="utf-8")
            files, _ = discover(root)
        self.assertEqual(sorted(s for _, s in files), ["one/notes.md", "two/notes.md"])

    def test_unsupported_and_temporary_files_are_reported_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "weights.bin").write_bytes(b"\0\0")
            (root / "~$draft.docx").write_bytes(b"\0")
            files, skipped = discover(root)
        self.assertEqual(files, [])
        self.assertEqual(skipped, ["weights.bin"])  # the lock file is not news


@NEEDS_READERS
class TestIndex(unittest.TestCase):
    def build(self, root: Path | None = None):
        return Index.build(Fake(), root=root or CORPUS)

    def test_it_indexes_the_whole_corpus(self):
        index, reports = self.build()
        self.assertEqual(len(index.sources), 6)
        self.assertEqual(index.vectors.shape, (len(index), 3))
        self.assertTrue(all(r.usable for r in reports), [r.problem for r in reports])

    def test_the_same_file_under_two_names_is_indexed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("the same words", encoding="utf-8")
            (root / "b.md").write_text("the same words", encoding="utf-8")
            index, reports = self.build(root)
        self.assertEqual(len(index.sources), 1)
        self.assertEqual([r.duplicate_of for r in reports if r.duplicate_of], ["a.md"])

    def test_a_file_with_no_text_is_reported_rather_than_dropped_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty.md").write_text("   ", encoding="utf-8")
            _, reports = self.build(root)
        self.assertIn("no text could be read", reports[0].problem)

    def test_search_returns_the_nearest_passages_first(self):
        index, _ = self.build()
        hits = index.search(Fake().query("hepatocyte"), limit=3)
        self.assertTrue(hits)
        self.assertGreaterEqual(hits[0][0], hits[-1][0])
        self.assertIn("hepatocyte", hits[0][1].text.lower())

    def test_search_can_be_held_to_named_documents(self):
        index, _ = self.build()
        hits = index.search(Fake().query("pcsk9"), limit=5, sources=["notes.md"])
        self.assertTrue(hits)
        self.assertEqual({chunk.source for _, chunk in hits}, {"notes.md"})

    def test_it_survives_a_round_trip_through_disk(self):
        index, _ = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            index.save(Path(tmp))
            reloaded = Index.load(Path(tmp))
            saved = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(reloaded), len(index))
        self.assertEqual(reloaded.sources, index.sources)
        self.assertIn("assays.xlsx", saved)

    def test_an_index_whose_halves_disagree_refuses_to_load(self):
        # Vectors and passages that have drifted apart would answer with the
        # wrong citation, which is worse than not answering.
        index, _ = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            index.save(Path(tmp))
            lines = (Path(tmp) / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            (Path(tmp) / "chunks.jsonl").write_text("\n".join(lines[:-1]),
                                                    encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                Index.load(Path(tmp))
        self.assertIn("Rebuild it", str(caught.exception))

    def test_an_empty_folder_gives_an_empty_index_rather_than_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            index, reports = self.build(Path(tmp))
        self.assertEqual(len(index), 0)
        self.assertEqual(reports, [])
        self.assertEqual(index.search(Fake().query("anything")), [])


if __name__ == "__main__":
    unittest.main()
