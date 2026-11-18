#!/usr/bin/env python3
"""Fabricated-citation detection at ingest + citation-change events.

Build item W1.6 (owner directive 2026-10-22). The citation
lockfile (scripts/wiki_cite_lock.py) verifies citations that
were locked at build time: it catches DRIFT — a source that
changed under a citation that once was real. It cannot catch
FABRICATION: a citation that never was real — invented at
ingest with a locator, a quote or a source that cannot exist
as cited — because build simply locks whatever it finds,
including a marker pointing at lines that do not exist. This
script is the ingest-side pass that closes that gap. It is
REPORT-ONLY: it flags and records; it never rejects a source,
never edits a page, and always exits 0 on a completed run.

Detection (subcommand `scan`, whole corpus; `ingest-check`,
one freshly ingested source):

  A citation is examined only when the lockfile cannot vouch
  for it. A marker whose lockfile entry verifies OK today
  (wiki_cite_lock.verify_citation) is LOCKFILE-VERIFIED and is
  never flagged — the corpus is the ground truth for that bar,
  and the test suite enforces it. Every other marker (not yet
  locked — the normal state of a citation written during an
  ingest — or locked but no longer verifying) is checked for
  the ways a citation can be impossible as cited:

    malformed-marker     a ^[cite: ...] span that does not
                         match the strict marker grammar (no
                         parseable locator at all). Scanned on
                         claim-bearing pages only: the
                         structural catalog/log pages are
                         exempt (the wiki_validate convention —
                         a log entry discussing the ^[cite:]
                         notation is prose, not a citation);
    locator-escapes-repo the cited path leaves the repo
                         (a .. component or an absolute path);
    source-missing       the cited file is not on disk;
    locator-out-of-range the line range cannot exist in the
                         source (start < 1, end < start, or
                         end beyond the file's line count);
    vacuous-range        the cited range exists but holds no
                         text at all — the locator points at
                         blank lines only, so nothing cited
                         can rest on it;
    quote-not-in-range   a direct quotation carrying this
                         marker (same or adjacent line, the
                         wiki_cite_lock quote lane's pairing)
                         whose text does not appear in the
                         cited range — a quote that cannot
                         exist as cited. Checked with
                         wiki_cite_lock.verify_quote, so the
                         divergence names the exact point.

  Pattern: the GhostCite research find (Round 8 candidates) —
  fabricated-citation detection as a deterministic existence
  check over locator / quote / source — IDEA ONLY, clean
  re-implementation on top of this wiki's own citation
  machinery; no code or text taken from any studied project.
  Marker scanning, verification, quote pairing and converter
  identity are reused in-process from scripts/wiki_cite_lock.py
  and scripts/wiki_validate.py, the house reuse pattern.

Citation-change events (subcommand `events`):

  Given two revisions of the corpus — two git refs, or two
  directory roots with the wiki layout — compute the
  deterministic change set of the citation graph between them,
  keyed by (page, claim hash):

    citation-added            a claim citation only in head;
    citation-removed          a claim citation only in base;
    citation-moved            same claim + source, the range
                              changed (content_changed says
                              whether the cited block's bytes
                              also differ — a pure move does
                              not change what the claim rests
                              on, a move-plus-edit does);
    citation-retargeted       same claim, a different source;
    citation-content-changed  same claim + source + range, but
                              the cited block's content hash
                              differs — the source was edited
                              under a stable locator.

  Every event carries SOURCE LINEAGE: the cited source's
  sha256 and line count at base and at head (for a retarget,
  both sources), so the citation machinery downstream gets
  evidence features, not bare assertions: which source bytes
  each side of the change rested on. Events are written as
  JSONL, sorted deterministically; identical revisions yield
  zero events.

Ingest sidecar flow: a conversion lands as raw text plus an
ingest sidecar (<source>.ingest.json, written by
scripts/wiki_convert.py) naming the original file, its sha256
and the converter identity. `ingest-check --source <rel>`
runs the detection over exactly the citations pointing into
that source and records the sidecar's converter/extraction
state in the report's lineage block. Suppression (above) is
stricter here: a locked citation over the source is vouchsafed
only when its lockfile entry verifies AND the source manifest
row verifies — i.e. the source bytes are the very bytes the
lock was taken over. A re-conversion that changed the bytes
re-opens every citation over it to the existence checks.

Nightly sweep hook (documentation only — wiring is the
coordinator's call, this script edits no schedule):

  python3 scripts/wiki_ghostcite.py scan
      rewrites evaluation/ghostcite-report.json
  python3 scripts/wiki_ghostcite.py events --base <ref> \
      --head <ref> --out evaluation/ghostcite-events.jsonl

Exit codes: 0 on any completed run (flags are data in the
report, never a gate verdict); 2 on usage error (bad ref,
missing lockfile where one is required, unreadable input).
Stdlib only. Deterministic ordering everywhere.
"""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SCRIPTS = ROOT / "scripts"
REPORT_PATH = ROOT / "evaluation" / "ghostcite-report.json"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cite_lock = _load("wiki_cite_lock")
validate = _load("wiki_validate")

CITE_RE = cite_lock.CITE_RE
CITE_LOOSE_RE = cite_lock.CITE_LOOSE_RE


def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


# -- Lockfile vouching ---------------------------------------------------------

def _verified_keys():
    """Marker keys (page, source, start, end) whose lockfile
    entry verifies OK against the current tree — plus the
    lockfile itself (None when absent). A citation the lockfile
    verifies is ground truth: the detector never flags it."""
    lockfile, _rows = cite_lock._load_lockfile()
    if lockfile is None:
        return None, set()
    ok = set()
    for entry in lockfile.get("citations", []):
        status, _detail = cite_lock.verify_citation(entry)
        if status == "OK":
            ok.add((entry["page"], entry["source"],
                    entry["range"][0], entry["range"][1]))
    return lockfile, ok


def _manifest_status():
    """Per-source manifest verdicts (OK / CHANGED / MISSING),
    or {} when there is no manifest."""
    _lockfile, rows = cite_lock._load_lockfile()
    if not rows:
        return {}
    return cite_lock.verify_manifest(rows)


# -- Source lineage ------------------------------------------------------------

def source_lineage(source_rel):
    """Evidence features for one cited source as it stands now:
    existence, bytes, line count, converter identity from the
    ingest-sidecar record, and the sidecar's extraction state
    where one exists. Nothing is guessed: a field the record
    cannot support is None / unknown-legacy, per the lockfile's
    own convention."""
    path = ROOT / source_rel
    lineage = {
        "source": source_rel,
        "exists": path.is_file(),
        "sha256": None,
        "size": None,
        "lines": None,
        "converter": cite_lock.converter_identity_for(source_rel),
        "extraction": None,
    }
    if path.is_file():
        lineage["sha256"] = cite_lock._file_sha256(path)
        lineage["size"] = path.stat().st_size
        lines = cite_lock._read_lines(source_rel)
        lineage["lines"] = len(lines) if lines is not None else None
    sidecar = ROOT / (source_rel + ".ingest.json")
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = None
        if isinstance(data, dict):
            lineage["extraction"] = data.get("extraction")
    return lineage


# -- Malformed markers -----------------------------------------------------------

def scan_malformed():
    """^[cite: ...] spans that fail the strict marker grammar.
    Fenced code and frontmatter are skipped, inline code spans
    are stripped — a marker quoted as syntax is not a claim
    (the wiki_validate convention) — and the structural pages
    (wiki/index.md, wiki/log.md) are exempt entirely: they are
    catalog/log, not claim-bearing pages. Returns dicts: page,
    page_line, raw (the marker text as written)."""
    out = []
    fm_re = cite_lock.observe.FM_RE
    for path in sorted(WIKI.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in validate.STRUCTURAL:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        m = fm_re.match(text)
        body = text[m.end():] if m else text
        offset = text[:m.end()].count("\n") if m else 0
        in_fence = False
        for i, line in enumerate(body.split("\n"), start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            stripped = validate.CODESPAN_RE.sub("", line)
            for lm in CITE_LOOSE_RE.finditer(stripped):
                if CITE_RE.fullmatch(lm.group(0)) is None:
                    out.append({"page": rel,
                                "page_line": offset + i,
                                "raw": lm.group(0)})
    out.sort(key=lambda d: (d["page"], d["page_line"], d["raw"]))
    return out


def _escapes_repo(source_rel):
    parts = Path(source_rel).parts
    return source_rel.startswith("/") or ".." in parts


# -- Detection -------------------------------------------------------------------

def detect(citations, quotes, verified, only_source=None,
           manifest=None):
    """Run the fabrication checks. `citations` from
    cite_lock.scan_citations(); `quotes` from
    cite_lock.find_checkable_quotes(); `verified` the set of
    lockfile-vouched marker keys. Returns (flags, stats):
    flags are per-citation records with a `kinds` list;
    stats classify every examined citation.

    Suppression is absolute: a key in `verified` is counted
    and skipped before any check runs. In ingest-check mode
    (only_source set, manifest given) the caller pre-filters
    `verified` so a locked citation over a changed source is
    NOT in the set — see cmd_ingest_check."""
    stats = {"examined": 0, "lockfile_verified": 0,
             "clean": 0, "flagged": 0,
             "quotes_checked": 0, "quotes_diverged": 0}
    quotes_by_key = {}
    for q in quotes:
        key = (q["page"], q["source"], q["start"], q["end"])
        if only_source is not None and q["source"] != only_source:
            continue
        quotes_by_key.setdefault(key, []).append(q)

    flag_records = {}
    line_cache = {}

    def lines_of(source_rel):
        if source_rel not in line_cache:
            line_cache[source_rel] = cite_lock._read_lines(source_rel)
        return line_cache[source_rel]

    def add_flag(c, kind, detail):
        key = (c["page"], c["page_line"], c["source"],
               c["start"], c["end"])
        rec = flag_records.get(key)
        if rec is None:
            rec = {"page": c["page"], "page_line": c["page_line"],
                   "source": c["source"], "start": c["start"],
                   "end": c["end"], "claim": c["claim"],
                   "kinds": []}
            flag_records[key] = rec
        rec["kinds"].append({"kind": kind, "detail": detail})

    for c in citations:
        if only_source is not None and c["source"] != only_source:
            continue
        stats["examined"] += 1
        key = (c["page"], c["source"], c["start"], c["end"])
        if key in verified:
            stats["lockfile_verified"] += 1
            continue
        src, start, end = c["source"], c["start"], c["end"]
        fkey = (c["page"], c["page_line"], src, start, end)
        rec_before = flag_records.get(fkey)
        kinds_before = (len(rec_before["kinds"])
                        if rec_before else 0)
        if _escapes_repo(src):
            add_flag(c, "locator-escapes-repo",
                     f"cited path {src} escapes the repo")
        else:
            lines = lines_of(src)
            if lines is None:
                add_flag(c, "source-missing",
                         f"cited file {src} is not on disk")
            elif start < 1 or end < start or end > len(lines):
                add_flag(c, "locator-out-of-range",
                         f"line range L{start}-L{end} cannot exist"
                         f" in {src} (1-{len(lines)})")
            else:
                block = lines[start - 1:end]
                if not cite_lock.normalize_text("\n".join(block)):
                    add_flag(c, "vacuous-range",
                             f"cited range {src}#L{start}-L{end}"
                             " holds no text — the locator"
                             " points at blank lines only")
        for q in quotes_by_key.get(key, []):
            stats["quotes_checked"] += 1
            ok, divergence = cite_lock.verify_quote(
                q["quote"], src, start, end)
            if not ok:
                stats["quotes_diverged"] += 1
                add_flag(c, "quote-not-in-range",
                         f"quotation on page line {q['page_line']}"
                         f" cannot exist as cited: {divergence}")
        rec_after = flag_records.get(fkey)
        if rec_after is None or len(rec_after["kinds"]) == kinds_before:
            stats["clean"] += 1

    flags = [flag_records[k] for k in sorted(flag_records)]
    stats["flagged"] = len(flags)
    lineage = {}
    for rec in flags:
        src = rec["source"]
        if src not in lineage:
            lineage[src] = source_lineage(src)
        rec["lineage"] = lineage[src]
    return flags, stats


def build_report(scope, flags, stats, malformed, extra=None):
    report = {
        "tool": "wiki_ghostcite fabricated-citation detection",
        "generated": date.today().isoformat(),
        "scope": scope,
        "report_only": True,
        "note": "Flags are findings for a human/agent to "
                "re-verify, never a rejection: a flagged "
                "citation is one whose locator, quote or "
                "source cannot exist as cited. Citations the "
                "citation lockfile verifies are never flagged. "
                "Pattern: GhostCite fabricated-citation "
                "detection (idea only) — re-implemented over "
                "wiki_cite_lock / wiki_validate.",
        "coverage": stats,
        "malformed_markers": malformed,
        "flags": flags,
    }
    if extra:
        report.update(extra)
    return report


def _print_summary(report):
    cov = report["coverage"]
    print(f"scope: {report['scope']}")
    print(f"citations examined: {cov['examined']}"
          f" (lockfile-verified {cov['lockfile_verified']},"
          f" clean {cov['clean']}, flagged {cov['flagged']})")
    print(f"quotations checked: {cov['quotes_checked']}"
          f" (diverged {cov['quotes_diverged']})")
    print(f"malformed markers: {len(report['malformed_markers'])}")
    for rec in report["flags"]:
        kinds = ", ".join(k["kind"] for k in rec["kinds"])
        print(f"  [FLAG] {rec['page']}:{rec['page_line']} ->"
              f" {rec['source']}#L{rec['start']}-L{rec['end']}"
              f" ({kinds})")
    for mm in report["malformed_markers"]:
        print(f"  [MALFORMED] {mm['page']}:{mm['page_line']}"
              f" {mm['raw']}")


def cmd_scan(args):
    lockfile, verified = _verified_keys()
    if lockfile is None and not args.no_lockfile_ok:
        print("no lockfile at evaluation/citation-lockfile.json"
              " — the vouching baseline is required (run"
              " `wiki_cite_lock.py build` first), or pass"
              " --no-lockfile-ok to scan unvouched")
        return 2
    citations = cite_lock.scan_citations()
    quotes = cite_lock.find_checkable_quotes()
    flags, stats = detect(citations, quotes, verified)
    malformed = scan_malformed()
    report = build_report("corpus", flags, stats, malformed)
    if not args.no_write:
        out = Path(args.out) if args.out else REPORT_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2,
                                  ensure_ascii=False) + "\n",
                       encoding="utf-8")
        print(f"wrote {out}")
    _print_summary(report)
    return 0


def cmd_ingest_check(args):
    source = Path(args.source).as_posix()
    if _escapes_repo(source):
        print(f"source {source} escapes the repo")
        return 2
    _lockfile, verified = _verified_keys()
    manifest = _manifest_status()
    # Over a freshly ingested source a locked citation is only
    # vouchsafed while the source bytes are the locked bytes:
    # if the manifest does not verify this source OK, drop its
    # keys from the verified set so every citation over it is
    # re-checked against the bytes as they now stand.
    status = manifest.get(source, ("UNRECORDED", ""))[0]
    if status != "OK":
        verified = {k for k in verified if k[1] != source}
    citations = [c for c in cite_lock.scan_citations()
                 if c["source"] == source]
    quotes = cite_lock.find_checkable_quotes()
    flags, stats = detect(citations, quotes, verified,
                          only_source=source, manifest=manifest)
    malformed = [m for m in scan_malformed()
                 if source in m["raw"]]
    lineage = source_lineage(source)
    extra = {"source_lineage": lineage,
             "manifest_status_for_source": status}
    report = build_report(f"ingest-check {source}", flags, stats,
                          malformed, extra=extra)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    _print_summary(report)
    return 0


# -- Revision-pair citation-change events --------------------------------------
#
# A snapshot is the citation state of one revision of the
# corpus, computed from page TEXT (never from the working
# tree's lockfile): the citations on every wiki page, and for
# every cited source its sha256 / line count (the lineage) and
# each citation's cited-block content hash. Two snapshots diff
# into deterministic events keyed by (page, claim hash).

def _scan_texts(pages):
    """scan_citations() over in-memory page texts: {rel: text}
    -> citation dicts in cite_lock.scan_citations() shape."""
    out = []
    observe = cite_lock.observe
    for rel in sorted(pages):
        text = pages[rel]
        for _pstart, para in observe.body_paragraphs(text):
            joined_parts, line_at = [], []
            pos = 0
            for line_no, line_text in para:
                line_at.append((pos, line_no))
                joined_parts.append(line_text.strip())
                pos += len(line_text.strip()) + 1
            joined = " ".join(joined_parts)
            for m in CITE_RE.finditer(joined):
                line_no = max(no for at, no in line_at
                              if at <= m.start())
                sentence = observe.sentence_around(
                    joined, m.start(), m.end())
                claim = observe.clean_text(
                    CITE_LOOSE_RE.sub("", sentence))
                if not claim:
                    claim = observe.clean_text(
                        CITE_LOOSE_RE.sub("", joined))
                start = int(m.group(2))
                end = int(m.group(3)) if m.group(3) else start
                out.append({
                    "page": rel,
                    "page_line": line_no,
                    "source": Path(m.group(1)).as_posix(),
                    "start": start,
                    "end": end,
                    "claim": claim,
                })
    out.sort(key=lambda c: (c["page"], c["page_line"], c["source"],
                            c["start"], c["end"]))
    return out


def _snapshot(citations, source_bytes):
    """Assemble a snapshot. source_bytes: {rel: bytes | None}
    for every cited source; None = not present at this
    revision."""
    sources = {}
    for rel, data in source_bytes.items():
        if data is None:
            sources[rel] = {"sha256": None, "lines": None}
        else:
            sources[rel] = {
                "sha256": _sha_bytes(data),
                "lines": len(data.decode("utf-8", errors="ignore")
                             .splitlines()),
            }
    enriched = []
    for c in citations:
        data = source_bytes.get(c["source"])
        block_hash = None
        if data is not None:
            lines = data.decode("utf-8", errors="ignore").splitlines()
            if 1 <= c["start"] <= c["end"] <= len(lines):
                block_hash = _sha_text(
                    "\n".join(lines[c["start"] - 1:c["end"]]))
        enriched.append({**c,
                         "claim_hash": _sha_text(c["claim"]),
                         "block_hash": block_hash})
    return {"citations": enriched, "sources": sources}


def snapshot_from_dir(root):
    root = Path(root)
    wiki = root / "wiki"
    pages = {}
    if wiki.is_dir():
        for path in sorted(wiki.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            pages[rel] = path.read_text(encoding="utf-8",
                                        errors="ignore")
    citations = _scan_texts(pages)
    source_bytes = {}
    for src in sorted({c["source"] for c in citations}):
        if _escapes_repo(src):
            source_bytes[src] = None
            continue
        path = root / src
        source_bytes[src] = path.read_bytes() if path.is_file() else None
    return _snapshot(citations, source_bytes)


def _git(*argv):
    return subprocess.run(["git", "-C", str(ROOT), *argv],
                          capture_output=True)


def _git_text(rev, path):
    res = _git("show", f"{rev}:{path}")
    if res.returncode != 0:
        return None
    return res.stdout


def snapshot_from_git(rev):
    chk = _git("rev-parse", "--verify", f"{rev}^{{commit}}")
    if chk.returncode != 0:
        raise ValueError(f"not a git revision: {rev}")
    listing = _git("ls-tree", "-r", "--name-only", "-z", rev,
                   "--", "wiki")
    if listing.returncode != 0:
        raise ValueError(f"git ls-tree failed for {rev}")
    pages = {}
    for name in listing.stdout.decode("utf-8", errors="ignore") \
            .split("\0"):
        if name.endswith(".md"):
            data = _git_text(rev, name)
            if data is not None:
                pages[name] = data.decode("utf-8", errors="ignore")
    citations = _scan_texts(pages)
    source_bytes = {}
    for src in sorted({c["source"] for c in citations}):
        if _escapes_repo(src):
            source_bytes[src] = None
        else:
            source_bytes[src] = _git_text(rev, src)
    return _snapshot(citations, source_bytes)


def _lineage(snap, source):
    row = snap["sources"].get(source)
    if row is None:
        return {"sha256": None, "lines": None}
    return row


def diff_snapshots(base, head, base_label, head_label):
    """Deterministic citation-change events between two
    snapshots. Citations are matched within (page, claim hash)
    groups: exact (source, range) pairs first, then leftovers
    in sorted order — a claim cited twice on one page diffs
    stably."""
    def grouped(snap):
        groups = {}
        for c in snap["citations"]:
            groups.setdefault((c["page"], c["claim_hash"]),
                              []).append(c)
        for key in groups:
            groups[key].sort(key=lambda c: (c["source"], c["start"],
                                            c["end"]))
        return groups

    base_groups = grouped(base)
    head_groups = grouped(head)
    events = []

    def emit(kind, b, h, extra=None):
        src = (h or b)["source"]
        ev = {"event": kind,
              "page": (h or b)["page"],
              "claim": (h or b)["claim"],
              "claim_hash": (h or b)["claim_hash"],
              "base": ({"source": b["source"],
                        "range": [b["start"], b["end"]],
                        "block_hash": b["block_hash"]} if b
                       else None),
              "head": ({"source": h["source"],
                        "range": [h["start"], h["end"]],
                        "block_hash": h["block_hash"]} if h
                       else None),
              "lineage": {
                  "source": src,
                  "base": _lineage(base, src),
                  "head": _lineage(head, src),
              },
              "revisions": {"base": base_label, "head": head_label}}
        if extra:
            ev.update(extra)
        events.append(ev)

    for key in sorted(set(base_groups) | set(head_groups)):
        bs = base_groups.get(key, [])
        hs = head_groups.get(key, [])
        b_left, h_left = [], []
        h_by_loc = {}
        for h in hs:
            h_by_loc.setdefault((h["source"], h["start"], h["end"]),
                                []).append(h)
        for b in bs:
            loc = (b["source"], b["start"], b["end"])
            if h_by_loc.get(loc):
                h = h_by_loc[loc].pop(0)
                if b["block_hash"] != h["block_hash"]:
                    emit("citation-content-changed", b, h)
            else:
                b_left.append(b)
        matched_h = {id(h) for lst in h_by_loc.values() for h in lst}
        h_left = [h for h in hs if id(h) in matched_h]
        for b, h in zip(b_left, h_left):
            if b["source"] != h["source"]:
                emit("citation-retargeted", b, h, extra={
                    "lineage_old_source": {
                        "source": b["source"],
                        "base": _lineage(base, b["source"]),
                        "head": _lineage(head, b["source"])}})
            else:
                emit("citation-moved", b, h, extra={
                    "content_changed":
                        b["block_hash"] != h["block_hash"]})
        for b in b_left[len(h_left):]:
            emit("citation-removed", b, None)
        for h in h_left[len(b_left):]:
            emit("citation-added", None, h)

    events.sort(key=lambda e: (e["page"], e["claim_hash"],
                               e["event"],
                               json.dumps(e["base"],
                                          sort_keys=True),
                               json.dumps(e["head"],
                                          sort_keys=True)))
    return events


def cmd_events(args):
    if bool(args.base) != bool(args.head):
        print("--base and --head go together")
        return 2
    if bool(args.base_root) != bool(args.head_root):
        print("--base-root and --head-root go together")
        return 2
    if bool(args.base) == bool(args.base_root):
        print("give exactly one revision pair: --base/--head"
              " (git refs) or --base-root/--head-root (dirs)")
        return 2
    try:
        if args.base:
            base = snapshot_from_git(args.base)
            head = snapshot_from_git(args.head)
            base_label, head_label = args.base, args.head
        else:
            base = snapshot_from_dir(args.base_root)
            head = snapshot_from_dir(args.head_root)
            base_label, head_label = args.base_root, args.head_root
    except ValueError as exc:
        print(str(exc))
        return 2
    events = diff_snapshots(base, head, base_label, head_label)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(
            json.dumps(ev, ensure_ascii=False, sort_keys=True)
            + "\n" for ev in events), encoding="utf-8")
        print(f"wrote {out}")
    counts = {}
    for ev in events:
        counts[ev["event"]] = counts.get(ev["event"], 0) + 1
    print(f"citation-change events {base_label} -> {head_label}:"
          f" {len(events)}")
    for kind in sorted(counts):
        print(f"  {kind}: {counts[kind]}")
    return 0


# -- CLI -------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(
        description="Fabricated-citation detection at ingest"
                    " (report-only) + deterministic"
                    " citation-change events over revision"
                    " pairs.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser(
        "scan", help="scan the corpus for citations that cannot"
                     " exist as cited; writes"
                     " evaluation/ghostcite-report.json")
    p_scan.add_argument("--out", help="report path (default:"
                                      " evaluation/"
                                      "ghostcite-report.json)")
    p_scan.add_argument("--no-write", action="store_true",
                        help="print the summary only")
    p_scan.add_argument("--no-lockfile-ok", action="store_true",
                        help="scan without a lockfile baseline"
                             " (nothing is vouchsafed)")

    p_ing = sub.add_parser(
        "ingest-check", help="detection scoped to the citations"
                             " over one freshly ingested source")
    p_ing.add_argument("--source", required=True,
                       help="repo-relative cited source, e.g."
                            " raw/sources/<file>.md")
    p_ing.add_argument("--out", help="write the JSON report"
                                     " here (default: summary"
                                     " only)")

    p_ev = sub.add_parser(
        "events", help="citation-change events between two"
                       " revisions, with source lineage")
    p_ev.add_argument("--base", help="base git ref")
    p_ev.add_argument("--head", help="head git ref")
    p_ev.add_argument("--base-root", help="base directory root")
    p_ev.add_argument("--head-root", help="head directory root")
    p_ev.add_argument("--out", help="write events as JSONL here"
                                    " (default: counts only)")

    args = ap.parse_args(argv[1:])
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "ingest-check":
        return cmd_ingest_check(args)
    return cmd_events(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
