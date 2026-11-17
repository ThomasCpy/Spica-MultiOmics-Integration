"""The API fallback, against a stub transport.

No test here touches the network: `Live` takes its opener as an argument,
and these give it canned payloads shaped like the real ones. What is being
tested is the routing and the parsing: that a source is only fetched when
it is not mirrored, that fetched values say so, and that a fetch is cached.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from spica.build import build_record, summarize
from spica.live import Live, LiveError
from spica.mirror import Mirror
from spica.record import NullState
from spica.sources import SOURCES
from spica.sources.base import Source

#: Sources with an API to fall back to. DepMap has none (its portal sits
#: behind a browser check), so with no mirror it is unavailable by design.
WITH_API = {source.key for source in SOURCES if type(source).fetch is not Source.fetch}


def statuses(record, keys=WITH_API) -> set[str]:
    return {stamp.status for stamp in record.sources if stamp.key in keys}

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mirror"

HGNC_DOC = {
    "hgnc_id": "HGNC:20001",
    "symbol": "PCSK9",
    "name": "proprotein convertase subtilisin/kexin type 9",
    "locus_type": "gene with protein product",
    "location": "1p32.3",
    "alias_symbol": ["NARC1", "HCHOLA3"],
    "prev_symbol": ["NARC1"],
    "entrez_id": "255738",
    "ensembl_gene_id": "ENSG00000169174",
    "uniprot_ids": ["Q8NBP7"],
}

PAYLOADS = {
    "rest.genenames.org/fetch/symbol/PCSK9": {"response": {"docs": [HGNC_DOC]}},
    "rest.genenames.org/fetch/hgnc_id/HGNC:20001": {"response": {"docs": [HGNC_DOC]}},
    "rest.ensembl.org/lookup/id/ENSG00000169174": {
        "id": "ENSG00000169174", "biotype": "protein_coding", "assembly_name": "GRCh38",
        "seq_region_name": "1", "start": 55039445, "end": 55064852, "strand": 1,
    },
    "rest.ensembl.org/info/data": {"releases": [116]},
    "rest.uniprot.org/uniprotkb/Q8NBP7.json": {
        "primaryAccession": "Q8NBP7",
        "proteinDescription": {
            "recommendedName": {
                "fullName": {"value": "Proprotein convertase subtilisin/kexin type 9"}
            }
        },
        "sequence": {"value": "MGTVSSRRSWWPLPLLLLLLLLLGPAGARA", "length": 692},
        "comments": [
            {
                "commentType": "SUBCELLULAR LOCATION",
                "subcellularLocations": [
                    {"location": {"value": "Secreted"}},
                    {"location": {"value": "Cell surface"}},
                ],
            },
            {"commentType": "FUNCTION"},
        ],
    },
    "gtexportal.org/api/v2/reference/gene": {
        "data": [{"gencodeId": "ENSG00000169174.10", "geneSymbol": "PCSK9"}]
    },
    "gtexportal.org/api/v2/expression/medianGeneExpression": {
        "data": [
            {"tissueSiteDetailId": "Liver", "median": 29.517, "datasetId": "gtex_v8"},
            {"tissueSiteDetailId": "Whole_Blood", "median": 0.0708, "datasetId": "gtex_v8"},
            {"tissueSiteDetailId": "Kidney_Cortex", "median": 1.5, "datasetId": "gtex_v8"},
        ]
    },
    "proteinatlas.org/ENSG00000169174.json": {
        "Gene": "PCSK9",
        "Subcellular main location": ["Golgi apparatus"],
        "Subcellular additional location": ["Nucleoplasm"],
        "Reliability (IF)": "Supported",
        "Reliability (IH)": "Enhanced",
        "Protein tissue specific Intensity": {"liver": "5642.2", "kidney": "bad"},
    },
}

HEADERS = {"rest.uniprot.org/uniprotkb/Q8NBP7.json": {"X-UniProt-Release": "2026_03"}}


class Stub:
    """A transport that answers from `PAYLOADS` and counts what was asked."""

    def __init__(self, payloads: dict | None = None):
        self.payloads = PAYLOADS if payloads is None else payloads
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict, timeout: int, body=None):
        self.calls.append(url)
        for fragment, payload in self.payloads.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return json.dumps(payload).encode(), HEADERS.get(fragment, {})
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def no_mirror(tmp: str) -> Mirror:
    return Mirror.load(tmp)


class TestFetchedRecord(unittest.TestCase):
    """Nothing mirrored at all: every source comes off its API."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stub = Stub()
        self.live = Live(self.tmp.name, opener=self.stub)
        self.record = build_record("PCSK9", no_mirror(self.tmp.name), self.live)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_gene_resolves_through_the_hgnc_api(self):
        self.assertTrue(self.record.resolution.resolved)
        self.assertEqual(self.record.resolution.symbol, "PCSK9")
        self.assertEqual(self.record.resolution.matched_on, "approved symbol")

    def test_fields_arrive_from_every_source(self):
        self.assertEqual(self.record.value("hgnc_id"), "HGNC:20001")
        self.assertEqual(self.record.value("aliases"), ["NARC1", "HCHOLA3"])
        self.assertEqual(self.record.value("gene_biotype"), "protein_coding")
        self.assertEqual(
            self.record.value("genomic_location"), "GRCh38 1:55039445-55064852 (+)"
        )
        self.assertEqual(self.record.value("protein_length"), 692)
        self.assertEqual(
            self.record.value("uniprot_subcellular_locations"),
            ["Secreted", "Cell surface"],
        )
        self.assertEqual(self.record.value("gtex_tissue_tpm")["Liver"], 29.52)
        self.assertEqual(self.record.value("gtex_max_tissue"), "Liver")
        self.assertEqual(self.record.value("hpa_subcellular_main"), ["Golgi apparatus"])

    def test_a_fetched_value_says_where_it_came_from(self):
        provenance = self.record["protein_length"].provenance
        self.assertEqual(provenance.source, "UniProt")
        self.assertEqual(provenance.version, "2026_03")  # from the response header
        self.assertTrue(provenance.locator.startswith("https://rest.uniprot.org/"))

    def test_the_release_is_taken_from_the_api_where_it_gives_one(self):
        self.assertEqual(self.record["gene_biotype"].provenance.version, "116")
        self.assertEqual(self.record["gtex_tissue_tpm"].provenance.version, "v8")

    def test_every_source_is_stamped_fetched(self):
        self.assertEqual(statuses(self.record), {"fetched"})
        # And the one without an API says so, rather than staying silent.
        self.assertEqual(statuses(self.record, {s.key for s in SOURCES} - WITH_API),
                         {"unavailable"})

    def test_the_summary_says_the_values_came_off_the_network(self):
        self.assertIn(f"{len(WITH_API)} fetched from the APIs",
                      summarize(self.record))

    def test_a_missing_profile_download_is_said_not_silent(self):
        # The stub has no download-API row: the profile fields say so,
        # and the mass-spec field falls back to the entry's partial one.
        level = self.record["hpa_protein_tissue_level"]
        self.assertEqual(level.state, NullState.NOT_FOUND)
        self.assertIn("download API", level.reason)
        self.assertEqual(self.record.value("hpa_protein_tissue_intensity"),
                         {"liver": 5642.2})  # bad numbers dropped

    def test_a_failed_profile_download_is_failed_not_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            payloads = dict(PAYLOADS)
            payloads["search_download.php"] = urllib.error.URLError("timed out")
            record = build_record("PCSK9", no_mirror(tmp), Live(tmp, opener=Stub(payloads)))
        self.assertEqual(record["hpa_rna_tissue_ntpm"].state, NullState.FAILED)
        self.assertEqual(record["hpa_protein_cell_type_level"].state, NullState.FAILED)


class TestCache(unittest.TestCase):
    def test_a_second_build_asks_nothing_and_matches_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_stub = Stub()
            first = build_record("PCSK9", no_mirror(tmp), Live(tmp, opener=first_stub))
            self.assertTrue(first_stub.calls)

            # Offline this time: everything has to come out of the cache.
            second_stub = Stub()
            second = build_record(
                "PCSK9", no_mirror(tmp), Live(tmp, allowed=False, opener=second_stub)
            )
            self.assertEqual(second_stub.calls, [])
            self.assertEqual(first.fingerprint(), second.fingerprint())
            # The same values, but nothing left the machine this time.
            self.assertEqual(statuses(second), {"cached"})
            self.assertIn("from the API cache", summarize(second))

    def test_the_retrieval_date_is_of_the_fetch_not_of_the_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_record("PCSK9", no_mirror(tmp), Live(tmp, opener=Stub()))
            # A source whose answer becomes values: whichever file sorts
            # first is not guaranteed to be one.
            cached = next((Path(tmp) / "cache" / "uniprot").rglob("*.json"))
            stored = json.loads(cached.read_text(encoding="utf-8"))
            stored["fetched"] = "2020-01-01"
            cached.write_text(json.dumps(stored), encoding="utf-8")

            record = build_record("PCSK9", no_mirror(tmp), Live(tmp, opener=Stub()))
            dates = {
                value.provenance.retrieved
                for value in record.fields.values()
                if value.provenance and value.provenance.retrieved
            }
            self.assertIn("2020-01-01", dates)

    def test_refresh_goes_back_to_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_record("PCSK9", no_mirror(tmp), Live(tmp, opener=Stub()))
            stub = Stub()
            build_record("PCSK9", no_mirror(tmp), Live(tmp, refresh=True, opener=stub))
            self.assertTrue(stub.calls)


class TestTheMirrorComesFirst(unittest.TestCase):
    def test_a_mirrored_source_is_never_fetched(self):
        def explode(url, headers, timeout, body=None):
            raise AssertionError(f"a mirrored build asked for {url}")

        record = build_record(
            "PCSK9", Mirror.load(FIXTURE), Live(FIXTURE, opener=explode)
        )
        self.assertEqual({stamp.status for stamp in record.sources}, {"read"})
        self.assertNotIn("API", summarize(record))

    def test_only_the_unmirrored_source_is_fetched(self):
        body = json.loads((FIXTURE / "mirror.json").read_text(encoding="utf-8"))
        for source in body["sources"].values():
            source["files"] = {
                name: str(FIXTURE / relative)
                for name, relative in source["files"].items()
            }
        body["sources"].pop("uniprot")  # the only one left to the API

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mirror.json").write_text(json.dumps(body), encoding="utf-8")
            stub = Stub()
            record = build_record("PCSK9", Mirror.load(tmp), Live(tmp, opener=stub))

        self.assertTrue(all("uniprot" in url for url in stub.calls), stub.calls)
        self.assertEqual(record.value("protein_length"), 692)  # fetched
        self.assertEqual(record.value("gtex_tissue_tpm")["Liver"], 77.41)  # mirrored
        statuses = {stamp.key: stamp.status for stamp in record.sources}
        self.assertEqual(statuses["uniprot"], "fetched")
        self.assertEqual(statuses["gtex"], "read")


class TestWhenTheApiCannotHelp(unittest.TestCase):
    def test_a_404_is_not_found_not_a_failure(self):
        payloads = dict(PAYLOADS)
        del payloads["proteinatlas.org/ENSG00000169174.json"]  # the stub 404s it
        with tempfile.TemporaryDirectory() as tmp:
            record = build_record(
                "PCSK9", no_mirror(tmp), Live(tmp, opener=Stub(payloads))
            )
        main = record["hpa_subcellular_main"]
        self.assertEqual(main.state, NullState.NOT_FOUND)
        self.assertIn("HPA has no entry", main.reason)
        self.assertEqual(record.value("protein_length"), 692)  # the rest is unharmed

    def test_an_unreachable_api_fails_and_says_both_halves(self):
        payloads = dict(PAYLOADS)
        payloads["rest.uniprot.org/uniprotkb/Q8NBP7.json"] = urllib.error.URLError(
            "getaddrinfo failed"
        )
        with tempfile.TemporaryDirectory() as tmp:
            record = build_record(
                "PCSK9", no_mirror(tmp), Live(tmp, opener=Stub(payloads))
            )
        sequence = record["protein_sequence"]
        self.assertEqual(sequence.state, NullState.FAILED)
        self.assertIn("No mirror manifest", sequence.reason)
        self.assertIn("API not reached", sequence.reason)

    def test_offline_means_offline(self):
        stub = Stub()
        with tempfile.TemporaryDirectory() as tmp:
            record = build_record(
                "PCSK9", no_mirror(tmp), Live(tmp, allowed=False, opener=stub)
            )
        self.assertEqual(stub.calls, [])
        self.assertFalse(record.resolution.resolved)
        self.assertIn("online access is off", record.resolution.reason)
        self.assertEqual(
            {value.state for value in record.fields.values()}, {NullState.FAILED}
        )

    def test_an_unknown_gene_is_not_found_after_every_route_is_tried(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Stub()
            record = build_record("ZZZZ9", no_mirror(tmp), Live(tmp, opener=stub))
        self.assertFalse(record.resolution.resolved)
        self.assertIn("No approved HGNC gene matches ZZZZ9", record.resolution.reason)
        # symbol, previous symbol, alias symbol: the three a bare word can be
        self.assertEqual(len(stub.calls), 3)


class TestLiveTransport(unittest.TestCase):
    def test_a_non_json_answer_is_an_error_not_a_crash(self):
        def plain_text(url, headers, timeout, body=None):
            return b"<html>down for maintenance</html>", {}

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LiveError) as caught:
                Live(tmp, opener=plain_text).get_json("hgnc", "https://example.org/x")
        self.assertIn("did not answer with JSON", str(caught.exception))

    def test_a_server_error_is_reported_with_its_code(self):
        def broken(url, headers, timeout, body=None):
            raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LiveError) as caught:
                Live(tmp, opener=broken).get_json("hgnc", "https://example.org/x")
        self.assertIn("HTTP 503", str(caught.exception))


class TestRateLimits(unittest.TestCase):
    def test_ncbi_requests_are_spaced_and_others_are_not(self):
        import time

        from spica import live

        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds"
        live._turns.clear()
        started = time.monotonic()
        for _ in range(3):
            live._wait_turn(url)
        self.assertGreaterEqual(time.monotonic() - started, 2 * live.SPACING["eutils.ncbi.nlm.nih.gov"] - 0.01)
        started = time.monotonic()
        for _ in range(3):
            live._wait_turn("https://rest.uniprot.org/uniprotkb/P04637.json")
        self.assertLess(time.monotonic() - started, 0.05)


if __name__ == "__main__":
    unittest.main()
