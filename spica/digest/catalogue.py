"""The podcasts Spica offers, and why each is on the list.

Chosen for one property: the people talking are the people doing the
work, under an editor who answers for it. Journals, learned societies and
universities; no business shows, no personalities. Feed addresses are
the publishers' own, as listed in Apple's podcast directory, checked on
2026-10-28 (`docs/digest.md` has the check).

Four publishers on the list reserve text and data mining (Springer Nature,
AAAS, Elsevier's Lancet, the AMA's JAMA). They stay listed so their new
episodes show up, by title and link, and are never transcribed or
indexed; `feeds.reservation` finds that out again on every update rather
than trusting this note.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Feed:
    key: str
    name: str
    publisher: str
    url: str
    #: The publisher's own site, where a TDMRep reservation would be.
    site: str
    about: str
    added: bool = False  # true for a feed the user added

    def to_dict(self) -> dict:
        return asdict(self)


CATALOGUE: tuple[Feed, ...] = (
    Feed("asco-daily-news", "ASCO Daily News", "American Society of Clinical Oncology",
         "https://rss.libsyn.com/shows/112889/destinations/632492.xml",
         "https://dailynews.ascopubs.org",
         "Meeting coverage and expert discussion of new data, from ASCO and its meetings."),
    Feed("jco", "Journal of Clinical Oncology Podcast", "American Society of Clinical Oncology",
         "https://rss.libsyn.com/shows/58526/destinations/222395.xml", "https://ascopubs.org",
         "JCO authors and editors on the papers of each issue."),
    Feed("jco-po", "JCO Precision Oncology Conversations", "American Society of Clinical Oncology",
         "https://rss.libsyn.com/shows/427415/destinations/3558386.xml", "https://ascopubs.org",
         "Biomarkers, targets and precision oncology, with the authors."),
    Feed("nejm-this-week", "NEJM This Week", "NEJM Group, Massachusetts Medical Society",
         "http://feeds.feedburner.com/nejm-this-week-audio-summaries", "https://www.nejm.org",
         "The week's New England Journal of Medicine, summarised by its editors."),
    Feed("elife", "The eLife Podcast", "eLife, with the Naked Scientists (University of Cambridge)",
         "https://www.thenakedscientists.com/rss/eLife_podcast.xml", "https://elifesciences.org",
         "Researchers on their eLife papers, across the life sciences."),
    Feed("aacr", "AACR Scientific Podcasts", "American Association for Cancer Research",
         "https://feeds.feedburner.com/AacrScientificPodcasts", "https://www.aacr.org",
         "Talks and discussions from AACR meetings."),
    Feed("nature", "Nature Podcast", "Springer Nature",
         "https://feeds.acast.com/public/shows/0185cea5-9e3b-4b82-a887-26f91f92765f",
         "https://www.nature.com", "Nature's research and news, with the authors."),
    Feed("science", "Science Magazine Podcast", "AAAS",
         "https://feeds.megaphone.fm/AAAS8717073854", "https://www.science.org",
         "Science's research and news, with the authors."),
    Feed("lancet-oncology", "The Lancet Oncology in conversation with", "The Lancet Group, Elsevier",
         "https://feed.podbean.com/lancetonc/feed.xml", "https://www.thelancet.com",
         "Lancet Oncology editors with the authors of its papers."),
    Feed("jama-oncology", "JAMA Oncology Author Interviews", "JAMA Network, American Medical Association",
         "https://rss.libsyn.com/shows/86891/destinations/422099.xml", "https://jamanetwork.com",
         "JAMA Oncology authors on their papers."),
)

BY_KEY = {feed.key: feed for feed in CATALOGUE}
