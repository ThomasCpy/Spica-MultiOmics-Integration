"""Competitive intelligence, against a stub transport.

No test here touches the network. The payloads are shaped like the real
ones: Europe PMC's from live responses, OPS's from its documented
XML-as-JSON form, including the two habits that break naive parsers: a
list of one arriving as a bare object, and "no results" arriving as 404.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

from spica.intel import literature, patents
from spica.intel.patents import Credentials
from spica.intel.terms import split, widen
from spica.intel.watch import Watches, run_watch, slug
from spica.live import Live

TODAY = date(2026, 10, 25)

EPMC_PAPER = {
    "id": "42867382", "source": "MED", "pmid": "42867382",
    "doi": "10.1080/1354750x.2026.2749578",
    "title": "Claudin 18.2: from a tight junction protein to a target &amp; more.",
    "authorString": "Bahrami M, Rajabi Vahid M.",
    "journalTitle": "Biomarkers", "pubYear": "2026",
    "pubType": "review; journal article", "firstPublicationDate": "2026-10-21",
}
EPMC_PREPRINT = {
    "id": "PPR1308474", "source": "PPR", "doi": "10.21203/rs.3.rs-10489398/v1",
    "title": "CLDN18.2-specific CAR-NK cells: a phase 1 trial",
    "authorString": "Yang L, Qian W.", "pubYear": "2026", "pubType": "preprint",
    "bookOrReportDetails": {"publisher": "Research Square"},
    "firstPublicationDate": "2026-10-02",
}


def ops_document(number, family, date_, applicant, title, cpc=("C07K", "16", "28")):
    """One OPS exchange-document, in OPS's own shape."""
    section_class, group, sub = cpc
    return {"exchange-document": {
        "@country": number[:2], "@doc-number": number[2:-2], "@kind": number[-2:],
        "@family-id": family,
        "bibliographic-data": {
            "publication-reference": {"document-id": [
                {"@document-id-type": "docdb", "country": {"$": number[:2]},
                 "doc-number": {"$": number[2:-2]}, "kind": {"$": number[-2:]},
                 "date": {"$": date_}},
                {"@document-id-type": "epodoc", "doc-number": {"$": number[:-2]}},
            ]},
            # A single title, as a bare object rather than a list of one.
            "invention-title": {"@lang": "en", "$": title},
            "parties": {"applicants": {"applicant": [
                {"@data-format": "epodoc", "applicant-name": {"name": {"$": applicant}}},
                {"@data-format": "original", "applicant-name": {"name": {"$": applicant.title()}}},
            ]}},
            "patent-classifications": {"patent-classification": {
                "classification-scheme": {"@scheme": "CPCI"},
                "section": {"$": section_class[0]}, "class": {"$": section_class[1:3]},
                "subclass": {"$": section_class[3:]}, "main-group": {"$": group},
                "subgroup": {"$": sub},
            }},
        },
    }}


OPS_PAGE = {"ops:world-patent-data": {"ops:biblio-search": {
    "@total-result-count": "3",
    "ops:search-result": {"exchange-documents": [
        ops_document("WO2026123456A1", "90001", "20261015", "ASTELLAS PHARMA INC [JP]",
                     "Anti-CLDN18.2 antibodies"),
        ops_document("EP4500001A1", "90001", "20260901", "ASTELLAS PHARMA INC [JP]",
                     "Anti-CLDN18.2 antibodies"),
        ops_document("CN120000001A", "90002", "20260820", "SUZHOU BIO CO LTD [CN]",
                     "Claudin 18.2 CAR-T cells", cpc=("C12N", "5", "0783")),
    ]},
}}}


class Transport:
    """Canned answers by URL fragment, and a log of what was asked."""

    def __init__(self, routes, token=True):
        self.routes = routes
        self.asked = []
        self.token = token

    def __call__(self, url, headers, timeout, body=None):
        self.asked.append(url)
        if "auth/accesstoken" in url:
            if not self.token:
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
            return json.dumps({"access_token": "t0k", "expires_in": "1199"}).encode(), {}
        for fragment, answer in self.routes.items():
            if fragment in url:
                if isinstance(answer, int):
                    raise urllib.error.HTTPError(url, answer, "", {}, None)
                return json.dumps(answer).encode(), {}
        raise urllib.error.HTTPError(url, 500, "unrouted", {}, None)


def epmc(results, total=None):
    return {"hitCount": total if total is not None else len(results),
            "nextCursorMark": "*", "resultList": {"result": results}}


class TestTerms(unittest.TestCase):
    def test_split_keeps_order_and_drops_duplicates(self):
        self.assertEqual(split(' CLDN18 ; zolbetuximab,\n"cldn18" '),
                         ["CLDN18", "zolbetuximab"])

    def test_widen_adds_gene_names_with_their_origin(self):
        lookup = lambda t: ({"symbol": "CLDN18", "name": "claudin 18",
                             "aliases": ["SFTPJ", "CL"], "previous_symbols": []}
                            if t == "CLDN18" else None)
        terms = widen(["CLDN18", "zolbetuximab"], lookup)
        texts = [(t.text, t.origin) for t in terms]
        self.assertEqual(texts[:2], [("CLDN18", "typed"), ("zolbetuximab", "typed")])
        self.assertIn(("claudin 18", "HGNC name of CLDN18"), texts)
        self.assertIn(("SFTPJ", "HGNC alias of CLDN18"), texts)
        # Two-letter aliases match too much to search on.
        self.assertNotIn("CL", [t.text for t in terms])


class TestLiterature(unittest.TestCase):
    def test_symbols_match_their_isoforms_and_nothing_wider(self):
        self.assertEqual(literature.clause("CLDN18"),
                         '(TITLE_ABS:"CLDN18" OR TITLE_ABS:CLDN18.*)')
        self.assertEqual(literature.clause("claudin 18"), 'TITLE_ABS:"claudin 18"')
        self.assertEqual(literature.clause("zolbetuximab"), 'TITLE_ABS:"zolbetuximab"')
        self.assertNotIn("IL1*", literature.query(["IL1"], TODAY, TODAY, "MED"))

    def test_paper_keeps_metadata_only_and_unescapes(self):
        item = literature.paper(EPMC_PAPER)
        self.assertEqual(item["id"], "MED:42867382")
        self.assertEqual(item["title"],
                         "Claudin 18.2: from a tight junction protein to a target & more")
        self.assertEqual(item["link"], "https://doi.org/10.1080/1354750x.2026.2749578")
        self.assertNotIn("abstract", item)

    def test_search_merges_papers_and_preprints_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({
                "SRC%3AMED": epmc([EPMC_PAPER]), "SRC%3APPR": epmc([EPMC_PREPRINT]),
            }))
            found = literature.search(live, ["CLDN18"], TODAY, TODAY, "2026-10-25")
        self.assertEqual(found.state, "ok")
        self.assertEqual(found.total, 2)
        self.assertEqual([i["kind"] for i in found.items], ["paper", "preprint"])
        kinds = dict(literature.facets(found.items)["kind"])
        self.assertEqual(kinds, {"review": 1, "preprint": 1})

    def test_offline_says_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = literature.search(Live(tmp, allowed=False), ["CLDN18"],
                                      TODAY, TODAY, "x")
        self.assertEqual(found.state, "offline")


class TestPatents(unittest.TestCase):
    def test_without_credentials_it_is_not_configured_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = Transport({})
            found = patents.search(Live(tmp, opener=transport), Credentials("", ""),
                                   ["CLDN18"], TODAY, TODAY, "x")
        self.assertEqual(found.state, "not_configured")
        self.assertEqual(transport.asked, [])  # nothing was sent anywhere

    def test_cql(self):
        self.assertEqual(
            patents.cql(["CLDN18", 'a "b"'], date(2026, 7, 27), TODAY),
            '(ta="CLDN18" or ta="a  b") and pd within "20260727 20261025"')

    def test_parse_and_group_by_family(self):
        total, pubs = patents.parse(OPS_PAGE)
        self.assertEqual(total, 3)
        self.assertEqual(pubs[0]["number"], "WO2026123456A1")
        self.assertEqual(pubs[0]["date"], "2026-10-15")
        self.assertEqual(pubs[0]["applicants"], ["ASTELLAS PHARMA INC [JP]"])
        self.assertEqual(pubs[0]["cpc"], ["C07K16/28"])

        families = patents.group(pubs)
        self.assertEqual(len(families), 2)  # the WO and EP are one invention
        first = families[0]
        self.assertEqual(first["family"], "90001")
        self.assertEqual([p["number"] for p in first["publications"]],
                         ["EP4500001A1", "WO2026123456A1"])
        self.assertEqual(first["applicants"], ["ASTELLAS PHARMA INC"])
        self.assertEqual(first["countries"], ["JP"])
        self.assertEqual(first["first"], "2026-09-01")
        self.assertEqual(first["date"], "2026-10-15")

        facets = patents.facets(families)
        self.assertEqual(facets["applicant"][0], ["ASTELLAS PHARMA INC", 1])
        self.assertIn(["C07K16", 1, "Antibodies"], facets["cpc"])

    def test_a_404_is_zero_results_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({"published-data/search": 404}))
            found = patents.search(live, Credentials("k", "s"), ["nothing"],
                                   TODAY, TODAY, "x")
        self.assertEqual((found.state, found.total, found.items), ("ok", 0, []))

    def test_rejected_credentials_fail_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({}, token=False))
            found = patents.search(live, Credentials("k", "bad"), ["CLDN18"],
                                   TODAY, TODAY, "x")
        self.assertEqual(found.state, "failed")
        self.assertIn("401", found.reason)

    def test_the_token_is_never_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Live(tmp, opener=Transport({"published-data/search": OPS_PAGE}))
            patents.search(live, Credentials("k", "s"), ["CLDN18"], TODAY, TODAY, "x")
            written = " ".join(p.read_text(encoding="utf-8")
                               for p in Path(tmp).rglob("*.json"))
        self.assertNotIn("t0k", written)
        self.assertNotIn("access_token", written)


class TestWatch(unittest.TestCase):
    def run_once(self, tmp, papers, today=TODAY, topic="CLDN18"):
        live = Live(Path(tmp) / "net", opener=Transport({
            "SRC%3AMED": epmc(papers), "SRC%3APPR": epmc([]),
            "published-data/search": OPS_PAGE,
        }))
        return run_watch(topic, live, Watches(Path(tmp)), Credentials("k", "s"),
                         days=90, today=today)

    def test_first_check_marks_nothing_new_then_later_checks_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.run_once(tmp, [EPMC_PAPER])
            self.assertTrue(first["first_check"])
            self.assertEqual(first["new"], {"papers": 0, "patents": 0, "trials": 0})
            self.assertEqual(first["patents"]["fetched"], 2)

            later = self.run_once(tmp, [EPMC_PREPRINT, EPMC_PAPER],
                                  today=date(2026, 10, 26))
            self.assertFalse(later["first_check"])
            self.assertEqual(later["new"], {"papers": 1, "patents": 0, "trials": 0})
            flags = {i["id"]: i["new"] for i in later["papers"]["items"]}
            self.assertEqual(flags, {"PPR:PPR1308474": True, "MED:42867382": False})
            self.assertFalse(later["search_changed"])

            # The history is the file: two lines, nothing rewritten.
            lines = (Path(tmp) / "intel" / f"{slug('CLDN18')}.jsonl").read_text(
                encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)

    def test_watches_are_listed_and_reopened_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_once(tmp, [EPMC_PAPER])
            listed = Watches(Path(tmp)).list()
            self.assertEqual([w["topic"] for w in listed], ["CLDN18"])
            self.assertEqual(listed[0]["papers"], 1)
            again = Watches(Path(tmp)).latest(listed[0]["slug"])
            self.assertEqual(again["papers"]["items"][0]["id"], "MED:42867382")

    def test_a_torn_last_line_costs_that_check_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_once(tmp, [EPMC_PAPER])
            path = Path(tmp) / "intel" / f"{slug('CLDN18')}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"at": "2026-10-2')
            self.assertEqual(len(Watches(Path(tmp)).runs("CLDN18")), 1)

    def test_empty_topic_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("error", self.run_once(tmp, [], topic=" , "))


if __name__ == "__main__":
    unittest.main()


class TestNewSource(unittest.TestCase):
    def test_a_source_first_asked_marks_nothing_new(self):
        from spica.intel.watch import view

        older = {"at": "1", "papers": {"items": [{"id": "p1"}]}, "patents": {"items": []}}
        newer = {"at": "2", "papers": {"items": [{"id": "p1"}, {"id": "p2"}]}, "patents": {"items": []},
                 "trials": {"items": [{"id": "NCT:1"}]}}
        found = view([older, newer])
        self.assertEqual(found["new"], {"papers": 1, "patents": 0, "trials": 0})
