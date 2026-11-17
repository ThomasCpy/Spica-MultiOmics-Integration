"""The digest: feeds read, reservations honoured, passages found.

Every network answer here comes from a stub, and transcription is never
run: what is tested is the reading, the rules and the search, which do not
need whisper.cpp.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

from spica.digest import feeds, genes, search, update
from spica.digest.catalogue import Feed
from spica.digest.store import Store
from spica.intel import trials
from spica.live import Live

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel><title>Oncology Rounds</title><link>https://example.org/show</link>
<copyright>{copyright}</copyright>
<item><title><![CDATA[HER2-low and beyond]]></title><guid>ep-2</guid>
<pubDate>Wed, 21 Oct 2026 10:00:00 GMT</pubDate><link>https://example.org/ep2</link>
<enclosure url="https://example.org/ep2.mp3" type="audio/mpeg" length="1"/>
<description><![CDATA[<p>Trastuzumab deruxtecan in <b>HER2</b>-low breast cancer.</p>]]></description>
<podcast:transcript url="https://example.org/ep2.vtt" type="text/vtt"/></item>
<item><title>Old talk</title><guid>ep-1</guid><pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
<enclosure url="https://example.org/ep1.m4a" type="audio/mp4" length="1"/>
<description>An older episode.</description></item>
</channel></rss>"""

VTT = """WEBVTT

00:00:01.000 --> 00:00:05.000
Welcome. Today, her two low disease and the ADC data.

00:01:10.500 --> 00:01:14.000
Resistance to trastuzumab deruxtecan is the open question.
"""


class Stub:
    """Answers by URL; anything else is a 404."""

    def __init__(self, answers: dict[str, tuple[bytes, dict]]):
        self.answers, self.calls = answers, []

    def __call__(self, url, headers, timeout, body=None):
        self.calls.append(url)
        if url in self.answers:
            return self.answers[url]
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def rss(copyright_line="Example Society"):
    return RSS.format(copyright=copyright_line).encode()


class FeedTest(unittest.TestCase):
    def test_an_episode_as_the_feed_has_it(self):
        parsed = feeds.parse("rounds", rss())
        first = parsed["episodes"][0]
        self.assertEqual(first["title"], "HER2-low and beyond")
        self.assertEqual(first["date"], "2026-10-21")
        self.assertEqual(first["notes"], "Trastuzumab deruxtecan in HER2 -low breast cancer.")
        self.assertEqual(first["transcripts"], [{"url": "https://example.org/ep2.vtt", "type": "text/vtt"}])
        self.assertEqual(first["id"], feeds.episode_id("rounds", "ep-2"))

    def test_three_ways_a_publisher_reserves_mining(self):
        live = Live(tempfile.mkdtemp(), opener=Stub({}))
        self.assertIn("header", feeds.reservation({"tdm-reservation": "1"}, "", "", live))
        self.assertIn("copyright line", feeds.reservation(
            {}, "All rights reserved, including those for text and data mining", "", live))
        tdmrep = json.dumps([{"location": "/", "tdm-reservation": 1}]).encode()
        live = Live(tempfile.mkdtemp(), opener=Stub({
            "https://publisher.example/.well-known/tdmrep.json": (tdmrep, {})}))
        self.assertIn("TDMRep", feeds.reservation({}, "", "https://publisher.example", live))
        self.assertEqual(feeds.reservation({}, "Example Society", "https://other.example", live), "")

    def test_transcripts_in_each_format(self):
        vtt = feeds.transcript_segments(VTT, "text/vtt")
        self.assertEqual(vtt[1][0], 70.5)
        self.assertTrue(vtt[0][2].startswith("Welcome"))
        srt = feeds.transcript_segments("1\n00:00:02,000 --> 00:00:03,000\nHello\n", "application/x-subrip")
        self.assertEqual(srt, [[2.0, 3.0, "Hello"]])
        data = json.dumps({"segments": [{"startTime": 4, "endTime": 6, "body": "Hi"}]})
        self.assertEqual(feeds.transcript_segments(data, "application/json"), [[4.0, 6.0, "Hi"]])


class GenesTest(unittest.TestCase):
    VOCAB = {"ERBB2": "ERBB2", "HER2": "ERBB2", "EGFR": "EGFR", "EGF": "EGF", "KRAS": "KRAS",
             "CLDN18": "CLDN18", "TROP2": "TACSTD2", "PDL1": "CD274", "HAS3": "HAS3", "TOP2": "TOP2A"}

    def test_as_people_say_them(self):
        tag = lambda text: genes.tag(text, self.VOCAB)
        self.assertEqual(tag("her two positive disease"), ["ERBB2"])
        self.assertEqual(tag("trope two directed conjugates"), ["TACSTD2"])
        self.assertEqual(tag("tested for EGF or ALK alterations"), ["EGFR"])
        self.assertEqual(tag("growth factor EGF binds"), ["EGF"])
        self.assertEqual(tag("CLDN18.2 and PD-L1"), ["CD274", "CLDN18"])

    def test_and_not_as_ordinary_words(self):
        tag = lambda text: genes.tag(text, self.VOCAB)
        self.assertEqual(tag("the room has three chambers"), [])
        self.assertEqual(tag("the top two answers"), [])
        self.assertEqual(tag("kras in lower case is not a symbol"), [])
        self.assertEqual(tag("an ADC in the ASCO session"), [])


class StoreAndSearchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_catalogue_feeds_are_on_until_turned_off(self):
        self.assertTrue(all(on for _, on in self.store.feeds()))
        chosen = self.store.settings()
        chosen["enabled"]["nature"] = False
        self.store.save_settings(chosen)
        self.assertFalse(dict((f.key, on) for f, on in self.store.feeds())["nature"])

    def test_events_fold_into_each_episodes_state(self):
        self.store.append({"event": "seen", "id": "e1", "feed": "rounds", "title": "A", "reserved": ""})
        self.store.append({"event": "skipped", "id": "e1", "reason": "no speech model", "permanent": False})
        self.store.append({"event": "transcribed", "id": "e1", "engine": "the publisher's transcript"})
        state = self.store.episodes()["e1"]
        self.assertEqual((state["status"], state["permanent"]), ("transcribed", False))
        self.assertEqual(len(self.store.events()), 3)  # appended, never rewritten

    def test_search_finds_what_was_said_and_the_gene_it_named(self):
        self.store.append({"event": "seen", "id": "e1", "feed": "rounds", "title": "Breast cancer ADCs",
                           "date": "2026-10-21", "link": "https://example.org/e1", "reserved": ""})
        self.store.write_transcript("e1", feeds.transcript_segments(VTT, "text/vtt"), "the publisher's transcript")
        self.store.append({"event": "seen", "id": "e2", "feed": "nature", "title": "Reserved news",
                           "date": "2026-10-20", "reserved": "https://www.nature.com reserves it"})
        runs = [{"trials": {"items": [trials.trial({"protocolSection": {
            "identificationModule": {"nctId": "NCT01", "briefTitle": "Zolbetuximab in CLDN18.2 gastric cancer"},
            "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-10-01"}},
            "designModule": {"phases": ["PHASE3"]}}})]}}]
        index = search.Index(search.passages(self.store, runs, GenesTest.VOCAB))
        kinds = sorted(p.kind for p in index.items)
        self.assertEqual(kinds, ["podcast", "podcast", "title", "trial"])
        found = search.search(index, "trastuzumab deruxtecan resistance", GenesTest.VOCAB)
        self.assertEqual(found["results"][0]["at"], "1:10")
        by_gene = search.search(index, "", GenesTest.VOCAB, gene="ERBB2")
        self.assertEqual([r["id"] for r in by_gene["results"]], ["e1:0"])
        trial = search.search(index, "zolbetuximab", GenesTest.VOCAB, kinds=["trial"])
        self.assertEqual(trial["results"][0]["genes"], ["CLDN18"])
        # The reserved episode is there by title, and only by title.
        self.assertEqual(search.search(index, "news", GenesTest.VOCAB)["results"][0]["text"], "Reserved news")


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = Store(self.root)
        self.store.save_settings({"enabled": {}, "added": [], "per_feed": 3})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_update(self, answers, feeds_list):
        with mock.patch.object(Store, "feeds", lambda self: [(f, True) for f in feeds_list]), \
                mock.patch.object(update.speech, "status", return_value={"ready": False}), \
                mock.patch.object(update.speech, "engine", return_value=""):
            return update.update(self.store, Live(self.root, opener=Stub(answers)))

    def test_publisher_transcripts_are_used_and_reservations_honoured(self):
        open_feed = Feed("rounds", "Rounds", "Society", "https://example.org/feed", "https://example.org", "")
        shut_feed = Feed("shut", "Shut", "Publisher", "https://shut.example/feed", "https://shut.example", "")
        summary = self.run_update({
            "https://example.org/feed": (rss(), {}),
            "https://example.org/ep2.vtt": (VTT.encode(), {}),
            "https://shut.example/feed": (rss("All rights reserved, including text and data mining"), {}),
        }, [open_feed, shut_feed])
        self.assertEqual(summary["new"], 4)
        self.assertEqual(summary["transcribed"], 1)
        state = self.store.episodes()
        transcribed = [e for e in state.values() if e.get("status") == "transcribed"]
        self.assertEqual([e["title"] for e in transcribed], ["HER2-low and beyond"])
        # The older episode is MP4 audio this build cannot decode: said once, for good.
        old = next(e for e in state.values() if e["title"] == "Old talk" and e["feed"] == "rounds")
        self.assertTrue(old["permanent"])
        self.assertIn("audio/mp4", old["status_note"])
        # Nothing of the reserved feed was asked for beyond its feed.
        shut = [e for e in state.values() if e["feed"] == "shut"]
        self.assertTrue(all(e["reserved"] and "status" not in e for e in shut))

    def test_process_all_goes_past_the_per_feed_limit(self):
        self.store.save_settings({"enabled": {}, "added": [], "per_feed": 0})
        feed = Feed("rounds", "Rounds", "Society", "https://example.org/feed", "https://example.org", "")
        answers = {"https://example.org/feed": (rss(), {}),
                   "https://example.org/ep2.vtt": (VTT.encode(), {})}
        self.assertEqual(self.run_update(answers, [feed])["transcribed"], 0)
        with mock.patch.object(Store, "feeds", lambda self: [(feed, True)]):
            self.assertEqual(update.backlog(self.store)["episodes"], 2)
            with mock.patch.object(update.speech, "status", return_value={"ready": False}), \
                    mock.patch.object(update.speech, "engine", return_value=""):
                summary = update.update(self.store, Live(self.root, opener=Stub(answers)), everything=True)
            self.assertEqual(summary["transcribed"], 1)
            # The MP4 episode is skipped for good, so nothing is left waiting.
            self.assertEqual(update.backlog(self.store)["episodes"], 0)

    def test_a_stopped_run_keeps_what_it_did_and_says_so(self):
        feed = Feed("rounds", "Rounds", "Society", "https://example.org/feed", "https://example.org", "")
        stop = mock.Mock(is_set=lambda: True)
        with mock.patch.object(Store, "feeds", lambda self: [(feed, True)]), \
                mock.patch.object(update.speech, "status", return_value={"ready": False}):
            summary = update.update(self.store, Live(self.root, opener=Stub({
                "https://example.org/feed": (rss(), {})})), everything=True, stop=stop)
        self.assertTrue(summary["stopped"])
        self.assertEqual((summary["new"], summary["transcribed"]), (2, 0))

    def test_the_backlog_says_how_much_audio_and_how_long(self):
        self.assertEqual(update.seconds("1:02:03"), 3723)
        self.assertEqual(update.seconds("62:03"), 3723)
        self.assertEqual(update.seconds("3723"), 3723)
        self.assertIsNone(update.seconds("an hour"))
        feed = Feed("rounds", "Rounds", "Society", "https://example.org/feed", "", "")
        for ident, duration in (("a", "1:00:00"), ("b", "30:00"), ("c", ""), ("done", "1:00:00")):
            self.store.append({"event": "seen", "id": ident, "feed": "rounds", "title": ident,
                               "date": "2026-10-01", "duration": duration, "reserved": ""})
        self.store.append({"event": "transcribed", "id": "done", "engine": "whisper.cpp",
                           "seconds": 600.0, "audio": 3600.0})
        with mock.patch.object(Store, "feeds", lambda self: [(feed, True)]):
            found = update.backlog(self.store)
        self.assertEqual(found["episodes"], 3)
        self.assertEqual(found["unknown_length"], 1)
        self.assertEqual(found["audio_hours"], 2.2)  # 1 h + 0.5 h + the median of those for "c"
        self.assertAlmostEqual(found["pace"], 1 / 6, places=3)
        self.assertEqual(found["estimate_hours"], 0.4)

    def test_offline_reads_nothing_and_says_so(self):
        feed = Feed("rounds", "Rounds", "Society", "https://example.org/feed", "", "")
        with mock.patch.object(Store, "feeds", lambda self: [(feed, True)]):
            summary = update.update(self.store, Live(self.root, allowed=False))
        self.assertEqual(summary["feeds"], 0)
        self.assertIn("online access is off", summary["problems"][0])


class TrialsTest(unittest.TestCase):
    def test_a_symbol_also_searches_its_isoforms(self):
        self.assertEqual(trials.expression(["CLDN18", "claudin 18", "KRAS"]),
                         'CLDN18 OR CLDN18.1 OR CLDN18.2 OR "claudin 18" OR KRAS')

    def test_a_registration_reduced_to_its_fields(self):
        found = trials.trial({"protocolSection": {
            "identificationModule": {"nctId": "NCT07872722", "briefTitle": "A trial"},
            "statusModule": {"overallStatus": "ACTIVE_NOT_RECRUITING",
                             "lastUpdatePostDateStruct": {"date": "2026-10-20"}},
            "designModule": {"phases": ["PHASE1", "PHASE2"]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "A Sponsor"}},
            "armsInterventionsModule": {"interventions": [{"name": "Drug X"}]}}})
        self.assertEqual((found["status"], found["phase"], found["date"]),
                         ("active, not recruiting", "phase 1, phase 2", "2026-10-20"))
        self.assertEqual(found["url"], "https://clinicaltrials.gov/study/NCT07872722")

    def test_trials_come_back_through_the_live_layer(self):
        page = {"totalCount": 1, "studies": [{"protocolSection": {
            "identificationModule": {"nctId": "NCT01", "briefTitle": "T"},
            "statusModule": {"lastUpdatePostDateStruct": {"date": "2026-10-01"}}}}]}

        def opener(url, headers, timeout, body=None):
            self.assertIn("clinicaltrials.gov/api/v2/studies", url)
            return json.dumps(page).encode(), {}

        found = trials.search(Live(tempfile.mkdtemp(), opener=opener), ["CLDN18"],
                              date(2026, 7, 1), date(2026, 10, 1), "t")
        self.assertEqual((found.state, found.total, found.items[0]["nct"]), ("ok", 1, "NCT01"))


class ToolTest(unittest.TestCase):
    def test_ai_mode_searches_the_digest(self):
        root = Path(tempfile.mkdtemp())
        try:
            store = Store(root)
            store.append({"event": "seen", "id": "e1", "feed": "rounds", "title": "ADC talk",
                          "date": "2026-10-21", "link": "https://example.org/e1", "reserved": ""})
            store.write_transcript("e1", feeds.transcript_segments(VTT, "text/vtt"), "publisher")
            search._CACHE.clear()
            with mock.patch.dict(os.environ, {"SPICA_DATA_DIR": str(root)}):
                from spica.agents.views import DigestSearch

                found = DigestSearch().run("trastuzumab deruxtecan")
            self.assertIn("[digest:e1:1]", found.text)
            self.assertIn("at 1:10", found.text)
            self.assertIn("Resistance to trastuzumab deruxtecan", found.text)
            self.assertEqual(found.citations, ["digest:e1:1"])
        finally:
            search._CACHE.clear()
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class MeaningTest(unittest.TestCase):
    def test_vectors_are_made_once_and_blended_into_the_ranking(self):
        import numpy as np

        from spica.digest import meaning

        class Fake:
            """Two dimensions: 'resistance' and everything else."""

            calls = 0

            def documents(self, texts):
                Fake.calls += len(texts)
                return np.asarray([[1.0, 0.0] if "resist" in t.lower() else [0.0, 1.0] for t in texts],
                                  dtype="float32")

            def query(self, text):
                return np.asarray([1.0, 0.0], dtype="float32")

        root = Path(tempfile.mkdtemp())
        try:
            items = [search.Passage("a", "podcast", "s", "A", "2026-10-01", "Drugs stop working."),
                     search.Passage("b", "podcast", "s", "B", "2026-10-02", "Resistance mechanisms."),
                     search.Passage("c", "title", "s", "C", "2026-10-03", "Reserved")]
            self.assertEqual(meaning.refresh(items, root, Fake()), 2)  # the title is not embedded
            self.assertEqual(meaning.refresh(items, root, Fake()), 0)  # nothing twice
            scores = meaning.scores(items, "why drugs fail", root, Fake())
            self.assertEqual(scores, {0: 0.0, 1: 1.0})
            index = search.Index(items)
            found = search.search(index, "why", {}, vectors=scores)
            self.assertEqual(found["results"][0]["id"], "b")  # by meaning, no shared word
        finally:
            shutil.rmtree(root, ignore_errors=True)


class CodeTest(unittest.TestCase):
    def test_a_drug_code_is_found_however_it_is_typed(self):
        trial = search.Passage(id="t1", kind="trial", source="ClinicalTrials.gov", title="NCT1: XYZ-123 in healthy volunteers",
                               date="2025-12-10", text="Safety of XYZ-123 in healthy volunteers. Sponsor: Example Bio.")
        talk = search.Passage(id="p1", kind="podcast", source="ASCO", title="GLP-1 and cancer", date="2026-08-06",
                              text="a little over 100,000 patients, and so 123,000 had GLP1 agonists")
        index = search.Index([trial, talk])
        for typed in ("XYZ-123", "XYZ 123", "XYZ123", "xyz 123"):
            found = search.search(index, typed, {})
            self.assertEqual([r["id"] for r in found["results"]], ["t1"], typed)


class RelevanceTest(unittest.TestCase):
    def test_one_shared_word_is_not_an_answer(self):
        items = [search.Passage("a", "podcast", "s", "A", "2026-10-01", "Checkpoint inhibitors in melanoma."),
                 search.Passage("b", "podcast", "s", "B", "2026-10-02", "Resistance to KRAS inhibitors."),
                 search.Passage("c", "podcast", "s", "C", "2026-10-03", "Sotorasib for lung cancer.",
                                genes=["KRAS"])]
        found = search.search(search.Index(items), "resistance to KRAS G12C inhibitors", {"KRAS": "KRAS"})
        self.assertEqual([r["id"] for r in found["results"]], ["b", "c"])  # never the melanoma one
        self.assertEqual(found["naming"], 1)
