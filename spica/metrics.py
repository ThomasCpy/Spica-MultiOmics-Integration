"""Derived measures that compare across genes.

A record full of numbers is not yet a triage tool. 77 TPM in liver has
little meaning without context. The gene can be liver-restricted, or near
the top of a flat profile, and the two lead to opposite decisions. These
measures make that difference visible. They are the reason to read a Spica
record and not a UniProt page.

Adapted from `core/analysis.py` of the MultiOmics integrator, which had the
two measures that matter:

*τ, the specificity index* (Yanai et al. 2005), the de facto standard. 0
is uniform across all contexts; 1 is one context only. It compares across
genes, tissues and assays, which a raw peak value never does.

*Fold over median*, for the other half: how far the top context stands
above the typical one.

All of this is plain arithmetic on values in the record. A derived field
is thus as reproducible as its source field.
"""

from __future__ import annotations

import math

import re
import statistics
from typing import Iterable, Mapping

#: Below 2 contexts, specificity is not defined: one value cannot be
#: concentrated anywhere relative to anything.
MIN_CONTEXTS = 2

#: Specificity bands. The boundaries are the integrator's, and they are
#: judgement rather than mathematics: τ is continuous, and these are where
#: the continuum becomes a decision.
BANDS = (
    (0.15, "Ubiquitous"),
    (0.50, "Broadly expressed"),
    (0.85, "Context-enhanced"),
)
HIGHLY_SPECIFIC = "Highly specific"


def numbers(values: Iterable) -> list[float]:
    """The usable numbers out of a mixed bag, negatives dropped."""
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value >= 0:
            out.append(float(value))
    return out


def tau(values: Iterable) -> float | None:
    """The specificity index: 0 for uniform expression, 1 for one place only.

        τ = Σ (1 - x_i / x_max) / (n - 1)

    Returns None when it has no definition (fewer than two contexts, or an
    all-zero profile). A number in that case would be compared with real
    ones.
    """
    vals = numbers(values)
    if len(vals) < MIN_CONTEXTS:
        return None
    peak = max(vals)
    if peak <= 0:
        return None
    return round(sum(1 - (value / peak) for value in vals) / (len(vals) - 1), 3)


#: Below this share of lines, and gathered nowhere, a gene is rarely a
#: dependency.
RARE_DEPENDENCY = 5.0
#: A lineage holds a dependency when it has this many lines, at least this
#: share of them depend on the gene, and that share is twice the overall one.
#: ESR1 qualifies through breast (about 19% of 53 lines, against 1% overall).
#: PCSK9, with 4 breast lines of 53, does not.
LINEAGE_MIN_LINES = 10
LINEAGE_MIN_SHARE = 15.0


def dependency_profile(share: float, common_essential: bool,
                       lineages: dict[str, float]) -> str:
    """DepMap's screens in one sentence: common essential, selective, or rare.

    `lineages` is keyed "Lung, 120 lines", as the record holds it.
    """
    if common_essential:
        return (f"Common essential: {share:g}% of lines depend on it. Inhibiting it is likely "
                f"to reach healthy dividing cells too.")
    gathered = []
    for key, value in lineages.items():
        name, _, count = key.rpartition(", ")
        lines = int(count.split()[0]) if count.split() and count.split()[0].isdigit() else 0
        if lines >= LINEAGE_MIN_LINES and value >= max(2 * share, LINEAGE_MIN_SHARE):
            gathered.append((value, name, lines))
    if gathered:
        value, name, lines = max(gathered)
        return (f"Selective: {share:g}% of lines depend on it, most in {name} "
                f"({value:g}% of {lines} lines).")
    if share < RARE_DEPENDENCY:
        return f"Rarely a dependency: {share:g}% of lines."
    return f"A dependency in {share:g}% of lines, spread across lineages."


def tau_bands() -> list[dict[str, float | str]]:
    """The bands as ranges, for a view that draws them."""
    out, low = [], 0.0
    for limit, label in BANDS:
        out.append({"from": low, "to": limit, "label": label})
        low = limit
    out.append({"from": low, "to": 1.0, "label": HIGHLY_SPECIFIC})
    return out


def specificity_class(score: float | None) -> str | None:
    """The band a τ falls in, as a phrase a report can print."""
    if score is None:
        return None
    for limit, label in BANDS:
        if score < limit:
            return label
    return HIGHLY_SPECIFIC


def fold_over_median(values: Iterable) -> float | None:
    """How far the top context stands above the typical one.

    When the median is zero (common for a profile detected in two of fifty
    tissues), the median of the non-zero contexts applies. The answer is
    then "20× the tissues where it is present", not a division by zero or a
    misleading infinity.
    """
    vals = numbers(values)
    if len(vals) < MIN_CONTEXTS:
        return None
    peak = max(vals)
    middle = statistics.median(vals)
    if middle <= 0:
        present = [value for value in vals if value > 0]
        middle = statistics.median(present) if present else 0.0
    if middle <= 0:
        return None
    return round(peak / middle, 1)


def peak(values: Mapping[str, float]) -> tuple[str, float] | None:
    """The highest context and its value; ties go to the first by name, so
    the same profile always names the same context."""
    usable = {key: float(value) for key, value in values.items()
              if not isinstance(value, bool) and isinstance(value, (int, float))}
    if not usable:
        return None
    return min(usable.items(), key=lambda item: (-item[1], item[0]))


# -- reconciling tissue vocabularies ----------------------------------------
#
# GTEx says "Brain_Cortex", the Human Protein Atlas says "cerebral cortex",
# UniProt says "brain". Comparing an RNA profile against a protein one means
# first agreeing on what organ each label refers to. This vocabulary is the
# integrator's, including the trap it documents: "cortex" alone is not a
# brain keyword, because the adrenal and the kidney have one too.

ORGANS: dict[str, tuple[str, ...]] = {
    "liver": ("liver", "hepat"),
    "brain": ("brain", "cerebr", "cerebell", "hippocamp", "neural",
              "amygdala", "frontal", "hypothalamus", "putamen", "caudate",
              "nucleus accumbens", "spinal", "basal ganglia", "choroid plexus",
              "midbrain", "substantia nigra", "pons", "medulla oblongata"),
    "heart": ("heart", "cardi", "ventricle", "atri", "myocard"),
    # Peripheral nerve is not brain. It used to be, through a "nerve"
    # keyword, and GTEx's tibial nerve then became the brain's peak.
    "nerve": ("nerve",),
    "lung": ("lung", "pulmon", "bronch", "alveol"),
    "kidney": ("kidney", "renal", "nephron"),
    "blood": ("blood", "platelet", "plasma", "pbmc", "serum", "leukocyte",
              "lymphocyte", "monocyte", "neutrophil"),
    "muscle": ("skeletal muscle", "myocyte", "myotube", "muscle"),
    "skin": ("skin", "epiderm", "keratin"),
    "pancreas": ("pancrea", "islet"),
    "spleen": ("spleen", "splen"),
    "stomach": ("stomach", "gastric"),
    "intestine": ("colon", "intestin", "bowel", "rectum", "ileum", "duoden",
                  "jejun", "appendix", "cecum"),
    "testis": ("testis", "testic", "sperm"),
    "ovary": ("ovary", "ovari"),
    "prostate": ("prostat",),
    # "thyroid" does not match inside "parathyroid": the keyword is anchored
    # to a word boundary, and para|thyroid has none. The two stay separate,
    # which is the same trap as adrenal against renal.
    "thyroid": ("thyroid",),
    "parathyroid": ("parathyroid",),
    "adipose": ("adipose", "fat"),
    "breast": ("breast", "mammary"),
    "bladder": ("bladder", "urothel"),
    "esophagus": ("esophag", "oesophag"),
    "adrenal": ("adrenal",),
    "pituitary": ("pituitar",),
    "salivary": ("salivary",),
    "uterus": ("uter", "endometr", "cervix"),
    "placenta": ("placent", "trophobl"),
    "lymphoid": ("lymph", "tonsil", "node", "thymus"),
    "bone": ("bone", "marrow", "osteo"),
    "eye": ("retina", "eye"),
    "gallbladder": ("gallbladder", "biliary"),
    "vessel": ("artery", "aorta", "coronary", "vein", "vascular",
               "blood vessel"),
    "fallopian tube": ("fallopian", "oviduct"),
    "epididymis": ("epididym",),
    "seminal vesicle": ("seminal",),
    "vagina": ("vagina",),
    "tongue": ("tongue",),
    # Not an organ, but a real measurement context, and GTEx has two of
    # them. Naming it keeps the values in the view instead of in a
    # footnote of things that did not match.
    "cultured cells": ("cultured", "cell line", "transformed lymphocyte",
                       "fibroblast"),
}


#: Labels that name two organs' keywords but mean one organ. Keyword
#: matching sends a label to every organ it mentions, which for these is
#: wrong and not harmless: "heart muscle" put cardiac values into the
#: skeletal-muscle row, "blood vessel" put vascular ones into blood.
EXACT: dict[str, str] = {
    "heart muscle": "heart",
    "blood vessel": "vessel",
    # HPA staining sites with no organ word in their name.
    "dorsal raphe": "brain",  # a brainstem nucleus
    "hair": "skin",
    "sole of foot": "skin",
    "efferent ducts": "epididymis",  # they drain the testis into it
}


def organs(label: str) -> frozenset[str]:
    """The canonical organs a tissue label refers to.

    Word-boundary matching, so "adrenal" does not match the kidney keyword
    "renal": the kind of silent mismatch that makes a concordance figure
    worse than no figure at all.
    """
    lowered = (label or "").lower().replace("_", " ").strip()
    if lowered in EXACT:
        return frozenset({EXACT[lowered]})
    # A cell line is a cell line, whatever it was derived from: GTEx's
    # EBV-transformed lymphocytes are not blood and not lymphoid tissue.
    if lowered.startswith("cells - "):
        return frozenset({"cultured cells"})
    return frozenset(
        organ for organ, keywords in ORGANS.items()
        if any(re.search(r"\b" + re.escape(word), lowered) for word in keywords)
    )


def concordance(first: Mapping[str, float], second: Mapping[str, object],
                names: tuple[str, str] = ("RNA", "protein"),
                caveat: str = "") -> str | None:
    """Whether two profiles peak in the same organ.

    Used twice, for two different questions. Between RNA and protein it
    asks whether a transcript peak is explained by the protein
    being there. Between two RNA atlases it asks whether the profile is
    real or an artefact of one pipeline. Either way the useful answer is
    the disagreement, so the wording is a parameter rather than a sentence
    baked in.
    """
    if not first or not second:
        return None
    top_rna = peak(first)
    if top_rna is None:
        return None

    ranked = _rank_labels(second)
    if not ranked:
        return None

    rna_organs = organs(top_rna[0])
    protein_organs = organs(ranked[0])
    if not rna_organs or not protein_organs:
        return None

    left, right = names
    if rna_organs & protein_organs:
        return (f"Concordant: {left} and {right} both peak in "
                f"{sorted(rna_organs & protein_organs)[0]}")
    tail = f" {caveat}" if caveat else ""
    return (f"Discordant: {left} peaks in {sorted(rna_organs)[0]}, {right} in "
            f"{sorted(protein_organs)[0]}.{tail}")


#: Antibody staining levels, strongest first, so a text profile can be ranked.
LEVELS = ("high", "medium", "low", "not detected")


def _rank_labels(profile: Mapping[str, object]) -> list[str]:
    """Contexts of a profile, strongest first, numeric or graded."""
    numeric = {key: value for key, value in profile.items()
               if not isinstance(value, bool) and isinstance(value, (int, float))}
    if numeric:
        return [key for key, _ in sorted(numeric.items(),
                                         key=lambda item: (-item[1], item[0]))]

    graded: list[tuple[int, str]] = []
    for key, value in profile.items():
        try:
            rank = LEVELS.index(str(value).strip().lower())
        except ValueError:
            continue
        graded.append((rank, key))
    return [key for _, key in sorted(graded)]


#: Fewer shared organs than this and a correlation says nothing.
MIN_SHARED = 5


def _ranks(values: list[float]) -> list[float]:
    """Ranks from 1, ties sharing the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda at: values[at])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman(first: list[float], second: list[float]) -> float | None:
    """Spearman's rank correlation, or None when it would mean nothing:
    too few points, or one side flat (every organ the same)."""
    if len(first) != len(second) or len(first) < MIN_SHARED:
        return None
    a, b = _ranks(first), _ranks(second)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    da, db = [x - mean_a for x in a], [y - mean_b for y in b]
    spread = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if spread < 1e-9:  # flat, up to rounding: nothing to correlate
        return None
    return sum(x * y for x, y in zip(da, db)) / spread


def log_correlation(first: list[float], second: list[float]) -> float | None:
    """Pearson r between log(1 + value) profiles, or None when it has no
    meaning (too few points, or one flat side).

    This measures whether two sources agree on where a gene is expressed.
    Ranks do not. For a specific gene (CLDN18 in stomach and lung) most
    organs are near zero, and their order is noise. Spearman then reads two
    atlases that agree on each important organ as barely correlated (0.37;
    this gives 0.95). On the log scale, the organs with the expression carry
    the measure, and a ten-fold step counts the same everywhere.
    """
    if len(first) != len(second) or len(first) < MIN_SHARED:
        return None
    a = [math.log1p(max(x, 0.0)) for x in first]
    b = [math.log1p(max(y, 0.0)) for y in second]
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    da, db = [x - mean_a for x in a], [y - mean_b for y in b]
    spread = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if spread < 1e-9:  # flat, up to rounding: nothing to correlate
        return None
    return sum(x * y for x, y in zip(da, db)) / spread
