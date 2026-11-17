"""A gene at a glance: the words that its annotations repeat.

Two word maps, at the top of a report, before any section opens:

*Function*, from the Gene Ontology terms of the gene (process, function
and component, as in UniProt). The weight of a word is the number of terms
that use it. The PCSK9 terms repeat "receptor", "low-density lipoprotein"
and "plasma membrane". The CLDN18 terms repeat "tight junction",
"epithelial" and "adhesion".

*Disease*, from the Open Targets associations. The weight of a word is the
sum of the squared association scores of each disease whose name uses it.
The square matters because a gene can have thousands of faint associations.
With a plain sum, the many rare congenital conditions of EGFR at 0.02 would
outweigh its lung cancers at 0.8. With squares, one association at 0.8
counts as much as 1,600 at 0.02. A theme across strong associations
("hypercholesterolemia", "adenocarcinoma") then stands out. Associations
that are measurements, not diseases ("total cholesterol measurement",
"FEV/FVC ratio", hundreds per gene from GWAS), stay out of the map and are
counted.

Words, not full terms. GO terms and disease names have up to eight words,
and the repeated parts give the impression. Words that occur together stay
together. A pair becomes one phrase when it repeats and makes up at least
half the uses of each word ("endoplasmic reticulum", "myocardial
infarction"). A run of such pairs becomes one longer phrase ("epidermal
growth factor").

Each word keeps its source terms, so the impression always leads back to
its evidence. As in the rest of the report, this comes from the record
alone and is deterministic: no model, no randomness, ties sorted
alphabetically.
"""

from __future__ import annotations

import re
from typing import Any

from spica.record import GeneRecord

GO_FIELDS = ("go_process", "go_function", "go_component")
DISEASE_FIELD = "disease_associations"

#: Hyphenated compounds stay whole ("low-density", "non-small"), and so do
#: slashed abbreviations ("FEV/FVC"); other slashes separate words.
TOKEN = re.compile(r"[A-Z0-9]{2,}(?:/[A-Z0-9]{2,})+|[A-Za-z0-9](?:[A-Za-z0-9'+-]*[A-Za-z0-9])?")

GRAMMAR = frozenset("""
a an and as at by for from in into of on or the to via with within without across between
""".split())

#: Words every GO term could use: they say what kind of statement a term
#: is, not what the gene does.
GO_STOP = GRAMMAR | frozenset("""
positive negative regulation regulates process processes activity activities binding
involved cellular cell cells protein proteins response stimulus particle component side
region organization assembly type complex molecule identical establishment maintenance
other organism multicellular organismal biological external extrinsic intrinsic integral
part single containing dependent mediated
""".split())

#: Words that say what kind of association it is, or how it presents,
#: rather than with what.
DISEASE_STOP = GRAMMAR | frozenset("""
disease diseases disorder disorders syndrome mellitus type susceptibility finding
abnormality abnormal response adverse event events cell cells trait traits quality system
autosomal dominant recessive familial hereditary inherited primary secondary
early late onset childhood adult juvenile exposure acute chronic
due associated isolated rare partial complete differences left right recurrent
cessation initiation
""".split())

#: An association whose name marks it as a measurement, not a disease:
#: "... measurement", "... ratio", metabolomic lipoprotein traits ("total
#: lipids in small VLDL", "VLDL particle size"), blood counts ("mean
#: corpuscular volume"), body measures ("body mass index", "bone mineral
#: density"), and behaviours ("sleep duration", "heart rate").
MEASUREMENT = re.compile(
    r"\b(measurement|ratio|amount|percentage|levels?|concentration|quantity|count|size"
    r"|rate|duration|physical activity|index|density)\b"
    r"|^(?:total|mean)\b|\bvolume\b"
    r"|\bin\s+(?:(?:very |extremely |extra )?(?:small|medium|large)\s+)?(?:V?LDL|IDL|HDL)\b",
    re.IGNORECASE)

#: A pair becomes one phrase when it occurs in at least this many terms and
#: makes up at least this share of the uses of each word.
PAIR_MIN = 2
PAIR_SHARE = 0.5


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text)


def _keep(word: str, stop: frozenset[str]) -> bool:
    lower = word.lower()
    if lower in stop or lower.isdigit():
        return False
    if sum(c.isdigit() for c in word) > len(word) / 2:
        return False
    return len(word) >= 3 or (len(word) == 2 and word.isupper())


def runs(phrase: str, stop: frozenset[str]) -> list[list[tuple[int, str]]]:
    """The phrase's kept words, in stretches a dropped word breaks:
    "negative regulation of receptor internalization" gives one stretch,
    [receptor, internalization]. Each word keeps its position."""
    out: list[list[tuple[int, str]]] = [[]]
    for position, word in enumerate(tokens(phrase)):
        if _keep(word, stop):
            out[-1].append((position, word))
        elif out[-1]:
            out.append([])
    return [run for run in out if run]


class _Casing:
    """How each word is written across all the terms, to decide how to show it."""

    def __init__(self, sentence_case: bool) -> None:
        self.sentence_case = sentence_case
        self.variants: dict[str, dict[str, int]] = {}
        self.proper: set[str] = set()
        self.lower: set[str] = set()

    def see(self, position: int, word: str) -> None:
        key = word.lower()
        forms = self.variants.setdefault(key, {})
        forms[word] = forms.get(word, 0) + 1
        if not word[:1].isupper():
            self.lower.add(key)
        elif position > 0:
            self.proper.add(key)

    def show(self, key: str) -> str:
        """Its own casing when the casing has meaning: capitals inside the
        word ("LDL", "COPII-coated", "FEV/FVC"), or a capital that it always
        keeps ("Golgi"). Lower case otherwise.

        Disease names use sentence case, and some start with a capital for
        no reason. There, a leading capital counts only if the word also
        keeps it inside names. "Hypercholesterolemia" is thus the same word
        as in "familial hypercholesterolemia". GO terms are lower case, so a
        capital there always marks a name.
        """
        forms = self.variants.get(key, {key: 1})
        ranked = sorted(forms, key=lambda v: (-forms[v], v))
        inner = [v for v in ranked if any(c.isupper() for c in v[1:])]
        if inner:
            return inner[0]
        capital = key in self.proper if self.sentence_case else True
        if capital and key not in self.lower and ranked[0][:1].isupper():
            return ranked[0]
        return key


def _pairs(phrases: list[str], stop: frozenset[str]) -> set[tuple[str, str]]:
    """Adjacent words that travel together, by the rule in PAIR_MIN/SHARE."""
    uses: dict[str, int] = {}
    together: dict[tuple[str, str], int] = {}
    for phrase in phrases:
        words: set[str] = set()
        pairs: set[tuple[str, str]] = set()
        for run in runs(phrase, stop):
            keys = [word.lower() for _, word in run]
            words.update(keys)
            pairs.update(zip(keys, keys[1:]))
        for key in words:
            uses[key] = uses.get(key, 0) + 1
        for pair in pairs:
            together[pair] = together.get(pair, 0) + 1
    return {pair for pair, n in together.items()
            if n >= PAIR_MIN and n >= PAIR_SHARE * uses[pair[0]]
            and n >= PAIR_SHARE * uses[pair[1]]}


def units(phrase: str, stop: frozenset[str], joined: set[tuple[str, str]]) -> list[list[str]]:
    """The phrase as the words and joined phrases a map counts."""
    out: list[list[str]] = []
    for run in runs(phrase, stop):
        current = [run[0][1]]
        for (_, before), (_, word) in zip(run, run[1:]):
            if (before.lower(), word.lower()) in joined:
                current.append(word)
            else:
                out.append(current)
                current = [word]
        out.append(current)
    return out


def word_map(phrases: list[tuple[str, float]], stop: frozenset[str],
             weighted: bool, sentence_case: bool = False) -> list[dict[str, Any]]:
    """Words and joined phrases of the terms, heaviest first.

    `phrases` pairs each term with its weight. With `weighted`, a word
    weighs the sum of its terms' squared weights; without, the number of
    terms that use it. Each word keeps its terms, heaviest first.
    """
    weight_of = dict(phrases)
    texts = list(weight_of)
    casing = _Casing(sentence_case)
    for text in texts:
        for run in runs(text, stop):
            for position, word in run:
                casing.see(position, word)
    joined = _pairs(texts, stop)

    found: dict[str, set[str]] = {}
    for text in texts:
        for unit in units(text, stop, joined):
            # A lone fragment that starts with a digit ("3-kinase" out of
            # "phosphatidylinositol 3-kinase", "1G" out of "limb-girdle 1G")
            # means nothing on its own.
            if len(unit) == 1 and unit[0][:1].isdigit():
                continue
            found.setdefault(" ".join(w.lower() for w in unit), set()).add(text)
    # "receptors" joins "receptor" when both occur; alone, it stays.
    for key in sorted(found):
        if key.endswith("s") and key[:-1] in found:
            found[key[:-1]] |= found.pop(key)

    words = []
    for key, sources in found.items():
        ordered = sorted(sources, key=lambda p: (-weight_of[p], p.lower()))
        weight = sum(weight_of[p] ** 2 for p in ordered) if weighted else len(ordered)
        words.append({
            "word": " ".join(casing.show(part) for part in key.split(" ")),
            "weight": round(weight, 3),
            "count": len(ordered),
            "from": [[p, weight_of[p]] for p in ordered] if weighted else ordered,
        })
    words.sort(key=lambda w: (-w["weight"], -w["count"], w["word"].lower()))
    return words


def _stamp(record: GeneRecord, name: str) -> str:
    provenance = record[name].provenance
    return f"{provenance.source} {provenance.version}".strip() if provenance else ""


def function_map(record: GeneRecord) -> dict[str, Any]:
    terms: list[str] = []
    reasons, stamp = [], ""
    for name in GO_FIELDS:
        value = record[name]
        if value.present:
            terms += [t for t in value.value if t not in terms]
            stamp = stamp or _stamp(record, name)
        else:
            reasons.append(value.reason)
    if not terms:
        return {"words": [], "terms": 0, "source": stamp,
                "reason": reasons[0] if reasons else "No Gene Ontology terms for this gene."}
    return {"words": word_map([(t, 1.0) for t in terms], GO_STOP, weighted=False),
            "terms": len(terms), "source": f"Gene Ontology, via {stamp}" if stamp else "",
            "reason": ""}


def disease_map(record: GeneRecord) -> dict[str, Any]:
    value = record[DISEASE_FIELD]
    if not value.present or not value.value:
        return {"words": [], "terms": 0, "source": _stamp(record, DISEASE_FIELD),
                "reason": value.reason or "No disease associations for this gene."}
    associations = [(str(name), float(score)) for name, score in value.value.items()
                    if isinstance(score, (int, float))]
    diseases = [pair for pair in associations if not MEASUREMENT.search(pair[0])]
    out = {"words": word_map(diseases, DISEASE_STOP, weighted=True, sentence_case=True),
           "terms": len(diseases), "measurements": len(associations) - len(diseases),
           "source": _stamp(record, DISEASE_FIELD), "reason": ""}
    if not diseases:
        out["reason"] = f"All {len(associations)} associations are measurements, not diseases."
    return out


def glance(record: GeneRecord) -> dict[str, Any]:
    return {"function": function_map(record), "disease": disease_map(record)}
