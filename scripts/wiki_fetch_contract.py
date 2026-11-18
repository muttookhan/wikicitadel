#!/usr/bin/env python3
"""wiki_fetch_contract.py — the Jina Reader fetch contract for
web ingest (Marathon Round 5, lane BA, item 1).

Pattern: jina-ai/reader (Apache-2.0) — a fetched web page comes
back as clean Markdown that carries its provenance with it:
the source URL it was fetched from and the title the page
declared. Re-implemented here in our own code, stdlib only;
no code copied. The pattern is adopted as a CONTRACT, not a
service: nothing here calls Jina, and no fetch is obliged to
pass through any external reader. What the contract fixes is
the shape every web fetch must land in BEFORE compilation, so
a compiled page can always be traced to the exact fetched
record it rests on.

THE CONTRACT. A web fetch record is ONE Markdown file:

    ---
    kind: web-fetch
    source_url: https://example.org/some/page
    fetched_at: 2026-10-21
    title: "The page's own title"
    content_sha256: <sha256 of the body bytes, hex>
    fetch_tool: wiki_fetch_contract.py 1.0
    ---

    <the fetched page as Markdown, title first>

The three provenance fields are REQUIRED and non-empty:

  source_url   the URL the bytes were fetched from. Must be
               an absolute http:// or https:// URL.
  fetched_at   when the fetch happened: an ISO 8601 date
               (YYYY-MM-DD) or datetime. A fetch record with
               no fetch date cannot be judged for staleness,
               so it is not a record.
  title        the page's own title, as fetched — never a
               slug, never an agent-invented summary title.

`content_sha256` binds the record to its body: the hex sha256
of the body exactly as stored (everything after the closing
frontmatter fence, leading blank lines stripped, UTF-8). When
the field is present, `check` recomputes it; a mismatch is a
broken record, the same discipline as the citation lockfile
applied at the fetch door. `kind: web-fetch` marks the file
as a fetch record rather than a compiled page.

Where records live: under `raw/sources/` as a new file, like
every other raw source — immutable once landed; a re-fetch is
a NEW record with its own fetched_at, never an edit of the
old one (the raw layer's standing rule).

The fetcher is INJECTABLE: `fetch_record(url, fetcher,
fetched_at)` takes a callable url -> (title, markdown). Tests
pass a fake fetcher — no live network in tests. The CLI's
default fetcher uses urllib and is the only network path; it
stores the response text as received and lifts the title out
of an HTML <title> element when the response is HTML. Full
HTML-to-Markdown conversion remains the ingest converter's
job (scripts/wiki_convert.py); this tool fixes the record
shape, not the conversion.

Commands:
  new --url U --title T --body-file F [--fetched-at D]
      [--out FILE]     render a record from already-fetched
                       material (no network)
  fetch <url> [--out-dir D] [--fetched-at D]
                       fetch via the default fetcher and land
                       the record (operator-run; the only
                       network path)
  check <file> [...]   validate records against the contract;
                       exit 1 naming every problem

Exit codes: 0 ok, 1 check found problems, 2 usage error.
Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path

TOOL_ID = "wiki_fetch_contract.py 1.0"
RECORD_KIND = "web-fetch"
REQUIRED_FIELDS = ("source_url", "fetched_at", "title")
FIELD_ORDER = ("kind", "source_url", "fetched_at", "title",
               "content_sha256", "fetch_tool")


def _valid_url(url):
    if not isinstance(url, str) or not url.strip():
        return False
    parts = urllib.parse.urlparse(url.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _valid_fetched_at(value):
    if not isinstance(value, str) or not value.strip():
        return False
    v = value.strip()
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        pass
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def body_bytes(body):
    """The canonical body bytes the content hash binds: the
    body with leading blank lines stripped and exactly one
    trailing newline, UTF-8."""
    text = body.replace("\r\n", "\n").lstrip("\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def content_hash(body):
    return hashlib.sha256(body_bytes(body)).hexdigest()


def _fmt_value(value):
    """Render one frontmatter scalar deterministically: bare
    when it is plain-safe, JSON-quoted otherwise, so the
    minimal parser below round-trips it exactly."""
    v = str(value)
    if v and "\n" not in v and ": " not in v \
            and not v.endswith(":") and " #" not in v \
            and v[0] not in "\"'[]{}#&*!|>%@`,":
        return v
    return json.dumps(v, ensure_ascii=False)


def render_fetch_record(source_url, title, body, fetched_at,
                        fetch_tool=TOOL_ID):
    """Render a contract record. Raises ValueError on any
    input that would produce an invalid record — a record
    that cannot be rendered valid is never written."""
    if not _valid_url(source_url):
        raise ValueError(f"source_url is not an absolute "
                         f"http(s) URL: {source_url!r}")
    if not _valid_fetched_at(fetched_at):
        raise ValueError(f"fetched_at is not an ISO date or "
                         f"datetime: {fetched_at!r}")
    if not title or not str(title).strip():
        raise ValueError("title is required and must be non-empty")
    if not body or not body.strip():
        raise ValueError("body is required and must be non-empty")
    canonical_body = body_bytes(body).decode("utf-8")
    fm = {
        "kind": RECORD_KIND,
        "source_url": source_url.strip(),
        "fetched_at": str(fetched_at).strip(),
        "title": str(title).strip(),
        "content_sha256": content_hash(body),
        "fetch_tool": fetch_tool,
    }
    lines = ["---"]
    for key in FIELD_ORDER:
        lines.append(f"{key}: {_fmt_value(fm[key])}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n" + canonical_body


def parse_frontmatter(text):
    """(frontmatter dict, body) for a record. Flat scalars
    only — the contract's fields are all scalars. Returns
    (None, text) when there is no opening fence."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    fm = {}
    for line in text[4:end].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        value = raw.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        fm[key.strip()] = value
    return fm, text[end + 5:]


def validate_fetch_record(text):
    """The contract's checks over one record's text. Returns
    a list of problem strings; an empty list is a valid
    record."""
    problems = []
    fm, body = parse_frontmatter(text.replace("\r\n", "\n"))
    if fm is None:
        return ["no YAML frontmatter block — a fetch record "
                "carries its provenance in frontmatter"]
    if fm.get("kind") != RECORD_KIND:
        problems.append(f"kind is {fm.get('kind')!r}, expected "
                        f"{RECORD_KIND!r}")
    for field in REQUIRED_FIELDS:
        if not fm.get(field) or not str(fm[field]).strip():
            problems.append(f"required field missing or empty: "
                            f"{field}")
    if fm.get("source_url") and not _valid_url(fm["source_url"]):
        problems.append(f"source_url is not an absolute http(s) "
                        f"URL: {fm['source_url']!r}")
    if fm.get("fetched_at") and not _valid_fetched_at(fm["fetched_at"]):
        problems.append(f"fetched_at is not an ISO date or "
                        f"datetime: {fm['fetched_at']!r}")
    if not body.strip():
        problems.append("body is empty — a fetch record holds "
                        "the fetched page as Markdown")
    declared = fm.get("content_sha256")
    if declared:
        actual = content_hash(body)
        if str(declared).strip().lower() != actual:
            problems.append(f"content_sha256 mismatch: frontmatter "
                            f"says {declared}, body hashes to "
                            f"{actual}")
    return problems


def slugify(url):
    s = re.sub(r"^https?://", "", url.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "source"


def fetch_record(url, fetcher, fetched_at, fetch_tool=TOOL_ID):
    """Fetch through the injected fetcher and render the
    record. The fetcher returns (title, markdown)."""
    title, markdown = fetcher(url)
    return render_fetch_record(url, title, markdown, fetched_at,
                               fetch_tool=fetch_tool)


def urllib_fetcher(url):
    """The CLI's default fetcher — the only network path in
    this tool, used only when the operator runs `fetch`."""
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "wiki-fetch-contract"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 — operator-run CLI
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", text,
                  re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    if not title:
        title = url
    return title, text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="render a record from "
                                   "already-fetched material")
    n.add_argument("--url", required=True)
    n.add_argument("--title", required=True)
    n.add_argument("--body-file", required=True)
    n.add_argument("--fetched-at", default=date.today().isoformat())
    n.add_argument("--out", default=None)

    f = sub.add_parser("fetch", help="fetch a URL and land "
                                     "the record")
    f.add_argument("url")
    f.add_argument("--out-dir", default=None)
    f.add_argument("--fetched-at", default=date.today().isoformat())

    c = sub.add_parser("check", help="validate fetch records")
    c.add_argument("files", nargs="+")

    ns = ap.parse_args(argv)
    if ns.cmd == "new":
        body = Path(ns.body_file).read_text(encoding="utf-8")
        try:
            record = render_fetch_record(ns.url, ns.title, body,
                                         ns.fetched_at)
        except ValueError as exc:
            print(f"wiki_fetch_contract: {exc}", file=sys.stderr)
            return 2
        if ns.out:
            Path(ns.out).write_text(record, encoding="utf-8")
            print(ns.out)
        else:
            sys.stdout.write(record)
        return 0
    if ns.cmd == "fetch":
        try:
            record = fetch_record(ns.url, urllib_fetcher,
                                  ns.fetched_at)
        except ValueError as exc:
            print(f"wiki_fetch_contract: {exc}", file=sys.stderr)
            return 2
        out_dir = Path(ns.out_dir) if ns.out_dir else Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{slugify(ns.url)}.md"
        dest.write_text(record, encoding="utf-8")
        print(str(dest))
        return 0
    bad = 0
    for name in ns.files:
        path = Path(name)
        if not path.is_file():
            print(f"{name}: not a file")
            bad += 1
            continue
        problems = validate_fetch_record(
            path.read_text(encoding="utf-8"))
        if problems:
            bad += 1
            for prob in problems:
                print(f"{name}: {prob}")
        else:
            print(f"{name}: OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
