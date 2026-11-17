"""Record build: resolve the gene, read each source, fill each field.

The order is fixed, and the result is always a complete record. A missing,
broken or silent source affects only its own fields. Each field stays in
the record, with its state and the sentence that gives the cause. Nothing
here raises: a half-built mirror is a normal condition for an offline tool.

Spica reads each source from the mirror when it is mirrored. Otherwise it
fetches the source from its public API, when the network is allowed (see
`live.py`). The record shows which one happened: the source is stamped
`read` or `fetched`, and the locator of a fetched value is its URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from spica import metrics
from spica.live import Fetched, Live, LiveError, NoLiveRoute, NotFoundUpstream
from spica.mirror import Mirror, MirrorEntry
from spica.record import (
    GeneRecord,
    NullState,
    Provenance,
    Resolution,
    SourceStamp,
    Value,
)
from spica.schema import (
    FIELDS,
    FIELDS_BY_NAME,
    SCHEMA_VERSION,
    FieldSpec,
    check_type,
    fields_for_source,
)
from spica.sources import RESOLVER, SOURCES, Absent, GeneNotInSource, Source


@dataclass(frozen=True)
class Origin:
    """Where a source's values came from this time: a release, or an API."""

    label: str
    version: str
    retrieved: str
    locator_for: Callable[[str], str]

    def provenance(self, field_name: str = "") -> Provenance:
        return Provenance(
            source=self.label,
            version=self.version,
            retrieved=self.retrieved,
            locator=self.locator_for(field_name) if field_name else "",
        )


def build_record(
    query: str, mirror: Mirror | None = None, live: Live | None = None
) -> GeneRecord:
    """The record for one gene, from the mirror and, where it is thin, the APIs."""
    mirror = Mirror.load() if mirror is None else mirror
    live = Live.from_env(mirror.root) if live is None else live
    query = query.strip()

    resolution, resolver_stamp = _resolve(query, mirror, live)
    if not resolution.resolved:
        return _unresolved(query, resolution, mirror, resolver_stamp)

    fields: dict[str, Value] = {}
    stamps: list[SourceStamp] = []
    for source in SOURCES:
        collected, stamp = _read(source, resolution, mirror, live)
        fields.update(collected)
        stamps.append(stamp)
    _no_protein(fields)

    for spec in FIELDS:
        if spec.derived:
            fields[spec.name] = _derive(spec, fields)

    return GeneRecord(
        query=query,
        resolution=resolution,
        fields={spec.name: fields[spec.name] for spec in FIELDS},  # schema order
        sources=tuple(stamps),
        schema_version=SCHEMA_VERSION,
    )


#: Fields about the protein. For a gene with no protein product they are
#: not covered rather than not found: no database was going to have one.
PROTEIN_FIELDS = tuple(
    spec.name for spec in FIELDS
    if spec.source in ("uniprot", "alphafold", "chembl") and spec.name != "uniprot_accession"
) + ("hpa_protein_tissue_level", "hpa_protein_cell_type_level",
     "hpa_protein_tissue_intensity", "hpa_protein_reliability", "hpa_interactions",
     "hpa_interactors", "hpa_subcellular_main", "hpa_subcellular_additional",
     "hpa_subcellular_reliability")


def _no_protein(fields: dict[str, Value]) -> None:
    """The protein fields of a non-coding gene give one cause, from HGNC.

    Otherwise each source reports its own miss ("MALAT1 is not in UniProt",
    "no peptide of this protein"), which looks like a gap in the data. It is
    not a gap: the gene makes no protein. Only "not found" is rewritten. A
    failure stays a failure, and a value that a source holds stays.
    """
    accession = fields.get("uniprot_accession")
    if accession is None or accession.state is not NullState.NOT_COVERED:
        return
    for name in PROTEIN_FIELDS:
        value = fields.get(name)
        if value is not None and value.state is NullState.NOT_FOUND:
            fields[name] = Value.missing(NullState.NOT_COVERED, accession.reason,
                                         value.provenance)


def identity(
    query: str, mirror: Mirror | None = None, live: Live | None = None
) -> tuple[Resolution, dict[str, Value]]:
    """Resolve a query and read only the fields of the resolver.

    For callers that need only the names of a gene (the literature watch
    expands a symbol into its aliases). They do not pay for all the sources
    of a full record.
    """
    mirror = Mirror.load() if mirror is None else mirror
    live = Live.from_env(mirror.root) if live is None else live
    resolution, _ = _resolve(query.strip(), mirror, live)
    if not resolution.resolved:
        return resolution, {}
    fields, _ = _read(RESOLVER, resolution, mirror, live)
    return resolution, fields


# -- resolution -------------------------------------------------------------


def _resolve(
    query: str, mirror: Mirror, live: Live
) -> tuple[Resolution, SourceStamp | None]:
    """Turn the query into identifiers, or say why that could not be done."""
    if not query:
        return Resolution(query=query, resolved=False,
                          reason="No gene entered."), None

    ok, problem = RESOLVER.availability(mirror)
    entry = mirror.entry(RESOLVER.key)

    if ok:
        assert entry is not None
        try:
            resolution = RESOLVER.resolve(query, entry)
        except Exception as exc:  # a broken resolver is reported, not raised
            trouble = f"{RESOLVER.label} could not be read: {exc}"
            return (
                Resolution(query=query, resolved=False, reason=trouble),
                SourceStamp(RESOLVER.key, RESOLVER.label, "failed", entry.version,
                            entry.retrieved, trouble),
            )
        return resolution, SourceStamp(
            RESOLVER.key, RESOLVER.label, "read", entry.version, entry.retrieved,
            "" if resolution.resolved else resolution.reason,
        )

    # Not mirrored. Nothing else can be looked up until the gene is named, so
    # this is the one fetch that decides whether a record happens at all.
    try:
        resolution = RESOLVER.resolve_live(query, live)
    except (LiveError, NotFoundUpstream) as exc:
        trouble = f"{problem}, and the HGNC API could not be reached: {exc}"
        return (
            Resolution(query=query, resolved=False, reason=trouble),
            SourceStamp(RESOLVER.key, RESOLVER.label, "unavailable", note=trouble),
        )
    except Exception as exc:
        trouble = f"{RESOLVER.label} could not be fetched: {exc}"
        return (
            Resolution(query=query, resolved=False, reason=trouble),
            SourceStamp(RESOLVER.key, RESOLVER.label, "failed", note=trouble),
        )

    return resolution, SourceStamp(
        RESOLVER.key, RESOLVER.label, _api_status(RESOLVER, live), "API", "",
        "" if resolution.resolved else resolution.reason,
    )


def _unresolved(
    query: str, resolution: Resolution, mirror: Mirror, stamp: SourceStamp | None
) -> GeneRecord:
    """A complete record for a gene that could not be identified.

    Still every field, still a state on each: an unresolved query is an
    answer about the query, and the other sources were never asked.
    """
    # Nothing resolved because the authority was unreachable is a failure;
    # nothing resolved because no gene matches is an answer.
    answered = stamp is None or stamp.status in ("read", "fetched", "cached")
    state = NullState.NOT_FOUND if answered else NullState.FAILED
    reason = resolution.reason or "The gene could not be identified."

    stamps = [stamp] if stamp else []
    for source in SOURCES:
        if source.key == RESOLVER.key:
            continue
        entry = mirror.entry(source.key)
        stamps.append(
            SourceStamp(
                source.key, source.label, "skipped",
                entry.version if entry else "",
                entry.retrieved if entry else "",
                "no identified gene to look up",
            )
        )

    return GeneRecord(
        query=query,
        resolution=resolution,
        fields={spec.name: Value.missing(state, reason) for spec in FIELDS},
        sources=tuple(stamps),
        schema_version=SCHEMA_VERSION,
    )


# -- one source -------------------------------------------------------------


def _read(
    source: Source, resolution: Resolution, mirror: Mirror, live: Live
) -> tuple[dict[str, Value], SourceStamp]:
    """Every field `source` owns, and what happened while getting them."""
    ok, problem = source.availability(mirror)
    if ok:
        entry = mirror.entry(source.key)
        assert entry is not None
        return _from_mirror(source, resolution, entry)
    return _from_api(source, resolution, live, problem)


def _from_mirror(
    source: Source, resolution: Resolution, entry: MirrorEntry
) -> tuple[dict[str, Value], SourceStamp]:
    specs = fields_for_source(source.key)
    origin = Origin(entry.label, entry.version, entry.retrieved,
                    lambda name: source.locator(name, entry))
    stamp = SourceStamp(source.key, source.label, "read", entry.version, entry.retrieved)

    try:
        collected = source.collect(resolution, entry)
    except GeneNotInSource as exc:
        return _all_null(specs, NullState.NOT_FOUND, str(exc), origin), SourceStamp(
            source.key, source.label, "read", entry.version, entry.retrieved, str(exc)
        )
    except Exception as exc:
        # Including the bugs: one adapter raising costs that source's fields,
        # never the record.
        reason = f"{source.label} not read: {exc}"
        return _all_null(specs, NullState.FAILED, reason), SourceStamp(
            source.key, source.label, "failed", entry.version, entry.retrieved, reason
        )

    return {spec.name: _value(spec, collected, source.label, origin)
            for spec in specs}, stamp


def _from_api(
    source: Source, resolution: Resolution, live: Live, mirror_problem: str
) -> tuple[dict[str, Value], SourceStamp]:
    """The fallback: the source's own API, when it is not mirrored.

    The mirror's problem is kept in every message. The fields being empty is
    first a fact about the mirror; the API not answering is the second half
    of the sentence, not the whole of it.
    """
    specs = fields_for_source(source.key)
    try:
        fetched: Fetched = source.fetch(resolution, live)
    except NoLiveRoute:
        reason = f"{mirror_problem}, and it has no API to fall back to"
        return _all_null(specs, NullState.FAILED, reason), SourceStamp(
            source.key, source.label, "unavailable", note=reason
        )
    except (LiveError, NotFoundUpstream) as exc:
        reason = f"{mirror_problem}; API not reached: {exc}"
        return _all_null(specs, NullState.FAILED, reason), SourceStamp(
            source.key, source.label, "unavailable", note=reason
        )
    except GeneNotInSource as exc:
        return _all_null(specs, NullState.NOT_FOUND, str(exc)), SourceStamp(
            source.key, source.label, _api_status(source, live), note=str(exc)
        )
    except Exception as exc:
        reason = f"{source.label} not fetched: {exc}"
        return _all_null(specs, NullState.FAILED, reason), SourceStamp(
            source.key, source.label, "failed", note=reason
        )

    origin = Origin(source.label, fetched.version, fetched.retrieved,
                    lambda name: fetched.locator)
    status = _api_status(source, live)
    stamp = SourceStamp(
        source.key, source.label, status, fetched.version, fetched.retrieved,
        f"{'fetched from' if status == 'fetched' else 'cached from'} {fetched.locator}",
    )
    return {spec.name: _value(spec, fetched.fields, source.label, origin)
            for spec in specs}, stamp


def _api_status(source: Source, live: Live) -> str:
    """`fetched` when this build opened a connection for the source,
    `cached` when the answer was already on disk. The values are the same
    either way; what differs is whether anything left the machine today."""
    return "fetched" if source.key in live.network_used else "cached"


def _all_null(
    specs: tuple[FieldSpec, ...], state: NullState, reason: str,
    origin: Origin | None = None,
) -> dict[str, Value]:
    provenance = origin.provenance() if origin else None
    return {spec.name: Value.missing(state, reason, provenance) for spec in specs}


def _value(
    spec: FieldSpec, collected: dict[str, Any], label: str, origin: Origin
) -> Value:
    """One collected field, checked and given its provenance."""
    raw = collected.get(spec.name)

    if isinstance(raw, Absent):
        return Value.missing(raw.state, raw.reason, origin.provenance())

    if raw is None or raw == "" or raw == [] or raw == {}:
        # An adapter that returns a blank means the value was empty, which is
        # the same statement as leaving the field out.
        return Value.missing(
            NullState.NOT_FOUND,
            f"{label} {origin.version} has no {phrase(unprefixed(spec.label))} for this gene",
            origin.provenance(),
        )

    problem = check_type(spec, raw)
    if problem:
        return Value.missing(
            NullState.FAILED,
            f"{label} returned an unusable {phrase(spec.label)}: {problem}",
            origin.provenance(),
        )
    return Value.found(raw, origin.provenance(spec.name))


# -- derived fields ---------------------------------------------------------


#: Source names some labels start with, to tell fields apart on screen. In a
#: sentence that already names the source they would say it twice.
SOURCE_PREFIXES = ("HPA ", "GTEx ", "UniProt ", "ChEMBL ", "ClinVar ", "AlphaFold ")


def unprefixed(label: str) -> str:
    """"HPA additional locations" -> "additional locations"."""
    for prefix in SOURCE_PREFIXES:
        if label.startswith(prefix):
            return label[len(prefix):]
    return label


def phrase(label: str) -> str:
    """A field label inside a sentence: lower case where that is safe, so
    "Single-cell RNA" reads "single-cell RNA" and "HPA additional locations"
    keeps its acronym."""
    first = label.split(" ", 1)[0]
    if any(c.isupper() for c in first[1:]):
        return label
    return label[:1].lower() + label[1:]


def _gtex_max_tissue(values: dict[str, float]) -> str:
    """The tissue with the highest median TPM; ties go to the first by name,
    so the same matrix always names the same tissue."""
    top = metrics.peak(values)
    return top[0] if top else ""


DERIVATIONS: dict[str, Callable[..., Any]] = {
    "gtex_max_tissue": _gtex_max_tissue,
    # The comparative layer. Each is arithmetic over one or two fields the
    # record already holds, so it is as reproducible as they are.
    "rna_specificity_tau": lambda values: metrics.tau(values.values()),
    "rna_specificity_class": lambda values: metrics.specificity_class(
        metrics.tau(values.values())),
    "rna_fold_over_median": lambda values: metrics.fold_over_median(values.values()),
    "single_cell_tau": lambda values: metrics.tau(values.values()),
    "rna_protein_concordance": lambda rna, protein: metrics.concordance(
        rna, protein, ("RNA", "protein"),
        "Treat the RNA profile as the weaker evidence for where it acts."),
    "rna_source_agreement": lambda gtex, hpa: metrics.concordance(
        gtex, hpa, ("GTEx", "HPA"),
        "Two pipelines disagree, so neither profile should carry a "
        "decision on its own."),
    "top_disease": lambda scores: _top_disease(scores),
    "dependency_profile": lambda share, essential, lineages: metrics.dependency_profile(
        share, essential.startswith("yes"), lineages),
    "druggable_modalities": lambda evidence: _modalities(evidence),
}


def _top_disease(scores: dict[str, float]) -> str:
    """The strongest association, named with its score so it can be weighed."""
    top = metrics.peak(scores)
    return f"{top[0]} ({top[1]:g})" if top else ""


def _modalities(evidence: list[str]) -> list[str]:
    """The modalities named in the tractability findings, in first-seen order."""
    seen: list[str] = []
    for line in evidence:
        modality = line.split(":", 1)[0].strip()
        if modality and modality not in seen:
            seen.append(modality)
    return seen


def _derive(spec: FieldSpec, fields: dict[str, Value]) -> Value:
    """A field calculated from other fields, with their provenance.

    A derived value is only as sound as its inputs. A missing input thus
    passes through with its own state; it does not merge into one state.
    """
    inputs = [fields.get(name) for name in spec.derived_from]
    for name, value in zip(spec.derived_from, inputs):
        if value is None or not value.present:
            state = value.state if value is not None else NullState.NOT_COVERED
            label = phrase(FIELDS_BY_NAME[name].label)
            return Value.missing(
                state or NullState.NOT_COVERED,
                f"needs {label}, which is not available: "
                f"{value.reason if value else 'the field was never built'}",
            )

    function = DERIVATIONS[spec.name]
    try:
        result = function(*[value.value for value in inputs])
    except Exception as exc:
        return Value.missing(NullState.FAILED, f"could not be derived: {exc}")

    problem = check_type(spec, result)
    if problem:
        return Value.missing(NullState.FAILED, f"derivation gave {problem}")

    first = inputs[0]
    assert first is not None and first.provenance is not None
    return Value.found(
        result,
        Provenance(
            source=first.provenance.source,
            version=first.provenance.version,
            retrieved=first.provenance.retrieved,
            locator=f"derived from {', '.join(spec.derived_from)}",
        ),
    )


# -- a sentence for the interface -------------------------------------------


def summarize(record: GeneRecord) -> str:
    """One plain line about the record, in the product's voice."""
    if not record.resolution.resolved:
        return record.resolution.reason

    filled = len(record.present_fields())
    counts = {"read": 0, "fetched": 0, "cached": 0}
    for stamp in record.sources:
        if stamp.status in counts:
            counts[stamp.status] += 1
    api = counts["fetched"] + counts["cached"]
    gene = f"{record.resolution.symbol} ({record.resolution.hgnc_id})"

    line = (f"{gene}: {filled} of {len(FIELDS)} fields "
            f"from {counts['read'] + api} sources.")
    if api:
        # Said plainly: some of this did not come off this disk.
        word = "fetched from the APIs" if counts["fetched"] else "from the API cache"
        line += f" {api} {word}."
    if record.resolution.matched_on not in ("approved symbol", ""):
        line += f" Matched on {record.resolution.matched_on}."
    return line
