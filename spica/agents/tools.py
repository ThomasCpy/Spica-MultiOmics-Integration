"""The orchestrator's tools.

The structure comes from Betelgeuse: one entry per source, one call
signature, and a catalogue in the prompt. The agent thus never has to
remember the needs of each source. A new tool is one new class here.

One difference: Betelgeuse runs each move as Python in a sandboxed REPL.
Here a move is a tool name and one string argument, for example
`documents("delivery to hepatocytes")`. This covers all tools, and there is
no code to sandbox.

Each tool returns a `Finding`: a few lines of fact and their citations. The
citations are essential. A passage cites its document and page; a record
value cites its schema field. The verifier then checks the answer against
them. A tool output without citations is unusable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

MAX_PASSAGES = 5
MAX_PASSAGE_CHARS = 700


@dataclass
class Finding:
    """What one move produced."""

    text: str  # what the orchestrator will read
    citations: list[str] = field(default_factory=list)
    raw: str = ""  # what the tool returned before condensing, for the log
    problem: str = ""  # why there is nothing, if there is nothing

    @property
    def empty(self) -> bool:
        return not self.text.strip()


class Tool(Protocol):
    key: str
    label: str
    usage: str

    def status(self) -> str:
        """One line on what this tool currently holds."""

    def run(self, argument: str) -> Finding:
        """Answer one move."""


# -- the user's documents ---------------------------------------------------


class Documents:
    """Semantic search over the corpus in `data/input`."""

    key = "documents"
    label = "Documents"
    usage = 'documents("<what you want to find>") -> passages from your own files'

    def __init__(self, index=None, embedder=None) -> None:
        self._index = index
        self._embedder = embedder
        self._problem = ""

    def _load(self) -> bool:
        from spica.agents.llm import ModelMissing
        from spica.corpus import Embedder, Index

        if self._index is not None and self._embedder is not None:
            return True
        try:
            if self._index is None:
                self._index = Index.load()
            if self._embedder is None:
                self._embedder = Embedder()
        except FileNotFoundError:
            self._problem = ("no index yet; run `python -m spica.ingest` "
                             "over data/input")
            return False
        except (ModelMissing, ValueError) as exc:
            self._problem = str(exc)
            return False
        return True

    def status(self) -> str:
        from spica.corpus import Index

        try:
            if self._index is None:
                self._index = Index.load()
        except (FileNotFoundError, ValueError) as exc:
            return f"unavailable: {exc}"
        return (f"{len(self._index)} passages from "
                f"{len(self._index.sources)} documents")

    def run(self, argument: str) -> Finding:
        if not argument.strip():
            return Finding("", problem="documents() needs something to search for")
        if not self._load():
            return Finding("", problem=self._problem)

        hits = self._index.search(self._embedder.query(argument), limit=MAX_PASSAGES)
        if not hits:
            return Finding("", problem=f"no document matches {argument}")

        lines, citations = [], []
        for score, chunk in hits:
            text = chunk.text.strip().replace("\n", " ")
            if len(text) > MAX_PASSAGE_CHARS:
                text = text[:MAX_PASSAGE_CHARS] + "..."
            lines.append(f"[{chunk.citation}] (similarity {score:.2f}) {text}")
            citations.append(chunk.citation)
        return Finding("\n\n".join(lines), citations=citations,
                       raw=f"{len(hits)} passages for {argument!r}")


# -- the deterministic record -----------------------------------------------


class Record:
    """One gene's record, built by the deterministic layer.

    The agent reads it; it does not produce it. Whatever the agent does
    with the values afterwards, the record itself is the same record the
    report screen shows, built the same way.
    """

    key = "record"
    label = "Gene record"
    usage = 'record("<gene symbol>") -> the sourced record for one gene'

    def __init__(self, builder=None) -> None:
        self._build = builder

    def status(self) -> str:
        return "every mirrored source, or its API"

    def _builder(self):
        if self._build is None:
            from spica.build import build_record

            self._build = build_record
        return self._build

    def run(self, argument: str) -> Finding:
        symbol = argument.strip()
        if not symbol:
            return Finding("", problem="record() needs a gene symbol")

        from spica.agents.context import render_record

        record = self._builder()(symbol)
        if not record.resolution.resolved:
            return Finding("", problem=record.resolution.reason)

        citations = [f"[{name}]" for name in record.present_fields()]
        # Empty fields are shown with their reasons: "MALAT1 makes no
        # protein" and "the lookup failed" are different answers.
        return Finding(
            f"Record for {record.resolution.symbol}:\n"
            + render_record(record, include_nulls=True).replace("<gene>",
                                                                 record.resolution.symbol),
            citations=citations,
            raw=f"{len(citations)} fields with values",
        )


# -- comparing genes --------------------------------------------------------


class Compare:
    """Several genes against each other on the comparable measures.

    The reason the record has an insights section at all: a peak expression
    value cannot be compared between genes, and specificity can. This is
    the tool that answers "which of these is the better target".
    """

    key = "compare"
    label = "Compare genes"
    usage = ('compare("<gene>, <gene>, ...") -> every comparable field side by side, for '
             'as many genes as given')

    #: Not compared: a sequence is not a measure, and a whole map does not fit
    #: a cell (field() reads one whole; the comparison shows its peak).
    SKIP_TYPES = ("sequence",)

    def __init__(self, builder=None) -> None:
        self._build = builder

    def status(self) -> str:
        return "compares on the derived, comparable measures"

    def _builder(self):
        if self._build is None:
            from spica.build import build_record

            self._build = build_record
        return self._build

    def run(self, argument: str) -> Finding:
        from spica.compare import compare

        symbols = [part.strip() for part in re.split(r"[,;/]| and ", argument)
                   if part.strip()]
        if len(symbols) < 2:
            return Finding("", problem="compare() needs at least two gene symbols")

        build = self._builder()
        table = compare(symbols, records=[build(symbol) for symbol in symbols])
        genes = [gene["symbol"] if gene["resolved"] else f"{gene['query']} (unresolved)"
                 for gene in table["genes"]]
        lines = ["Genes: " + ", ".join(genes)]
        for gene in table["genes"]:
            if not gene["resolved"]:
                lines.append(f"  {gene['query']}: {gene['reason']}")
        citations = []
        for section in table["sections"]:
            lines.append(section["label"])
            for row in section["rows"]:
                if row["type"] in self.SKIP_TYPES:
                    continue
                cells = []
                for gene, cell in zip(genes, row["cells"]):
                    shown = cell["display"] if not cell["state"] else cell["state"].replace("_", " ")
                    mark = " (highest)" if cell.get("notable") else ""
                    cells.append(f"{gene} {shown}{mark}")
                unit = f" ({row['unit']})" if row["unit"] else ""
                lines.append(f"  [{row['field']}] {row['label']}{unit}: " + "; ".join(cells))
                if row["filled"]:
                    citations.append(f"[{row['field']}]")
        return Finding("\n".join(lines), citations=sorted(set(citations)),
                       raw=f"compared {len(symbols)} genes on {len(citations)} fields")


# -- the catalogue ----------------------------------------------------------


def default_tools() -> dict[str, Tool]:
    """Every tool: the user's documents, the record, comparison, and each view the
    report shows beside the record (`spica/agents/views.py`)."""
    from spica.agents.views import view_tools

    return {tool.key: tool for tool in (Documents(), Record(), Compare(), *view_tools())}


def catalogue(tools: dict[str, Tool], used: list[str] | None = None) -> str:
    """The tools as the orchestrator sees them, with what each holds.

    The status line is Betelgeuse's idea and it earns its place: an agent
    told the document library is empty stops trying to search it.
    """
    spent = set(used or [])
    lines = []
    for key, tool in tools.items():
        try:
            detail = tool.status()
        except Exception as exc:  # a broken status must not stop a run
            detail = f"unavailable: {exc}"
        note = "  (used already)" if key in spent else ""
        lines.append(f"  {tool.usage}\n      {detail}{note}")
    return "\n".join(lines)


MOVE = re.compile(r'^([a-z_]+)\s*\(\s*(.*?)\s*\)\s*$', re.DOTALL)

#: A weak model copies the placeholder out of the usage line rather than
#: filling it in. Caught here, where the message can say so, instead of
#: being run as a search for the literal text "<gene>".
PLACEHOLDER = re.compile(r"<[^>]+>|\bGENE\d\b|\byour question\b|\bthe question\b",
                         re.IGNORECASE)


def is_placeholder(argument: str) -> bool:
    return bool(PLACEHOLDER.search(argument or ""))


def parse_call(text: str) -> tuple[str, str] | None:
    """Read `documents("delivery")` into ("documents", "delivery").

    Quotes are optional because models forget them, and a bare word is
    unambiguous anyway.
    """
    # Small models write `Record("PCSK9")` or number their calls `2. record(...)`.
    text = re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", text.strip()).rstrip(";").strip("`")
    match = MOVE.match(text[:1].lower() + text[1:] if text else text)
    if not match:
        return None
    name, argument = match.group(1).lower(), match.group(2).strip()
    if len(argument) >= 2 and argument[0] == argument[-1] and argument[0] in "\"'":
        argument = argument[1:-1]
    return name, argument
