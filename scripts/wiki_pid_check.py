#!/usr/bin/env python3
"""Persistent-identifier validation at citation ingest (idutils).

Marathon R8 lane BB (ideas board R6 research, Tier A): pattern of
idutils (Revised BSD) - validate / normalise / scheme-detect
persistent identifiers (DOI, ARK, ORCID, Handle, URN) before
they enter the citation lockfile. Implemented in stdlib only; no
new dependency, no idutils code copied.

Wiring (least invasive): this is a STANDALONE checker at the
ingest boundary. Nothing in the ingest or lockfile build path
imports it yet, because the current lockfile records carry no PID
fields at all (verified: ``scan`` over
evaluation/citation-lockfile.json finds the PID-shaped strings
actually present, today only inside source paths/URLs if any).
The checker is ready to gate the moment a citation record gains
an identifier field; until then it validates identifiers handed
to it directly and audits the lockfile read-only. It never
writes to the lockfile.

Usage:
  python3 scripts/wiki_pid_check.py IDENTIFIER [IDENTIFIER ...]
  python3 scripts/wiki_pid_check.py --file RECORDS.jsonl
  python3 scripts/wiki_pid_check.py scan [--lockfile FILE]
Exit: 0 = every checked identifier valid (or scan completed);
1 = at least one invalid; 2 = usage error. Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCKFILE = ROOT / "evaluation" / "citation-lockfile.json"

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
_ARK_RE = re.compile(r"^ark:/?\d{5,}/.+$")
_URN_RE = re.compile(r"^urn:([a-z0-9][a-z0-9-]{0,31}):(.+)$", re.I)
_HANDLE_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/\S+$")


def _orcid_checksum_ok(orcid):
    digits = orcid.replace("-", "")
    total = 0
    for ch in digits[:15]:
        total = (total + int(ch)) * 2
    check = (12 - (total % 11)) % 11
    want = "X" if check == 10 else str(check)
    return digits[15].upper() == want


def detect_and_normalise(raw):
    """Return {input, scheme, normalised, valid, errors}."""
    s = (raw or "").strip()
    out = {"input": raw, "scheme": None, "normalised": None,
           "valid": False, "errors": []}
    if not s:
        out["errors"].append("empty identifier")
        return out
    low = s.lower()
    # ORCID (bare, hyphenated, or iD URL form)
    cand = re.sub(r"^https?://orcid\.org/", "", low)
    if _ORCID_RE.match(cand.upper()) and "-" in cand:
        out["scheme"] = "orcid"
        out["normalised"] = cand.upper()
        if _orcid_checksum_ok(cand.upper()):
            out["valid"] = True
        else:
            out["errors"].append("ORCID checksum digit mismatch")
        return out
    # DOI (bare, doi: prefix, or doi.org URL)
    cand = re.sub(r"^https?://(dx\.)?doi\.org/", "", s)
    cand = re.sub(r"^doi:", "", cand, flags=re.I)
    if _DOI_RE.match(cand):
        out.update(scheme="doi", normalised="doi:" + cand,
                   valid=True)
        return out
    if low.startswith("doi:") or "doi.org/" in low:
        out.update(scheme="doi",
                   errors=["malformed DOI: expected 10.<registrant>"
                           "/<suffix>"])
        return out
    # ARK
    if low.startswith("ark:"):
        if _ARK_RE.match(low):
            name = low[4:].lstrip("/")
            out.update(scheme="ark", normalised="ark:/" + name,
                       valid=True)
        else:
            out.update(scheme="ark", errors=[
                "malformed ARK: expected ark:/<NAAN>/<name>"])
        return out
    # URN
    m = _URN_RE.match(s)
    if low.startswith("urn:"):
        if m:
            out.update(scheme="urn",
                       normalised="urn:" + m.group(1).lower()
                                    + ":" + m.group(2), valid=True)
        else:
            out.update(scheme="urn", errors=[
                "malformed URN: expected urn:<nid>:<nss>"])
        return out
    # Handle (hdl: prefix, handle.net URL, or bare prefix/suffix)
    cand = re.sub(r"^https?://hdl\.handle\.net/", "", s)
    cand = re.sub(r"^hdl:", "", cand, flags=re.I)
    if low.startswith("hdl:") or "hdl.handle.net/" in low:
        if _HANDLE_RE.match(cand) and not _DOI_RE.match(cand):
            out.update(scheme="handle", normalised="hdl:" + cand,
                       valid=True)
        else:
            out.update(scheme="handle", errors=[
                "malformed Handle: expected <prefix>/<suffix>"])
        return out
    out["errors"].append(
        "no known persistent-identifier scheme detected "
        "(DOI, ARK, ORCID, Handle, URN)")
    return out


def check_records(records, fields=("doi", "identifier", "pid",
                                   "ark", "orcid", "handle",
                                   "urn")):
    """Validate identifier fields of citation/ingest records."""
    results = []
    for rec in records:
        for field in fields:
            if field in rec and rec[field] is not None:
                r = detect_and_normalise(str(rec[field]))
                r["record_id"] = rec.get("id")
                r["field"] = field
                results.append(r)
    return results


def scan_lockfile(path=None):
    """Read-only audit: PID-shaped strings anywhere in the
    lockfile text, each validated. Never writes."""
    p = Path(path) if path else DEFAULT_LOCKFILE
    text = p.read_text(encoding="utf-8")
    found = set(re.findall(
        r"(?:doi:|https?://(?:dx\.)?doi\.org/|ark:/|urn:|"
        r"https?://orcid\.org/)\S+", text))
    bare_dois = set(re.findall(r"\b10\.\d{4,9}/[^\s\"',\]]+", text))
    results = [detect_and_normalise(x) for x in
               sorted(found | bare_dois)]
    return {"lockfile": str(p), "identifiers_found": len(results),
            "results": results,
            "note": "read-only scan; the lockfile was not modified"}


def main(argv):
    ap = argparse.ArgumentParser(
        description="Persistent-identifier checker (idutils "
                    "pattern).")
    ap.add_argument("identifiers", nargs="*")
    ap.add_argument("--file", default=None,
                    help="JSONL records with identifier fields")
    ap.add_argument("--lockfile", default=None)
    args = ap.parse_args(argv[1:])
    if args.identifiers and args.identifiers[0] == "scan":
        report = scan_lockfile(args.lockfile)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if all(r["valid"] for r in report["results"]) \
            else 1
    results = [detect_and_normalise(x) for x in args.identifiers]
    if args.file:
        records = [json.loads(l) for l in
                   Path(args.file).read_text(
                       encoding="utf-8").splitlines() if l.strip()]
        results += check_records(records)
    if not results:
        print("pid-check: nothing to check", file=sys.stderr)
        return 2
    for r in results:
        state = "VALID" if r["valid"] else "INVALID"
        print(f"  [{state}] {r['input']!r} scheme={r['scheme']} "
              f"normalised={r['normalised']!r} "
              f"{'; '.join(r['errors'])}")
    return 0 if all(r["valid"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
