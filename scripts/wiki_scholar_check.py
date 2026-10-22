#!/usr/bin/env python3
"""Scholarly citation truth-checking pack.

Build item W1.3 (owner directive 2026-10-22). The comprehensive
research report named scholarly citation truth-checking as one
of its honestly-open gaps: this wiki verifies its INTERNAL
citations (the ^[cite:] lockfile machinery proves a cited local
passage still says what a claim rests on), but nothing checked
the SCHOLARLY citations the corpus carries — the papers named
in prose with authors, titles, years and DOIs — against the
scholarly record itself. A citation can be wrong in ways the
lockfile cannot see: a DOI that resolves to a different paper,
a year or author that does not match the record, a fabricated
DOI, a source that has since been retracted. This script is
that check. It is REPORT-ONLY: it never edits a page, never
gates an ingest, and its verdicts are data in a report.

Staged design (the staging is the honesty mechanism — each
stage's outcome is recorded, and no stage borrows another's
evidence):

  Stage 1 — resolution. A citation carrying a DOI is resolved
  against Crossref (GET /works/<doi>) and OpenAlex
  (GET /works/doi:<doi>). A citation without a DOI but with a
  usable title is resolved by title search on both registries
  (Crossref query.bibliographic, OpenAlex search); a search
  candidate is accepted only at title score >= 0.90, and two
  distinct works scoring within 0.03 of each other at or above
  that bar are AMBIGUOUS, never a coin flip.

  Stage 2 — field-level scoring. For every resolved record the
  citation's fields are compared field by field: title
  (normalised similarity; containment of a main title in a
  title+subtitle counts as agreement), authors (surname sets),
  year (the citation's year against every year the record
  carries — issued / print / online legitimately differ), and
  venue. Title, authors and year are the verdict-bearing
  fields. Venue is compared and reported but is NOT
  verdict-bearing: registry container titles and citation
  venue strings diverge by abbreviation too often ("Proc. ACL
  2016" vs the full proceedings name) to convict on venue
  alone — a venue disagreement is named in the entry's field
  table and in `field_notes`, never hidden.

  Stage 3 — status. Every resolved record is read for
  retraction / status signals: Crossref `updated-by` /
  `update-to` entries (type retraction / withdrawal, fed in
  part by Retraction Watch), a registry title carrying the
  "RETRACTED:" marker, and OpenAlex `is_retracted`. A signal
  becomes an ALERT entry on the citation's report row, naming
  the registry and the exact evidence. Coverage is stated per
  citation: `queried` names the registries that actually
  answered (a record, or an explicit no-record), `doors_failed`
  names the ones that did not — retraction coverage is never
  claimed for a registry that was not reached.

Verdicts (exactly four; the fourth is a first-class outcome,
not a failure of the tool):

  verified        a record resolved and every comparable
                  verdict-bearing field agrees. The basis
                  states what was compared; a bare DOI that
                  resolves with no fields to compare is
                  verified on "doi-resolution-only", said so.
  field-mismatch  a record resolved but a verdict-bearing
                  field disagrees; the disagreeing fields are
                  NAMED, with the cited value and the registry
                  value side by side.
  not_found       every registry door that was tried ANSWERED
                  and none holds the work: a DOI drew a 404
                  from both registries, or a title search found
                  no candidate at the acceptance bar on either.
  cannot_determine the evidence does not settle the citation
                  and the tool says so instead of guessing:
                  no DOI and no usable title; a door failed, so
                  a negative is not established (a door failure
                  is a statement about the door, never a
                  negative finding — the wiki's proof-bar rule);
                  ambiguous search candidates; or the citation
                  carries fields no resolved record carries, so
                  nothing could actually be compared.

Quote grading (subcommand `quotes`, and attached to `verify`
entries whose citation carries a quote + a local locator):
direct quotations are graded against the LOCAL corpus, reusing
the cite-lock quote lane's pairing (find_checkable_quotes) and
its normalisation (whitespace + smart quotes only):

  exact       the normalised quote appears verbatim in the
              cited range;
  close       not verbatim, but >= 0.85 of the quote's tokens
              match, in order, inside the range — and the
              differences ARE shown (the verify_quote
              divergence point + the coverage), never just
              the grade;
  distorted   partial agreement (coverage >= 0.45) — some of
              the quote is there, materially altered;
  not_found   no meaningful agreement with the cited range.

Patterns (IDEAS ONLY — clean re-implementation, no code or
text taken from any of them): the staged registry verification
of bibverify-opencode and Terobyte/librarian-cli, the
field-level verdicts of Refwright, Retraction Watch's
point-of-use status (via the Zotero integration), and
EndNote-style field comparison. Crossref and OpenAlex are
used as public data APIs under their polite-pool conventions
(the tool identifies itself, paces requests singly, and needs
no key). GROBID-parsed references (Wave 4 item) can feed this
tool later through the same --citations input.

Inputs:
  --scan              extract DOI-bearing citations from the
                      compiled wiki pages (wiki/**/*.md);
                      --include-raw widens the scan to raw/.
                      Extraction is heuristic (DOI + the title,
                      authors, year and venue its own line
                      carries) and says so in the report's
                      coverage block; title-only citations
                      enter through --citations.
  --citations FILE    JSON list or JSONL of citation records
                      in the house shape ({doi, title, authors,
                      year, venue, quote, locator:{source,
                      start, end}, label}) or CSL-JSON shape
                      ({DOI, title, author:[{family, given}],
                      issued:{"date-parts":[[year]]},
                      container-title}).

Usage:
  python3 scripts/wiki_scholar_check.py verify --scan [--include-raw]
  python3 scripts/wiki_scholar_check.py verify --citations FILE.jsonl
  python3 scripts/wiki_scholar_check.py quotes
  (--out PATH overrides the report path; --delay S paces the
  registry requests; --crossref-base / --openalex-base or the
  WIKI_SCHOLAR_CROSSREF_BASE / WIKI_SCHOLAR_OPENALEX_BASE
  environment variables point the tool at a registry mirror.)

Reports: evaluation/scholar-check-report.json (verify) and
evaluation/scholar-quote-report.json (quotes).

Exit codes: 0 on any completed run (verdicts are data, never a
gate); 2 on usage error. Stdlib only. Deterministic ordering
everywhere: the same inputs always produce the same report
(apart from the generated date).
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
VERIFY_REPORT = ROOT / "evaluation" / "scholar-check-report.json"
QUOTE_REPORT = ROOT / "evaluation" / "scholar-quote-report.json"

CROSSREF_DEFAULT = "https://api.crossref.org"
OPENALEX_DEFAULT = "https://api.openalex.org"
MAILTO_DEFAULT = "wikicitadel@example.org"
USER_AGENT = ("wiki-scholar-check/1.0 (LLM Wiki scholarly"
              " citation truth-check; mailto:%s)")

TITLE_AGREE = 0.80        # field comparison: titles agree
TITLE_ACCEPT = 0.90       # title search: a candidate resolves
TITLE_TIE = 0.03          # search candidates this close are a tie
CLOSE_RATIO = 0.85        # quote grade: close
DISTORTED_RATIO = 0.45    # quote grade: distorted floor

VERDICT_FIELDS = ("title", "authors", "year")


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cite_lock = _load("wiki_cite_lock")


# -- Registry doors ------------------------------------------------------------

class DoorFailed(Exception):
    """A registry door did not answer (transport error, HTTP
    5xx/429, timeout, unparseable body). A statement about the
    door — never evidence about the cited work."""


class RegistryMiss(Exception):
    """The registry answered: no such record (HTTP 404). This
    IS evidence — one registry, searched, does not hold it."""


class HttpFetcher:
    """Singly-paced JSON GETs against the two registries.
    Identifies the tool per the polite-pool conventions."""

    def __init__(self, crossref_base, openalex_base,
                 mailto=MAILTO_DEFAULT, delay=0.4, timeout=30):
        self.crossref_base = crossref_base.rstrip("/")
        self.openalex_base = openalex_base.rstrip("/")
        self.mailto = mailto
        self.delay = delay
        self.timeout = timeout
        self.requests = 0

    def get_json(self, url):
        if self.delay:
            time.sleep(self.delay)
        self.requests += 1
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT % self.mailto,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(
                    req, timeout=self.timeout) as fh:
                body = fh.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RegistryMiss(f"HTTP 404 for {url}") from exc
            raise DoorFailed(
                f"HTTP {exc.code} for {url}") from exc
        except (urllib.error.URLError, TimeoutError,
                OSError) as exc:
            raise DoorFailed(f"{exc} for {url}") from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise DoorFailed(
                f"unparseable JSON from {url}") from exc

    # Crossref
    def crossref_work(self, doi):
        url = (f"{self.crossref_base}/works/"
               f"{urllib.parse.quote(doi, safe='')}"
               f"?mailto={urllib.parse.quote(self.mailto)}")
        return self.get_json(url)["message"]

    def crossref_search(self, cit):
        query = " ".join(x for x in (
            cit.get("title") or "",
            " ".join(cit.get("authors") or []),
            str(cit.get("year") or "")) if x)
        url = (f"{self.crossref_base}/works?rows=5"
               f"&query.bibliographic="
               f"{urllib.parse.quote(query)}"
               f"&mailto={urllib.parse.quote(self.mailto)}")
        return self.get_json(url)["message"].get("items", [])

    # OpenAlex
    def openalex_work(self, doi):
        url = (f"{self.openalex_base}/works/doi:"
               f"{urllib.parse.quote(doi, safe='/')}"
               f"?mailto={urllib.parse.quote(self.mailto)}")
        return self.get_json(url)

    def openalex_search(self, cit):
        url = (f"{self.openalex_base}/works?per-page=5"
               f"&search={urllib.parse.quote(cit.get('title') or '')}"
               f"&mailto={urllib.parse.quote(self.mailto)}")
        return self.get_json(url).get("results", [])


# -- Normalisation ---------------------------------------------------------------

def _strip_diacritics(text):
    return unicodedata.normalize(
        "NFKD", text).encode(
            "ascii", "ignore").decode("ascii")


def norm_surname(name):
    """One author's surname, normalised for comparison. Accepts
    a display name ("Sarah Higgins"), a "Surname, Given" string,
    or a CSL dict ({family, given})."""
    if isinstance(name, dict):
        name = name.get("family") or name.get("name") or ""
    name = _strip_diacritics(str(name)).strip()
    if "," in name:
        name = name.split(",", 1)[0]
    parts = [p for p in re.split(r"\s+", name) if p]
    if not parts:
        return ""
    last = parts[-1].strip(".'\"")
    return re.sub(r"[^a-z-]", "", last.lower())


def norm_authors(authors):
    """A citation's authors in any accepted shape -> a list of
    display names, order preserved."""
    if not authors:
        return []
    if isinstance(authors, str):
        parts = re.split(r"\s*(?:&|\band\b|;)\s*", authors)
        return [p.strip() for p in parts if p.strip()]
    out = []
    for a in authors:
        if isinstance(a, dict):
            fam = (a.get("family") or "").strip()
            giv = (a.get("given") or "").strip()
            out.append((giv + " " + fam).strip()
                       or a.get("name") or a.get("literal") or "")
        else:
            out.append(str(a).strip())
    return [a for a in out if a]


def norm_title_text(title):
    """Title text for similarity: registry retraction markers
    and articles/punctuation/case do not make two titles of the
    same work different."""
    t = str(title or "")
    t = re.sub(r"^\s*(RETRACTED|WITHDRAWN)\s*:\s*", "", t,
               flags=re.IGNORECASE)
    t = _strip_diacritics(t).lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return t


def title_score(cited, registry):
    """0..1 similarity of two titles. Identical after
    normalisation = 1.0; one containing the other (a main
    title against a title+subtitle) = 0.97; otherwise the
    difflib ratio of the normalised strings."""
    a, b = norm_title_text(cited), norm_title_text(registry)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.97
    return difflib.SequenceMatcher(None, a, b).ratio()


def _norm_venue(venue):
    v = _strip_diacritics(str(venue or "")).lower()
    v = re.sub(r"[^a-z0-9 ]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def _venue_agrees(cited, registry):
    a, b = _norm_venue(cited), _norm_venue(registry)
    if not a or not b:
        return None
    if a in b or b in a:
        return True
    ta = {t for t in a.split() if len(t) > 2}
    tb = {t for t in b.split() if len(t) > 2}
    if not ta or not tb:
        return None
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.5


# -- Registry record normalisation ----------------------------------------------

def _crossref_years(msg):
    years = set()
    for key in ("issued", "published-print", "published-online",
                "published", "created"):
        if key == "created":
            continue
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            years.add(int(parts[0][0]))
    return sorted(years)


def _crossref_updates(msg):
    out = []
    for key in ("updated-by", "update-to"):
        for u in msg.get(key) or []:
            out.append({
                "type": (u.get("type") or "").lower(),
                "doi": u.get("DOI"),
                "label": u.get("label"),
                "source": u.get("source"),
                "via": key,
            })
    return out


def normalise_crossref(msg):
    authors = []
    for a in msg.get("author") or []:
        disp = ((a.get("given") or "") + " "
                + (a.get("family") or "")).strip()
        if disp:
            authors.append(disp)
    title = (msg.get("title") or [None])[0]
    venue = (msg.get("container-title") or [None])[0]
    return {
        "registry": "crossref",
        "id": msg.get("URL") or msg.get("DOI"),
        "doi": (msg.get("DOI") or "").lower() or None,
        "title": title,
        "authors": authors,
        "surnames": [norm_surname(a) for a in authors],
        "years": _crossref_years(msg),
        "venue": venue,
        "type": msg.get("type"),
        "updates": _crossref_updates(msg),
        "is_retracted": None,
    }


def normalise_openalex(work):
    authors = []
    for a in work.get("authorships") or []:
        disp = ((a.get("author") or {}).get("display_name")
                or "")
        if disp:
            authors.append(disp)
    doi = work.get("doi") or ""
    doi = re.sub(r"^https?://doi\.org/", "", doi).lower() or None
    venue = None
    loc = work.get("primary_location") or {}
    if loc.get("source"):
        venue = loc["source"].get("display_name")
    return {
        "registry": "openalex",
        "id": work.get("id"),
        "doi": doi,
        "title": work.get("title") or work.get("display_name"),
        "authors": authors,
        "surnames": [norm_surname(a) for a in authors],
        "years": ([int(work["publication_year"])]
                  if work.get("publication_year") else []),
        "venue": venue,
        "type": work.get("type"),
        "updates": [],
        "is_retracted": work.get("is_retracted"),
    }


# -- Status alerts -----------------------------------------------------------------

RETRACTION_TYPES = {"retraction", "withdrawal", "remove",
                    "removal", "retract"}
STATUS_TYPES = {"correction", "erratum", "expression_of_concern",
                "expression-of-concern", "addendum"}


def record_alerts(rec):
    """Retraction / status signals carried by ONE normalised
    registry record. Each alert names its evidence — the field
    and value — so a reader never has to take the alert's word
    for it."""
    alerts = []
    if rec.get("is_retracted") is True:
        alerts.append({
            "kind": "retraction", "registry": rec["registry"],
            "evidence": "OpenAlex is_retracted = true",
        })
    title = rec.get("title") or ""
    if re.match(r"\s*(RETRACTED|WITHDRAWN)\s*:", title,
                flags=re.IGNORECASE):
        alerts.append({
            "kind": "retraction", "registry": rec["registry"],
            "evidence": ("registry title carries the "
                         f"{title.split(':')[0].strip()!r} marker"),
        })
    for u in rec.get("updates") or []:
        if u["type"] in RETRACTION_TYPES:
            alerts.append({
                "kind": "retraction",
                "registry": rec["registry"],
                "evidence": (f"Crossref {u['via']} entry of type"
                             f" {u['type']!r} (updating DOI"
                             f" {u.get('doi')}, source"
                             f" {u.get('source')})"),
            })
        elif u["type"] in STATUS_TYPES:
            alerts.append({
                "kind": "status", "registry": rec["registry"],
                "evidence": (f"Crossref {u['via']} entry of type"
                             f" {u['type']!r} (updating DOI"
                             f" {u.get('doi')}, source"
                             f" {u.get('source')})"),
            })
    return alerts


# -- Field-level scoring -------------------------------------------------------------

def compare_fields(cit, records):
    """cit fields vs every resolved record, field by field.
    Per field: agree (at least one record agrees — registries
    legitimately differ, e.g. online vs print year), disagree
    (comparable everywhere, agrees nowhere), or not-comparable
    (the citation or every record lacks the field). Registry
    values are carried verbatim into the result."""
    fields = {}

    def verdict(per_record):
        comparable = [p for p in per_record
                      if p["result"] != "not-comparable"]
        if not comparable:
            return "not-comparable"
        if any(p["result"] == "agree" for p in comparable):
            return "agree"
        return "disagree"

    # title
    if cit.get("title"):
        per = []
        for rec in records:
            if rec.get("title"):
                score = title_score(cit["title"], rec["title"])
                per.append({
                    "registry": rec["registry"],
                    "value": rec["title"],
                    "score": round(score, 3),
                    "result": ("agree" if score >= TITLE_AGREE
                               else "disagree"),
                })
            else:
                per.append({"registry": rec["registry"],
                            "value": None,
                            "result": "not-comparable"})
        fields["title"] = {"cited": cit["title"],
                           "result": verdict(per), "per": per}
    # authors
    cited_surnames = [norm_surname(a)
                      for a in cit.get("authors") or []]
    cited_surnames = [s for s in cited_surnames if s]
    if cited_surnames:
        per = []
        for rec in records:
            reg = [s for s in rec.get("surnames") or [] if s]
            if reg:
                agree = (cited_surnames[0] in reg
                         and set(cited_surnames) <= set(reg))
                per.append({
                    "registry": rec["registry"],
                    "value": rec.get("authors"),
                    "result": "agree" if agree else "disagree",
                })
            else:
                per.append({"registry": rec["registry"],
                            "value": None,
                            "result": "not-comparable"})
        fields["authors"] = {"cited": cit.get("authors"),
                             "result": verdict(per), "per": per}
    # year
    if cit.get("year"):
        per = []
        for rec in records:
            if rec.get("years"):
                per.append({
                    "registry": rec["registry"],
                    "value": rec["years"],
                    "result": ("agree" if int(cit["year"])
                               in rec["years"] else "disagree"),
                })
            else:
                per.append({"registry": rec["registry"],
                            "value": None,
                            "result": "not-comparable"})
        fields["year"] = {"cited": cit["year"],
                          "result": verdict(per), "per": per}
    # venue — compared and reported, never verdict-bearing
    if cit.get("venue"):
        per = []
        for rec in records:
            if rec.get("venue"):
                ag = _venue_agrees(cit["venue"], rec["venue"])
                per.append({
                    "registry": rec["registry"],
                    "value": rec["venue"],
                    "result": ("not-comparable" if ag is None
                               else "agree" if ag
                               else "disagree"),
                })
            else:
                per.append({"registry": rec["registry"],
                            "value": None,
                            "result": "not-comparable"})
        fields["venue"] = {"cited": cit["venue"],
                           "result": verdict(per), "per": per}
    return fields


def _field_outcome(fields):
    """(disagreements, comparable) over the verdict-bearing
    fields, plus any venue disagreement as a note."""
    disagreements = [f for f in VERDICT_FIELDS
                     if fields.get(f, {}).get("result")
                     == "disagree"]
    comparable = [f for f in VERDICT_FIELDS
                  if fields.get(f, {}).get("result")
                  in ("agree", "disagree")]
    notes = []
    if fields.get("venue", {}).get("result") == "disagree":
        notes.append(
            "venue disagrees (reported, not verdict-bearing):"
            f" cited {fields['venue']['cited']!r} vs registry"
            " "
            + ", ".join(
                f"{p['registry']} {p['value']!r}"
                for p in fields["venue"]["per"]
                if p.get("value")))
    return disagreements, comparable, notes


# -- The staged verification ----------------------------------------------------------

def verify_citation(cit, fetcher):
    """One citation record through the three stages. Returns
    the report entry. `fetcher` is the registry-door seam: an
    HttpFetcher in the CLI, a recorded-fixture fetcher in
    tests (the wiki_correction_gate resolver pattern)."""
    entry = {
        "citation": {k: cit.get(k) for k in
                     ("doi", "title", "authors", "year", "venue")
                     if cit.get(k)},
        "locations": cit.get("locations") or [],
        "verdict": None,
        "basis": "",
        "fields": {},
        "field_notes": [],
        "queried": [],
        "doors_failed": {},
        "alerts": [],
        "resolved": {},
    }
    doi = (cit.get("doi") or "").strip().lower() or None
    title = (cit.get("title") or "").strip()
    if doi:
        _verify_by_doi(entry, cit, doi, fetcher)
    elif title and (len(norm_title_text(title).split()) >= 2
                    or cit.get("authors")):
        _verify_by_title(entry, cit, fetcher)
    else:
        entry["verdict"] = "cannot_determine"
        entry["basis"] = ("insufficient identifiers: the"
                          " citation carries no DOI and no"
                          " usable title, so no registry door"
                          " can be tried")
    # A quote + local locator rides along: graded locally.
    quote = cit.get("quote")
    locator = cit.get("locator") or {}
    if quote and locator.get("source"):
        start = int(locator.get("start") or 1)
        end = int(locator.get("end") or start)
        entry["quote_grade"] = grade_quote_at(
            quote, locator["source"], start, end)
    return entry


def _finish_resolved(entry, cit, records, basis_prefix):
    """Stages 2+3 over a non-empty resolved-record set."""
    entry["resolved"] = {
        rec["registry"]: {
            "doi": rec.get("doi"), "title": rec.get("title"),
            "authors": rec.get("authors"),
            "years": rec.get("years"), "venue": rec.get("venue"),
            "type": rec.get("type"), "id": rec.get("id"),
        } for rec in records}
    seen = set()
    for rec in records:
        for alert in record_alerts(rec):
            key = (alert["kind"], alert["registry"],
                   alert["evidence"])
            if key not in seen:
                seen.add(key)
                entry["alerts"].append(alert)
    fields = compare_fields(cit, records)
    entry["fields"] = fields
    disagreements, comparable, notes = _field_outcome(fields)
    entry["field_notes"] = notes
    if disagreements:
        entry["verdict"] = "field-mismatch"
        entry["basis"] = (
            basis_prefix + "; verdict-bearing field(s) disagree:"
            " " + ", ".join(disagreements)
            + " — cited vs registry values in the field table")
    elif comparable:
        entry["verdict"] = "verified"
        entry["basis"] = (
            basis_prefix + "; fields compared and agreeing: "
            + ", ".join(comparable))
    elif cit.get("title") or cit.get("authors") or cit.get("year"):
        entry["verdict"] = "cannot_determine"
        entry["basis"] = (
            basis_prefix + "; but the citation's fields could"
            " not be compared — no resolved record carries"
            " them, so agreement was never actually tested")
    else:
        entry["verdict"] = "verified"
        entry["basis"] = (basis_prefix + "; the citation"
                          " carries no fields beyond the DOI"
                          " (doi-resolution-only)")
    return entry


def _verify_by_doi(entry, cit, doi, fetcher):
    records, misses = [], 0
    for name, fetch, normalise in (
            ("crossref", fetcher.crossref_work,
             normalise_crossref),
            ("openalex", fetcher.openalex_work,
             normalise_openalex)):
        try:
            records.append(normalise(fetch(doi)))
            entry["queried"].append(name)
        except RegistryMiss:
            misses += 1
            entry["queried"].append(name)
        except DoorFailed as exc:
            entry["doors_failed"][name] = str(exc)
    if records:
        names = ", ".join(sorted(r["registry"]
                                 for r in records))
        return _finish_resolved(
            entry, cit, records,
            f"DOI {doi} resolved in {names}")
    if misses == 2 and not entry["doors_failed"]:
        entry["verdict"] = "not_found"
        entry["basis"] = (f"DOI {doi} drew a 404 from both"
                          " Crossref and OpenAlex — both doors"
                          " answered, neither holds the work")
    else:
        entry["verdict"] = "cannot_determine"
        failed = ", ".join(sorted(entry["doors_failed"]))
        entry["basis"] = (
            f"DOI {doi} did not resolve and the negative is"
            " not established: "
            + (f"door(s) failed: {failed}" if failed else
               "no registry answered")
            + "; a door failure is not a negative finding")
    return entry


def _search_one(fetcher, registry, cit):
    """(candidates, error) — candidates are normalised records
    carrying their title score against the citation."""
    try:
        if registry == "crossref":
            raw = fetcher.crossref_search(cit)
            recs = [normalise_crossref(m) for m in raw]
        else:
            raw = fetcher.openalex_search(cit)
            recs = [normalise_openalex(w) for w in raw]
    except RegistryMiss:
        return [], None
    except DoorFailed as exc:
        return [], str(exc)
    for rec in recs:
        rec["_score"] = (title_score(cit.get("title"),
                                     rec.get("title"))
                         if rec.get("title") else 0.0)
    recs.sort(key=lambda r: -r["_score"])
    return recs, None


def _verify_by_title(entry, cit, fetcher):
    accepted = {}
    ambiguous = []
    answered = 0
    for registry in ("crossref", "openalex"):
        cands, err = _search_one(fetcher, registry, cit)
        if err:
            entry["doors_failed"][registry] = err
            continue
        entry["queried"].append(registry)
        answered += 1
        strong = [c for c in cands
                  if c["_score"] >= TITLE_ACCEPT]
        if not strong:
            continue
        top = strong[0]
        tied = [c for c in strong[1:]
                if top["_score"] - c["_score"] < TITLE_TIE
                and c.get("doi") != top.get("doi")]
        if tied:
            ambiguous.append(
                f"{registry}: {top.get('title')!r}"
                f" (score {top['_score']:.2f}) vs"
                f" {tied[0].get('title')!r}"
                f" (score {tied[0]['_score']:.2f}) — distinct"
                " works, no basis to choose")
        else:
            accepted[registry] = top
    dois = {rec.get("doi") for rec in accepted.values()
            if rec.get("doi")}
    if len(dois) > 1:
        entry["verdict"] = "cannot_determine"
        entry["basis"] = (
            "ambiguous: the registries resolved the title to"
            " different works ("
            + "; ".join(f"{r} -> DOI {rec.get('doi')}"
                        for r, rec in sorted(accepted.items()))
            + ") and the citation carries no DOI to settle it")
        return entry
    if accepted:
        records = list(accepted.values())
        return _finish_resolved(
            entry, cit, records,
            "resolved by title search via "
            + ", ".join(sorted(accepted))
            + f" (title score "
            + ", ".join(f"{r} {rec['_score']:.2f}"
                        for r, rec in sorted(accepted.items()))
            + ")")
    if ambiguous:
        entry["verdict"] = "cannot_determine"
        entry["basis"] = ("ambiguous title search: "
                          + "; ".join(ambiguous))
    elif entry["doors_failed"]:
        entry["verdict"] = "cannot_determine"
        entry["basis"] = (
            "title search incomplete — door(s) failed: "
            + ", ".join(sorted(entry["doors_failed"]))
            + "; a negative is not established")
    elif answered:
        entry["verdict"] = "not_found"
        entry["basis"] = (
            "title search answered on "
            + ", ".join(entry["queried"])
            + f" with no candidate at the {TITLE_ACCEPT:.2f}"
            " acceptance bar")
    else:
        entry["verdict"] = "cannot_determine"
        entry["basis"] = "no registry door answered the search"
    return entry


# -- Quote grading (local corpus) ------------------------------------------------------

def _divergence(needle, hay):
    """The cite-lock quote lane's divergence rule, restated on
    already-normalised text: the longest prefix of the quote
    that does appear, and what the quote says next."""
    lo = 0
    for cut in range(len(needle), 0, -1):
        if needle[:cut] in hay:
            lo = cut
            break
    if lo == 0:
        return "quotation not present in the cited range"
    nxt = needle[lo:lo + 40]
    return (f"diverges after {lo} of {len(needle)} chars — the"
            f" quotation continues {nxt!r}, which is not in"
            " the cited range")


def grade_quote_against(quote, range_text):
    """Grade one quotation against the text of its cited
    range: {grade, token_ratio, divergence}. token_ratio is
    COVERAGE: the fraction of the quote's tokens matched, in
    order, inside the range (so a range holding text around
    the quotation does not dilute the grade). Grades: exact /
    close (differences shown) / distorted / not_found."""
    needle = cite_lock.normalize_text(quote).replace('"', "")
    hay = cite_lock.normalize_text(range_text).replace('"', "")
    if not needle:
        return {"grade": "not_found", "token_ratio": 0.0,
                "divergence": "empty quotation"}
    if needle in hay:
        return {"grade": "exact", "token_ratio": 1.0,
                "divergence": ""}
    qtok = needle.split()
    htok = hay.split()
    sm = difflib.SequenceMatcher(None, qtok, htok)
    matched = sum(b.size for b in sm.get_matching_blocks())
    coverage = matched / len(qtok) if qtok else 0.0
    div = _divergence(needle, hay)
    if coverage >= CLOSE_RATIO:
        grade = "close"
    elif coverage >= DISTORTED_RATIO:
        grade = "distorted"
    else:
        grade = "not_found"
    return {"grade": grade, "token_ratio": round(coverage, 3),
            "divergence": div}


def grade_quote_at(quote, source, start, end):
    """grade_quote_against over a repo-relative cited range,
    read with the cite-lock lane's own line reader."""
    lines = cite_lock._read_lines(source)
    if lines is None:
        return {"grade": "not_found", "token_ratio": 0.0,
                "divergence": f"source {source} not on disk",
                "source": source, "range": [start, end]}
    out = grade_quote_against(
        quote, "\n".join(lines[start - 1:end]))
    out["source"] = source
    out["range"] = [start, end]
    return out


# -- Citation input: records, CSL, corpus extraction -----------------------------------

def normalise_record(rec):
    """A citation record in house or CSL-JSON shape -> the
    internal shape {doi, title, authors, year, venue, quote,
    locator, locations}."""
    out = {}
    doi = rec.get("doi") or rec.get("DOI") or ""
    doi = re.sub(r"^https?://doi\.org/", "",
                 str(doi).strip()).lower()
    if doi:
        out["doi"] = doi
    title = rec.get("title")
    if isinstance(title, list):
        title = title[0] if title else None
    if title:
        out["title"] = str(title).strip()
    authors = norm_authors(rec.get("authors")
                           or rec.get("author"))
    if authors:
        out["authors"] = authors
    year = rec.get("year")
    if not year:
        for key in ("issued", "published-print",
                    "published-online", "published"):
            parts = ((rec.get(key) or {}).get("date-parts")
                     or [])
            if parts and parts[0] and parts[0][0]:
                year = parts[0][0]
                break
    if year:
        try:
            out["year"] = int(str(year)[:4])
        except ValueError:
            pass
    venue = rec.get("venue") or rec.get("container-title")
    if isinstance(venue, list):
        venue = venue[0] if venue else None
    if venue:
        out["venue"] = str(venue).strip()
    if rec.get("quote"):
        out["quote"] = rec["quote"]
    loc = rec.get("locator") or {}
    if loc.get("source"):
        out["locator"] = {
            "source": loc["source"],
            "start": loc.get("start") or 1,
            "end": loc.get("end") or loc.get("start") or 1,
        }
    label = rec.get("label") or rec.get("location")
    out["locations"] = [label] if label else []
    return out


def load_citations_file(path):
    text = Path(path).read_text(encoding="utf-8")
    records = []
    stripped = text.strip()
    if stripped.startswith("["):
        records = [normalise_record(r)
                   for r in json.loads(stripped)]
    else:
        for line in stripped.splitlines():
            line = line.strip()
            if line:
                records.append(normalise_record(
                    json.loads(line)))
    return records


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'\)\]\},;]+")
_QUOTED_RE = re.compile(r"[“\"]([^“”\"]{15,})[”\"]")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]{4,})\*(?!\*)")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_AUTHOR_PAIR_RE = re.compile(
    r"([A-Z][A-Za-z'’\-]+)\s*(?:&|\band\b)\s*"
    r"([A-Z][A-Za-z'’\-]+)")
_AUTHOR_ETAL_RE = re.compile(
    r"([A-Z][A-Za-z'’\-]+)\s+et\s+al")
_AUTHOR_LEAD_RE = re.compile(
    r"^([A-Z][A-Za-z'’\-]+)\s*(?:,|\s+\d{4})")


def _clean_doi(raw):
    doi = raw.rstrip(".,;")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi.lower()


def extract_from_line(line):
    """The scholarly citation one prose line carries, if any:
    its DOI plus whatever title / authors / year / venue the
    line itself states. Fields the line does not state stay
    absent — extraction never invents them."""
    m = DOI_RE.search(line)
    if not m:
        return None
    doi = _clean_doi(m.group(0))
    window = line
    prefix = window[:m.start()]
    rec = {"doi": doi}
    quoted = [q.strip() for q in _QUOTED_RE.findall(window)
              if len(q.strip()) < 160
              and "doi" not in q.lower()
              and "http" not in q.lower()]
    if quoted:
        rec["title"] = max(quoted, key=len)
    italics = [i.strip() for i in _ITALIC_RE.findall(window)
               if not i.rstrip().endswith(":")]
    if italics:
        venue = italics[-1]
        if venue and venue != rec.get("title"):
            rec["venue"] = venue
    years = []
    range_spans = [m.span() for m in re.finditer(
        r"\d{3,4}\s*[–—-]\s*\d{3,4}", prefix)]
    for m in _YEAR_RE.finditer(prefix):
        if any(s <= m.start() < e for s, e in range_spans):
            continue  # a page range (pp. 1848–1858), not a year
        years.append(m.group(1))
    if years:
        rec["year"] = int(years[-1])
    lead = re.sub(r"^[\s\-\*#>:]+", "", prefix)
    lead = re.sub(r"^(Source opened|Source|Reference)s?\s*:\s*",
                  "", lead)
    pair = _AUTHOR_PAIR_RE.search(lead)
    etal = _AUTHOR_ETAL_RE.search(lead)
    if pair:
        rec["authors"] = [pair.group(1), pair.group(2)]
    elif etal:
        rec["authors"] = [etal.group(1)]
    else:
        leadm = _AUTHOR_LEAD_RE.match(lead)
        if leadm:
            rec["authors"] = [leadm.group(1)]
    return rec


def scan_corpus(include_raw=False):
    """DOI-bearing citations from the compiled pages (and,
    with include_raw, the raw layer). Deduped by DOI: the
    richest extraction wins, every location is kept."""
    dirs = [ROOT / "wiki"]
    if include_raw:
        dirs.append(ROOT / "raw")
    by_doi = {}
    scanned = 0
    for base in dirs:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            scanned += 1
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
            file_lines = text.splitlines()
            in_frontmatter = bool(
                file_lines and file_lines[0].strip() == "---")
            in_fence = False
            for i, line in enumerate(file_lines, 1):
                if in_frontmatter:
                    if i > 1 and line.strip() == "---":
                        in_frontmatter = False
                    continue
                if line.lstrip().startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                rec = extract_from_line(line)
                if not rec:
                    continue
                rec["locations"] = [f"{rel}#L{i}"]
                cur = by_doi.get(rec["doi"])
                if cur is None:
                    by_doi[rec["doi"]] = rec
                else:
                    cur["locations"].extend(rec["locations"])
                    for k in ("title", "authors", "year",
                              "venue"):
                        if not cur.get(k) and rec.get(k):
                            cur[k] = rec[k]
    records = sorted(by_doi.values(),
                     key=lambda r: r["doi"])
    return records, scanned


# -- Commands ---------------------------------------------------------------------------

def _fetcher_from_args(args):
    crossref_base = (args.crossref_base
                     or os.environ.get(
                         "WIKI_SCHOLAR_CROSSREF_BASE")
                     or CROSSREF_DEFAULT)
    openalex_base = (args.openalex_base
                     or os.environ.get(
                         "WIKI_SCHOLAR_OPENALEX_BASE")
                     or OPENALEX_DEFAULT)
    return HttpFetcher(crossref_base, openalex_base,
                       mailto=args.mailto, delay=args.delay)


def _sort_key(entry):
    cit = entry["citation"]
    return (cit.get("doi") or "", cit.get("title") or "")


def cmd_verify(args):
    fetcher = _fetcher_from_args(args)
    if args.citations:
        records = load_citations_file(args.citations)
        mode = f"citations file {args.citations}"
        scanned = None
    else:
        records, scanned = scan_corpus(
            include_raw=args.include_raw)
        mode = ("corpus scan (wiki/ pages"
                + (", raw/ included" if args.include_raw
                   else "") + ")")
    results = [verify_citation(rec, fetcher)
               for rec in records]
    results.sort(key=_sort_key)
    summary = {"verified": 0, "field-mismatch": 0,
               "not_found": 0, "cannot_determine": 0}
    alerts = 0
    for r in results:
        summary[r["verdict"]] += 1
        alerts += len(r["alerts"])
    report = {
        "tool": "wiki_scholar_check verification report",
        "generated": date.today().isoformat(),
        "mode": mode,
        "coverage": {
            "citations_checked": len(results),
            "with_doi": sum(1 for r in results
                            if r["citation"].get("doi")),
            "title_only": sum(1 for r in results
                              if not r["citation"].get("doi")),
            "pages_scanned": scanned,
            "extraction": ("scan mode: heuristic extraction"
                           " of DOI-bearing lines; fields are"
                           " only what the citing line states"
                           if scanned is not None else
                           "records as supplied"),
            "registries": ["crossref", "openalex"],
            "honesty": ("verdicts are data in this report,"
                        " never a gate; cannot_determine is"
                        " a first-class verdict; a failed"
                        " registry door is recorded as a door"
                        " failure, never as a negative"
                        " finding; retraction coverage is"
                        " claimed only for registries named in"
                        " each entry's `queried` list"),
        },
        "summary": {**summary, "alerts": alerts},
        "results": results,
    }
    out = Path(args.out) if args.out else VERIFY_REPORT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2,
                              ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"Scholarly citation check — {len(results)}"
          f" citation(s), mode: {mode}")
    print(f"  verified {summary['verified']} ·"
          f" field-mismatch {summary['field-mismatch']} ·"
          f" not_found {summary['not_found']} ·"
          f" cannot_determine"
          f" {summary['cannot_determine']} ·"
          f" alerts {alerts}")
    for r in results:
        if r["verdict"] != "verified" or r["alerts"]:
            cit = r["citation"]
            name = cit.get("doi") or cit.get("title") or "?"
            print(f"  [{r['verdict']}] {name} — {r['basis']}")
            for a in r["alerts"]:
                print(f"    [ALERT {a['kind']}]"
                      f" {a['registry']}: {a['evidence']}")
    print(f"wrote {out}")
    return 0


def cmd_quotes(args):
    quotes = cite_lock.find_checkable_quotes()
    results = []
    counts = {"exact": 0, "close": 0, "distorted": 0,
              "not_found": 0}
    for q in quotes:
        lines = cite_lock._read_lines(q["source"])
        if lines is None:
            graded = {"grade": "not_found",
                      "token_ratio": 0.0,
                      "divergence": f"source {q['source']}"
                                    " not on disk"}
        else:
            graded = grade_quote_against(
                q["quote"],
                "\n".join(lines[q["start"] - 1:q["end"]]))
        counts[graded["grade"]] += 1
        results.append({
            "page": q["page"], "page_line": q["page_line"],
            "source": q["source"],
            "range": [q["start"], q["end"]],
            "quote": q["quote"], **graded,
        })
    results.sort(key=lambda r: (r["page"], r["page_line"]))
    report = {
        "tool": "wiki_scholar_check quote grades",
        "generated": date.today().isoformat(),
        "coverage": {
            "quotes_checked": len(results),
            "pages": len({r["page"] for r in results}),
            "pairing": ("the cite-lock quote lane's pairing"
                        " (a quotation carrying a ^[cite:]"
                        " marker on its own or the adjacent"
                        " line), graded exact / close /"
                        " distorted / not_found against the"
                        " cited range of the local corpus"),
        },
        "summary": counts,
        "results": results,
    }
    out = Path(args.out) if args.out else QUOTE_REPORT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2,
                              ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"Quote grades — {len(results)} checkable"
          f" quotation(s) on {report['coverage']['pages']}"
          " page(s)")
    print(f"  exact {counts['exact']} · close"
          f" {counts['close']} · distorted"
          f" {counts['distorted']} · not_found"
          f" {counts['not_found']}")
    for r in results:
        if r["grade"] != "exact":
            print(f"  [{r['grade']}] {r['page']}"
                  f":{r['page_line']} -> {r['source']}"
                  f"#L{r['range'][0]}-L{r['range'][1]}"
                  f" — {r['divergence']}")
    print(f"wrote {out}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Scholarly citation truth-checking:"
                    " staged Crossref/OpenAlex verification"
                    " with field-level verdicts, retraction"
                    " alerts, and graded quote verification"
                    " against the local corpus.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_verify = sub.add_parser(
        "verify", help="verify scholarly citations against"
                       " Crossref + OpenAlex")
    src = p_verify.add_mutually_exclusive_group(required=True)
    src.add_argument("--scan", action="store_true",
                     help="extract DOI-bearing citations from"
                          " the wiki pages")
    src.add_argument("--citations", metavar="FILE",
                     help="JSON list or JSONL of citation"
                          " records (house or CSL shape)")
    p_verify.add_argument("--include-raw", action="store_true",
                          help="with --scan, also scan raw/")
    p_verify.add_argument("--out", metavar="PATH",
                          help="report path (default"
                               " evaluation/scholar-check-"
                               "report.json)")
    p_verify.add_argument("--delay", type=float, default=0.4,
                          help="seconds between registry"
                               " requests (default 0.4)")
    p_verify.add_argument("--mailto", default=MAILTO_DEFAULT,
                          help="polite-pool contact (default"
                               " the agent's own inbox)")
    p_verify.add_argument("--crossref-base",
                          help="Crossref base URL (mirror /"
                               " test override)")
    p_verify.add_argument("--openalex-base",
                          help="OpenAlex base URL (mirror /"
                               " test override)")
    p_quotes = sub.add_parser(
        "quotes", help="grade the corpus's checkable"
                       " quotations against their cited"
                       " ranges")
    p_quotes.add_argument("--out", metavar="PATH",
                          help="report path (default"
                               " evaluation/scholar-quote-"
                               "report.json)")
    args = ap.parse_args(argv[1:])
    if args.cmd == "verify":
        return cmd_verify(args)
    return cmd_quotes(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
