"""One update: read each active feed, and transcribe the new episodes.

For each feed, newest first, Spica records each new episode. When the
publisher reserves mining, it stops there. Otherwise the newest few
episodes without a transcript get one: the publisher transcript when the
feed links it, else a whisper.cpp transcript of the audio, which is then
deleted. The decoder gets the names that the user's watches follow.

An episode without a transcript gives the cause: no speech model yet (a
retry happens next time), an audio format this build cannot decode, or a
reservation on the audio itself (both final).

"Process all" is the same pass with no per-feed limit. It covers each
episode of each active feed that allows mining, newest first across feeds,
to build the corpus in one go. A stop is possible between episodes. Done
work stays done, and the next run continues from there.
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Callable

from spica.digest import feeds, speech
from spica.digest.store import Store
from spica.live import Live, LiveError, NotFoundUpstream

#: Words that prime the decoder whatever is watched.
PRIMER = ("Oncology and drug discovery. ADC, CAR-T, bispecific, PD-L1, PD-1, HER2, TROP2, "
          "CLDN18.2, KRAS G12C, EGFR, BRCA, ctDNA, NSCLC, phase 3, ASCO, ESMO, AACR. "
          "Sacituzumab govitecan, trastuzumab deruxtecan, datopotamab deruxtecan, enfortumab "
          "vedotin, zolbetuximab, pembrolizumab, nivolumab, osimertinib, sotorasib, adagrasib, "
          "tarlatamab, amivantamab, olaparib, palbociclib.")


def seconds(duration: str) -> int | None:
    """An itunes:duration ("1:02:03", "62:03" or "3723") in seconds."""
    text = str(duration or "").strip()
    try:
        parts = [float(p) for p in text.split(":")] if text else []
    except ValueError:
        return None
    if not parts or len(parts) > 3:
        return None
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return int(total) if total > 0 else None


def waiting(store: Store) -> list[dict[str, Any]]:
    """Every episode "Process all" would transcribe, newest first: in a feed
    that is on, not reserved, not transcribed, not skipped for good."""
    on = {feed.key for feed, enabled in store.feeds() if enabled}
    out = [e for e in store.episodes().values()
           if e.get("feed") in on and not e.get("reserved")
           and e.get("status") != "transcribed" and not e.get("permanent")]
    out.sort(key=lambda e: (e.get("date", ""), e.get("id", "")), reverse=True)
    return out


def pace(store: Store) -> float | None:
    """Seconds of work per second of audio on this computer, from past
    transcriptions. The median, so one odd episode has little effect. None
    before the first timed transcription."""
    ratios = [e["seconds"] / e["audio"] for e in store.events()
              if e.get("event") == "transcribed" and e.get("seconds") and e.get("audio")]
    return round(statistics.median(ratios), 4) if ratios else None


def backlog(store: Store) -> dict[str, Any]:
    """What "Process all" faces: how many episodes, how much audio, how long."""
    episodes = waiting(store)
    lengths = [seconds(e.get("duration", "")) for e in episodes]
    known = [n for n in lengths if n]
    rate = pace(store)
    audio = float(sum(known))
    # Episodes without a stated length are counted at the median of the rest.
    if known and len(known) < len(lengths):
        audio += statistics.median(known) * (len(lengths) - len(known))
    return {"episodes": len(episodes), "audio_hours": round(audio / 3600, 1),
            "unknown_length": len(lengths) - len(known), "pace": rate,
            "estimate_hours": round(audio * rate / 3600, 1) if rate and audio else None}


def update(store: Store, live: Live, prime: list[str] | None = None,
           progress: Callable[[int, int], None] | None = None,
           everything: bool = False, stop: Any = None) -> dict[str, Any]:
    chosen = store.settings()
    per_feed = max(0, int(chosen["per_feed"]))
    enabled = [feed for feed, on in store.feeds() if on]
    known = store.episodes()
    ready = speech.status()["ready"]
    prompt = PRIMER + (" " + ", ".join(prime) + "." if prime else "")
    summary = {"feeds": 0, "new": 0, "transcribed": 0, "problems": [], "everything": everything}
    work: list[tuple[Any, dict[str, Any]]] = []

    for feed in enabled:
        try:
            parsed = feeds.read(feed.key, feed.url, feed.site, live)
        except (LiveError, NotFoundUpstream, ValueError) as exc:
            summary["problems"].append(f"{feed.name}: {exc}")
            continue
        summary["feeds"] += 1
        for episode in parsed["episodes"]:
            if episode["id"] not in known:
                store.append({"event": "seen", **episode, "reserved": parsed["reserved"]})
                known[episode["id"]] = {**episode, "reserved": parsed["reserved"]}
                summary["new"] += 1
        if parsed["reserved"] or everything:
            continue
        pending = [e for e in parsed["episodes"]
                   if not (known[e["id"]].get("status") == "transcribed"
                           or known[e["id"]].get("permanent"))][:per_feed]
        work += [(feed, episode) for episode in pending]

    if everything:
        # Every episode on record, not only those the feed still lists.
        feeds_by_key = {feed.key: feed for feed in enabled}
        work = [(feeds_by_key[e["feed"]], e) for e in waiting(store) if e.get("feed") in feeds_by_key]

    for done, (feed, episode) in enumerate(work, start=1):
        if stop is not None and stop.is_set():
            summary["stopped"] = True
            break
        if progress:
            progress(done - 1, len(work))
        began = time.monotonic()
        try:
            segments, engine = _transcript(episode, live, ready, prompt)
        except _Skip as skip:
            store.append({"event": "skipped", "id": episode["id"], "reason": str(skip),
                          "permanent": skip.permanent})
            continue
        except (LiveError, NotFoundUpstream, RuntimeError, ValueError) as exc:
            summary["problems"].append(f"{feed.name}, {episode['title'][:60]}: {exc}")
            continue
        store.write_transcript(episode["id"], segments, engine)
        timed = {}
        if engine.startswith("whisper") and segments:
            # Timed, so "Process all" can say how long the rest will take.
            timed = {"seconds": round(time.monotonic() - began, 1),
                     "audio": round(float(segments[-1][1]), 1)}
        store.append({"event": "transcribed", "id": episode["id"], "engine": engine,
                      "segments": len(segments), **timed})
        summary["transcribed"] += 1
    if progress and not summary.get("stopped"):
        progress(len(work), len(work))
    store.append({"event": "update", **summary})
    return summary


class _Skip(Exception):
    def __init__(self, reason: str, permanent: bool) -> None:
        super().__init__(reason)
        self.permanent = permanent


def _transcript(episode: dict[str, Any], live: Live, ready: bool, prompt: str) -> tuple[list, str]:
    for offered in episode.get("transcripts", []):
        try:
            body, _ = live.fetch(feeds.SOURCE_KEY, offered["url"])
            segments = feeds.transcript_segments(body.decode("utf-8", "replace"), offered["type"])
        except (LiveError, NotFoundUpstream, ValueError):
            continue
        if segments:
            return segments, "the publisher's transcript"
    if not episode.get("audio"):
        raise _Skip("the feed gives no audio for this episode", True)
    kind = (episode.get("type") or "").lower()
    if kind and kind not in speech.DECODABLE:
        raise _Skip(f"its audio is {kind}, which this build cannot decode", True)
    if not ready:
        problem = speech.engine() or "no speech model yet: download one in Digest, Sources"
        raise _Skip(problem, False)
    try:
        audio, headers = live.fetch(feeds.SOURCE_KEY, episode["audio"])
    except NotFoundUpstream:
        raise _Skip("its audio is gone from the publisher's server (HTTP 404)", True) from None
    if str(headers.get("tdm-reservation", "")).strip() == "1":
        raise _Skip("the audio's server reserves text and data mining", True)
    model = speech.model()
    segments = speech.transcribe(audio, prompt)
    return segments, f"whisper.cpp, {model.name if model else 'local model'}"
