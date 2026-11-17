# The digest

What scientists are saying before it is in a database: podcasts run by journals and learned
societies, transcribed on this computer, beside the clinical trials and papers the watches
find. Searchable from the Digest screen and from AI mode. Code: `spica/digest/`,
`spica/intel/trials.py`.

## Sources

Chosen for one property: the people talking are the people doing the work, under an editor
who answers for it. Journals, learned societies, universities; no business shows, no
personalities. The feeds are the publishers' own (Apple's podcast directory lists them), and
each was read on 2026-10-28:

| Podcast | Publisher | Transcribed | Why not, when not |
| --- | --- | --- | --- |
| ASCO Daily News | American Society of Clinical Oncology | Yes | |
| Journal of Clinical Oncology Podcast | ASCO | Yes | Some episodes are MP4 audio, listed, not decoded |
| JCO Precision Oncology Conversations | ASCO | Yes | |
| NEJM This Week | NEJM Group | Yes | |
| The eLife Podcast | eLife, with the Naked Scientists (Cambridge) | Yes | |
| AACR Scientific Podcasts | AACR | Yes | Five episodes, the newest from 2025 |
| Nature Podcast | Springer Nature | Titles only | nature.com's TDMRep file reserves text and data mining |
| Science Magazine Podcast | AAAS | Titles only | science.org's TDMRep file reserves it |
| The Lancet Oncology in conversation with | The Lancet, Elsevier | Titles only | thelancet.com's TDMRep file reserves it |
| JAMA Oncology Author Interviews | JAMA Network, AMA | Titles only | The feed's copyright line reserves "text and data mining, AI training" |
| Cell Podcast | Elsevier | Left out | The feed sends `tdm-reservation: 1`, and stopped in 2018 |

Any feed can be added by its address. Video platforms, streaming services and conference
sites behind a login are not supported, by design.

### A reservation is honoured, every time

The EU's copyright directive lets text and data mining proceed on lawfully reached content
unless the rights holder has reserved it in machine-readable form, and publishers do that
with the W3C's TDMRep. On every update, for every feed, Spica checks three places: a
`tdm-reservation` header on the feed, a `/.well-known/tdmrep.json` file on the publisher's
site, and the feed's copyright line. Any of them makes the feed "titles only": its episodes
are listed by title, date and link, and nothing of them is transcribed or indexed. The audio
of each episode is checked again when it is fetched. An added feed is checked the same way,
at once.

Whatever is transcribed stays on this computer. Audio is deleted once transcribed;
transcripts are shown as short passages with a link to the episode and never go into a
client report. This is a reading aid, not a republication; whether a use is fair in a given
jurisdiction is a legal question.

## Transcription

whisper.cpp, run here, through pywhispercpp's low-level bindings, with miniaudio decoding
the audio (both MIT; `./run.sh --speech` installs them). The speech model is one of OpenAI's
Whisper models converted for whisper.cpp (MIT), downloaded once from Digest, Sources:

| Model | Size | Speed measured here |
| --- | --- | --- |
| base.en | 148 MB | a 21-minute episode in 38 s (about 33 times real time, 8 threads) |
| small.en | 488 MB | about three times slower, more accurate on names |

The decoder is primed with oncology vocabulary and the names the watches follow. Names
still come out wrong at times: "sacituzumab govitecan" was heard as "sastatusumab govatican"
by base.en. A publisher's own transcript (the Podcasting 2.0 `<podcast:transcript>` tag) is
used instead whenever the feed links one.

Each update reads every feed that is on, records new episodes, and transcribes the newest few
per feed (Sources, "Transcribe per feed": 3 by default). An episode that cannot be
transcribed says why: no speech model yet (tried again next time), audio this build cannot
decode (MP4/AAC), or a reservation on the audio (both final). Everything is kept the way
watches are kept, appended to `data/digest/events.jsonl` and never rewritten.

**Process all** builds the corpus in one go: every episode of every feed that is on and
allows mining, not only the newest few, newest first across feeds. Sources says beforehand
how many episodes wait, how many hours of audio that is (episodes without a stated length
counted at the median of the rest) and how long it should take at this computer's measured
pace, from the work and audio seconds each transcription records. It runs in the background,
one digest job at a time, survives leaving the screen, and stops between episodes when asked:
what is done stays done, and the next run carries on.

## Genes

Every passage is tagged with the genes it names, through HGNC: written symbols ("KRAS",
"PD-L1", "CLDN18.2", which names CLDN18), spoken ones as speech recognition writes them ("her
two" is ERBB2, "trope two" TACSTD2, "EGF or" is EGFR said letter by letter), aliases two genes
share never used, and clinical abbreviations that are also aliases (ADC, CAR, ORR) left out.
A tag is a pointer for search: the passage is always shown with it.

## Search

Passages are about a minute of speech, an episode's show notes when it has no transcript, a
reserved episode's title, each trial the watches found (title, conditions, interventions,
sponsor, phase, status), and each paper's bibliographic line. Ranked by BM25 over words, with
a boost for passages tagged with a gene the query names, whatever the passage called it. When
an embedding model is installed (the one AI mode uses for documents), each passage is
embedded during the update and the query at search time, and meaning joins the ranking.

The Digest screen shows what arrived when there is no query, filters by kind, gene and date,
marks the query's words in each passage, opens the transcript at the passage's minute, and
sends a gene straight to its report. AI mode searches the same index:
`digest("resistance to KRAS G12C inhibitors; kind podcast; since 2026-01-01")`.

## Clinical trials

Every Intelligence watch now asks ClinicalTrials.gov too, for trials registered or updated
inside its window, on the same widened terms. The registry does not match a symbol inside an
isoform name: in one quarter "CLDN18" found 2 updated trials where "CLDN18.2" found 43, and no
wildcard form works, so a symbol ending in a digit also searches its first two isoform forms.
Trials appear in the watch, with phase, status and sponsor facets, and in the digest.
