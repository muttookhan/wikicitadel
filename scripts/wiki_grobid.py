#!/usr/bin/env python3
"""wiki_grobid.py — GROBID bibliographic-extraction sidecar
(W4, build-list item 40: "GROBID standing sidecar").

GROBID (grobidOrg/grobid, Apache-2.0 — adapt-with-credit) is a
Java service that extracts bibliographic structure from
scholarly PDFs: header metadata (title / authors / venue /
date / DOI), parsed references, and citation contexts, as TEI
XML. It is NOT a document converter — it does not produce the
ingest markdown — so it does not join the converter-engine
registry in scripts/wiki_convert_engines.py as an engine; it
is registered there as a SIDECAR SERVICE (SIDECAR_SERVICES),
and this module is its client + TEI parser + sidecar block.

The sidecar's discipline:

  * CONFIGURATION ONLY. The endpoint comes from the caller
    (an explicit URL) or the GROBID_URL environment variable.
    Nothing is hardcoded; this module never starts a service.
  * THE HONEST DOOR. No endpoint configured -> the sidecar
    block records the door "grobid-not-configured". An
    endpoint configured but unreachable -> the named failure
    "grobid-unreachable" with the transport error verbatim.
    A service that answers with unparseable TEI -> the door
    "grobid-malformed-tei". A non-PDF -> the door
    "grobid-format-unsupported". No path pretends extraction
    happened when it did not.
  * MACHINE-UNVERIFIED, ALWAYS. Everything GROBID returns is
    engine output. It lands in the ingest sidecar under
    "grobid" with state "machine-unverified" and feeds the
    staged registry verification in
    scripts/wiki_scholar_check.py (header_as_citation() maps
    a header to that tool's citation shape) — verification
    happens there, never here. A GROBID DOI is a claim to be
    checked, not a fact: the DOI-defect lesson of 2026-10-22
    (a wrong DOI recorded in this corpus for a real paper) is
    exactly what this separation exists to catch.
  * PARTIAL IS PARTIAL. A header TEI that parses but lacks
    fields records the extraction with every missing field
    NAMED in "missing_fields"; a references/fulltext stage
    that fails after the header succeeded is recorded in
    "stage_failures" with the extracted parts kept and the
    block flagged "partial".

Environment record: GROBID cannot run on this VM — the
Round 10 trial door-failed (no Java runtime; Gradle daemon
loopback reset), recorded in evaluation/grobid-trial-evidence
.json, and a fresh probe on 2026-10-22 confirms it: `java`
absent, nothing answering on the default port 8070, no
GROBID_URL set. The adapter is therefore proven end-to-end
against a local fixture server speaking the GROBID API shape
(the test suite's stub) — the document-engine lane's stub
precedent. No corpus PDF is ever sent to a third-party
GROBID demo server: the only endpoints this client will call
are the ones it is configured with.

API shape (from the public GROBID REST API documentation;
the client code is this project's own):
  GET  /api/isalive                 -> "true"
  GET  /api/version                 -> version string
  POST /api/processHeaderDocument   (form field "input": the
  POST /api/processReferences        PDF) -> TEI XML
  POST /api/processFulltextDocument

Licence: GROBID is Apache-2.0 (grobidOrg/grobid); the API
shape and TEI conventions are used with credit, no GROBID
code is carried or fetched. TEI parsing is stdlib
ElementTree over the TEI P5 namespace, matched by local
name so namespace-prefix variations do not matter.

CLI:
  python3 scripts/wiki_grobid.py probe [--url URL]
  python3 scripts/wiki_grobid.py extract FILE.pdf
      [--url URL] [--out BLOCK.json]
Exit codes: 0 = extraction recorded (or probe: alive);
4 = a door / failure, with the block (or probe record)
still printed — the house door convention.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

ENV_VAR = "GROBID_URL"
DEFAULT_PORT = 8070

SERVICE = {
    "service": "grobid",
    "label": "GROBID (grobidOrg/grobid)",
    "licence": "Apache-2.0",
    "licence_route": "adapt-with-credit",
}

UNVERIFIED_NOTE = (
    "unverified — GROBID output is machine extraction; it "
    "becomes 'verified' only through staged registry "
    "verification (scripts/wiki_scholar_check.py), which "
    "this block feeds but never replaces")


# ---------------------------------------------------------------- doors

class GrobidDoor(Exception):
    """A named door: extraction did not happen, and the block
    says why. Carries the door record for the sidecar."""

    def __init__(self, name, reason, **extra):
        self.door = {"name": name, "reason": reason}
        self.door.update(extra)
        super().__init__(f"{name}: {reason}")


# ------------------------------------------------------------- endpoint

def configured_endpoint(explicit=None, env=None):
    """Resolve the endpoint: an explicit URL wins; True means
    'use the configured one'; otherwise the GROBID_URL
    environment variable. Returns None when nothing is
    configured — the caller doors it, never guesses a host."""
    env = os.environ if env is None else env
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().rstrip("/")
    return (env.get(ENV_VAR) or "").strip().rstrip("/") or None


# ---------------------------------------------------------------- client

class GrobidClient:
    """Stdlib HTTP client for one configured GROBID endpoint.
    `opener` is injectable for tests; by default real urllib."""

    def __init__(self, endpoint, timeout=120, probe_timeout=5,
                 opener=None):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.probe_timeout = probe_timeout
        self._opener = opener or urllib.request.urlopen

    def _get_text(self, path, timeout):
        req = urllib.request.Request(
            self.endpoint + path,
            headers={"User-Agent": "wiki-grobid-sidecar/1.0",
                     "Accept": "text/plain, application/xml"})
        with self._opener(req, timeout=timeout) as fh:
            return fh.read().decode("utf-8", errors="replace")

    def _post_pdf(self, path, pdf_bytes, filename):
        boundary = "wikigrobid" + uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="input"; '
            f'filename="{filename}"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + pdf_bytes + (
            f"\r\n--{boundary}--\r\n").encode("utf-8")
        req = urllib.request.Request(
            self.endpoint + path, data=body,
            headers={
                "User-Agent": "wiki-grobid-sidecar/1.0",
                "Content-Type": "multipart/form-data; "
                                f"boundary={boundary}",
                "Accept": "application/xml"})
        with self._opener(req, timeout=self.timeout) as fh:
            return fh.read().decode("utf-8", errors="replace")

    # the GROBID API surface this sidecar uses
    def is_alive(self):
        return self._get_text("/api/isalive",
                              self.probe_timeout).strip() \
            .lower() == "true"

    def version(self):
        return self._get_text("/api/version",
                              self.probe_timeout).strip() or None

    def process_header(self, pdf_bytes, filename):
        return self._post_pdf("/api/processHeaderDocument",
                              pdf_bytes, filename)

    def process_references(self, pdf_bytes, filename):
        return self._post_pdf("/api/processReferences",
                              pdf_bytes, filename)

    def process_fulltext(self, pdf_bytes, filename):
        return self._post_pdf("/api/processFulltextDocument",
                              pdf_bytes, filename)


def probe(endpoint, client=None):
    """Liveness probe of one endpoint. Returns
    {"available", "version", "blocker"} — the blocker is the
    transport error verbatim, never paraphrased."""
    client = client or GrobidClient(endpoint)
    try:
        if not client.is_alive():
            return {"available": False, "version": None,
                    "blocker": "the endpoint answered "
                               "/api/isalive but did not "
                               "report 'true'"}
    except urllib.error.HTTPError as exc:
        return {"available": False, "version": None,
                "blocker": f"HTTP {exc.code} for "
                           f"{endpoint}/api/isalive"}
    except (urllib.error.URLError, TimeoutError,
            OSError) as exc:
        return {"available": False, "version": None,
                "blocker": f"{type(exc).__name__}: {exc}"}
    version = None
    try:
        version = client.version()
    except Exception:
        version = None  # liveness is proven; version is a bonus
    return {"available": True, "version": version,
            "blocker": None}


# ------------------------------------------------------------ TEI parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) \
        else ""


def _find_all(elem, name):
    return [e for e in elem.iter() if _local(e.tag) == name]


def _find_first(elem, name):
    for e in elem.iter():
        if _local(e.tag) == name:
            return e
    return None


def _text(elem):
    if elem is None:
        return None
    text = re.sub(r"\s+", " ", "".join(elem.itertext())).strip()
    return text or None


def _parse_tei(xml_text, stage):
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise GrobidDoor(
            "grobid-malformed-tei",
            f"the GROBID {stage} response is not parseable "
            f"TEI XML: {exc}", stage=stage) from exc


def _author_name(author_elem):
    """One <author> -> {"given", "family", "display"} from its
    <persName>; falls back to the element's whole text."""
    pers = _find_first(author_elem, "persName")
    scope = pers if pers is not None else author_elem
    surname = _find_first(scope, "surname")
    family = _text(surname)
    given_parts = []
    for e in scope.iter():
        if _local(e.tag) == "forename":
            t = _text(e)
            if t:
                given_parts.append(t)
    given = " ".join(given_parts) or None
    if family is None and given is None:
        display = _text(scope)
        return {"given": None, "family": None,
                "display": display} if display else None
    display = " ".join(x for x in (given, family) if x) or None
    return {"given": given, "family": family,
            "display": display}


def _bibl_fields(bibl):
    """The bibliographic fields of one <biblStruct>, in the
    sidecar's shape. Missing fields are None here and NAMED
    in the caller's missing_fields list."""
    analytic = _find_first(bibl, "analytic")
    title_scope = analytic if analytic is not None else bibl
    title = None
    for t in _find_all(title_scope, "title"):
        if t.get("type") == "main" or title is None:
            title = _text(t)
        if t.get("type") == "main":
            break
    authors = []
    for a in _find_all(title_scope, "author"):
        name = _author_name(a)
        if name and name["display"]:
            authors.append(name)
    doi = None
    for idno in _find_all(bibl, "idno"):
        if (idno.get("type") or "").upper() == "DOI":
            raw = _text(idno)
            if raw:
                doi = re.sub(r"^https?://doi\.org/", "",
                             raw.strip()).lower()
                break
    monogr = _find_first(bibl, "monogr")
    venue = None
    date = None
    if monogr is not None:
        mt = _find_first(monogr, "title")
        venue = _text(mt)
        imprint = _find_first(monogr, "imprint")
        if imprint is not None:
            for d in _find_all(imprint, "date"):
                if d.get("when"):
                    date = d.get("when")
                    break
    if date is None:
        for d in _find_all(bibl, "date"):
            if d.get("type") == "published" and d.get("when"):
                date = d.get("when")
                break
    year = None
    if date and re.match(r"\d{4}", date):
        year = int(date[:4])
    fields = {"title": title, "authors": authors,
              "venue": venue, "date": date, "year": year,
              "doi": doi}
    missing = [k for k in ("title", "venue", "date", "doi")
               if not fields[k]]
    if not authors:
        missing.append("authors")
    fields["missing_fields"] = sorted(missing)
    return fields


def parse_header_tei(xml_text):
    """TEI from processHeaderDocument -> the header record."""
    root = _parse_tei(xml_text, "processHeaderDocument")
    bibl = _find_first(root, "biblStruct")
    if bibl is None:
        empty = {"title": None, "authors": [], "venue": None,
                 "date": None, "year": None, "doi": None}
        empty["missing_fields"] = sorted(
            ["title", "authors", "venue", "date", "doi"])
        return empty
    return _bibl_fields(bibl)


def parse_references_tei(xml_text):
    """TEI from processReferences -> one record per parsed
    reference (<biblStruct> under the references list)."""
    root = _parse_tei(xml_text, "processReferences")
    refs = []
    for bibl in _find_all(root, "biblStruct"):
        fields = _bibl_fields(bibl)
        xml_id = bibl.get(
            "{http://www.w3.org/XML/1998/namespace}id") \
            or bibl.get("id")
        raw = None
        for note in _find_all(bibl, "note"):
            if note.get("type") == "raw_reference":
                raw = _text(note)
                break
        refs.append({"id": xml_id, **fields, "raw": raw})
    return refs


def parse_citation_contexts_tei(xml_text):
    """TEI from processFulltextDocument -> one record per
    in-text bibliographic reference: the marker as printed,
    its target reference id, and the paragraph text around
    it (whitespace-normalised, truncated at 500 chars)."""
    root = _parse_tei(xml_text, "processFulltextDocument")
    contexts = []
    for para in _find_all(root, "p"):
        refs = [e for e in para.iter()
                if _local(e.tag) == "ref"
                and e.get("type") == "bibr"]
        if not refs:
            continue
        context = re.sub(r"\s+", " ",
                         "".join(para.itertext())).strip()
        if len(context) > 500:
            context = context[:497] + "..."
        for ref in refs:
            target = ref.get("target") or ""
            contexts.append({
                "marker": _text(ref),
                "target": target.lstrip("#") or None,
                "context": context})
    return contexts


def header_as_citation(header):
    """A parsed header in wiki_scholar_check.py's citation
    shape — the feed into staged registry verification.
    Only fields the header actually carries are included;
    author display names in order."""
    cit = {}
    if header.get("doi"):
        cit["doi"] = header["doi"]
    if header.get("title"):
        cit["title"] = header["title"]
    authors = [a["display"] for a in header.get("authors") or []
               if a.get("display")]
    if authors:
        cit["authors"] = authors
    if header.get("year"):
        cit["year"] = header["year"]
    if header.get("venue"):
        cit["venue"] = header["venue"]
    return cit


# -------------------------------------------------------------- extraction

def _block(**kw):
    block = dict(SERVICE)
    block.update({
        "state": None,
        "verification": UNVERIFIED_NOTE,
        "endpoint": None,
        "probe": None,
        "header": None,
        "references": [],
        "citation_contexts": [],
        "missing_fields": [],
        "partial": False,
        "stage_failures": [],
        "door": None,
        "failure": None,
        "wall_seconds": None,
    })
    block.update(kw)
    return block


def format_door_block(suffix):
    """The sidecar block for a non-PDF handed to the sidecar:
    GROBID reads PDFs; anything else is a named door, and the
    conversion itself is unaffected (the sidecar is additive)."""
    return _block(
        state="door",
        door={"name": "grobid-format-unsupported",
              "format": suffix,
              "reason": "GROBID extracts bibliographic "
                        "structure from PDF only; "
                        f"{suffix or '(no suffix)'} is not "
                        "a PDF"})


def extract(pdf_path, endpoint=None, env=None, client=None,
            fulltext=True):
    """Run the sidecar over one PDF. Returns the sidecar
    block; never raises for a door/failure — those are
    recorded IN the block. `endpoint`: a URL string, or None
    to resolve from the environment. `client`: an injected
    GrobidClient (tests)."""
    started = time.monotonic()
    p = Path(pdf_path)
    resolved = configured_endpoint(endpoint, env=env)
    if resolved is None and client is None:
        return _block(
            state="door",
            wall_seconds=round(time.monotonic() - started, 3),
            door={"name": "grobid-not-configured",
                  "reason": "no GROBID endpoint is configured "
                            f"({ENV_VAR} is unset and no "
                            "endpoint was passed); GROBID is a "
                            "separate Java service (default "
                            f"port {DEFAULT_PORT}) and the "
                            "sidecar does not start one — the "
                            "Round 10 trial record stands at "
                            "evaluation/grobid-trial-evidence"
                            ".json (no Java runtime on this "
                            "VM)"})
    client = client or GrobidClient(resolved)
    probe_rec = probe(resolved, client=client)
    if not probe_rec["available"]:
        return _block(
            state="failed", endpoint=resolved, probe=probe_rec,
            wall_seconds=round(time.monotonic() - started, 3),
            failure={"name": "grobid-unreachable",
                     "endpoint": resolved,
                     "reason": probe_rec["blocker"]})
    pdf_bytes = p.read_bytes()
    filename = p.name
    block = _block(state="machine-unverified",
                   endpoint=resolved, probe=probe_rec)

    def _service_failure(stage, exc):
        if isinstance(exc, urllib.error.HTTPError):
            reason = (f"HTTP {exc.code} for "
                      f"{resolved}/api/{stage}")
        else:
            reason = f"{type(exc).__name__}: {exc}"
        return {"name": "grobid-service-error",
                "stage": stage, "reason": reason}

    try:
        header_tei = client.process_header(pdf_bytes, filename)
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, OSError) as exc:
        block["state"] = "failed"
        block["failure"] = _service_failure(
            "processHeaderDocument", exc)
        block["wall_seconds"] = round(
            time.monotonic() - started, 3)
        return block
    try:
        header = parse_header_tei(header_tei)
    except GrobidDoor as door:
        block["state"] = "door"
        block["door"] = door.door
        block["wall_seconds"] = round(
            time.monotonic() - started, 3)
        return block
    block["header"] = header
    block["missing_fields"] = header["missing_fields"]
    if header["missing_fields"]:
        block["partial"] = True

    stages = [("processReferences", client.process_references,
               parse_references_tei, "references")]
    if fulltext:
        stages.append(("processFulltextDocument",
                       client.process_fulltext,
                       parse_citation_contexts_tei,
                       "citation_contexts"))
    for stage, call, parse, key in stages:
        try:
            tei = call(pdf_bytes, filename)
            block[key] = parse(tei)
        except GrobidDoor as door:
            block["partial"] = True
            block["stage_failures"].append(door.door)
        except (urllib.error.URLError,
                urllib.error.HTTPError, TimeoutError,
                OSError) as exc:
            block["partial"] = True
            block["stage_failures"].append(
                _service_failure(stage, exc))
    block["wall_seconds"] = round(time.monotonic() - started, 3)
    return block


# -------------------------------------------------------------------- CLI

def main(argv):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser(
        "probe", help="probe the configured GROBID endpoint")
    pp.add_argument("--url", default=None, metavar="URL",
                    help="endpoint base URL (default: the "
                         f"{ENV_VAR} environment variable)")
    pe = sub.add_parser(
        "extract", help="extract the bibliographic sidecar "
                        "for one PDF")
    pe.add_argument("file", help="the scholarly PDF")
    pe.add_argument("--url", default=None, metavar="URL",
                    help="endpoint base URL (default: the "
                         f"{ENV_VAR} environment variable)")
    pe.add_argument("--out", default=None, metavar="PATH",
                    help="write the sidecar block JSON here "
                         "instead of stdout")
    args = ap.parse_args(argv)
    if args.cmd == "probe":
        endpoint = configured_endpoint(args.url)
        if endpoint is None:
            print(json.dumps(
                {"endpoint": None,
                 "available": False,
                 "blocker": f"no GROBID endpoint configured "
                            f"({ENV_VAR} unset, no --url "
                            "passed)"}, indent=2, sort_keys=True))
            return 4
        record = probe(endpoint)
        record["endpoint"] = endpoint
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0 if record["available"] else 4
    block = extract(args.file, endpoint=args.url)
    text = json.dumps(block, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wiki_grobid: sidecar block (state "
              f"{block['state']}) written to {args.out}",
              file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0 if block["state"] == "machine-unverified" else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
