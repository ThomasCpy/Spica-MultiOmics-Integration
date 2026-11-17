"""Spica desktop app: a native window around the React interface.

Run:   python app.py          (loads frontend/dist/index.html)
Dev:   python app.py --dev    (loads the Vite dev server with hot reload;
                               start it first with `npm run dev` in frontend/)

Python owns the window. The interface calls each public method of `Api`
as `window.pywebview.api.<method>(...)`. Each call returns a Promise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import webview

from spica import build_record, schema_to_dict, summarize
from spica.compare import compare
from spica.dogma import align
from spica.glance import glance
from spica.locations import compartments
from spica.metrics import tau_bands
from spica.agents import Agents
from spica import settings
from spica.intel import Watches, run_watch
from spica.intel.patents import Credentials
from spica.intel.terms import gene_lookup
from spica.live import Live, LiveError, NotFoundUpstream, network_allowed
from spica.mirror import Mirror
from spica.genome import atlas as genome_atlas_view, encode as genome_encode, locus as genome_locus, tracks as genome_tracks
from spica import (benchmark, coexpression, genelist, genetics, interactions, isoforms,
                   ranking, recent, regulators, structure)
from spica.sources import SOURCES
from spica.paths import bundled, frozen

APP_DIR = Path(__file__).resolve().parent
UI_FILE = bundled("frontend", "dist", "index.html")
DEV_URL = "http://localhost:5173"


class Api:
    """Backend entry points for the interface.

    All methods return plain data. The agent methods use polling, not push.
    A model streams for minutes. A polled snapshot survives a reload, a stall
    and a crash. A one-shot callback does not.
    """

    def __init__(self) -> None:
        self.agents = Agents()
        self._job: subprocess.Popen | None = None
        # Reports saved in this session: the only files open_exported opens.
        self._exported: set[str] = set()
        self._jobs = Jobs()

    # -- the licence ------------------------------------------------------

    def licence_documents(self) -> dict:
        """The licence and the third-party notices, as shipped."""
        return {name: _read_bundled(file) for name, file in
                (("licence", "LICENSE"), ("notices", "THIRD_PARTY_NOTICES.md"))}

    def build_report(self, target: str) -> dict:
        """Build the gene record for `target` and send it to the interface.

        The result has `status`, a one-line `message` for the welcome screen,
        the `schema` of the record, and the `record`. Each field has a value
        and its provenance, or a null state that gives the cause.

        Spica reads mirrored sources from disk. It fetches the other sources
        from their public APIs and caches the answers, so the app works before
        the mirror exists. `SPICA_OFFLINE=1` stops the fetch. The fields then
        stay empty, and each one says what is missing.
        """
        try:
            record = build_record(target)
        except Exception as exc:  # a crash in the data layer is still an answer
            return {
                "status": "error",
                "message": f"Record not built: {exc}",
                "schema": schema_to_dict(),
                "record": None,
            }

        if record.resolution.resolved:
            recent.add(record.resolution.symbol or record.query)
        return {
            "status": "ok" if record.resolution.resolved else "unresolved",
            "message": summarize(record),
            "schema": schema_to_dict(),
            "record": record.to_dict(),
            # Transcript and protein on one organ axis. Derived from the
            # record, so it is as deterministic as the record is.
            "dogma": align(record) if record.resolution.resolved else None,
            # The tau bands the specificity class is cut from, so the plot
            # and the label read from one definition.
            "bands": tau_bands(),
            # The words its GO terms and disease associations keep returning
            # to, for the top of the report. Derived from the record too.
            "glance": glance(record) if record.resolution.resolved else None,
            # Where the protein sits: UniProt, HPA and GO on one set of
            # compartments, for the cell diagram.
            "locations": compartments(record) if record.resolution.resolved else None,
        }


    def build_comparison(self, targets: list) -> dict:
        """Several genes side by side, deterministically.

        The comparable measures lead, because that is the question a table
        answers that six database pages do not.
        """
        queries = [str(t).strip() for t in (targets or []) if str(t).strip()]
        if not queries:
            return {"error": "No gene entered."}
        if len(queries) > 8:
            return {"error": "Eight genes maximum."}
        try:
            table = compare(queries)
        except Exception as exc:
            return {"error": f"Comparison not built: {exc}"}
        table["schema"] = schema_to_dict()
        table["bands"] = tau_bands()
        return table

    # -- competitive intelligence ----------------------------------------

    def _intel(self) -> tuple[Live, Watches, Credentials, Mirror]:
        mirror = Mirror.load()
        chosen = settings.load()
        return (Live.from_env(mirror.root), Watches(mirror.root),
                Credentials(chosen["epo_key"], chosen["epo_secret"]), mirror)

    def intel_status(self) -> dict:
        """Whether patents can be searched, and the watches kept so far."""
        live, watches, credentials, _ = self._intel()
        return {
            "patents_configured": credentials.present,
            "online": live.allowed,
            "watches": watches.list(),
        }

    def intel_watch(self, topic: str, days: int = 90, expand: bool = True) -> dict:
        """Check a topic for new papers, preprints and patents, and keep the check."""
        live, watches, credentials, mirror = self._intel()
        try:
            return run_watch(topic, live, watches, credentials, days=int(days),
                             expand=bool(expand),
                             lookup=gene_lookup(mirror, live) if expand else None)
        except Exception as exc:
            return {"error": f"Check failed: {exc}"}

    def intel_open(self, slug: str) -> dict:
        """The last check of a saved watch, readable offline."""
        _, watches, _, _ = self._intel()
        found = watches.latest(slug)
        if found is None:
            return {"error": "No check for this watch."}
        found["slug"] = slug
        return found

    def intel_configure(self, key: str, secret: str) -> dict:
        """Save the user's OPS credentials, after proving they work.

        The secret goes to settings and to ops.epo.org, never back to the
        interface: the screen only ever learns whether one is set.
        """
        key, secret = (key or "").strip(), (secret or "").strip()
        if not key and not secret:
            settings.save({"epo_key": "", "epo_secret": ""})
            return {"ok": True, "patents_configured": False}
        credentials = Credentials(key, secret)
        live, _, _, _ = self._intel()
        try:
            credentials.token(live)
        except LiveError as exc:
            return {"ok": False, "error": f"Credentials rejected by EPO: {exc}"}
        settings.save({"epo_key": key, "epo_secret": secret})
        return {"ok": True, "patents_configured": True}

    def app_status(self) -> dict:
        """What the sidebar shows: how much is local, whether the network is
        used, and the reports built on this machine."""
        mirror = Mirror.load()
        live = Live.from_env(mirror.root)
        local = [source.label for source in SOURCES if source.availability(mirror)[0]]
        from spica import mirrorbuild

        # Sources the views beside the record read (OmniPath), mirrored too.
        extra =[key for key in mirrorbuild.STEPS if key not in {source.key for source in SOURCES}]
        local += [mirrorbuild.LABELS[key] for key in extra
                  if (entry := mirror.entry(key)) is not None and not entry.missing_files()]
        return {"local": local, "sources": len(SOURCES) + len(extra), "online": live.allowed,
                "recent": recent.load()}

    # -- settings and the local data ------------------------------------

    def settings_status(self) -> dict:
        """The choices Settings shows, and what overrides them."""
        forced = ("SPICA_OFFLINE" if os.environ.get("SPICA_OFFLINE", "").strip()
                  not in ("", "0", "false") else
                  "SPICA_ONLINE" if os.environ.get("SPICA_ONLINE", "").strip()
                  not in ("", "0", "false") else "")
        chosen = settings.load()
        return {"online": chosen.get("online", False),
                "online_effective": network_allowed(), "forced_by": forced,
                "theme": chosen.get("theme", "light"),
                "thinking": bool(chosen.get("thinking", True)),
                "menu": chosen.get("menu", "sidebar")}

    def set_menu(self, style: str) -> dict:
        """The main menu: the sidebar, or floating cards on a home screen."""
        if style in ("sidebar", "cards"):
            settings.save({"menu": style})
        return self.settings_status()

    def set_thinking(self, on: bool) -> dict:
        """AI mode: reason before planning and writing, or answer at once."""
        settings.save({"thinking": bool(on)})
        return self.settings_status()

    def set_online(self, on: bool) -> dict:
        """Turn Spica's own use of the network on or off."""
        settings.save({"online": bool(on)})
        return self.settings_status()

    def set_theme(self, theme: str) -> dict:
        """Light, dark, or "system" to follow Windows."""
        if theme in ("light", "dark", "system"):
            settings.save({"theme": theme})
        return self.settings_status()

    def mirror_status(self) -> dict:
        """Every source: what is local, what is newer upstream (as of the
        last check), and what a running update is doing."""
        from spica import mirrorbuild

        mirror = Mirror.load()
        latest = _read_json(mirrorbuild.LATEST)
        job = _read_json(mirrorbuild.STATUS)
        ours = self._job is not None and self._job.poll() is None
        # Alive if this window started it and it runs, or another window's
        # build is still beating; a build that stopped beating has died.
        beating = bool(job.get("running")) and time.time() - float(job.get("beat") or 0) < 60
        job["running"] = ours or beating
        if job.get("running") is False and job.get("started") and not job.get("finished"):
            job["interrupted"] = True
        labels = {**mirrorbuild.LABELS, **{source.key: source.label for source in SOURCES}}
        rows = []
        for key in mirrorbuild.STEPS:
            entry = mirror.entries.get(key)
            found = (latest.get("sources") or {}).get(key) or {}
            local = entry.version if entry else ""
            upstream = found.get("version", "")
            size = sum((mirror.root / rel).stat().st_size for rel in entry.files.values()
                       if (mirror.root / rel).exists()) if entry else 0
            rows.append({
                "key": key, "label": labels.get(key, key), "version": local,
                "retrieved": entry.retrieved if entry else "", "bytes": size,
                "missing": entry.missing_files() if entry else [],
                "latest": upstream, "error": found.get("error", ""),
                "newer": bool(upstream) and bool(local) and upstream != local,
            })
        return {"rows": rows, "checked": latest.get("checked", ""), "job": job,
                "folder": str(mirror.root), "online": network_allowed(),
                "parquet": mirrorbuild.has_parquet()}

    def mirror_check(self) -> dict:
        """Ask each source for its newest release: one small request each."""
        from spica import mirrorbuild

        mirrorbuild.latest()
        return self.mirror_status()

    def mirror_update(self, sources: list, rebuild: bool = True) -> dict:
        """Build or rebuild sources, in a process of its own so the window
        stays responsive through a half-hour download."""
        from spica import mirrorbuild

        status = self.mirror_status()
        if status["job"].get("running"):
            return {**status, "error": "Update already running."}
        chosen = [key for key in mirrorbuild.STEPS if key in (sources or [])]
        if not chosen:
            return {**status, "error": "No source selected."}
        if frozen():
            command = [sys.executable, "--build-mirror", *chosen]
        else:
            command = [sys.executable, "-m", "spica.mirrorbuild", *chosen]
        if rebuild:
            command.append("--refresh")
        no_window = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        try:
            self._job = subprocess.Popen(command, cwd=APP_DIR, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=no_window)
        except OSError as exc:
            return {**status, "error": f"Update not started: {exc}"}
        time.sleep(1.5)  # let it write its first status before the screen asks
        return self.mirror_status()

    def mirror_stop(self) -> dict:
        """Stop an update this window started. Files finished so far stay;
        a source half way through keeps the release it had."""
        if self._job is not None and self._job.poll() is None:
            self._job.terminate()
            try:
                self._job.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._job.kill()
        return self.mirror_status()

    # -- the genome view -------------------------------------------------

    def _locus(self, symbol: str, ensembl_id: str):
        mirror = Mirror.load()
        live = Live.from_env(mirror.root)
        return genome_locus.find(str(symbol), str(ensembl_id), live, mirror), live

    def genome_locus(self, symbol: str, ensembl_id: str, top_tissue: str = "") -> dict:
        """The gene's window, its sequence, and every track that can go on it.

        Tracks are listed here and fetched one by one with `genome_track`, so
        the view opens as soon as the default tracks arrive.
        """
        try:
            locus, live = self._locus(symbol, ensembl_id)
            reference = genome_locus.reference(locus, live)
        except genome_locus.LocusError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Locus not opened: {exc}"}
        return {
            "locus": locus.to_dict(),
            "reference": reference,
            "catalog": [track.to_dict() for track in genome_tracks.CATALOG],
            "hint": genome_tracks.tissue_hint(top_tissue),
            "labels": genome_tracks.gtex_labels(live),
            "organs": list(genome_encode.ORGANS),
            "assays": {key: spec["label"] for key, spec in genome_encode.ASSAYS.items()},
            "online": live.allowed,
        }

    def genome_track(self, symbol: str, ensembl_id: str, track_id: str) -> dict:
        """One track's features for the window, or why there are none."""
        try:
            locus, live = self._locus(symbol, ensembl_id)
        except Exception as exc:
            return {"id": track_id, "state": "failed", "reason": str(exc)}
        return genome_tracks.load(str(track_id), locus, live)

    def genome_encode(self, symbol: str, ensembl_id: str, organ: str, assay: str,
                      adult: bool = True) -> dict:
        """ENCODE experiments of one assay in one organ, each a possible track."""
        if assay not in genome_encode.ASSAYS:
            return {"state": "failed", "reason": f"no assay called {assay}", "items": []}
        live = Live.from_env(Mirror.load().root)
        return genome_encode.by_organ(live, str(organ), assay, bool(adult))

    def genome_regulators(self, symbol: str, ensembl_id: str) -> dict:
        """The gene's regulators (OmniPath, commercial records) and their ENCODE ChIP-seq."""
        try:
            locus, live = self._locus(symbol, ensembl_id)
            tfs = genome_tracks.regulators(locus, live, Mirror.load())
        except Exception as exc:
            return {"state": "failed", "reason": str(exc), "regulators": [], "items": []}
        found = genome_encode.for_regulators(live, tfs)
        return {**found, "regulators": tfs}

    def tf_analysis(self, symbol: str, ensembl_id: str, upstream: int = 2000,
                    downstream: int = 500) -> dict:
        """The gene's regulators, their JASPAR motifs scanned in its promoter,
        and whether each factor's own ChIP-seq peak covers its sites."""
        from spica import tfscan

        mirror = Mirror.load()
        try:
            return tfscan.analyse(str(symbol), str(ensembl_id), Live.from_env(mirror.root), mirror,
                                  int(upstream), int(downstream))
        except Exception as exc:  # a crash in the scan is still an answer
            return {"state": "failed", "error": f"Analysis failed: {exc}"}

    # -- GEO: any series, its samples, their tracks -------------------------

    def geo_search(self, text: str, human: bool = True, tracks: bool = False, offset: int = 0) -> dict:
        """GEO series for any terms, a gene's other names included."""
        from spica.geo import search as geo_search
        from spica.intel.terms import gene_lookup

        mirror = Mirror.load()
        live = Live.from_env(mirror.root)
        text = str(text or "").strip()
        if text.upper().startswith("GSE") and text[3:].isdigit():
            return {"open": text.upper()}
        try:
            return geo_search.search(text, live, bool(human), bool(tracks), int(offset or 0),
                                     lookup=gene_lookup(mirror, live))
        except LiveError as exc:
            return {"error": _offline_or(exc, "GEO search failed")}
        except Exception as exc:
            return {"error": f"GEO search failed: {exc}"}

    def geo_series(self, accession: str) -> dict:
        """One series: what it is, every sample in context, every file."""
        from spica.geo import records as geo_records

        live = Live.from_env(Mirror.load().root)
        try:
            return geo_records.read(str(accession or ""), live)
        except ValueError as exc:
            return {"error": str(exc)}
        except NotFoundUpstream as exc:
            return {"error": str(exc)}
        except LiveError as exc:
            return {"error": _offline_or(exc, "GEO not read")}
        except Exception as exc:
            return {"error": f"Series not read: {exc}"}

    def gene_locate(self, text: str) -> dict:
        """A gene's symbol and Ensembl id, to open its locus outside a report."""
        from spica.build import identity

        try:
            resolution, _ = identity(str(text or ""))
        except Exception as exc:
            return {"error": f"Gene not resolved: {exc}"}
        if not resolution.resolved or not resolution.ensembl_gene_id:
            return {"error": f"{text}: no genome position."}
        return {"symbol": resolution.symbol, "ensembl_id": resolution.ensembl_gene_id}

    def geo_gene(self, accession: str, symbol: str, file_url: str = "") -> dict:
        """One gene's values in a series' processed table, sample by sample."""
        from spica.geo import records as geo_records, response as geo_response
        from spica.intel.terms import gene_lookup

        mirror = Mirror.load()
        live = Live.from_env(mirror.root)
        try:
            found = geo_records.read(str(accession or ""), live)
            fields = gene_lookup(mirror, live)(str(symbol or "").strip()) or {}
            gene = str(fields.get("symbol") or symbol or "").strip()
            if not gene:
                return {"error": "No gene entered."}
            aliases = [str(a) for a in (fields.get("aliases") or []) + (fields.get("previous_symbols") or [])]
            return {"gene": gene, **geo_response.gene(found, gene, str(fields.get("ensembl_gene_id") or ""),
                                                      live, str(file_url or ""), aliases)}
        except ValueError as exc:
            return {"error": str(exc)}
        except LiveError as exc:
            return {"error": _offline_or(exc, "Table not read")}
        except Exception as exc:
            return {"error": f"Table not read: {exc}"}

    def geo_de_inspect(self, accession: str, file_url: str) -> dict:
        """What one table file of a series holds, and the analyses it allows."""
        from spica.geo import de, records as geo_records

        live = Live.from_env(Mirror.load().root)
        try:
            found = geo_records.read(str(accession or ""), live)
            return {"tables_in_series": [{"name": t["name"], "url": t["url"]} for t in de.tables(found)],
                    **(de.inspect(found, str(file_url), live) if file_url else {})}
        except (ValueError, de.DeError) as exc:
            return {"error": str(exc)}
        except LiveError as exc:
            return {"error": _offline_or(exc, "Table not read")}
        except Exception as exc:
            return {"error": f"Table not read: {exc}"}

    def geo_de_start(self, accession: str, file_url: str, sheet: str, route: str, contrast: str = "",
                     field: str = "", reference: str = "", comparison: str = "", covariate: str = "",
                     reference_columns: list | None = None, comparison_columns: list | None = None) -> dict:
        """Volcano data for one table, in the background: published results as
        published, or DESeq2 on raw counts. Poll job_status."""
        from spica.geo import de, records as geo_records

        def work(progress):
            mirror = Mirror.load()
            live = Live.from_env(mirror.root)
            try:
                found = geo_records.read(str(accession or ""), live)
                result = de.run(found, str(file_url), str(sheet or ""), live, mirror, str(route),
                                str(contrast or ""), str(field or ""), str(reference or ""),
                                str(comparison or ""), str(covariate or ""),
                                [str(c) for c in reference_columns or []],
                                [str(c) for c in comparison_columns or []])
            except de.DeError as exc:
                return {"error": str(exc)}
            except LiveError as exc:
                return {"error": _offline_or(exc, "Table not read")}
            progress(1, 1)
            return result

        return {"job": self._jobs.start("de", 1, work)}

    def genome_atlas(self, symbol: str, ensembl_id: str, family: str) -> dict:
        """One assay across every tissue, over the locus: the regulation atlas."""
        try:
            locus, live = self._locus(symbol, ensembl_id)
        except Exception as exc:
            return {"error": str(exc)}
        return genome_atlas_view.atlas(str(family), locus, live)

    # -- views over one gene, beside the record ---------------------------

    def structure_profile(self, accession: str) -> dict:
        """AlphaFold confidence, AlphaMissense and PDB coverage along the sequence."""
        try:
            mirror = Mirror.load()
            return structure.profile(str(accession), Live.from_env(mirror.root), mirror)
        except Exception as exc:
            return {"error": f"Structure profile not built: {exc}"}

    def isoform_table(self, symbol: str, ensembl_id: str) -> dict:
        """GTEx transcript expression by tissue."""
        try:
            mirror = Mirror.load()
            return isoforms.table(str(symbol), str(ensembl_id), Live.from_env(mirror.root), mirror)
        except Exception as exc:
            return {"error": f"Isoform table not built: {exc}"}

    def coexpressed(self, symbol: str, ensembl_id: str) -> dict:
        """Genes whose GTEx tissue profile moves with this one (mirror only)."""
        try:
            return coexpression.correlated(str(symbol), str(ensembl_id), Mirror.load())
        except Exception as exc:
            return {"error": f"Co-expression not computed: {exc}"}

    def disease_genetics(self, symbol: str, ensembl_id: str) -> dict:
        """Open Targets' associations beside ClinVar's variants, per disease."""
        try:
            return genetics.evidence(str(symbol), str(ensembl_id), Mirror.load())
        except Exception as exc:
            return {"error": f"Disease and genetics not read: {exc}"}

    def interaction_partners(self, symbol: str, ensembl_id: str) -> dict:
        """HPA's experimental partners beside OmniPath's curated ones."""
        try:
            return interactions.compare(str(symbol), str(ensembl_id), Mirror.load())
        except Exception as exc:
            return {"error": f"Interaction partners not read: {exc}"}

    # -- the digest: podcasts and trials, searchable ----------------------

    def _digest(self):
        from spica.digest.service import Digest

        return Digest(mirror=Mirror.load())

    def digest_status(self) -> dict:
        """The feeds, what each holds, the speech engine, the last update."""
        try:
            found = self._digest().status()
        except Exception as exc:
            return {"error": f"Digest not read: {exc}"}
        found["online"] = network_allowed()
        return found

    def digest_latest(self, kinds: list | None = None, since: str = "", offset: int = 0) -> dict:
        """What arrived, newest first: episodes, trials, papers."""
        try:
            return self._digest().latest([str(k) for k in kinds or []], str(since or ""),
                                         offset=int(offset or 0))
        except Exception as exc:
            return {"error": f"Digest not read: {exc}"}

    def digest_search(self, query: str, kinds: list | None = None, gene: str = "",
                      since: str = "", offset: int = 0) -> dict:
        """Passages ranked by what they say, with the genes they name."""
        try:
            return self._digest().search(str(query or ""), [str(k) for k in kinds or []],
                                         str(gene or ""), str(since or ""), offset=int(offset or 0))
        except Exception as exc:
            return {"error": f"Search failed: {exc}"}

    def digest_transcript(self, episode: str) -> dict:
        """One episode's transcript, whole, to read around a result."""
        digest = self._digest()
        found = digest.store.episodes().get(str(episode))
        if not found:
            return {"error": "No such episode."}
        if found.get("reserved"):
            return {**found, "segments": [], "note": f"Not transcribed: {found['reserved']}."}
        transcript = digest.store.transcript(str(episode)) or {}
        return {**found, "segments": transcript.get("segments", []),
                "engine": transcript.get("engine", "")}

    def digest_set_feed(self, key: str, on: bool) -> dict:
        digest = self._digest()
        chosen = digest.store.settings()
        chosen["enabled"][str(key)] = bool(on)
        digest.store.save_settings(chosen)
        return self.digest_status()

    def digest_set_per_feed(self, count: int) -> dict:
        digest = self._digest()
        chosen = digest.store.settings()
        chosen["per_feed"] = max(0, min(50, int(count)))
        digest.store.save_settings(chosen)
        return self.digest_status()

    def digest_add_feed(self, url: str) -> dict:
        """A podcast feed of the user's choosing: read once to check it is a
        feed, and to say at once if its publisher reserves mining."""
        import re as _re
        import urllib.parse as _parse

        from spica.digest import feeds as digest_feeds

        address = str(url or "").strip()
        if not _re.match(r"^https?://", address):
            return {"error": "Feed URL required, https:// only."}
        digest = self._digest()
        mirror = Mirror.load()
        try:
            parsed = digest_feeds.read("added", address, "", Live.from_env(mirror.root))
        except Exception as exc:
            return {"error": f"No podcast feed at this URL: {exc}"}
        key = "added-" + (_re.sub(r"[^a-z0-9]+", "-", parsed["title"].lower()).strip("-")[:40] or "feed")
        site = "{0.scheme}://{0.netloc}".format(_parse.urlparse(parsed["link"] or address))
        chosen = digest.store.settings()
        chosen["added"] = [f for f in chosen["added"] if f.get("key") != key] + [{
            "key": key, "name": parsed["title"] or address, "publisher": parsed["copyright"][:80],
            "url": address, "site": site, "about": "Added manually."}]
        chosen["enabled"][key] = True
        digest.store.save_settings(chosen)
        return {**self.digest_status(), "added": key, "reserved": parsed["reserved"]}

    def digest_remove_feed(self, key: str) -> dict:
        digest = self._digest()
        chosen = digest.store.settings()
        chosen["added"] = [f for f in chosen["added"] if f.get("key") != str(key)]
        chosen["enabled"].pop(str(key), None)
        digest.store.save_settings(chosen)
        return self.digest_status()

    def digest_update_start(self, everything: bool = False) -> dict:
        """Read every feed that is on and transcribe what is new, in the
        background. `everything` is "Process all": every episode waiting, not
        only the newest few per feed. One digest job runs at a time."""
        from spica.digest import update as digest_update

        if not network_allowed():
            return {"error": "Online access off (Settings). Feeds and ClinicalTrials.gov not read; "
                             "held items stay searchable."}
        running = self._jobs.running("digest")
        if running:
            return {"job": running, "already": True}

        def work(progress):
            digest = self._digest()
            summary = digest_update.update(digest.store, Live.from_env(digest.mirror.root),
                                           digest.watched(), progress, everything=bool(everything),
                                           stop=getattr(progress, "stop", None))
            try:
                summary["embedded"] = digest.embed()
            except Exception as exc:  # meaning search is an extra; keyword search still works
                summary["problems"].append(f"meaning search: {exc}")
            return summary

        return {"job": self._jobs.start("digest", 0, work)}

    def digest_running(self) -> dict:
        """The digest job still running, if any, so a reopened screen can follow it."""
        job = self._jobs.running("digest")
        return self._jobs.status(job) if job else {}

    def job_stop(self, job: str) -> dict:
        """Stop a background job after the item it is on."""
        return self._jobs.stop(str(job))

    def speech_download_start(self, name: str = "base.en") -> dict:
        """Download a speech model: an explicit action, like updating the data."""
        from spica.digest import speech

        if name not in speech.MODELS:
            return {"error": f"No speech model {name}."}

        def work(progress):
            path = speech.download(str(name), progress)
            return {"model": path.name}

        return {"job": self._jobs.start("speech", 0, work)}

    # -- candidates: gene lists, the ranked table, the benchmark -----------

    def candidates_criteria(self) -> dict:
        """The criteria the ranked table weighs, what each reads, and the presets."""
        return {"criteria": [ranking.criterion_dict(c) for c in ranking.CRITERIA],
                "presets": ranking.presets(), "benchmarks": {
                    key: label for key, (_, label) in benchmark.MODALITIES.items()}}

    def genelist_map(self, text: str) -> dict:
        """The mapping report for a pasted list: how each entry matched a gene."""
        entries = genelist.parse(str(text or ""))
        if not entries:
            return {"error": "No gene list."}
        if len(entries) > LIST_LIMIT:
            return {"error": f"{len(entries):,} entries; maximum {LIST_LIMIT:,} per list."}
        try:
            return {"entries": entries, **genelist.map_entries(entries)}
        except Exception as exc:
            return {"error": f"List not mapped: {exc}"}

    def genelist_read_file(self) -> dict:
        """A list file the user picks: .txt, .csv, .tsv, or .xlsx."""
        if not webview.windows:
            return {"error": "No window for the file dialog."}
        chosen = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=("Gene lists (*.txt;*.csv;*.tsv;*.xlsx)",
                                                 "All files (*.*)"))
        if not chosen:
            return {"cancelled": True}
        path = chosen if isinstance(chosen, str) else chosen[0]
        try:
            return {"text": genelist.read_file(path), "name": Path(path).stem}
        except Exception as exc:
            return {"error": f"File not read: {exc}"}

    def genelist_save(self, name: str, entries: list, mapping: dict, choices: dict,
                      weights: dict | None = None, preset: str = "", indication: str = "") -> dict:
        """Confirm the mapping and keep the list, with its choices and weights."""
        confirmed = genelist.confirm(mapping.get("rows", []), {str(k): str(v) for k, v in
                                                               (choices or {}).items()})
        if confirmed.get("error"):
            return confirmed
        saved = genelist.save(str(name or ""), [str(e) for e in entries or []], mapping,
                              confirmed["genes"], {str(k): str(v) for k, v in (choices or {}).items()},
                              _weights(weights), str(preset or ""), str(indication or ""))
        return {**saved, "genes": confirmed["genes"]}

    def genelists(self) -> dict:
        """The saved lists, newest first."""
        return {"lists": genelist.saved()}

    def genelist_open(self, slug: str) -> dict:
        """One saved list: its entries, mapping, confirmed genes and weights."""
        found = genelist.load(str(slug))
        return found if found else {"error": f"No saved list {slug}."}

    def genelist_delete(self, slug: str) -> dict:
        return {"deleted": genelist.delete(str(slug))}

    def rank_start(self, genes: list, weights: dict, indication: str = "",
                   missing: str = "skip") -> dict:
        """Rank the genes on the weights, in the background; poll job_status."""
        queries = [str(g) for g in genes or [] if str(g).strip()]
        if not queries:
            return {"error": "No gene to rank."}
        chosen = _weights(weights)

        def work(progress):
            mirror = Mirror.load()
            live = Live.from_env(mirror.root)
            records = []
            for done, query in enumerate(queries, start=1):
                records.append(build_record(query, mirror, live))
                progress(done, len(queries))
            return ranking.rank(records, chosen, str(indication or ""),
                                "zero" if missing == "zero" else "skip", mirror)

        return {"job": self._jobs.start("rank", len(queries), work)}

    def benchmark_start(self, modality: str, weights: dict, missing: str = "skip") -> dict:
        """Known targets against decoys for one modality, in the background."""
        chosen = _weights(weights)
        sets = {"antibody", "small_molecule"}
        if modality not in sets:
            return {"error": "Modality: antibody or small_molecule."}

        def work(progress):
            return benchmark.run(str(modality), chosen, progress=progress,
                                 missing="zero" if missing == "zero" else "skip")

        return {"job": self._jobs.start("benchmark", 0, work)}

    def benchmark_latest(self, modality: str = "") -> dict:
        """The newest benchmark result kept on this computer."""
        found = benchmark.latest(str(modality or ""))
        return found if found else {"error": "No benchmark run."}

    def export_ranked_start(self, genes: list, weights: dict, indication: str = "",
                            missing: str = "skip", project: str = "", profiles: int = 10) -> dict:
        """The client report for a ranked list, built in the background:
        the ranked table first, then a profile for each of the top genes."""
        from spica import export

        queries = [str(g) for g in genes or [] if str(g).strip()]
        if not queries:
            return {"error": "No gene."}
        chosen = _weights(weights)

        def work(progress):
            return export.ranked_report(queries, chosen, str(indication or ""),
                                        "zero" if missing == "zero" else "skip",
                                        str(project or ""), int(profiles) if profiles else None,
                                        progress=progress)

        return {"job": self._jobs.start("export", len(queries), work)}

    def export_save(self, job: str) -> dict:
        """Save a finished ranked report where the user picks."""
        state = self._jobs.status(str(job))
        built = state.get("result") or {}
        if state.get("state") != "done" or not built.get("html"):
            return {"error": state.get("error") or "The report is not ready."}
        target = _save_path(built["filename"])
        if target is None:
            return {"cancelled": True}
        try:
            target.write_text(built["html"], encoding="utf-8")
        except OSError as exc:
            return {"error": f"Report not saved: {exc}."}
        self._exported.add(str(target.resolve()))
        return {"path": str(target)}

    def job_status(self, job: str) -> dict:
        """Where a background job is, and its result once done."""
        state = self._jobs.status(str(job))
        if state.get("kind") == "export" and state.get("result"):
            # The page is large; the screen needs only to know it is ready.
            state = {**state, "result": {"filename": state["result"].get("filename")}}
        return state

    # -- the client report ------------------------------------------------

    def export_report(self, symbols: list, project: str = "") -> dict:
        """The client report for one gene or several, saved where the user picks."""
        from spica import export

        try:
            built = export.report([str(s) for s in symbols or []], str(project or ""))
        except Exception as exc:
            return {"error": f"Report not built: {exc}"}
        if built.get("error"):
            return {"error": built["error"]}
        target = _save_path(built["filename"])
        if target is None:
            return {"cancelled": True}
        try:
            target.write_text(built["html"], encoding="utf-8")
        except OSError as exc:
            return {"error": f"Report not saved: {exc}."}
        self._exported.add(str(target.resolve()))
        return {"path": str(target), "genes": built["genes"]}

    def exported_reports(self) -> dict:
        """The client reports in the export folder, newest first, and the
        reports saved elsewhere in this session."""
        folder = REPORTS_DIR
        found = []
        paths = list(folder.glob("*.htm*")) if folder.exists() else []
        paths += [Path(p) for p in self._exported if Path(p).parent != folder and Path(p).exists()]
        for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
            stat = path.stat()
            found.append({"name": path.name, "path": str(path),
                          "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                          "megabytes": round(stat.st_size / 1e6, 1)})
        return {"folder": str(folder), "reports": found}

    def open_exported(self, path: str) -> dict:
        """Open a report saved in this session, in the default browser."""
        resolved = str(Path(str(path)).resolve())
        in_folder = Path(resolved).parent == REPORTS_DIR.resolve() and \
            Path(resolved).suffix.lower() in (".html", ".htm")
        if resolved not in self._exported and not in_folder:
            return {"error": "Report not in the export folder or this session."}
        try:
            os.startfile(resolved)  # type: ignore[attr-defined]  # Windows only, as the app is
        except OSError as exc:
            return {"error": f"Report not opened: {exc}"}
        return {"opened": resolved}

    def compare_regulators(self, symbols: list) -> dict:
        """Shared transcriptional regulators of the compared genes, and links between them."""
        try:
            mirror = Mirror.load()
            return regulators.compare([str(s) for s in symbols or []],
                                      Live.from_env(mirror.root), mirror)
        except Exception as exc:
            return {"error": f"Shared regulation not read: {exc}"}

    # -- the agent pipeline --------------------------------------------

    def agents_status(self) -> dict:
        """Which model will run, and where to put one if there is none."""
        return self.agents.status()

    def agents_ask(self, question: str, thinking=None) -> dict:
        """Answer an arbitrary question from the indexed documents and the tools.

        Nothing to do with `build_report`: that is deterministic and no
        model touches it. This is the other mode. `thinking` overrides the
        saved choice for this question; the Ask screen saves it too.
        """
        question = (question or "").strip()
        if not question:
            return {"error": "No question entered."}
        if thinking is None:
            thinking = bool(settings.load().get("thinking", True))
        return self.agents.ask(question, thinking=bool(thinking))

    def agents_poll(self, run_id: str, version: int = -1) -> dict:
        return self.agents.poll(run_id, int(version))

    def agents_cancel(self, run_id: str) -> dict:
        return self.agents.cancel(run_id)

    def agents_rollback(self, run_id: str, index: int) -> dict:
        return self.agents.rollback(run_id, int(index))

    def agents_resume(self, run_id: str) -> dict:
        return self.agents.resume(run_id)


def _offline_or(exc: Exception, what: str) -> str:
    """The reason a network read failed, or what to do when the network is off."""
    from spica.live import OFF

    if OFF in str(exc):
        return f"{what}: online access off (Settings). Cached reads still open."
    return f"{what}: {exc}"


def _read_json(path: Path) -> dict:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
        return found if isinstance(found, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_bundled(name: str) -> str:
    try:
        return bundled(name).read_text(encoding="utf-8")
    except OSError:
        return ""


#: The most entries one list maps in one go.
LIST_LIMIT = 2000


def _weights(weights: dict | None) -> dict[str, float]:
    """Weights from the interface, as numbers 0 to 10, every criterion present."""
    chosen = weights or {}
    out = {}
    for criterion in ranking.CRITERIA:
        try:
            out[criterion.key] = min(float(ranking.SCALE), max(0.0, float(chosen.get(criterion.key, 0) or 0)))
        except (TypeError, ValueError):
            out[criterion.key] = 0.0
    return out


class Jobs:
    """Work that takes longer than a call should: started in a thread,
    polled by the interface, kept until the app closes."""

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._stops: dict = {}

    def start(self, kind: str, total: int, work) -> str:
        import threading
        import uuid

        job = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job] = {"job": job, "kind": kind, "state": "running", "done": 0,
                               "total": total, "started": time.time()}
        stop = threading.Event()
        self._stops[job] = stop

        def progress(done: int, of: int) -> None:
            with self._lock:
                self._jobs[job].update(done=done, total=of)

        # Long work checks this between items; "Stop" sets it.
        progress.stop = stop

        def run() -> None:
            try:
                result = work(progress)
                error = result.get("error") if isinstance(result, dict) else None
                update = {"state": "failed", "error": error} if error else \
                    {"state": "done", "result": result}
            except Exception as exc:  # a failure is reported, never raised into the void
                update = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}
            with self._lock:
                self._jobs[job].update(update, seconds=round(time.time() - self._jobs[job]["started"], 1))

        threading.Thread(target=run, daemon=True).start()
        return job

    def status(self, job: str) -> dict:
        with self._lock:
            found = self._jobs.get(job)
            return dict(found) if found else {"state": "unknown", "error": "No such job."}

    def stop(self, job: str) -> dict:
        """Ask a job to stop after the item in hand."""
        event = self._stops.get(job)
        if event is not None:
            event.set()
            with self._lock:
                if job in self._jobs and self._jobs[job]["state"] == "running":
                    self._jobs[job]["stopping"] = True
        return self.status(job)

    def running(self, kind: str) -> str:
        """The id of a job of this kind still running, or ""."""
        with self._lock:
            return next((j for j, found in self._jobs.items()
                         if found["kind"] == kind and found["state"] == "running"), "")


#: Where exported reports go unless the user picks another folder.
REPORTS_DIR = Path.home() / "Documents" / "Spica reports"


def _save_path(filename: str) -> Path | None:
    """Where to save an exported report: the user's choice in a save dialog,
    starting in Documents/Spica reports; that folder itself with no window."""
    folder = REPORTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    if not webview.windows:
        return folder / filename
    chosen = webview.windows[0].create_file_dialog(
        webview.FileDialog.SAVE, directory=str(folder), save_filename=filename,
        file_types=("HTML report (*.html)",))
    if not chosen:
        return None
    path = Path(chosen if isinstance(chosen, str) else chosen[0])
    return path if path.suffix.lower() in (".html", ".htm") else path.with_suffix(".html")


def main() -> None:
    # The exe is also the mirror builder: Settings starts it again with this
    # flag, as a process of its own, because tools/ does not ship.
    if "--build-mirror" in sys.argv:
        from spica import mirrorbuild

        at = sys.argv.index("--build-mirror")
        sys.exit(mirrorbuild.main(sys.argv[at + 1:]))

    dev = "--dev" in sys.argv

    if dev:
        url = DEV_URL
    else:
        if not UI_FILE.exists():
            sys.exit("Interface not built. Run `npm install && npm run build` in frontend/ first.")
        url = UI_FILE.as_uri()  # one self-contained local file, no server needed

    webview.create_window(
        title="Spica",
        url=url,
        js_api=Api(),
        width=1280,
        height=820,
        min_size=(960, 640),
        # Matches the page, so launching does not flash a different colour.
        background_color="#0A121C" if settings.load().get("theme") == "dark" else "#F5FAFF",
        text_select=False,  # app-like: chrome not selectable, inputs selectable
    )
    webview.start(debug=dev and not frozen(), private_mode=True)


if __name__ == "__main__":
    main()
