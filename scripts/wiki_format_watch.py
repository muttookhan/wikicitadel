#!/usr/bin/env python3
"""Format-risk watch: what formats does the corpus hold, and
which of them carry an evidenced preservation risk?

Pattern: PRONOM + PUIDs as a format-risk watch (the survey,
find 12) and identification by signature, never by
extension (find 13) — docs/research-notes.md.
The identification machinery itself
lives in scripts/wiki_convert.py (`identify_format`), which
records format + PUID + basis + extension_mismatch in every
ingest sidecar (`<out>.ingest.json`) from this build forward.

This tool REPORTS; it changes nothing. Two coverages, kept
honestly separate in the output:

  - the SIDECAR record: files actually ingested through
    wiki_convert.py, with signature-identified formats. Young
    by construction — sidecars exist only where the converter
    has run since they were introduced.
  - the EXTENSION CENSUS: every file under raw/ counted by
    extension. This is today's honest coverage of the whole
    corpus — and it takes extensions on faith, exactly the
    weakness find 13 names. The report says so, in so many
    words, rather than dressing the census up as identification.

Risk classes come from evaluation/format-risk.json, the watch
list seeded from the evidence only: a format on the
list is class "watch" (non-trivial evidenced risk, with the
migration note); everything else is "standard" — not certified
safe, just carrying no evidenced risk on this wiki's record.

Usage:
  python3 scripts/wiki_format_watch.py report [--json]
  python3 scripts/wiki_format_watch.py identify <file>

Stdlib only.
"""
import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH_PATH = ROOT / "evaluation" / "format-risk.json"


def _load_convert():
    spec = importlib.util.spec_from_file_location(
        "wiki_convert", Path(__file__).resolve().parent
        / "wiki_convert.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_watch(path=WATCH_PATH):
    if not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _risk_index(watch):
    """(formats set, extensions set) carrying an evidenced risk."""
    formats, exts = set(), set()
    for entry in (watch or {}).get("watch") or []:
        if entry.get("format"):
            formats.add(entry["format"])
        for ext in entry.get("extensions") or []:
            exts.add(ext.lower())
    return formats, exts


def collect(root: Path, watch):
    """The report data: sidecar record + extension census over
    root/raw, each format/extension classified by risk class."""
    raw = root / "raw"
    risk_formats, risk_exts = _risk_index(watch)

    sidecars = []
    if raw.is_dir():
        for sc in sorted(raw.rglob("*.ingest.json")):
            try:
                rec = json.loads(sc.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            sidecars.append({
                "sidecar": sc.relative_to(root).as_posix(),
                "format": rec.get("format"),
                "puid": rec.get("puid"),
                "basis": rec.get("format_basis"),
                "extension_mismatch": bool(
                    rec.get("extension_mismatch")),
                "converter_format": (rec.get("converter") or {})
                .get("format"),
            })
    by_format = Counter(s["format"] for s in sidecars)
    mismatches = [s for s in sidecars if s["extension_mismatch"]]

    census = Counter()
    total_files = 0
    if raw.is_dir():
        for p in sorted(raw.rglob("*")):
            if p.is_file() and not p.name.endswith(".ingest.json"):
                census[p.suffix.lower() or "(none)"] += 1
                total_files += 1

    def classify(fmt=None, ext=None):
        if fmt and fmt in risk_formats:
            return "watch"
        if ext and ext in risk_exts:
            return "watch"
        return "standard"

    return {
        "sidecars": sidecars,
        "sidecar_formats": [
            {"format": fmt, "count": n,
             "risk_class": classify(fmt=fmt)}
            for fmt, n in sorted(by_format.items(),
                                 key=lambda kv: str(kv[0]))],
        "mismatches": mismatches,
        "census": [
            {"extension": ext, "count": n,
             "risk_class": classify(ext=ext)}
            for ext, n in sorted(census.items())],
        "census_files": total_files,
        "watch_entries": (watch or {}).get("watch") or [],
    }


def render(data):
    lines = ["Format-risk watch — report", ""]
    lines.append("== Ingest sidecars (signature-identified) ==")
    if data["sidecars"]:
        for row in data["sidecar_formats"]:
            lines.append(f"  {row['format']}: {row['count']}"
                         f"  [{row['risk_class']}]")
        lines.append(f"  sidecars on disk: {len(data['sidecars'])}")
        if data["mismatches"]:
            lines.append(f"  EXTENSION MISMATCHES:"
                         f" {len(data['mismatches'])}")
            for s in data["mismatches"]:
                lines.append(f"    - {s['sidecar']}: identified"
                             f" as {s['format']} against its"
                             f" extension")
        else:
            lines.append("  extension mismatches: 0")
    else:
        lines.append("  no ingest sidecars under raw/ yet — the"
                     " sidecar record starts with the next"
                     " conversion")
    lines += ["", "== Extension census over raw/ (all files) =="]
    for row in data["census"]:
        lines.append(f"  {row['extension']}: {row['count']}"
                     f"  [{row['risk_class']}]")
    lines.append(f"  files counted: {data['census_files']}"
                 " (.ingest.json sidecars excluded)")
    lines += ["", "== Watch list (evaluation/format-risk.json) =="]
    if data["watch_entries"]:
        for e in data["watch_entries"]:
            lines.append(f"  {e['format']} — risk: {e['risk']}")
            lines.append(f"    migration: {e['migration']}")
    else:
        lines.append("  (empty)")
    lines += ["",
              "Coverage honesty: the sidecar record covers only"
              " files ingested through wiki_convert.py since"
              " sidecars were introduced; the extension census"
              " covers the whole corpus but takes extensions on"
              " faith — the weakness find 13 names."
              " Signature identification applies at ingest from"
              " this build forward."]
    return "\n".join(lines) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Format-risk watch: corpus formats by risk"
                    " class, from ingest sidecars + the raw/"
                    " extension census.")
    ap.add_argument("--root", default=None,
                    help="repository root (default: this script's repo)")
    ap.add_argument("--watch", default=None,
                    help="watch list path (default:"
                         " <root>/evaluation/format-risk.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_rep = sub.add_parser("report", help="the format-risk report")
    p_rep.add_argument("--json", action="store_true",
                       help="machine-readable output")
    p_id = sub.add_parser("identify",
                          help="identify one file's format by"
                               " signature (wiki_convert's table)")
    p_id.add_argument("file")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT

    if args.cmd == "identify":
        wc = _load_convert()
        print(json.dumps(wc.identify_format(Path(args.file)),
                         indent=2))
        return 0
    watch_path = Path(args.watch) if args.watch else \
        root / "evaluation" / "format-risk.json"
    watch = load_watch(watch_path)
    if watch is None:
        print(f"wiki_format_watch: no watch list at {watch_path}",
              file=sys.stderr)
        return 2
    data = collect(root, watch)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
