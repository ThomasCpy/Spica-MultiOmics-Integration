"""The check of the draft against the record, in code, not in a model.

The roadmap requires a field citation for each claim of the LLM, and a
check of each citation. A second model that judges support is not a check.
It can be wrong in the same direction as the first. This stage is thus
plain code with plain rules, and it cannot hallucinate:

1. A cited field must exist in the schema.
2. A cited field must have a value in this record. A citation of a field
   marked `not_found` is the worst failure: it looks sourced and is not.
3. A sentence with a number must cite something.
4. A prose draft that cites nothing has failed, whatever it says.
5. A number in a sentence must occur in one of the cited fields.

Rule 5 gives a warning, not a failure: a draft can correctly say "three of
five sources" about the record. Rules 1 to 4 are failures.

Rule 4 exists because of the typical failure of a weak model. It writes a
fluent, plausible assessment and omits all brackets. A check of only the
present citations then reports "no claims to check". That gives a clean
verdict on unsourced prose, which is worse than no check.
"""

from __future__ import annotations

import re
from typing import Any

from spica.record import GeneRecord
from spica.agents.context import known_fields, present_text

CITATION = re.compile(r"\[([a-z0-9_]+)\]")
# A number, not a digit inside a name. Gene symbols and accessions are full
# of digits -- PCSK9, Q8NBP7, 1p32.3, HGNC:20001 -- and reading those as
# claims made every sourced sentence look unsupported.
NUMBER = re.compile(r"(?<![\w.:-])-?\d+(?:\.\d+)?(?![\w.])")
# Sentences end at punctuation followed by space, never mid-token: splitting
# on every "." cut "77.41" into two claims, and neither half meant anything.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")

SEVERITY = {"unknown_field": "error", "empty_field": "error",
            "uncited_number": "error", "nothing_cited": "error",
            "unsupported_number": "warning"}

# Below this a "draft" is a sentence fragment or a refusal, not prose that
# should have been sourced.
PROSE = 40


def _numbers(text: str) -> list[str]:
    """Numbers in a claim, with citation names and markdown left out."""
    stripped = CITATION.sub(" ", text)
    return NUMBER.findall(stripped)


def _matches(number: str, haystack: str) -> bool:
    """Whether the number occurs in the cited text, allowing for rounding in prose.

    Compared against the numbers in the field rather than against its text:
    a substring test said 0 was supported by "12.05", which is how an
    invented figure passes a check that looks like it works.
    """
    candidates = NUMBER.findall(haystack)
    if number in candidates:
        return True
    try:
        value = float(number)
    except ValueError:
        return False
    for candidate in candidates:
        try:
            other = float(candidate)
        except ValueError:
            continue
        # "about 25 TPM" for 25.55: rounding is allowed, but only to
        # something that rounds back.
        if other == value or round(other) == value or round(other, 1) == value:
            return True
    return False


def verify(draft: str, record: GeneRecord) -> dict[str, Any]:
    """Check every claim in `draft`. Returns the verdict as plain data."""
    available = present_text(record)
    schema = known_fields()
    problems: list[dict[str, str]] = []
    cited: set[str] = set()
    claims = 0
    sentences = 0
    sourced = 0

    for raw in SENTENCE_BREAK.split(draft):
        sentence = raw.strip()
        if not sentence or sentence.startswith("#"):
            continue
        body = sentence.lstrip("-*0123456789. ").strip()
        if not body:
            continue

        sentences += 1
        names = CITATION.findall(sentence)
        numbers = _numbers(sentence)
        if names:
            sourced += 1
        if not names and not numbers:
            continue
        claims += 1
        cited.update(names)

        for name in names:
            if name not in schema:
                problems.append({
                    "kind": "unknown_field",
                    "field": name,
                    "detail": f"cites [{name}], which is not a field in the record",
                    "claim": sentence,
                })
            elif name not in available:
                state = record.fields[name].state
                problems.append({
                    "kind": "empty_field",
                    "field": name,
                    "detail": (f"cites [{name}], which has no value in this record "
                               f"({state.value if state else 'empty'})"),
                    "claim": sentence,
                })

        if numbers and not names:
            problems.append({
                "kind": "uncited_number",
                "field": "",
                "detail": f"states {', '.join(numbers)} without citing a field",
                "claim": sentence,
            })
            continue

        supported = " ".join(available.get(name, "") for name in names)
        for number in numbers:
            if not _matches(number, supported):
                problems.append({
                    "kind": "unsupported_number",
                    "field": ", ".join(names),
                    "detail": (f"states {number}, which is not in "
                               f"{' or '.join('[' + n + ']' for n in names)}"),
                    "claim": sentence,
                })

    if sentences and not cited and len(draft.strip()) >= PROSE:
        problems.append({
            "kind": "nothing_cited",
            "field": "",
            "detail": (f"{sentences} sentences and not one cites the record. "
                       f"An assessment that names no field is not sourced."),
            "claim": "",
        })

    errors = [p for p in problems if SEVERITY.get(p["kind"]) == "error"]
    return {
        "ok": not errors,
        "claims": claims,
        "sentences": sentences,
        "sourced": sourced,
        "citations": sorted(cited),
        "problems": [dict(problem, severity=SEVERITY.get(problem["kind"], "error"))
                     for problem in problems],
        "errors": len(errors),
        "warnings": len(problems) - len(errors),
        "summary": summarize(sentences, sourced, len(cited), errors, problems),
    }


def summarize(sentences: int, sourced: int, fields: int,
              errors: list, problems: list) -> str:
    """One line, in the product's voice: what was checked and what held."""
    if not sentences:
        return "Nothing to check: the draft is empty."
    if not sourced:
        return f"None of the {sentences} sentences cites the record."

    checked = (f"{sourced} of {sentences} sentences cite the record, "
               f"across {fields} field{'s' if fields != 1 else ''}")
    if errors:
        return f"{checked}. {len(errors)} do not hold."
    if problems:
        return f"{checked}. {len(problems)} numbers worth a look."
    return f"{checked}. Every citation holds."


# -- answers ----------------------------------------------------------------
#
# A record claim cites a schema field, and the field either has a value or
# does not. An answer cites a passage of the user's documents, and the check
# is different in kind: the citation has to be one a tool vouched
# for. A model that writes a plausible page number has invented a source,
# and that is the failure this exists to catch.

ANY_CITATION = re.compile(r"\[([^\[\]]{1,120})\]")


def verify_answer(draft: str, notes) -> dict[str, Any]:
    """Check an AI-mode answer against the notes it was written from."""
    vouched: set[str] = set()
    said: dict[str, str] = {}  # citation -> what the tool returned under it
    for note in notes or []:
        for citation in getattr(note, "fields", []) or []:
            key = citation.strip("[]").strip()
            vouched.add(key)
            said[key] = said.get(key, "") + "\n" + (getattr(note, "sources", "") or note.text)

    problems: list[dict[str, str]] = []
    cited: set[str] = set()
    sentences = 0
    sourced = 0

    for raw in SENTENCE_BREAK.split(draft or ""):
        sentence = raw.strip()
        if not sentence or sentence.startswith("#"):
            continue
        body = sentence.lstrip("-*0123456789. ").strip()
        if not body:
            continue

        sentences += 1
        names = [name.strip() for name in ANY_CITATION.findall(sentence)]
        numbers = NUMBER.findall(ANY_CITATION.sub(" ", sentence))
        if names:
            sourced += 1
        cited.update(names)

        for name in names:
            # A note number is a citation too: the writer is given the notes
            # numbered, and "[3]" is a fair way to refer to one.
            if name.isdigit():
                if not (1 <= int(name) <= len(notes or [])):
                    problems.append({
                        "kind": "unknown_source", "field": name,
                        "detail": f"cites note [{name}], which does not exist",
                        "claim": sentence,
                    })
                continue
            if name not in vouched:
                problems.append({
                    "kind": "unknown_source", "field": name,
                    "detail": (f"cites [{name}], which no tool returned. "
                               f"The source was invented, not found."),
                    "claim": sentence,
                })

        if numbers and not names:
            problems.append({
                "kind": "uncited_number", "field": "",
                "detail": f"states {', '.join(numbers)} without citing anything",
                "claim": sentence,
            })
        elif numbers:
            # A number the cited tools never returned is a misquote, however
            # real the source: checked against what they said, not the note.
            haystack = "\n".join(said.get(name, "") for name in names if name in said)
            if haystack:
                missing = [number for number in numbers if not _matches(number, haystack)]
                if missing:
                    problems.append({
                        "kind": "unsupported_number", "field": ", ".join(names),
                        "detail": (f"states {', '.join(missing)}, which the cited tools did "
                                   f"not return"),
                        "claim": sentence,
                    })

    if sentences and not cited and len((draft or "").strip()) >= PROSE:
        problems.append({
            "kind": "nothing_cited", "field": "",
            "detail": (f"{sentences} sentences and not one cites a note. "
                       f"An answer that names no source is not grounded."),
            "claim": "",
        })

    errors = [p for p in problems if ANSWER_SEVERITY.get(p["kind"]) == "error"]
    return {
        "ok": not errors,
        "claims": sourced,
        "sentences": sentences,
        "sourced": sourced,
        "citations": sorted(cited),
        "problems": [dict(problem, severity=ANSWER_SEVERITY.get(problem["kind"], "error"))
                     for problem in problems],
        "errors": len(errors),
        "warnings": len(problems) - len(errors),
        "summary": summarize_answer(sentences, sourced, len(cited), errors, problems),
    }


def summarize_answer(sentences: int, sourced: int, sources: int,
                     errors: list, problems: list) -> str:
    """One line about an answer: what was checked and what held."""
    if not sentences:
        return "Nothing to check: the answer is empty."
    if not sourced:
        return f"None of the {sentences} sentences cites a source."
    checked = (f"{sourced} of {sentences} sentences cite a source, "
               f"across {sources} of them")
    if errors:
        return f"{checked}. {len(errors)} do not hold."
    if problems:
        return f"{checked}. {len(problems)} worth a look."
    return f"{checked}. Every citation was returned by a tool."


ANSWER_SEVERITY = {"unknown_source": "error", "uncited_number": "error",
                   "nothing_cited": "error", "unsupported_number": "warning"}
