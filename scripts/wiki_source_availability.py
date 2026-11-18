#!/usr/bin/env python3
"""Cited-source availability probe (Marathon R12 lane BA).

Ideas board line 183 (Round 10 RA, Tier A): over the URLs
ALREADY in the citation registers, record HTTP status +
last-checked, flag dead/moved for HUMAN decision, and
change nothing automatically.

THE POPULATION is closed: URLs are collected only from the
citation registers named on the command line (default:
evaluation/citation-lockfile.json, the citation register).
Registers are parsed as JSON/JSONL and every string value
is walked; URLs are extracted from those values exactly as
cited, then cleaned of surrounding prose punctuation. No
URL is invented, guessed, or added from anywhere else, and
`collect` prints the population so it can be eyeballed
against the registers before any probe runs.

THE SIDE REGISTER — evaluation/source-availability.jsonl,
append-only, seeded header-only. A probe run APPENDS one
record per URL: {kind: availability, url, source_registers,
status (int or null), final_url, flag, checked, probe_mode}.
History is never rewritten: a later probe appends new
records; `report` reads the LATEST record per URL.

FLAGS (for a human; the tool acts on none of them):
  ok             2xx/3xx with no redirect away from the URL
  moved          a redirect status, or the fetcher's final
                 URL differs from the cited URL
  dead           404 or 410
  attention      any other status (5xx, 401/403, ...) —
                 a human looks; the tool does not guess
  error          the fetch itself failed (status null)
  not-probeable  the cited string is not a fetchable URL as
                 written (e.g. it carries a {template}
                 placeholder) — recorded, never fetched
A flag never edits a page, a citation, or any register
other than this side register's own appended probe records.

OFFLINE SAFETY: the probe core takes a FETCHER callable —
(url) -> (status, final_url) — and never touches the
network itself. The CLI reaches the network ONLY under an
explicit `probe --live` (urllib, GET, 15s timeout); the
default `probe --fixture FILE` reads recorded responses
{url: {"status": int, "final_url": str}} from a JSON file,
which is how the tests run: fixtures, never the network.
Without --live or --fixture, `probe` refuses (exit 2)
rather than silently doing nothing or going online.

Commands: collect / probe / report / check.
Exit 0 ok · 1 check findings · 2 usage error.
Stdlib only.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "source-availability.jsonl"
DEFAULT_SOURCES = [ROOT / "evaluation" / "citation-lockfile.json"]
URL_RE = re.compile(r"https?://[^\s\"'\)\]<>]+")
FLAGS = ["ok", "moved", "dead", "attention", "error",
         "not-probeable"]


# ------------------------------------------------------------ collection

def _walk_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def clean_url(raw):
    """Strip prose punctuation a cited URL picks up from the
    sentence around it; never alter the URL's own body."""
    u = raw.strip()
    while u and u[-1] in ".,;:!?":
        u = u[:-1]
    if u.endswith(")") and "(" not in u:
        u = u[:-1]
    return u


def collect_urls(source_paths):
    """{url: sorted [register relpaths]} over the named
    citation registers. Raises ValueError on a register
    that cannot be read or parsed."""
    found = {}
    for sp in source_paths:
        p = Path(sp)
        if not p.is_file():
            raise ValueError(f"citation register missing: {p}")
        text = p.read_text(encoding="utf-8", errors="ignore")
        objs = []
        if p.suffix == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    objs.append(json.loads(line))
        else:
            objs.append(json.loads(text))
        try:
            label = p.relative_to(ROOT).as_posix()
        except ValueError:
            label = str(p)
        for obj in objs:
            for s in _walk_strings(obj):
                for m in URL_RE.finditer(s):
                    u = clean_url(m.group(0))
                    if u:
                        found.setdefault(u, set()).add(label)
    return {u: sorted(srcs) for u, srcs in sorted(found.items())}


def probeable(url):
    """A URL is fetchable as written when it parses with an
    http(s) scheme and a host and carries no template
    placeholder."""
    if "{" in url or "}" in url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


# ------------------------------------------------------------ probing

def flag_for(url, status, final_url):
    if not probeable(url):
        return "not-probeable"
    if status is None:
        return "error"
    if status in (404, 410):
        return "dead"
    if status in (301, 302, 303, 307, 308):
        return "moved"
    if final_url and final_url != url:
        return "moved"
    if 200 <= status < 400:
        return "ok"
    return "attention"


def run_probe(urls, fetcher, checked=None, mode="fixture"):
    """One availability record per URL. `fetcher` is the
    ONLY way a status is obtained: (url) -> (status,
    final_url); it may raise, which records flag 'error'
    with the exception named — a failed fetch is a record,
    never a crash and never a silent skip."""
    checked = checked or date.today().isoformat()
    records = []
    for url, srcs in urls.items():
        if not probeable(url):
            status, final, note = None, None, "not fetchable as written"
        else:
            try:
                status, final = fetcher(url)
                note = ""
            except Exception as exc:  # recorded, not hidden
                status, final = None, None
                note = f"fetch error: {type(exc).__name__}: {exc}"
        records.append({
            "kind": "availability",
            "url": url,
            "source_registers": srcs,
            "status": status,
            "final_url": final,
            "flag": flag_for(url, status, final),
            "checked": checked,
            "probe_mode": mode,
            "note": note,
        })
    return records


def fixture_fetcher(path):
    """Fetcher backed by a JSON fixture file:
    {url: {"status": int|null, "final_url": str|null}}.
    A URL absent from the fixture is an error record
    (flag 'error'), never an implicit ok."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    def fetch(url):
        if url not in data:
            raise LookupError(f"no fixture response for {url}")
        entry = data[url] or {}
        return entry.get("status"), entry.get("final_url")
    return fetch


def live_fetcher(url):
    """The ONLY network path in this tool, reached solely
    via `probe --live`. GET with redirects followed by
    urllib; HTTP error statuses are returned, not raised."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "wiki-source-availability/1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.geturl() or url


# ------------------------------------------------------------ side register

def load_register(path=None):
    p = Path(path) if path else REGISTER
    records, errors = [], []
    if not p.is_file():
        return records, [f"register missing: {p}"]
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON ({e})")
            continue
        if obj.get("kind") == "header":
            continue
        if obj.get("kind") != "availability":
            errors.append(f"line {i}: kind must be 'availability'")
            continue
        for f in ("url", "checked", "flag"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        if obj.get("flag") not in FLAGS:
            errors.append(f"line {i}: flag {obj.get('flag')!r} "
                          f"not in {FLAGS}")
        if obj.get("status") is not None and \
                not isinstance(obj.get("status"), int):
            errors.append(f"line {i}: status must be an int or null")
        records.append(obj)
    return records, errors


def latest_by_url(records):
    latest = {}
    for r in records:
        latest[r["url"]] = r
    return latest


def build_report(path=None):
    records, errors = load_register(path)
    latest = latest_by_url(records)
    by_flag = {f: 0 for f in FLAGS}
    flagged = []
    for url, r in sorted(latest.items()):
        if r.get("flag") in by_flag:
            by_flag[r["flag"]] += 1
        if r.get("flag") in ("dead", "moved"):
            flagged.append({"url": url, "flag": r["flag"],
                            "status": r.get("status"),
                            "final_url": r.get("final_url"),
                            "checked": r.get("checked")})
    return {"records": len(records), "urls": len(latest),
            "by_flag": by_flag,
            "flagged_for_human_decision": flagged,
            "errors": errors}


# ------------------------------------------------------------ commands

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cited-source availability probe "
                    "(report-only side register).")
    sub = ap.add_subparsers(dest="command")
    for name in ("collect", "report", "check"):
        p = sub.add_parser(name)
        p.add_argument("--register", default=None)
        if name == "collect":
            p.add_argument("--source", action="append", default=None)
            p.add_argument("--json", action="store_true")
        if name == "report":
            p.add_argument("--json", action="store_true")
    pp = sub.add_parser("probe")
    pp.add_argument("--register", default=None)
    pp.add_argument("--source", action="append", default=None)
    pp.add_argument("--fixture", default=None,
                    help="JSON fixture of recorded responses "
                         "(offline; the test route)")
    pp.add_argument("--live", action="store_true",
                    help="explicitly probe over the network "
                         "with urllib (the only online route)")
    pp.add_argument("--checked", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    sources = [Path(s) for s in args.source] \
        if getattr(args, "source", None) else DEFAULT_SOURCES

    if cmd == "collect":
        try:
            urls = collect_urls(sources)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"source-availability: {e}", file=sys.stderr)
            return 2
        if getattr(args, "json", False):
            print(json.dumps(urls, indent=2, ensure_ascii=False))
        else:
            print(f"source-availability: {len(urls)} cited "
                  f"URL(s) in {len(sources)} citation "
                  f"register(s)")
            for u, srcs in urls.items():
                print(f"  {u}  [{', '.join(srcs)}]")
        return 0

    if cmd == "probe":
        if bool(args.fixture) == bool(args.live):
            print("source-availability: probe requires exactly "
                  "one of --fixture FILE (offline) or --live "
                  "(explicit network); refusing to guess",
                  file=sys.stderr)
            return 2
        try:
            urls = collect_urls(sources)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"source-availability: {e}", file=sys.stderr)
            return 2
        if args.fixture:
            try:
                fetcher = fixture_fetcher(args.fixture)
            except (OSError, json.JSONDecodeError) as e:
                print(f"source-availability: cannot read "
                      f"fixture: {e}", file=sys.stderr)
                return 2
            mode = "fixture"
        else:
            fetcher, mode = live_fetcher, "live"
        records = run_probe(urls, fetcher,
                            checked=args.checked, mode=mode)
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        flagged = [r for r in records
                   if r["flag"] in ("dead", "moved")]
        print(f"source-availability: probed {len(records)} "
              f"URL(s) via {mode}; appended to {p}; "
              f"{len(flagged)} flagged dead/moved for human "
              f"decision (nothing else was changed)")
        for r in flagged:
            print(f"  {r['flag']}: {r['url']} "
                  f"(status {r['status']})")
        return 0

    if cmd == "check":
        _r, errors = load_register(args.register)
        for e in errors:
            print(f"source-availability: {e}", file=sys.stderr)
        print(f"source-availability: register "
              f"{'INVALID' if errors else 'valid'} "
              f"({len(_r)} record(s))")
        return 1 if errors else 0

    rep = build_report(args.register)
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"source-availability: {rep['urls']} URL(s) with "
              f"a latest record ({rep['records']} record(s) "
              f"total)")
        for f in FLAGS:
            print(f"  {f}: {rep['by_flag'][f]}")
        for r in rep["flagged_for_human_decision"]:
            print(f"  FOR HUMAN DECISION {r['flag']}: {r['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
