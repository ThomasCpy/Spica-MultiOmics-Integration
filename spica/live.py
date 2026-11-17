"""Fetches from the public APIs when a source is not mirrored yet.

This is the only part of Spica that uses the network. It lets the app work
before the mirror exists. It is a fallback, never a preference: Spica never
fetches a mirrored source.

Three rules keep it honest.

*It is visible.* A fetched value has its source URL as its provenance
locator, and the record stamps its source `fetched`, not `read`.

*It is cached.* Each response goes under `<data>/cache/` and is reused from
then on. A rebuilt record thus stays the same, and a second look at the
same gene sends no request. The retrieval date on the provenance is the
date of the fetch, not of the rebuild.

*It is off by default.* "Online access" in Settings is off by default, and
then nothing here uses the network. Unmirrored sources report what they
could not read, and earlier cached answers stay in use. `SPICA_OFFLINE=1`
forces it off, whatever the setting. `SPICA_ONLINE=1` forces it on, for
development. `--offline` and `--online` do the same on the command line.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

USER_AGENT = "Spica/0.1 (target triage; https://github.com/)"
TIMEOUT = 30
CACHE_DIRNAME = "cache"


def network_allowed(explicit: bool | None = None) -> bool:
    """Whether Spica may use the network. Off unless enabled."""
    import os

    if explicit is not None:
        return explicit
    if os.environ.get("SPICA_OFFLINE", "").strip() not in ("", "0", "false"):
        return False
    if os.environ.get("SPICA_ONLINE", "").strip() not in ("", "0", "false"):
        return True
    from spica import settings

    return bool(settings.load().get("online"))


#: What a request says when online access is off. Code tells "offline" from
#: "failed" by it, so it is one constant rather than five strings.
OFF = "online access is off (Settings)"


class LiveError(Exception):
    """The request could not be made or came back unusable."""


class NotFoundUpstream(Exception):
    """The API answered, and has no such record (HTTP 404, or an empty body)."""


class NoLiveRoute(Exception):
    """This source has no API fallback, so only the mirror can fill it."""


@dataclass(frozen=True)
class Response:
    url: str
    payload: Any
    fetched: str  # ISO date, of the fetch rather than of this read
    headers: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False


@dataclass(frozen=True)
class Fetched:
    """What a source got from its API, ready to be given provenance."""

    fields: dict[str, Any]
    version: str  # the release the API reports, or "API" when it reports none
    retrieved: str
    locator: str  # the URL the values came from


def _slug(url: str) -> str:
    """A readable, collision-proof file name for a URL."""
    tail = re.sub(r"[^A-Za-z0-9._-]+", "-", url.rsplit("/", 1)[-1])[:60].strip("-")
    return f"{hashlib.sha1(url.encode()).hexdigest()[:12]}-{tail or 'response'}"


#: Hosts that limit request rates, and the gap kept between two requests to
#: each. NCBI allows three a second without an API key; the agents run tools
#: in parallel, so GEO and ClinVar would otherwise meet HTTP 429.
SPACING = {"eutils.ncbi.nlm.nih.gov": 0.34}
_turns: dict[str, float] = {}
_turns_lock = threading.Lock()


def _wait_turn(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    gap = SPACING.get(host)
    if not gap:
        return
    with _turns_lock:
        now = time.monotonic()
        start = max(now, _turns.get(host, 0.0) + gap)
        _turns[host] = start
    time.sleep(start - now)


def _open(url: str, headers: dict[str, str], timeout: int,
          body: bytes | None = None) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url, data=body, headers={"User-Agent": USER_AGENT, **headers})
    for attempt in (0, 1):
        _wait_turn(url)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            # One retry on a rate limit, after the wait the server asks for.
            if exc.code != 429 or attempt:
                raise
            wait = str(exc.headers.get("Retry-After", "1")).strip()
            time.sleep(min(5.0, float(wait) if wait.isdigit() else 1.0))
    raise AssertionError("unreachable")


class Live:
    """The network side of a build: allowed or not, cached either way."""

    def __init__(
        self,
        root: Path | str,
        allowed: bool = True,
        refresh: bool = False,
        timeout: int = TIMEOUT,
        opener: Callable[..., tuple[bytes, dict[str, str]]] = _open,
    ) -> None:
        self.root = Path(root)
        self.allowed = allowed
        self.refresh = refresh
        self.timeout = timeout
        self._opener = opener
        self.urls: list[str] = []  # what this build requested
        self.network_used: set[str] = set()  # sources that reached the network

    @classmethod
    def from_env(cls, root: Path | str, allowed: bool | None = None, refresh: bool = False):
        """The live layer as the user has set it up.

        `allowed` decides when given (the command line's flags); otherwise
        the environment, then the saved setting, which is off by default.
        """
        return cls(root, allowed=network_allowed(allowed), refresh=refresh)

    # -- cache --------------------------------------------------------------

    def _cache_path(self, source_key: str, url: str) -> Path:
        return self.root / CACHE_DIRNAME / source_key / f"{_slug(url)}.json"

    def _cached(self, source_key: str, url: str) -> Response | None:
        path = self._cache_path(source_key, url)
        if self.refresh or not path.exists():
            return None
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # a half-written cache file is fetched again
        if stored.get("not_found"):
            # "This API has no record for that gene" is a durable answer. It
            # is cached like any other, so an offline rebuild gives the same
            # record and does not fail where it once said not_found.
            raise NotFoundUpstream(stored.get("reason", f"{url} has no record"))
        return Response(
            url=url,
            payload=stored.get("body"),
            fetched=stored.get("fetched", ""),
            headers=stored.get("headers", {}),
            from_cache=True,
        )

    def _store_absence(self, source_key: str, key: str, reason: str) -> None:
        """Remember that there is nothing there, so the next build agrees."""
        path = self._cache_path(source_key, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "url": key,
                "fetched": date.today().isoformat(),
                "not_found": True,
                "reason": reason,
            }, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _store(self, source_key: str, response: Response) -> None:
        path = self._cache_path(source_key, response.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "url": response.url,
                    "fetched": response.fetched,
                    "headers": response.headers,
                    "body": response.payload,
                },
                indent=1,
            ),
            encoding="utf-8",
        )

    # -- requests -----------------------------------------------------------

    def post_json(
        self,
        source_key: str,
        url: str,
        body: dict[str, Any],
        cache_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """A JSON POST, for the sources that answer questions rather than
        serve documents.

        GraphQL is the reason this exists: the URL is the same for every
        query, so `cache_key` names the query. Without it two
        different questions would share one cache file.
        """
        return self.get_json(
            source_key, url, headers=headers,
            body=json.dumps(body).encode("utf-8"),
            cache_key=cache_key or url,
        )

    def post_form(
        self,
        source_key: str,
        url: str,
        form: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """A form POST that is never cached, for exchanging credentials.

        An access token is a secret and expires within the hour: writing it
        to the cache would keep a credential on disk to replay a stale one.
        It still honours the offline switch like every other request.
        """
        if not self.allowed:
            raise LiveError(OFF)
        body = urllib.parse.urlencode(form).encode("ascii")
        sent = {"Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                **(headers or {})}
        self.network_used.add(source_key)
        try:
            raw, _ = self._opener(url, sent, self.timeout, body)
        except urllib.error.HTTPError as exc:
            raise LiveError(f"HTTP {exc.code} from {url}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise LiveError(f"could not reach {url}: {getattr(exc, 'reason', exc)}") from None
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LiveError(f"{url} did not answer with JSON") from None
        if not isinstance(payload, dict):
            raise LiveError(f"{url} answered with something other than an object")
        return payload

    def get_json(
        self,
        source_key: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        cache_key: str | None = None,
    ) -> Response:
        """A JSON response, from the cache when it is there.

        Raises `NotFoundUpstream` when the API has no such record, and
        `LiveError` for all other problems. A source can thus tell "no data"
        from "no answer", as it does when it reads a file.
        """
        key = cache_key or url
        cached = self._cached(source_key, key)
        if cached is not None:
            return cached
        if not self.allowed:
            raise LiveError(OFF)

        self.urls.append(url)
        self.network_used.add(source_key)
        sent = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            sent.setdefault("Content-Type", "application/json")
        try:
            raw, response_headers = self._opener(url, sent, self.timeout, body)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                reason = f"{url} has no record (HTTP 404)"
                self._store_absence(source_key, key, reason)
                raise NotFoundUpstream(reason) from None
            raise LiveError(f"HTTP {exc.code} from {url}") from None
        except urllib.error.URLError as exc:
            raise LiveError(f"could not reach {url}: {exc.reason}") from None
        except OSError as exc:
            raise LiveError(f"could not reach {url}: {exc}") from None

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LiveError(f"{url} did not answer with JSON") from None

        response = Response(
            url=key,
            payload=payload,
            fetched=date.today().isoformat(),
            headers={
                name: value
                for name, value in response_headers.items()
                # Only what provenance needs; the rest is noise in the cache.
                if name.lower().startswith("x-") or name.lower() == "date"
            },
        )
        self._store(source_key, response)
        return response

    def get_text(self, source_key: str, url: str, cache_key: str | None = None) -> Response:
        """A plain-text response (TSV, FASTA), cached like JSON ones.

        Some services answer in tables rather than JSON. The text is stored
        as the payload, so an offline rebuild reads exactly what was read.
        """
        key = cache_key or url
        cached = self._cached(source_key, key)
        if cached is not None:
            return cached
        if not self.allowed:
            raise LiveError(OFF)
        self.urls.append(url)
        self.network_used.add(source_key)
        try:
            raw, _ = self._opener(url, {"Accept": "text/plain, */*"}, self.timeout, None)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                reason = f"{url} has no record (HTTP 404)"
                self._store_absence(source_key, key, reason)
                raise NotFoundUpstream(reason) from None
            raise LiveError(f"HTTP {exc.code} from {url}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise LiveError(f"could not reach {url}: {getattr(exc, 'reason', exc)}") from None
        response = Response(url=key, payload=raw.decode("utf-8", "replace"),
                            fetched=date.today().isoformat())
        self._store(source_key, response)
        return response

    def fetch(self, source_key: str, url: str,
              headers: dict[str, str] | None = None) -> tuple[bytes, dict[str, str]]:
        """Bytes and response headers, uncached: for what Spica keeps on its
        own terms (a podcast feed, an episode's audio). Honours the offline
        switch and counts as network use like any other fetch."""
        if not self.allowed:
            raise LiveError(OFF)
        self.urls.append(url)
        self.network_used.add(source_key)
        try:
            data, received = self._opener(url, headers or {"Accept": "*/*"}, self.timeout, None)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise NotFoundUpstream(f"{url} has no record (HTTP 404)") from None
            raise LiveError(f"HTTP {exc.code} from {url}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise LiveError(f"could not reach {url}: {getattr(exc, 'reason', exc)}") from None
        return data, {key.lower(): value for key, value in (received or {}).items()}

    def raw(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        """Bytes from a URL, uncached: for use inside `remember`, whose
        result is what gets cached. Honours the offline switch."""
        if not self.allowed:
            raise LiveError(OFF)
        try:
            data, _ = self._opener(url, headers or {"Accept": "application/json"},
                                   self.timeout, None)
        except urllib.error.HTTPError as exc:
            raise LiveError(f"HTTP {exc.code} from {url}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise LiveError(f"could not reach {url}: {getattr(exc, 'reason', exc)}") from None
        return data

    def remember(self, source_key: str, key: str, produce: Callable[[], Any]) -> Response:
        """Something computed from several requests, cached as one answer.

        A bigBed region is a header, two index walks and a few compressed
        blocks: caching each range would be pointless, caching the records
        they add up to is what makes the second look instant and offline.
        `produce` runs only when the cache has nothing and the network is
        allowed; whatever it raises, the caller sees.
        """
        cached = self._cached(source_key, key)
        if cached is not None:
            return cached
        if not self.allowed:
            raise LiveError(OFF)
        self.urls.append(key)
        self.network_used.add(source_key)
        response = Response(url=key, payload=produce(), fetched=date.today().isoformat())
        self._store(source_key, response)
        return response
