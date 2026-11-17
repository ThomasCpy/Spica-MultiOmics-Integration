"""Clinical trials, from ClinicalTrials.gov.

All interventional and observational studies registered there, searched
on the terms of the watch (with the widened gene names). The window applies
to the date of the last update of the record. A new trial and a changed old
trial (new phase, new status, posted results) both count.

The U.S. National Library of Medicine runs ClinicalTrials.gov. Reuse is
free, commercial use included. NLM asks for credit ("Courtesy of the U.S.
National Library of Medicine"), for a note that copies may not be current,
and for no implied endorsement (`docs/licences.md`). Spica keeps only the
fields of the registration and links each trial to its record.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date
from typing import Any

from spica.intel.literature import Found
from spica.live import Live, LiveError, NotFoundUpstream, OFF

API = "https://clinicaltrials.gov/api/v2/studies"
SOURCE_KEY = "clinicaltrials"
LABEL = "ClinicalTrials.gov"
CREDIT = "Courtesy of the U.S. National Library of Medicine (ClinicalTrials.gov)"
#: Per check: more than this many trials updated in one window is a topic
#: to narrow, and the screen says how many were not fetched.
CAP = 1000
PAGE = 1000
FIELDS = ("NCTId,BriefTitle,OverallStatus,Phase,LeadSponsorName,Condition,InterventionName,"
          "StartDate,LastUpdatePostDate,StudyFirstPostDate")

STATUS = {"RECRUITING": "recruiting", "NOT_YET_RECRUITING": "not yet recruiting",
          "ACTIVE_NOT_RECRUITING": "active, not recruiting", "COMPLETED": "completed",
          "TERMINATED": "terminated", "WITHDRAWN": "withdrawn", "SUSPENDED": "suspended",
          "ENROLLING_BY_INVITATION": "enrolling by invitation", "UNKNOWN": "unknown"}


#: A gene symbol as trials write it, ending in a digit (CLDN18, CD19).
SYMBOL = re.compile(r"^[A-Z][A-Z0-9-]*[0-9]$")


def expression(terms: list[str]) -> str:
    """ClinicalTrials.gov's search syntax: any term, phrases quoted.

    Trials name isoforms, and the registry does not match a symbol inside
    one: in one quarter "CLDN18" found 2 updated trials where "CLDN18.2"
    found 43, and no wildcard form works. So a symbol ending in a digit
    also searches its first two isoform forms; one that does not exist
    costs nothing."""
    parts = []
    for term in terms:
        text = term.replace('"', " ").strip()
        if not text:
            continue
        parts.append(f'"{text}"' if " " in text or "-" in text else text)
        if SYMBOL.match(text):
            parts += [f"{text}.1", f"{text}.2"]
    return " OR ".join(parts)


def trial(study: dict[str, Any]) -> dict[str, Any]:
    """One registration, reduced to its own fields."""
    section = study.get("protocolSection") or {}
    ident = section.get("identificationModule") or {}
    status = section.get("statusModule") or {}
    nct = str(ident.get("nctId") or "")
    phases = (section.get("designModule") or {}).get("phases") or []
    return {
        "id": f"NCT:{nct}",
        "nct": nct,
        "title": str(ident.get("briefTitle") or "").strip(),
        "status": STATUS.get(str(status.get("overallStatus") or ""),
                             str(status.get("overallStatus") or "").lower().replace("_", " ")),
        "phase": ", ".join("not applicable" if p == "NA" else
                           p.replace("PHASE", "phase ").replace("EARLY_", "early ").lower()
                           for p in phases) or "not applicable",
        "sponsor": str(((section.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {})
                       .get("name") or ""),
        "conditions": list((section.get("conditionsModule") or {}).get("conditions") or []),
        "interventions": [str(i.get("name") or "") for i in
                          (section.get("armsInterventionsModule") or {}).get("interventions") or []
                          if i.get("name")],
        "start": str((status.get("startDateStruct") or {}).get("date") or ""),
        "first_posted": str((status.get("studyFirstPostDateStruct") or {}).get("date") or ""),
        "date": str((status.get("lastUpdatePostDateStruct") or {}).get("date") or ""),
        "url": f"https://clinicaltrials.gov/study/{nct}",
    }


def search(live: Live, terms: list[str], since: date, until: date, stamp: str) -> Found:
    """Trials whose record was updated inside the window, newest first.

    `stamp` goes into the cache key, as for papers: the same check on the
    same day agrees with itself, tomorrow's asks again."""
    if not terms:
        return Found(state="failed", reason="no terms to search")
    found = Found()
    token = ""
    params = {"query.term": expression(terms),
              "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since.isoformat()},"
                                 f"{until.isoformat()}]",
              "fields": FIELDS, "pageSize": PAGE, "countTotal": "true", "format": "json"}
    while len(found.items) < CAP:
        query = dict(params, **({"pageToken": token} if token else {}))
        url = f"{API}?{urllib.parse.urlencode(query)}"
        try:
            response = live.get_json(SOURCE_KEY, url, cache_key=f"{url}#{stamp}")
        except NotFoundUpstream:
            break
        except LiveError as exc:
            state = "offline" if OFF in str(exc) else "failed"
            return Found(state=state, reason=f"{LABEL}: {exc}")
        payload = response.payload if isinstance(response.payload, dict) else {}
        if not token:
            found.total = int(payload.get("totalCount") or 0)
        found.items += [trial(s) for s in payload.get("studies") or [] if isinstance(s, dict)]
        token = str(payload.get("nextPageToken") or "")
        if not token:
            break
    found.items.sort(key=lambda item: (item["date"], item["id"]), reverse=True)
    found.search_url = ("https://clinicaltrials.gov/search?term="
                        + urllib.parse.quote(expression(terms)))
    return found


def facets(items: list[dict[str, Any]]) -> dict[str, list[list[Any]]]:
    """Counts by phase, by status and by sponsor, most first."""
    out: dict[str, list[list[Any]]] = {}
    for key in ("phase", "status", "sponsor"):
        counts: dict[str, int] = {}
        for item in items:
            counts[item[key]] = counts.get(item[key], 0) + 1
        out[key] = [[name, n] for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return out
