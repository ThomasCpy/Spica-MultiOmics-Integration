"""The digest: what scientists say, before it is in a database.

Podcasts from journals, learned societies and universities (meeting
coverage, author interviews, expert discussion), transcribed on this
computer, and clinical trials as they are registered and updated. Each
episode is cut into passages. Each passage carries the genes it names. The
Digest screen and AI mode can search all of it.

Three rules make it a tool that a scientist can trust:

- **Chosen sources, no scraping.** A short catalogue of feeds from
  publishers and societies (`catalogue.py`), plus feeds that the user adds.
  No video platform, no streaming service, no conference site with a login.
- **A publisher's reservation is respected.** Some publishers reserve text
  and data mining in machine-readable form: a `tdm-reservation` header, a
  TDMRep file on their site, or a copyright line. A reserved feed shows
  episode titles and links only. Spica does not transcribe or index it
  (`feeds.reservation`).
- **Nothing leaves this computer.** Audio is downloaded, transcribed and
  deleted. Transcripts stay here. They show as short quotes with a link to
  the episode and never go into a report.

The fetch goes through the live layer, as for Intelligence. It needs the
network by nature, respects `SPICA_OFFLINE`, and gathered data stays
readable offline. Transcription is optional, as is the local language
model. Without whisper.cpp or a speech model, the episode list still shows,
with show notes and any transcript from the publisher.
"""
