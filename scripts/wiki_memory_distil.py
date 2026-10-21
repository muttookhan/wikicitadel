#!/usr/bin/env python3
"""wiki_memory_distil.py — the MemU-shaped pipeline over our own
memory files (Marathon R4, lane C).

Pattern: NevaMind-AI/MemU (Apache-2.0 per its README) — mine
session logs -> bridge jobs -> distil to Markdown -> commit /
index, re-implemented deterministically in our own code over
OUR memory-shaped files (daily logs like ~/memory/*.md and the
mirrored raw/sources/claude-memory/ pages). The pipeline here:

  mine    read every *.md in a directory (non-recursive)
  bridge  split each file into dated entries: a dated heading
          (## [YYYY-MM-DD] ... or ## YYYY-MM-DD ...) starts an
          entry; an undated heading starts an entry dated by
          its file's name when the name carries a date, else
          "undated"; text before the first heading is an entry
          under the file's stem when it is non-empty
  distil  collapse exact duplicates (same topic + same
          normalised text) into one entry with a count, then
          render a Markdown digest: one section per topic,
          entries chronological, every entry attributed to
          its source file + date
  index   a JSON index of topics, entries, counts and sources

Deterministic: no wall clock anywhere — the digest and index
depend only on the input files. Inputs are read-only to this
tool; the only writes are the --out digest and --index files
the caller names. (In tests it runs ONLY against fixtures —
never over the real memory corpus.)

    python3 scripts/wiki_memory_distil.py <log-dir>
        --out DIGEST.md --index INDEX.json

Exit codes: 0 ok · 1 refusal · 2 usage error. Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
DATED_HEADING_RE = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2})\]?\s*[|—–-]?\s*(.*)$")
FILE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
WS_RE = re.compile(r"\s+")


class DistilError(Exception):
    pass


def _norm(text):
    return WS_RE.sub(" ", text.strip().lower())


def split_entries(path):
    """Bridge step: one file -> [{date, topic, text}]."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = FILE_DATE_RE.search(path.name)
    file_date = m.group(1) if m else "undated"
    entries = []
    current = None

    def flush():
        if current and current["text"].strip():
            entries.append(current)

    for line in text.splitlines():
        hm = HEADING_RE.match(line)
        if hm:
            flush()
            heading = hm.group(2).strip()
            dm = DATED_HEADING_RE.match(heading)
            if dm:
                date = dm.group(1)
                topic = dm.group(2).strip() or path.stem
            else:
                date = file_date
                topic = heading
            current = {"date": date, "topic": topic,
                       "text": "", "_heading": heading}
        elif current is None:
            current = {"date": file_date, "topic": path.stem,
                       "text": line + "\n", "_heading": ""}
        else:
            current["text"] += line + "\n"
    flush()
    for e in entries:
        e["text"] = e["text"].strip()
        e.pop("_heading", None)
    return entries


def distil(log_dir):
    """Mine + bridge + collapse. Returns (digest_data, index)."""
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        raise DistilError("no such log directory: %s" % log_dir)
    files = sorted(p for p in log_dir.glob("*.md") if p.is_file())
    if not files:
        raise DistilError("no .md logs in %s" % log_dir)
    raw_entries = []
    for f in files:
        for e in split_entries(f):
            raw_entries.append({**e, "source_file": f.name})
    # Collapse duplicates: same topic + same normalised text.
    collapsed = {}
    order = []
    for e in raw_entries:
        key = (e["topic"].lower(), _norm(e["text"]))
        if key not in collapsed:
            collapsed[key] = {**e, "count": 0, "sources": []}
            order.append(key)
        rec = collapsed[key]
        rec["count"] += 1
        src = {"source_file": e["source_file"], "date": e["date"]}
        if src not in rec["sources"]:
            rec["sources"].append(src)
        if e["date"] < rec["date"]:
            rec["date"] = e["date"]
    unique = [collapsed[k] for k in order]
    topics = {}
    for e in unique:
        topics.setdefault(e["topic"], []).append(e)
    for entries in topics.values():
        entries.sort(key=lambda e: (e["date"], e["text"]))
    index = {
        "tool": "scripts/wiki_memory_distil.py",
        "kind": "memory-distil-index",
        "source_dir": str(log_dir),
        "files": [f.name for f in files],
        "total_entries": len(raw_entries),
        "unique_entries": len(unique),
        "duplicates_collapsed": len(raw_entries) - len(unique),
        "topics": {
            topic: [{"date": e["date"],
                     "source_file": e["source_file"],
                     "count": e["count"],
                     "sources": e["sources"],
                     "sha256": hashlib.sha256(
                         e["text"].encode("utf-8")).hexdigest(),
                     "text_preview": e["text"][:120]}
                    for e in entries]
            for topic, entries in sorted(topics.items())},
    }
    return topics, index


def render_digest(topics, index):
    lines = ["# Memory digest (distilled)",
             "",
             "Distilled deterministically from %d log file(s): "
             "%d entries, %d unique, %d duplicate(s) collapsed. "
             "Every entry is attributed to its source file and "
             "date; the inputs were not modified."
             % (len(index["files"]), index["total_entries"],
                index["unique_entries"],
                index["duplicates_collapsed"]),
             ""]
    for topic in sorted(topics):
        lines.append("## %s" % topic)
        lines.append("")
        for e in topics[topic]:
            lines.append(e["text"])
            lines.append("")
            attr = "; ".join(
                "%s, %s" % (s["source_file"], s["date"])
                for s in e["sources"])
            dup = " (×%d duplicates collapsed)" % e["count"] \
                if e["count"] > 1 else ""
            lines.append("— source: %s%s" % (attr, dup))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True,
                    help="distilled Markdown digest path")
    ap.add_argument("--index", type=Path, required=True,
                    help="index JSON path")
    args = ap.parse_args(argv)
    try:
        topics, index = distil(args.log_dir)
    except DistilError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_digest(topics, index),
                        encoding="utf-8")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(json.dumps(index, indent=2) + "\n",
                          encoding="utf-8")
    print("distilled: %d entries -> %d unique (%d duplicates "
          "collapsed) across %d topic(s)"
          % (index["total_entries"], index["unique_entries"],
             index["duplicates_collapsed"], len(topics)))
    print("digest: %s" % args.out)
    print("index: %s" % args.index)
    return 0


if __name__ == "__main__":
    sys.exit(main())
