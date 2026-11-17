"""Reading a podcast feed, and whether its publisher permits text and data mining.

A feed is RSS: one item per episode, with a title, a date, the audio as an
enclosure, show notes, and sometimes a publisher transcript
(`<podcast:transcript>`, the Podcasting 2.0 tag). These are read as they
are. Spica visits nothing else on the publisher site, except the one file
that states a text and data mining reservation.

`reservation` is the base rule of the digest. The EU copyright directive
permits text and data mining on lawfully accessed content, unless the
rights holder reserved it "in an appropriate manner, such as
machine-readable means". Publishers use the W3C TDMRep for this: a
`tdm-reservation` HTTP header, or a `/.well-known/tdmrep.json` file. Some
put it in the copyright line of the feed. Any of the three limits the feed
to titles and links.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from hashlib import sha1
from typing import Any

from spica.live import Live, LiveError, NotFoundUpstream

SOURCE_KEY = "digest"
NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
      "podcast": "https://podcastindex.org/namespace/1.0",
      "content": "http://purl.org/rss/1.0/modules/content/"}
#: Words in a copyright line that reserve mining, whatever the header says.
RESERVING = ("text and data mining", "data mining", "ai training", "machine learning")


def _text(element, path: str) -> str:
    found = element.find(path, NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def plain(markup: str) -> str:
    """Show notes as text: tags dropped, entities read, spaces collapsed."""
    text = re.sub(r"<(br|p|/p|li)[^>]*>", "\n", markup or "", flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def iso(stamp: str) -> str:
    try:
        return parsedate_to_datetime(stamp).date().isoformat()
    except (TypeError, ValueError, IndexError):
        found = re.search(r"\d{4}-\d{2}-\d{2}", stamp or "")
        return found.group(0) if found else ""


def episode_id(feed_key: str, guid: str) -> str:
    return sha1(f"{feed_key}|{guid}".encode()).hexdigest()[:16]


def parse(feed_key: str, body: bytes) -> dict[str, Any]:
    """The channel and its episodes, newest first."""
    root = ET.fromstring(body)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("not an RSS feed: no channel")
    episodes = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        audio = enclosure.get("url", "") if enclosure is not None else ""
        guid = _text(item, "guid") or audio or _text(item, "link") or _text(item, "title")
        transcripts = [{"url": node.get("url", ""), "type": node.get("type", "")}
                       for node in item.findall("podcast:transcript", NS) if node.get("url")]
        notes = _text(item, "content:encoded") or _text(item, "description") \
            or _text(item, "itunes:summary")
        episodes.append({
            "id": episode_id(feed_key, guid), "feed": feed_key, "guid": guid,
            "title": html.unescape(_text(item, "title")),
            "date": iso(_text(item, "pubDate")),
            "link": _text(item, "link"),
            "audio": audio,
            "type": enclosure.get("type", "") if enclosure is not None else "",
            "duration": _text(item, "itunes:duration"),
            "notes": plain(notes)[:4000],
            "transcripts": transcripts,
        })
    episodes.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return {"title": _text(channel, "title"), "link": _text(channel, "link"),
            "copyright": html.unescape(_text(channel, "copyright")),
            "episodes": episodes}


def _tdmrep(site: str, live: Live) -> str:
    """The reservation a site's TDMRep file declares for its root, or ""."""
    if not site:
        return ""
    url = urllib.parse.urljoin(site.rstrip("/") + "/", ".well-known/tdmrep.json")
    try:
        body, _ = live.fetch(SOURCE_KEY, url, {"Accept": "application/json"})
        rules = json.loads(body.decode("utf-8", "replace"))
    except (LiveError, NotFoundUpstream, ValueError):
        return ""
    for rule in rules if isinstance(rules, list) else []:
        if isinstance(rule, dict) and str(rule.get("tdm-reservation")) == "1":
            policy = rule.get("tdm-policy") or ""
            return f"{site} reserves text and data mining (TDMRep{', policy ' + str(policy) if policy else ''})"
    return ""


def reservation(headers: dict[str, str], copyright_line: str, site: str, live: Live) -> str:
    """Why this feed may not be mined, or "" when nothing reserves it."""
    if str(headers.get("tdm-reservation", "")).strip() == "1":
        return "the feed's server reserves text and data mining (tdm-reservation header)"
    lowered = copyright_line.lower()
    for words in RESERVING:
        if words in lowered:
            return f'the feed\'s copyright line reserves it: "{copyright_line.strip()[:200]}"'
    return _tdmrep(site, live)


def read(feed_key: str, url: str, site: str, live: Live) -> dict[str, Any]:
    """Fetch and parse a feed, and say whether it may be mined."""
    body, headers = live.fetch(SOURCE_KEY, url, {"Accept": "application/rss+xml, application/xml, */*"})
    parsed = parse(feed_key, body)
    host = site or "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(parsed["link"] or url))
    parsed["reserved"] = reservation(headers, parsed["copyright"], host, live)
    return parsed


# -- publisher transcripts --------------------------------------------------------------------


def _clock(stamp: str) -> float:
    parts = stamp.strip().replace(",", ".").split(":")
    try:
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
        return seconds
    except ValueError:
        return 0.0


def transcript_segments(body: str, kind: str) -> list[list[Any]]:
    """[[start, end, text]] in seconds, from WebVTT, SRT, JSON or plain text."""
    kind = kind.lower()
    if "json" in kind:
        data = json.loads(body)
        rows = data.get("segments", []) if isinstance(data, dict) else []
        return [[float(r.get("startTime", 0)), float(r.get("endTime", 0)),
                 str(r.get("body", "")).strip()] for r in rows if str(r.get("body", "")).strip()]
    if "vtt" in kind or "srt" in kind or "subrip" in kind or "-->" in body:
        out = []
        for block in re.split(r"\n\s*\n", body.replace("\r", "")):
            lines = [line for line in block.split("\n") if line.strip()]
            timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if timing is None:
                continue
            start, _, end = lines[timing].partition("-->")
            text = " ".join(re.sub(r"<[^>]+>", "", line) for line in lines[timing + 1:]).strip()
            if text:
                out.append([_clock(start), _clock(end.split()[0] if end.split() else end), text])
        return out
    text = plain(body)
    return [[0.0, 0.0, paragraph] for paragraph in text.split("\n") if paragraph.strip()]
