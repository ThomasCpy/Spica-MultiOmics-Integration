"""Transcribing an episode on this computer, with whisper.cpp.

Optional, like the local language model: the engine is pywhispercpp's
bindings to whisper.cpp (MIT) and miniaudio (MIT) to decode MP3, WAV, FLAC
and Ogg; the model is one of OpenAI's Whisper models converted for
whisper.cpp (MIT), downloaded once into `data/models/speech/` by an
explicit action. Without them the digest still lists episodes.

Only the low-level bindings are used: pywhispercpp's convenience layer
would pull in packages under licences the exe does not ship.

The decoder is primed with the names the user watches, so "CLDN18.2" is
more likely to come out as written than as "claudine eighteen".
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Callable

from spica.paths import data_dir

#: The models offered, smallest first: (file, megabytes, what it is for).
MODELS = {
    "base.en": ("ggml-base.en.bin", 148, "English, fast: about 30 times real time on a laptop"),
    "small.en": ("ggml-small.en.bin", 488, "English, more accurate, about three times slower"),
}
SOURCE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
SAMPLE_RATE = 16000
#: Audio types miniaudio decodes; others (MP4/AAC) are listed, not transcribed.
DECODABLE = ("audio/mpeg", "audio/mp3", "audio/x-mpeg", "audio/wav", "audio/x-wav", "audio/flac",
             "audio/ogg", "audio/x-flac")


def folder() -> Path:
    return data_dir() / "models" / "speech"


def engine() -> str:
    """Why transcription cannot run, or "" when it can (model aside)."""
    try:
        import _pywhispercpp  # noqa: F401
        import miniaudio  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as exc:
        return (f"the transcription engine is not installed ({exc.name}); run "
                "`./run.sh --speech`, or use publisher transcripts only")
    return ""


def model() -> Path | None:
    """The speech model to use: the most accurate one present."""
    for name in reversed(list(MODELS)):
        path = folder() / MODELS[name][0]
        if path.exists() and path.stat().st_size > 1_000_000:
            return path
    return None


def status() -> dict:
    problem = engine()
    found = model()
    return {"engine": not problem, "problem": problem,
            "model": found.name if found else "",
            "models": [{"name": name, "file": file, "megabytes": mb, "about": about,
                        "present": (folder() / file).exists()}
                       for name, (file, mb, about) in MODELS.items()],
            "ready": not problem and found is not None}


def download(name: str, progress: Callable[[int, int], None] | None = None) -> Path:
    """Fetch one model, as an explicit action (like updating the mirror)."""
    if name not in MODELS:
        raise ValueError(f"no speech model called {name}")
    file, _, _ = MODELS[name]
    dest = folder() / file
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    request = urllib.request.Request(SOURCE + file, headers={"User-Agent": "Spica/0.1 (speech model)"})
    with urllib.request.urlopen(request, timeout=120) as response, open(part, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(part, dest)
    return dest


def decode(audio: bytes):
    """Mono float32 samples at 16 kHz, what whisper.cpp reads."""
    import miniaudio
    import numpy as np

    decoded = miniaudio.decode(audio, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1,
                               sample_rate=SAMPLE_RATE)
    return np.asarray(decoded.samples, dtype=np.float32)


def transcribe(audio: bytes, prompt: str = "", threads: int | None = None) -> list[list]:
    """[[start, end, text]] in seconds, for one episode's audio."""
    import _pywhispercpp as pw

    path = model()
    if path is None:
        raise RuntimeError("no speech model: download one in Digest, Sources")
    samples = decode(audio)
    context = pw.whisper_init_from_file_with_params(str(path), pw.whisper_context_default_params())
    try:
        params = pw.whisper_full_default_params(pw.whisper_sampling_strategy.WHISPER_SAMPLING_GREEDY)
        params.n_threads = threads or max(1, min(8, (os.cpu_count() or 4) - 1))
        params.print_progress = False
        params.print_realtime = False
        params.language = "en"
        if prompt:
            params.initial_prompt = prompt[:800]
        pw.whisper_full(context, params, samples, samples.size)
        out = []
        for i in range(pw.whisper_full_n_segments(context)):
            text = pw.whisper_full_get_segment_text(context, i).decode("utf-8", "replace").strip()
            if text and not (text.startswith(("[", "(")) and text.endswith(("]", ")"))):
                # "[MUSIC PLAYING]" and "(upbeat music)" are not speech.
                out.append([pw.whisper_full_get_segment_t0(context, i) / 100,
                            pw.whisper_full_get_segment_t1(context, i) / 100, text])
        return out
    finally:
        pw.whisper_free(context)
