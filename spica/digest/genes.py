"""The genes that a passage names, through HGNC, as people say them.

A transcript writes what was spoken: "HER2" becomes "her two", and
"CLDN18.2" becomes "CLDN18.2", "claudin 18.2" or "Claudin-18.2". A passage
is thus read in three ways:
- written symbols: capitals with a digit, or capitals alone from three letters,
- spoken symbols: a short word, then a number ("her two", "trop 2"),
- symbols with an isoform suffix, without the suffix ("CLDN18.2" names CLDN18).
Each candidate is looked up among the approved symbols, aliases and previous
symbols of HGNC. An alias that two genes share is never used.

It does not read "MET" in a sentence about a meeting as the MET receptor.
Lower-case words are never symbols, and clinical abbreviations that are
also gene aliases (ADC, CAR, ORR) are excluded. Tags help search; they are
not claims. The passage always shows with them.
"""

from __future__ import annotations

import re
from typing import Iterable

#: Abbreviations a cancer podcast says all the time that happen to be HGNC
#: symbols or aliases. Read as genes they would tag half the passages.
STOP = frozenset("""
ADC ADCS AND ALL AML ASCO AACR ESMO CAR CART CEO CFO CLL CRC DFS DLBCL DNA EMA ECOG EFS FDA
GVHD HCC ICI ICU IRB MRD MRI NCCN NCI NIH NSCLC ORR PFS PET PHD RNA SCLC SOC TKI TNBC TMB USA
WHO AACR CNS CTDNA CTC EGFR-TKI HRD IHC FISH NGS PCR RCT SAE TEAE AI ML NHS EU UK MD PI QOL
CAT SET MAX IMPACT CELL CAN ARE HAS NOT BUT THE FOR WAS ONE TWO SIX TEN
""".split())

NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
           "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}
SPOKEN = re.compile(r"\b([A-Za-z]{2,6})[ -](" + "|".join(NUMBERS) + r"|\d{1,2})\b", re.I)
WRITTEN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*\b")

_VOCAB: dict[str, dict[str, str]] = {}


def _key(token: str) -> str:
    return re.sub(r"[.\-]", "", token.upper())


def vocabulary(mirror) -> dict[str, str]:
    """Normalised name -> HGNC symbol, from the mirror's HGNC copy."""
    from spica.sources.base import split_list
    from spica.sources.hgnc import table

    entry = mirror.entry("hgnc") if mirror is not None else None
    if entry is None or entry.missing_files():
        return {}
    path = entry.path("complete_set")
    stamp = f"{path}|{path.stat().st_size}|{int(path.stat().st_mtime)}"
    if stamp not in _VOCAB:
        names: dict[str, set[str]] = {}
        for row in table(path)["rows"]:
            symbol = row["symbol"]
            if len(symbol) >= 3:
                names.setdefault(_key(symbol), set()).add(symbol)
            for other in split_list(row.get("alias_symbol", "")) + split_list(row.get("prev_symbol", "")):
                if len(other) >= 3 and (len(other) >= 4 or any(c.isdigit() for c in other)):
                    names.setdefault(_key(other), set()).add(symbol)
        _VOCAB.clear()
        _VOCAB[stamp] = {key: next(iter(found)) for key, found in names.items()
                         if len(found) == 1 and key not in STOP}
    return _VOCAB[stamp]


#: Words a number follows in speech that are never half a gene name:
#: "phase two" is not PHASE2, "top two" is not TOP2.
NOT_NAMES = frozenset("""
the and or of to in on at by for with from top day page phase arm part cohort stage grade type line
week weeks year years figure table dose level step cycle group number chapter section round trial
study patient patients point only last first next about over under than all some
it is has have had was be we me he she you they them get got see say said one two are its any
did does do can may might must will would could should not no yes now then this that these those
his him who what when where why how out up down off into onto via per each every both either
take took make made give gave keep let lot lots bit like just very more most less least many much
""".split())


#: "EGFR" said letter by letter is written "EGF or" by speech recognition.
LETTER_R = re.compile(r"\b([A-Z]{2,6}) or\b")


#: How speech recognition tends to spell a spoken symbol's letters.
HEARD = {"trope": "TROP", "her": "HER", "erb": "ERB", "cd": "CD", "pd": "PD", "il": "IL"}


def candidates(text: str) -> Iterable[str]:
    for match in LETTER_R.finditer(text):
        yield match.group(1) + "R"
    for match in SPOKEN.finditer(text):
        word, number = match.group(1), match.group(2).lower()
        if word.lower() not in NOT_NAMES:
            yield HEARD.get(word.lower(), word) + NUMBERS.get(number, number)
    for token in WRITTEN.findall(text):
        upper = sum(1 for c in token if c.isupper())
        digit = any(c.isdigit() for c in token)
        # Written symbols are capitals: with a digit from two capitals
        # ("HER2", "PD-L1"), without one from three, all capitals ("KRAS").
        if (digit and upper >= 2) or (len(token) >= 3 and token.isupper()):
            if re.search(r"\b" + re.escape(token) + r" or\b", text):
                continue  # "EGF or" was EGFR, read above
            yield token
            stem = re.sub(r"\.\d+$", "", token)  # CLDN18.2 names CLDN18
            if stem != token:
                yield stem


def tag(text: str, vocab: dict[str, str]) -> list[str]:
    found = set()
    for candidate in candidates(text):
        key = _key(candidate)
        if key in STOP:
            continue
        symbol = vocab.get(key)
        if symbol:
            found.add(symbol)
    return sorted(found)
