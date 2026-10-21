#!/usr/bin/env python3
"""WARC-archived web ingests (Marathon R3, Tier B row
TB3-5; Gnosis pattern).

Pattern: Gnosis / gnosis-markdown (MIT, via the 2026-10-19
survey) — web ingests preserved as WARC records, so the
fetched bytes themselves are archived beside the converted
markdown, with a byte-level SHA-256 provenance digest.
Re-implemented from the idea with a stdlib WARC 1.0 writer;
no code copied.

A .warc file written here holds, in order:
  1. a warcinfo record (software, format, the ingest's own
     metadata: source URL, fetch date, converter identity);
  2. one response record per fetched resource, carrying the
     fetched bytes verbatim as an application/http-style
     block: a minimal status line + the payload, framed by
     WARC headers (WARC-Record-ID, WARC-Date, WARC-Target-URI,
     Content-Type, Content-Length, WARC-Block-Digest sha256).

Records are framed exactly: header block, CRLF CRLF,
content block, CRLF CRLF. `verify` re-parses the file and
recomputes every block digest — a single altered byte
fails it.

THE FETCHER IS INJECTABLE: archive() takes a fetcher
callable(url) -> (bytes, content_type). The CLI's default
fetcher uses urllib, and only when invoked with a URL;
`from-file` archives already-preserved clip bytes with no
network at all. Tests inject a fixture fetcher — no live
network anywhere in the suite.

Usage:
  python3 scripts/wiki_warc.py archive --url URL --out F.warc
  python3 scripts/wiki_warc.py from-file PRESERVED [--url URL] --out F.warc
  python3 scripts/wiki_warc.py verify F.warc
  python3 scripts/wiki_warc.py show F.warc

Exit codes: verify 0 = all digests recompute, 1 = a break,
2 = usage error. Stdlib only.
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
CRLF = b"\r\n"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(rectype: str, content: bytes, content_type: str,
            uri: str | None, extra: dict | None = None) -> bytes:
    headers = [
        ("WARC/1.0", None),
        ("WARC-Type", rectype),
        ("WARC-Record-ID", f"<urn:uuid:{uuid.uuid4()}>"),
        ("WARC-Date", utcnow()),
    ]
    if uri:
        headers.append(("WARC-Target-URI", uri))
    headers += [
        ("Content-Type", content_type),
        ("Content-Length", str(len(content))),
        ("WARC-Block-Digest",
         "sha256:" + hashlib.sha256(content).hexdigest()),
    ]
    for k, v in (extra or {}).items():
        headers.append((k, v))
    out = b""
    for k, v in headers:
        out += (k if v is None else f"{k}: {v}").encode("utf-8") + CRLF
    return out + CRLF + content + CRLF + CRLF


def write_warc(out_path: Path, url: str, payload: bytes,
               content_type: str = "text/html",
               metadata: dict | None = None) -> Path:
    """Write warcinfo + one response record for `payload`."""
    info = {
        "software": "wiki_warc.py (llm-wiki, stdlib WARC 1.0 writer)",
        "format": "WARC File Format 1.0",
        "source-url": url,
        "payload-sha256": hashlib.sha256(payload).hexdigest(),
    }
    info.update(metadata or {})
    warcinfo = _record(
        "warcinfo",
        ("\r\n".join(f"{k}: {v}" for k, v in info.items())
         ).encode("utf-8"),
        "application/warc-fields", None)
    http_block = (f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n"
                  f"Content-Length: {len(payload)}\r\n\r\n"
                  ).encode("utf-8") + payload
    response = _record("response", http_block, "application/http", url)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(warcinfo + response)
    return out_path


def archive(url: str, out_path: Path, fetcher, metadata=None) -> Path:
    """fetcher(url) -> (payload_bytes, content_type)."""
    payload, ctype = fetcher(url)
    return write_warc(out_path, url, payload, ctype, metadata)


def parse_warc(path: Path):
    """Parse records: [{headers: dict, content: bytes}]."""
    data = path.read_bytes()
    records, pos = [], 0
    while pos < len(data):
        sep = data.find(b"\r\n\r\n", pos)
        if sep < 0:
            break
        head = data[pos:sep].decode("utf-8", "replace")
        headers = {}
        lines = head.split("\r\n")
        headers["_version"] = lines[0]
        for ln in lines[1:]:
            if ": " in ln:
                k, v = ln.split(": ", 1)
                headers[k] = v
        length = int(headers.get("Content-Length", "0"))
        start = sep + 4
        content = data[start:start + length]
        records.append({"headers": headers, "content": content})
        pos = start + length + 4  # trailing CRLF CRLF
    return records


def verify(path: Path):
    """(ok, problems) — every block digest recomputes and
    every Content-Length matches its framed block."""
    problems = []
    records = parse_warc(path)
    if not records:
        return False, ["no records parsed"]
    for i, rec in enumerate(records):
        digest = "sha256:" + hashlib.sha256(rec["content"]).hexdigest()
        if rec["headers"].get("WARC-Block-Digest") != digest:
            problems.append(f"record {i}: block digest mismatch")
        if len(rec["content"]) != int(
                rec["headers"].get("Content-Length", "-1")):
            problems.append(f"record {i}: content length mismatch")
    return not problems, problems


def default_fetcher(url: str):
    """The live seam — urllib, used only by an explicit CLI
    archive of a URL. Never used by tests."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent":
                                                "llm-wiki-warc/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), resp.headers.get_content_type()


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("archive", help="fetch (injectable seam) + archive")
    pa.add_argument("--url", required=True)
    pa.add_argument("--out", required=True)
    pf = sub.add_parser("from-file",
                        help="archive preserved bytes (no network)")
    pf.add_argument("file")
    pf.add_argument("--url", default="")
    pf.add_argument("--out", required=True)
    pv = sub.add_parser("verify", help="recompute all block digests")
    pv.add_argument("file")
    ps = sub.add_parser("show", help="list records + digests")
    ps.add_argument("file")
    args = ap.parse_args(argv)
    if args.cmd == "archive":
        archive(args.url, Path(args.out), default_fetcher)
        print(f"wrote {args.out}")
        return 0
    if args.cmd == "from-file":
        payload = Path(args.file).read_bytes()
        write_warc(Path(args.out), args.url or args.file, payload,
                   "application/octet-stream",
                   {"preserved-from": args.file})
        print(f"wrote {args.out}")
        return 0
    if args.cmd == "verify":
        ok, problems = verify(Path(args.file))
        print(json.dumps({"file": args.file, "ok": ok,
                          "problems": problems}, indent=2))
        return 0 if ok else 1
    records = parse_warc(Path(args.file))
    print(json.dumps([{"type": r["headers"].get("WARC-Type"),
                       "uri": r["headers"].get("WARC-Target-URI"),
                       "digest": r["headers"].get("WARC-Block-Digest"),
                       "length": len(r["content"])}
                      for r in records], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
