#!/usr/bin/env python3
"""Pack-time secret-pattern scan (round-2 research addition).

Item: "a secret-pattern scan pass before any context bundle
is packed for a model" (repomix pattern, r2 Tier A addition;
also the east-asia r2 find: a secret-pattern lint pass before
any corpus is packed into an LLM context bundle). Here the
packing path is this wiki's own: the BagIt preservation
export (scripts/wiki_bag.py) and any take-home bundle built
from the same snapshot sets.

The scan reuses the export-surface leak lint's pattern
classes (scripts/wiki_leak_lint.py scan_text: the gateway
scanner's credential/PII classes plus the local path-shape
classes), so pack time and export time judge by the same
shapes. Discipline inherited from the leak lint: findings
name file, pattern CLASS and count only — the matched value
is never printed, returned, or stored.

Wiring: scripts/wiki_bag.py pack runs this scan over the
payload BEFORE copying anything. A hit refuses the pack
(ValueError / CLI exit 2) unless the caller explicitly
passes --allow-pack-findings, in which case the pack
proceeds, the findings are reported as warnings, and the
scan result rides in the pack stats. `--no-pack-scan`
skips the scan and says so in the stats — skipping is a
recorded act, never a silent default.

Standalone use scans a snapshot set in place (report-only;
nothing is packed, nothing is baselined — this tool has no
baseline and writes none):

  python3 scripts/wiki_pack_scan.py [--root DIR]
      [--set compiled|full] [--json]

Exit codes: 0 = no findings, 3 = findings, 2 = usage error.

Stdlib only (plus wiki_leak_lint / wiki_bag, imported
in-process).
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".html",
                 ".yaml", ".yml", ".csv", ".tsv"}
READ_CAP = 2 * 1024 * 1024


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LEAK = None


def scan_text_hits(text):
    """[{pattern, count}] for one text, via the leak lint
    (module loaded once and cached — reloading it per file
    would re-exec the gateway scanner every time)."""
    global _LEAK
    if _LEAK is None:
        _LEAK = _load("wiki_leak_lint")
    return _LEAK.scan_text(text)


def scan_payload_files(payload):
    """Scan [(repo-relative path, absolute path)] — the shape
    wiki_bag.collect_payload returns. Binary/non-text payload
    files are counted as skipped, never read. Returns the
    report dict (no matched values anywhere in it)."""
    findings = []
    scanned = skipped = capped = 0
    for rel, path in payload:
        path = Path(path)
        if path.suffix.lower() not in TEXT_SUFFIXES:
            skipped += 1
            continue
        raw = path.read_bytes()
        if len(raw) > READ_CAP:
            capped += 1
            raw = raw[:READ_CAP]
        scanned += 1
        text = raw.decode("utf-8", errors="ignore")
        for hit in scan_text_hits(text):
            findings.append({"file": rel, **hit})
    findings.sort(key=lambda f: (f["file"], f["pattern"]))
    total = sum(f["count"] for f in findings)
    return {"tool": "wiki_pack_scan",
            "files_scanned": scanned, "files_skipped": skipped,
            "files_capped": capped, "findings": findings,
            "findings_total": total,
            "verdict": "findings" if findings else "clean"}


def scan_set(root, set_name):
    """Scan one of wiki_bag's snapshot sets in place."""
    bag = _load("wiki_bag")
    payload = bag.collect_payload(Path(root), set_name)
    report = scan_payload_files(payload)
    report["set"] = set_name
    report["payload_files"] = len(payload)
    return report


def format_hits(report, limit=20):
    """One line per finding: file, class, count — never a
    matched value."""
    lines = [f"{f['file']}: {f['pattern']} x{f['count']}"
             for f in report["findings"][:limit]]
    if len(report["findings"]) > limit:
        lines.append(f"... and {len(report['findings']) - limit} "
                     f"more finding line(s)")
    return lines


def main(argv):
    ap = argparse.ArgumentParser(
        description="Secret-pattern scan over a bag snapshot "
                    "set, before anything is packed (report-only).")
    ap.add_argument("--root", default=None)
    ap.add_argument("--set", default="compiled",
                    choices=("compiled", "full"),
                    help="snapshot set to scan (default: compiled)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT
    if not (root / "wiki").is_dir():
        print(f"error: no wiki/ at {root}", file=sys.stderr)
        return 2
    report = scan_set(root, args.set)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"== Pack scan — set {report['set']} ==")
        print(f"payload files: {report['payload_files']}   "
              f"scanned: {report['files_scanned']}   "
              f"skipped (non-text): {report['files_skipped']}   "
              f"verdict: {report['verdict']}")
        for line in format_hits(report):
            print(f"  - {line}")
    return 3 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
