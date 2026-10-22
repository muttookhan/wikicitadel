#!/usr/bin/env python3
"""wiki_isbn_capture.py — identifier-first book capture (Open Library).

Build-list wave 4 (2026-10-22, "ISBN book-capture door (Open
Library)"; clean re-implementation: the Open Library Books and
Covers APIs are a public DATA source — the client here is our own
code, Python standard library only, no new packages, no Open
Library code taken).

    python3 scripts/wiki_isbn_capture.py ISBN [--out-dir DIR]
        [--sensitivity CLASS] [--no-cover]

The door takes ONE ISBN (typed or scanned as text), validates it
by checksum BEFORE any network call — an invalid ISBN is refused
with the reason and is never fetched — then fetches the edition
record (and, paced, its author and work records) from the Open
Library Books API and lands a source record in raw/ through the
normal ingest path: the record text passes through
scripts/wiki_convert.py's seam, so the API's text is sanitised,
the source's trust tier is classified, and the `.ingest.json`
sidecar carries both, plus a `book_capture` block recording the
ISBN as entered, the ISBN-13 it was normalised to, the fetch URLs
and the fetch timestamp as provenance.

Per-item discipline (the APIs' own terms): one ISBN per
invocation, calls paced, a descriptive User-Agent, and NO bulk
mode anywhere in this tool — the Covers API guidelines
(https://openlibrary.org/dev/docs/api/covers, read 2026-10-22)
ask users not to crawl the cover API, and this door complies by
construction.

Honest doors, never invented metadata:
  - unknown ISBN        -> verdict "not_found", recorded in a
                           sidecar-only artefact; no record file.
  - API unreachable or
    malformed response  -> a named door in the sidecar
                           ("openlibrary-unreachable" /
                           "openlibrary-malformed-response");
                           sidecar-only artefact, no record file.
  - partial metadata    -> the record lands with what exists;
                           every field Open Library did not
                           supply is NAMED in the sidecar's
                           fields_missing and on the record's own
                           face. Verdict "found-partial" (the
                           missing list, not the verdict, is the
                           detail — a missing cover or subtitle
                           is enough to make a record partial).
  - an existing record  -> refused, never overwritten: raw
                           records are history.

Exit codes (wiki_convert.py's conventions): 0 = record landed;
2 = refusal (invalid ISBN, unknown sensitivity class, existing
record, or an ingest into raw/ without a --sensitivity class);
4 = door / not_found (sidecar written, no record).
"""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "raw" / "sources"
API_BASE = "https://openlibrary.org"
COVERS_BASE = "https://covers.openlibrary.org"
USER_AGENT = ("wiki-isbn-capture/1.0 (LLM Wiki ingest; "
              "per-item book capture, one ISBN per run)")
PACE_SECONDS = 0.35
FETCH_TIMEOUT = 15
MAX_AUTHORS = 10
# The Covers API's blank placeholder (served when ?default=false
# is forgotten) is a 43-byte 1x1 image; anything at placeholder
# scale is treated as "no cover served", never stored as a cover.
COVER_PLACEHOLDER_MAX_BYTES = 100

COVER_TERMS_NOTE = (
    "Open Library Covers API guidelines "
    "(https://openlibrary.org/dev/docs/api/covers, read "
    "2026-10-22): do not crawl the Covers API; covers are also "
    "available in bulk from archive.org; for public-facing "
    "display Open Library asks for a src URL pointing at "
    "covers.openlibrary.org and appreciates a courtesy link "
    "back (the record carries the book's Open Library page URL "
    "for that purpose). The guidelines state no licence for "
    "the underlying cover artwork, so no rights over the "
    "artwork are asserted: this copy is stored only inside "
    "the owner's private wiki.")

# The canonical metadata fields a complete record carries. The
# sidecar's fields_missing names every one of these Open Library
# did not supply; nothing is filled from reputation or memory.
CORE_FIELDS = ("title", "authors", "publishers", "publish_date",
               "number_of_pages", "identifiers")
EXTRA_FIELDS = ("subtitle", "languages", "subjects",
                "description", "cover")
ALL_FIELDS = CORE_FIELDS + EXTRA_FIELDS


class IsbnError(Exception):
    """A refused ISBN (or refused capture) — exit 2, no fetch."""


class CaptureDoor(Exception):
    """A named door: the API could not be used this run. The
    sidecar records the door; no metadata is invented."""

    def __init__(self, name, reason):
        super().__init__(reason)
        self.name = name
        self.reason = reason


# ------------------------------------------------------------ ISBN
# Validation and normalisation, our own code against the ISBN
# checksum definitions. Pure: this section never touches the
# network, and capture() validates before it fetches anything.

def _isbn13_check_digit(first12):
    total = sum(int(d) * (1 if i % 2 == 0 else 3)
                for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def _isbn10_check_char(first9):
    total = sum((10 - i) * int(d) for i, d in enumerate(first9))
    check = (11 - total % 11) % 11
    return "X" if check == 10 else str(check)


def _isbn10_to_13(clean10):
    first12 = "978" + clean10[:9]
    return first12 + _isbn13_check_digit(first12)


def validate_isbn(raw):
    """Validate an ISBN by checksum. Returns a dict:
    {input, cleaned, kind ("isbn10"/"isbn13"), isbn13,
     normalised_from (the ISBN-10, when a conversion was
     applied, else None), errors [..]}. Never raises and never
     fetches; the caller refuses when errors is non-empty."""
    out = {"input": raw, "cleaned": None, "kind": None,
           "isbn13": None, "normalised_from": None, "errors": []}
    cleaned = re.sub(r"[-\s]", "", (raw or "")).upper()
    out["cleaned"] = cleaned
    if not cleaned:
        out["errors"].append("empty ISBN")
        return out
    if len(cleaned) not in (10, 13):
        out["errors"].append(
            f"an ISBN has 10 or 13 characters after hyphens and "
            f"spaces are removed; this one has {len(cleaned)} "
            f"({cleaned!r})")
        return out
    if len(cleaned) == 13:
        out["kind"] = "isbn13"
        if not cleaned.isdigit():
            out["errors"].append(
                "an ISBN-13 is all digits (the X check character "
                "exists only in ISBN-10)")
            return out
        if cleaned[:3] not in ("978", "979"):
            out["errors"].append(
                f"an ISBN-13 begins 978 or 979; this one begins "
                f"{cleaned[:3]}")
            return out
        want = _isbn13_check_digit(cleaned[:12])
        if cleaned[12] != want:
            out["errors"].append(
                f"checksum mismatch: for {cleaned} the check "
                f"digit should be {want}, not {cleaned[12]}")
            return out
        out["isbn13"] = cleaned
        return out
    # ISBN-10: nine digits + a check character (digit or X).
    out["kind"] = "isbn10"
    if not cleaned[:9].isdigit() \
            or cleaned[9] not in "0123456789X":
        out["errors"].append(
            "an ISBN-10 is nine digits plus a check character "
            "(a digit, or X for the value 10)")
        return out
    want = _isbn10_check_char(cleaned[:9])
    if cleaned[9] != want:
        out["errors"].append(
            f"checksum mismatch: for {cleaned} the check "
            f"character should be {want}, not {cleaned[9]}")
        return out
    out["isbn13"] = _isbn10_to_13(cleaned)
    out["normalised_from"] = cleaned
    return out


# --------------------------------------------------------- network
# One choke point (wiki_convert.py's _fetch_url precedent) so
# tests can stand in for the network. Calls are paced: this door
# is per-item by design and never crawls.

def _fetch(url, timeout=FETCH_TIMEOUT):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _pace():
    if PACE_SECONDS > 0:
        time.sleep(PACE_SECONDS)


def _fetch_json(url, what):
    """Fetch and parse JSON. HTTP errors pass through for the
    caller to read; transport failures and malformed bodies are
    named doors."""
    try:
        body = _fetch(url)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise CaptureDoor(
            "openlibrary-unreachable",
            f"the Open Library {what} at {url} could not be "
            f"fetched from this environment ({exc}) — no "
            f"metadata was captured")
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise CaptureDoor(
            "openlibrary-malformed-response",
            f"the Open Library {what} at {url} returned a body "
            f"that is not JSON ({exc}) — no metadata was "
            f"captured from it")


def _http_door(url, what, exc):
    return CaptureDoor(
        "openlibrary-unreachable",
        f"the Open Library {what} at {url} answered HTTP "
        f"{exc.code} — no metadata was captured")


# ------------------------------------------------------ timestamps

def _now():
    utc = datetime.now(timezone.utc)
    local, tz_name = utc, "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Indiana/Indianapolis")
        local, tz_name = utc.astimezone(tz), \
            "America/Indiana/Indianapolis"
    except Exception:
        pass
    return {"utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "local_date": local.strftime("%Y-%m-%d"),
            "local_tz": tz_name}


# --------------------------------------------------------- capture

def _load_converter():
    spec = importlib.util.spec_from_file_location(
        "wiki_convert", Path(__file__).resolve().parent
        / "wiki_convert.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text_value(node):
    """Open Library text fields are strings or {value: ...}."""
    if isinstance(node, dict):
        return node.get("value") or None
    return node or None


def capture(isbn_raw, out_dir, sensitivity=None, want_cover=True):
    """Run one capture. Returns a result dict. Raises IsbnError
    (refusal, exit 2) or CaptureDoor (named door, exit 4); a
    not_found verdict returns normally with the sidecar-only
    artefact written."""
    check = validate_isbn(isbn_raw)
    if check["errors"]:
        raise IsbnError("invalid ISBN refused (never fetched): "
                        + "; ".join(check["errors"]))
    isbn13 = check["isbn13"]
    out_dir = Path(out_dir)
    stem = f"book-{isbn13}"
    record_path = out_dir / (stem + ".md")
    sidecar_path = out_dir / (stem + ".md.ingest.json")
    cover_path = out_dir / (stem + "-cover.jpg")
    if record_path.exists():
        raise IsbnError(
            f"a record for ISBN-13 {isbn13} already stands at "
            f"{record_path} — captures never overwrite a filed "
            f"record")
    stamp = _now()
    fetched = []

    def sidecar_only(verdict, door=None, extra=None):
        block = {"isbn_input": isbn_raw,
                 "isbn_cleaned": check["cleaned"],
                 "isbn13": isbn13,
                 "isbn_normalised_from": check["normalised_from"],
                 "verdict": verdict,
                 "door": door,
                 "fetched_at_utc": stamp["utc"],
                 "fetch_urls": list(fetched)}
        if extra:
            block.update(extra)
        doc = {"source": None,
               "capture_tool": "scripts/wiki_isbn_capture.py",
               "book_capture": block,
               "note": "no source record was created; this "
                       "sidecar is the capture's whole artefact"}
        out_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        return {"verdict": verdict, "isbn13": isbn13,
                "record": None, "sidecar": str(sidecar_path),
                "cover": None, "door": door}

    edition_url = f"{API_BASE}/isbn/{isbn13}.json"
    fetched.append(edition_url)
    try:
        edition = _fetch_json(edition_url, "Books API")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return sidecar_only("not_found", extra={
                "not_found_basis": f"the Open Library Books API "
                f"answered HTTP 404 for {edition_url} — it holds "
                f"no edition under ISBN-13 {isbn13}; that is a "
                f"finding about Open Library's catalogue, not "
                f"about the book's existence"})
        raise _http_door(edition_url, "Books API", exc)
    if not isinstance(edition, dict) or not edition.get("key"):
        raise CaptureDoor(
            "openlibrary-malformed-response",
            f"the Open Library Books API at {edition_url} "
            f"returned JSON without an edition record — no "
            f"metadata was captured from it")

    loss = []
    present, missing = [], []

    def field(name, value):
        if value:
            present.append(name)
            return value
        missing.append(name)
        return None

    title = field("title", edition.get("title"))
    subtitle = field("subtitle", edition.get("subtitle"))

    author_names = []
    author_keys = [a.get("key") for a in edition.get("authors")
                   or [] if isinstance(a, dict) and a.get("key")]
    if len(author_keys) > MAX_AUTHORS:
        loss.append(f"the edition lists {len(author_keys)} "
                    f"authors; only the first {MAX_AUTHORS} were "
                    f"fetched (per-item pacing)")
        author_keys = author_keys[:MAX_AUTHORS]
    for key in author_keys:
        _pace()
        url = f"{API_BASE}{key}.json"
        fetched.append(url)
        try:
            rec = _fetch_json(url, "Books API (author record)")
            name = rec.get("name") if isinstance(rec, dict) \
                else None
        except (CaptureDoor, urllib.error.HTTPError):
            name = None
        if name:
            author_names.append(f"{name} ({key})")
        else:
            author_names.append(f"name not served ({key})")
            loss.append(f"author name for {key} could not be "
                        f"fetched — the Open Library key is "
                        f"recorded in its place")
    authors = field("authors", author_names or None)

    publishers = field("publishers", edition.get("publishers"))
    publish_date = field("publish_date",
                         edition.get("publish_date"))
    pages = field("number_of_pages",
                  edition.get("number_of_pages"))
    languages = field("languages",
                      [lang.get("key", "").rsplit("/", 1)[-1]
                       for lang in edition.get("languages") or []
                       if isinstance(lang, dict)])
    identifiers = {}
    for label, key in (("ISBN-13", "isbn_13"), ("ISBN-10", "isbn_10"),
                       ("OCLC", "oclc_numbers"), ("LCCN", "lccn")):
        vals = edition.get(key)
        if vals:
            identifiers[label] = list(vals)
    for label, val in (edition.get("identifiers") or {}).items():
        identifiers[label] = list(val) if isinstance(val, list) \
            else [val]
    field("identifiers", identifiers or None)

    description = _text_value(edition.get("description"))
    subjects = None
    work_key = None
    works = edition.get("works") or []
    if works and isinstance(works[0], dict):
        work_key = works[0].get("key")
    if work_key:
        _pace()
        url = f"{API_BASE}{work_key}.json"
        fetched.append(url)
        try:
            work = _fetch_json(url, "Books API (work record)")
            if isinstance(work, dict):
                subjects = work.get("subjects") or None
                if not description:
                    description = _text_value(
                        work.get("description"))
        except (CaptureDoor, urllib.error.HTTPError) as exc:
            loss.append(f"the work record {work_key} could not "
                        f"be fetched ({exc}) — subjects and the "
                        f"work description were not captured")
    field("subjects", subjects)
    field("description", description)

    cover_block = {"status": "not-requested", "file": None,
                   "source_url": None, "bytes": None,
                   "sha256": None, "terms_note": COVER_TERMS_NOTE}
    cover_bytes = None
    if want_cover:
        _pace()
        cover_url = (f"{COVERS_BASE}/b/isbn/{isbn13}"
                     f"-L.jpg?default=false")
        fetched.append(cover_url)
        cover_block["source_url"] = cover_url
        try:
            cover_bytes = _fetch(cover_url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                cover_block["status"] = "not-served"
                loss.append("the Covers API served no cover for "
                            "this ISBN (HTTP 404 with "
                            "default=false) — the record stands "
                            "without one")
            else:
                cover_block["status"] = "fetch-failed"
                loss.append(f"the cover fetch answered HTTP "
                            f"{exc.code} — the record stands "
                            f"without a cover")
                cover_bytes = None
        except (urllib.error.URLError, OSError,
                TimeoutError) as exc:
            cover_block["status"] = "fetch-failed"
            loss.append(f"the cover could not be fetched "
                        f"({exc}) — the record stands without "
                        f"a cover")
            cover_bytes = None
        if cover_bytes is not None \
                and len(cover_bytes) <= COVER_PLACEHOLDER_MAX_BYTES:
            loss.append(f"the Covers API returned "
                        f"{len(cover_bytes)} bytes — placeholder "
                        f"scale, treated as no cover served")
            cover_block["status"] = "not-served"
            cover_bytes = None
    if cover_bytes:
        cover_block.update({
            "status": "stored",
            "file": cover_path.name,
            "bytes": len(cover_bytes),
            "sha256": hashlib.sha256(cover_bytes).hexdigest()})
        present.append("cover")
    else:
        missing.append("cover")

    verdict = "found" if not missing else "found-partial"
    book_url = f"{API_BASE}/isbn/{isbn13}"

    lines = [f"# {title or 'Untitled edition'} — book record "
             f"(ISBN capture)", "",
             f"Source: {edition_url} (Open Library Books API)",
             f"Open Library page: {book_url}",
             f"ISBN (as entered): {isbn_raw}",
             f"ISBN-13: {isbn13}"]
    if check["normalised_from"]:
        lines.append(f"Normalised from ISBN-10: "
                     f"{check['normalised_from']}")
    lines += [f"Date captured: {stamp['local_date']} "
              f"({stamp['local_tz']})",
              f"Fetch timestamp (UTC): {stamp['utc']}", "",
              "## Bibliographic record (as served by Open "
              "Library)", ""]
    if title:
        lines.append(f"Title: {title}")
    if subtitle:
        lines.append(f"Subtitle: {subtitle}")
    if authors:
        lines.append(f"Authors: {'; '.join(authors)}")
    if publishers:
        lines.append(f"Publishers: {'; '.join(publishers)}")
    if publish_date:
        lines.append(f"Publish date (as recorded by Open "
                     f"Library): {publish_date}")
    if pages:
        lines.append(f"Pages: {pages}")
    if languages:
        lines.append(f"Language codes: {', '.join(languages)}")
    lines.append(f"Open Library edition: "
                 f"{edition.get('key')}")
    if work_key:
        lines.append(f"Open Library work: {work_key}")
    if identifiers:
        lines += ["", "## Identifiers", ""]
        for label, vals in identifiers.items():
            lines.append(f"- {label}: {', '.join(map(str, vals))}")
    if subjects:
        lines += ["", "## Subjects (from the Open Library work "
                      "record)", ""]
        lines += [f"- {s}" for s in subjects]
    if description:
        lines += ["", "## Description (from Open Library)", "",
                  description]
    if missing:
        lines += ["", "## Fields Open Library did not supply",
                  ""]
        lines += [f"- {name}" for name in missing]
        lines += ["", "These fields are recorded as missing, "
                      "never filled from the book's reputation "
                      "or any other source."]
    lines += ["", "## Capture provenance", "",
              "- Door: scripts/wiki_isbn_capture.py (ISBN "
              "book-capture door, Open Library Books/Covers "
              "APIs)",
              f"- Verdict: {verdict}",
              "- Fetch URLs: " + "; ".join(fetched)]
    if cover_block["status"] == "stored":
        lines.append(f"- Cover: stored beside this record as "
                     f"{cover_path.name} (Open Library Covers "
                     f"API; the sidecar's book_capture.cover "
                     f"block carries the use-guideline note — "
                     f"no rights over the artwork are asserted)")
    elif want_cover:
        lines.append(f"- Cover: {cover_block['status']} — the "
                     f"record stands without one (see the "
                     f"conversion-loss notes)")
    if loss:
        lines += ["", "Conversion-loss notes:"]
        lines += [f"- {note}" for note in loss]
    md = "\n".join(lines).rstrip() + "\n"

    out_dir.mkdir(parents=True, exist_ok=True)
    record_path.write_text(md, encoding="utf-8")
    if cover_bytes:
        cover_path.write_bytes(cover_bytes)

    # The converter seam: the API's text is sanitised and the
    # trust tier classified exactly as for any ingested source;
    # the cleaned markdown is what stays on disk.
    wc = _load_converter()
    try:
        clean_md, report = wc.convert_with_report(
            record_path, sensitivity)
    except wc.ConvertError as exc:
        raise IsbnError(f"the converter seam refused the "
                        f"record: {exc}")
    record_path.write_text(clean_md, encoding="utf-8")
    report["book_capture"] = {
        "isbn_input": isbn_raw,
        "isbn_cleaned": check["cleaned"],
        "isbn_kind": check["kind"],
        "isbn13": isbn13,
        "isbn_normalised_from": check["normalised_from"],
        "verdict": verdict,
        "door": None,
        "fetched_at_utc": stamp["utc"],
        "captured_local_date": stamp["local_date"],
        "fetch_urls": fetched,
        "fields_present": present,
        "fields_missing": missing,
        "metadata_source": "Open Library Books API (edition"
                           + (", author and work records"
                              if author_keys or work_key else
                              " record only") + ")",
        "cover": cover_block}
    if loss:
        report["conversion_loss"] = list(
            report.get("conversion_loss") or []) + loss
    sidecar_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return {"verdict": verdict, "isbn13": isbn13,
            "record": str(record_path),
            "sidecar": str(sidecar_path),
            "cover": cover_block, "door": None,
            "fields_missing": missing}


# ----------------------------------------------------------------

def _is_raw_path(path):
    try:
        Path(path).resolve().relative_to(
            (ROOT / "raw").resolve())
        return True
    except ValueError:
        return False


def main(argv):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    ap.add_argument("isbn",
                    help="the ISBN-10 or ISBN-13, hyphens "
                         "optional; validated by checksum "
                         "before any fetch")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                    help="where the record lands "
                         "(default: raw/sources/)")
    ap.add_argument("--sensitivity", default=None,
                    metavar="CLASS",
                    help="sensitivity class for this ingest, "
                         "from evaluation/sensitivity.json. "
                         "REQUIRED when --out-dir is inside "
                         "raw/: an ingest without a class is "
                         "refused, because unclassified never "
                         "reads as public")
    ap.add_argument("--no-cover", action="store_true",
                    help="skip the Covers API fetch")
    ap.add_argument("--json", action="store_true",
                    help="print the result as JSON")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    if _is_raw_path(out_dir) and not args.sensitivity:
        print("wiki_isbn_capture: refusing to ingest into raw/ "
              "without a --sensitivity class "
              "(evaluation/sensitivity.json). Classify the "
              "material at the door: unclassified never reads "
              "as public.", file=sys.stderr)
        return 2
    try:
        result = capture(args.isbn, out_dir, args.sensitivity,
                         want_cover=not args.no_cover)
    except IsbnError as exc:
        print(f"wiki_isbn_capture: {exc}", file=sys.stderr)
        return 2
    except CaptureDoor as exc:
        # capture() raises before writing when the edition
        # fetch itself doors; write the sidecar-only artefact
        # here so the door is on the record either way.
        check = validate_isbn(args.isbn)
        sidecar = out_dir / f"book-{check['isbn13']}" \
                            ".md.ingest.json"
        if not sidecar.exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            doc = {"source": None,
                   "capture_tool": "scripts/wiki_isbn_capture.py",
                   "book_capture": {
                       "isbn_input": args.isbn,
                       "isbn_cleaned": check["cleaned"],
                       "isbn13": check["isbn13"],
                       "isbn_normalised_from":
                           check["normalised_from"],
                       "verdict": "door",
                       "door": {"name": exc.name,
                                "reason": exc.reason},
                       "fetched_at_utc": _now()["utc"],
                       "fetch_urls": [
                           f"{API_BASE}/isbn/"
                           f"{check['isbn13']}.json"]},
                   "note": "no source record was created; this "
                           "sidecar is the capture's whole "
                           "artefact"}
            sidecar.write_text(
                json.dumps(doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        print(f"wiki_isbn_capture: door {exc.name!r}: "
              f"{exc.reason} — recorded in {sidecar}; no "
              f"record was written", file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"wiki_isbn_capture: verdict {result['verdict']}; "
              f"ISBN-13 {result['isbn13']}")
        if result["record"]:
            print(f"wrote {result['record']} + "
                  f"{Path(result['sidecar']).name} (ingest "
                  f"record: trust tier + sanitiser report + "
                  f"book_capture provenance)")
            if result["cover"] \
                    and result["cover"]["status"] == "stored":
                print(f"cover stored: {result['cover']['file']} "
                      f"({result['cover']['bytes']} bytes)")
            if result.get("fields_missing"):
                print("fields Open Library did not supply: "
                      + ", ".join(result["fields_missing"]))
        else:
            print(f"no record written; verdict recorded in "
                  f"{result['sidecar']}")
    return 0 if result["record"] else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
