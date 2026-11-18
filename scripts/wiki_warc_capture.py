#!/usr/bin/env python3
"""WARC 1.1 source capture with payload-digest locking
(Marathon R8, Tier A; warcio pattern, Apache-2.0 — PATTERN
only, no dependency: the minimal WARC 1.1 write/read needed
here is implemented in stdlib below).

scripts/wiki_warc.py (Marathon R3) already archives fetched
bytes as WARC 1.0 records with a BLOCK digest. What it does
not give the citation machinery is a PAYLOAD digest: the
hash of the fetched resource itself, in the field a WARC
reader looks for (WARC-Payload-Digest), stated so a checker
can hold it against the hash the citation lockfile locks to
for that source (evaluation/source-manifest.jsonl's per-source
sha256, built by scripts/wiki_cite_lock.py — the lockfile's
own per-source hash record).

This module is that narrower capture:

  write_warc(path, url, payload, content_type, date=...)
      writes a warcinfo record + one response record whose
      content block IS the payload bytes verbatim (no HTTP
      framing), with
        WARC-Payload-Digest: sha256:<sha256 of payload>
        WARC-Block-Digest:   sha256:<sha256 of block>
      (identical here by construction — the block is the
      payload — and both are recomputed on read).
  read_records(path) -> [{headers: {...}, content: bytes}]
      a strict-enough parser: version line, headers, exactly
      Content-Length bytes, CRLF CRLF framing.
  verify(path, locked_hash=None) -> [problems]
      recomputes both digests for every record; when a locked
      hash is given, the response record's payload digest
      must EQUAL it — a mismatch is the finding this exists
      to surface.
  locked_hash_for(source_path, manifest=...) -> sha256 | None
      looks a source's locked hash up in the source manifest.

Usage:
  python3 scripts/wiki_warc_capture.py write --url URL \
      --from-file PAYLOAD --out F.warc [--content-type T]
  python3 scripts/wiki_warc_capture.py verify F.warc \
      [--locked-hash HEX | --source raw/sources/<file>]

NO NETWORK anywhere in this module: the payload arrives as
bytes (the fetching capture step is the caller's, exactly as
wiki_snapshot.py's fetcher is injectable). Exit codes:
verify 0 = digests recompute and any locked hash matches,
1 = a break, 2 = usage error. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "evaluation" / "source-manifest.jsonl"
CRLF = b"\r\n"
SOFTWARE = "wiki_warc_capture.py (Marathon R8; WARC 1.1, stdlib)"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(rectype, content, content_type, uri, date, extra=None):
    headers = [
        ("WARC/1.1", None),
        ("WARC-Type", rectype),
        ("WARC-Record-ID", f"<urn:uuid:{uuid.uuid4()}>"),
        ("WARC-Date", date),
    ]
    if uri:
        headers.append(("WARC-Target-URI", uri))
    headers += [
        ("Content-Type", content_type),
        ("Content-Length", str(len(content))),
        ("WARC-Block-Digest", "sha256:" + sha256_hex(content)),
    ]
    for key, value in (extra or {}).items():
        headers.append((key, value))
    out = b""
    for key, value in headers:
        out += (key if value is None else f"{key}: {value}").encode(
            "utf-8") + CRLF
    return out + CRLF + content + CRLF + CRLF


def write_warc(path, url, payload, content_type="application/octet-stream",
               date=None):
    """Write warcinfo + one response record for `payload`
    (bytes, verbatim). Returns the payload digest (hex)."""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes — the fetched bytes "
                        "themselves, never a re-encoding")
    payload = bytes(payload)
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = sha256_hex(payload)
    info = (f"software: {SOFTWARE}\r\n"
            f"format: WARC File Format 1.1\r\n"
            f"source-uri: {url}\r\n").encode("utf-8")
    warcinfo = _record("warcinfo", info, "application/warc-fields",
                       None, date)
    response = _record(
        "response", payload, content_type, url, date,
        extra={"WARC-Payload-Digest": "sha256:" + digest})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(warcinfo + response)
    return digest


def read_records(path):
    """Parse a WARC file written in this framing into
    [{headers, content}]. Raises ValueError on bad framing."""
    data = Path(path).read_bytes()
    records, pos = [], 0
    while pos < len(data):
        if data[pos:pos + 2] == CRLF:
            pos += 2
            continue
        head_end = data.find(CRLF + CRLF, pos)
        if head_end < 0:
            raise ValueError(f"unterminated header block at {pos}")
        lines = data[pos:head_end].decode("utf-8").split("\r\n")
        if not lines[0].startswith("WARC/"):
            raise ValueError(f"record at {pos} does not start WARC/: "
                             f"{lines[0]!r}")
        headers = {"_version": lines[0]}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            headers[key.strip()] = value.strip()
        length = int(headers["Content-Length"])
        start = head_end + 4
        content = data[start:start + length]
        if len(content) != length:
            raise ValueError("content block shorter than Content-Length")
        records.append({"headers": headers, "content": content})
        pos = start + length
        if data[pos:pos + 4] == CRLF + CRLF:
            pos += 4
    return records


def verify(path, locked_hash=None):
    problems = []
    try:
        records = read_records(path)
    except (ValueError, KeyError) as exc:
        return [f"unparseable WARC: {exc}"]
    if not records:
        return ["no records in file"]
    responses = [r for r in records
                 if r["headers"].get("WARC-Type") == "response"]
    if not responses:
        problems.append("no response record")
    for rec in records:
        headers = rec["headers"]
        block = headers.get("WARC-Block-Digest", "")
        if block != "sha256:" + sha256_hex(rec["content"]):
            problems.append(
                f"{headers.get('WARC-Type')}: block digest mismatch")
        payload_digest = headers.get("WARC-Payload-Digest")
        if headers.get("WARC-Type") == "response":
            if not payload_digest:
                problems.append("response record carries no "
                                "WARC-Payload-Digest")
            elif payload_digest != "sha256:" + sha256_hex(rec["content"]):
                problems.append("response payload digest does not "
                                "recompute from the payload bytes")
            elif locked_hash is not None and \
                    payload_digest != "sha256:" + locked_hash.lower():
                problems.append(
                    f"payload digest {payload_digest} != locked hash "
                    f"sha256:{locked_hash.lower()} — the archived "
                    f"payload is not the bytes the lockfile locks to")
    return problems


def locked_hash_for(source_path, manifest=MANIFEST):
    """The sha256 scripts/wiki_cite_lock.py locked for a source,
    from evaluation/source-manifest.jsonl (None if unregistered)."""
    if not Path(manifest).exists():
        return None
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("path") == source_path:
            return row.get("sha256")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--url", required=True)
    w.add_argument("--from-file", required=True,
                   help="file holding the fetched payload bytes")
    w.add_argument("--out", required=True)
    w.add_argument("--content-type", default="application/octet-stream")
    v = sub.add_parser("verify")
    v.add_argument("warc")
    v.add_argument("--locked-hash", default=None)
    v.add_argument("--source", default=None,
                   help="repo-relative source path; its locked hash "
                        "is read from the source manifest")
    args = ap.parse_args(argv)
    if args.cmd == "write":
        payload = Path(args.from_file).read_bytes()
        digest = write_warc(args.out, args.url, payload, args.content_type)
        print(json.dumps({"warc": args.out, "url": args.url,
                          "payload_digest": "sha256:" + digest,
                          "payload_sha256": digest}, indent=2))
        return 0
    locked = args.locked_hash
    if args.source:
        locked = locked_hash_for(args.source)
        if locked is None:
            print(f"source not in the lock manifest: {args.source}",
                  file=sys.stderr)
            return 2
    problems = verify(args.warc, locked_hash=locked)
    print(json.dumps({"warc": args.warc, "locked_hash": locked,
                      "ok": not problems, "problems": problems},
                     indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
