#!/usr/bin/env python3
"""Public-tier leak lint for the LLM Wiki's export surfaces.

Adapted from portablellm.wiki's lint swarm (assessed in
docs/research-notes.md): of its four parallel lint agents
— contradictions, stale claims, missing pages, public-tier leaks —
the leaks lane is the one this wiki lacked. This script is that
lane, as a standalone pass. Like the swarm, it SURFACES issues for
the owner and never rewrites, moves, or deletes anything.

Why it exists: the gateway secrets scan
(tools/gateway/gateway/defense.py) guards the door IN — every
proposal staged through the gateway is scanned and blocked on a
hit. This lint guards the door OUT: the artefacts that leave (or
could leave) the wiki's private core are scanned with the same
pattern classes, so a secret or PII shape that reached an export
surface is caught before the surface travels.

Surfaces scanned (each guarded: an absent surface is recorded as
"not present", never a crash):

  1. lens-build — a Lens build output directory (--lens-dir;
     default /tmp/lens-brief when it exists). All .txt/.md/.html/
     .json files, scanned for secrets/PII pattern hits.
  2. filings — the agent filings areas inside the repo,
     raw/filings/** and wiki/filings/**. Scanned for pattern hits
     AND for mirrored-memory content. Heuristic (deliberately
     simple): a file is flagged as apparently containing
     mirrored-memory content when it contains the literal string
     "raw/sources/agent-memory" — the path of the verbatim
     memory mirror (AGENTS.md: the agent's own memory, mirrored
     under raw/sources/agent-memory/) — as a copied-content
     marker, or when it carries a pattern hit. Filings are
     agent-facing and travel on collaborator branches; the
     owner's mirrored memory must never ride along in them.
  3. takehome-zip — the newest wikicitadel*.zip under ~/workspace
     (by mtime). Members are listed; text members (.md/.txt/
     .json) are scanned, each read capped at 2 MB.

Discipline (inherited from defense.py): findings name the file,
the pattern CLASS, and a count ONLY — the matched value is never
copied into stdout, the JSON report, or anywhere else.

Baseline (delta reporting): a checked-in baseline at
scripts/leak-baseline.json fingerprints the findings an audit has
already cleared — fingerprint = surface + file + pattern class +
sha256 of the matched line's content. The matched value itself is
never stored, only the hash of the line it appeared on. A normal
run reports only NEW findings: "N new (M baselined)". Regenerate
the baseline after auditing the current corpus with
--write-baseline.

Carve-out (hard rule): credential-shaped pattern classes are
NEVER baselined — private-key, aws-access-key-id, github-token,
slack-token, provider-api-key, jwt, bearer-token,
connection-string, credential-assignment, ssn. Their findings
surface on every run until the owner rules on them (the two
bearer-token prose hit is the standing example). Only two
classes are baselinable: credit-card (the Luhn-shape class whose
hits over this corpus are audited long-number false positives)
and mirrored-memory-marker (benign by direction inside agent
filings — see the note in the baseline file's header). Any class
not explicitly baselinable is carved out by default, so a class
added to the gateway scanner later cannot be silenced by an old
baseline.

Path shapes (added in the B3 governance round): two further
pattern classes are detected locally in this script (not by the
gateway scanner, whose classes guard the door IN):

  absolute-home-path — an absolute home-directory path:
    /home/<user>/…, /Users/<user>/…, or a Windows drive home path… —
    it names a person's machine layout and account name, and
    an export surface has no business carrying one.
  bare-username-in-path — the same leak without the absolute
    root: ~<user>/…, a relative home/<user>/… or
    Users/<user>/… path segment.

A path-shape hit is reported exactly like every other hit —
pattern class + file + count, with the matched line's number
and sha256 in the line findings — and the matched text itself
is NEVER quoted, printed, or stored. Both classes are
baselinable through the same baseline mechanism as
credit-card (see BASELINABLE_PATTERNS below): they are shapes,
not credentials, and an audited example path in documentation
may be baselined by an audited run — a real home path is
scrubbed, never baselined to silence the lane.

Output: a human summary to stdout listing only new findings;
with --json <path>, the same result machine-readable (findings
carry new_count / baselined_count alongside count). Exit codes:
0 = no NEW findings (surfaces clean, or every finding
baselined), 3 = new findings on any surface (carved-out classes
always count as new), 2 = usage error.

Usage:
  python3 scripts/wiki_leak_lint.py [--lens-dir DIR] [--json OUT]
  python3 scripts/wiki_leak_lint.py --write-baseline

Stdlib only (plus the gateway scanner, imported in-process).
"""
import argparse
import glob
import hashlib
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path.home() / "workspace"
DEFAULT_LENS_DIR = Path("/tmp/lens-brief")
TEXT_SUFFIXES = {".txt", ".md", ".html", ".json"}
ZIP_TEXT_SUFFIXES = {".md", ".txt", ".json"}
ZIP_MEMBER_CAP = 2 * 1024 * 1024
MIRROR_MARKER = "raw/sources/agent-memory"
BASELINE_PATH = Path(__file__).resolve().parent / "leak-baseline.json"
# Only these classes may ever enter the baseline (see docstring).
# Every other class — including any the gateway scanner gains
# later — is carved out by default and surfaces on every run.
BASELINABLE_PATTERNS = {"credit-card", "mirrored-memory-marker",
                        "absolute-home-path", "bare-username-in-path"}
NEVER_BASELINE_PATTERNS = {
    "private-key", "aws-access-key-id", "github-token",
    "slack-token", "provider-api-key", "jwt", "bearer-token",
    "connection-string", "credential-assignment", "ssn",
}

sys.path.insert(0, str(ROOT / "tools" / "gateway"))
from gateway.defense import scan_secrets  # noqa: E402


# -- Path / username shapes (local classes; see docstring) ----------------
# Absolute home paths: /home/<user>/, /Users/<user>/,
# C:\Users\<user>\. The lookarounds keep the bare-username
# class from double-counting the tail of an absolute path.
ABS_HOME_RES = (
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"\b[A-Za-z]:\\Users\\[A-Za-z0-9._\- ]+\\"),
)
BARE_USERNAME_RES = (
    re.compile(r"(?<![\w/.-])~[A-Za-z0-9._-]+/"),
    re.compile(r"(?<![\w/.-])home/[A-Za-z0-9._-]+/"),
    re.compile(r"(?<![\w/.\\-])Users/[A-Za-z0-9._-]+/"),
)
PATH_SHAPE_RES = (("absolute-home-path", ABS_HOME_RES),
                  ("bare-username-in-path", BARE_USERNAME_RES))


def scan_path_shapes(text):
    """-> [{pattern, count}] for the path/username shape
    classes only (class+count; the matched text is never
    returned, here or anywhere else in this script)."""
    out = []
    for pattern, regexes in PATH_SHAPE_RES:
        n = sum(len(rx.findall(text)) for rx in regexes)
        if n:
            out.append({"pattern": pattern, "count": n})
    return out


def scan_text(text):
    """-> [{pattern, count}] sorted by pattern class (class+count
    only; scan_secrets never returns the matched value). Merges
    the gateway scanner's classes with this script's local
    path/username shape classes."""
    result = scan_secrets(text)
    merged = {}
    for f in result["findings"]:
        merged[f["pattern"]] = merged.get(f["pattern"], 0) + f["count"]
    for f in scan_path_shapes(text):
        merged[f["pattern"]] = merged.get(f["pattern"], 0) + f["count"]
    return [{"pattern": k, "count": v}
            for k, v in sorted(merged.items())]


def _line_findings(text, wanted):
    """Per-line fingerprints for the pattern classes in `wanted`
    (the classes this one file hit). Returns [{pattern,
    line_sha256, matches}] aggregated over identical lines. Only
    the sha256 of a matched line is kept — never the line, never
    the matched value."""
    groups = {}
    first_line = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        pats = {}
        for hit in scan_text(line):
            if hit["pattern"] in wanted:
                pats[hit["pattern"]] = hit["count"]
        if "mirrored-memory-marker" in wanted:
            n = line.count(MIRROR_MARKER)
            if n:
                pats["mirrored-memory-marker"] = n
        if not pats:
            continue
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        for pattern, n in pats.items():
            key = (pattern, digest)
            groups[key] = groups.get(key, 0) + n
            first_line.setdefault(key, lineno)
    return [{"pattern": pattern, "line_sha256": digest,
             "line": first_line[(pattern, digest)],
             "matches": matches}
            for (pattern, digest), matches in sorted(groups.items())]


def _attach_line_findings(surface, rel, text, hits, markers):
    wanted = {h["pattern"] for h in hits}
    if markers:
        wanted.add("mirrored-memory-marker")
    if not wanted:
        return
    for entry in _line_findings(text, wanted):
        surface["line_findings"].append({"file": rel, **entry})


def _surface(name, location):
    return {"surface": name, "location": str(location),
            "present": False, "files_scanned": 0,
            "findings": [], "findings_total": 0,
            "line_findings": [], "new_total": 0, "baselined_total": 0,
            "verdict": "not present"}


def _finish(surface):
    surface["findings"].sort(key=lambda f: (f["file"], f["pattern"]))
    surface["findings_total"] = sum(f["count"] for f in surface["findings"])
    if surface["present"]:
        surface["verdict"] = "findings" if surface["findings"] else "clean"
    return surface


def scan_lens_dir(lens_dir):
    """Surface 1: a Lens build output directory."""
    surface = _surface("lens-build", lens_dir)
    if lens_dir is None or not Path(lens_dir).is_dir():
        return surface
    surface["present"] = True
    for path in sorted(Path(lens_dir).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        surface["files_scanned"] += 1
        rel = path.relative_to(lens_dir).as_posix()
        hits = scan_text(text)
        for hit in hits:
            surface["findings"].append({"file": rel, **hit})
        _attach_line_findings(surface, rel, text, hits, 0)
    return _finish(surface)


def scan_filings(root=ROOT):
    """Surface 2: raw/filings/** + wiki/filings/** — pattern hits
    plus the mirrored-memory marker heuristic (see docstring)."""
    surface = _surface("filings", "raw/filings/** + wiki/filings/**")
    areas = [root / "raw" / "filings", root / "wiki" / "filings"]
    if not any(a.is_dir() for a in areas):
        return surface
    surface["present"] = True
    for area in areas:
        if not area.is_dir():
            continue
        for path in sorted(area.rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            surface["files_scanned"] += 1
            rel = path.relative_to(root).as_posix()
            hits = scan_text(text)
            for hit in hits:
                surface["findings"].append({"file": rel, **hit})
            markers = text.count(MIRROR_MARKER)
            if markers:
                surface["findings"].append(
                    {"file": rel, "pattern": "mirrored-memory-marker",
                     "count": markers})
            _attach_line_findings(surface, rel, text, hits, markers)
    return _finish(surface)


def newest_takehome_zip(workspace=WORKSPACE):
    candidates = glob.glob(str(Path(workspace) / "wikicitadel*.zip"))
    if not candidates:
        return None
    return Path(max(candidates, key=lambda p: Path(p).stat().st_mtime))


def scan_zip(zip_path):
    """Surface 3: the newest take-home/export zip."""
    surface = _surface("takehome-zip",
                         zip_path if zip_path else "(none found)")
    if zip_path is None or not Path(zip_path).is_file():
        return surface
    surface["present"] = True
    surface["members_total"] = 0
    surface["members_capped"] = 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        surface["verdict"] = "unreadable"
        return surface
    with archive:
        for info in sorted(archive.infolist(), key=lambda i: i.filename):
            if info.is_dir():
                continue
            surface["members_total"] += 1
            if Path(info.filename).suffix.lower() not in ZIP_TEXT_SUFFIXES:
                continue
            raw = archive.read(info.filename)
            if len(raw) > ZIP_MEMBER_CAP:
                surface["members_capped"] += 1
                raw = raw[:ZIP_MEMBER_CAP]
            text = raw.decode("utf-8", errors="ignore")
            surface["files_scanned"] += 1
            hits = scan_text(text)
            for hit in hits:
                surface["findings"].append(
                    {"file": info.filename, **hit})
            _attach_line_findings(surface, info.filename, text,
                                  hits, 0)
    return _finish(surface)


def collect_surfaces(lens_dir=None, root=ROOT, workspace=WORKSPACE):
    """Run all three surfaces. lens_dir=None resolves to
    /tmp/lens-brief when it exists, else the surface is absent."""
    if lens_dir is None and DEFAULT_LENS_DIR.is_dir():
        lens_dir = DEFAULT_LENS_DIR
    return [
        scan_lens_dir(lens_dir),
        scan_filings(root),
        scan_zip(newest_takehome_zip(workspace)),
    ]


def overall_verdict(surfaces):
    return "findings" if any(s["verdict"] == "findings"
                             for s in surfaces) else "clean"


# -- Baseline ---------------------------------------------------------------
# The baseline turns the lint from a nightly shout into a delta:
# findings an audit has already cleared are fingerprinted (surface
# + file + pattern class + sha256 of the matched line) and stop
# resurfacing while their line is unchanged. Credential-shaped
# classes are never baselined (see the module docstring).

def load_baseline(path=BASELINE_PATH):
    """-> {"meta": <baseline file dict>, "index": {(surface, file,
    pattern, line_sha256): matches}} or None when no baseline is
    checked in."""
    if not Path(path).is_file():
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    index = {}
    for fp in data.get("fingerprints", []):
        key = (fp["surface"], fp["file"], fp["pattern"],
               fp["line_sha256"])
        index[key] = index.get(key, 0) + fp["matches"]
    return {"meta": data, "index": index}


def build_baseline(surfaces, generated):
    """Baseline payload from a fresh scan: one fingerprint per
    baselinable matched line. Carved-out classes are counted in
    the header as still-surfacing, never fingerprinted."""
    fingerprints = []
    per_class = {}
    carved = {}
    for s in surfaces:
        for f in s["findings"]:
            if f["pattern"] not in BASELINABLE_PATTERNS:
                carved[f["pattern"]] = (carved.get(f["pattern"], 0)
                                         + f["count"])
        for lf in s.get("line_findings", []):
            if lf["pattern"] not in BASELINABLE_PATTERNS:
                continue
            fingerprints.append({
                "surface": s["surface"], "file": lf["file"],
                "pattern": lf["pattern"],
                "line_sha256": lf["line_sha256"],
                "matches": lf["matches"]})
            per_class[lf["pattern"]] = (
                per_class.get(lf["pattern"], 0) + lf["matches"])
    fingerprints.sort(key=lambda fp: (fp["surface"], fp["file"],
                                      fp["pattern"],
                                      fp["line_sha256"]))
    return {
        "tool": "wiki_leak_lint baseline",
        "generated": generated,
        "fingerprint": "surface + file + pattern class + sha256 "
                       "of the matched line's content. The matched "
                       "value is never stored — only the hash of "
                       "the line it appeared on.",
        "carve_out_rule": "Credential-shaped pattern classes are "
                          "NEVER baselined and surface on every "
                          "run until the owner rules: "
                          + ", ".join(sorted(
                              NEVER_BASELINE_PATTERNS))
                          + ". Any pattern class not listed under "
                          "baselined_classes is likewise carved "
                          "out by default.",
        "baselined_classes": sorted(BASELINABLE_PATTERNS),
        "mirror_note": "mirrored-memory-marker hits are "
                     "baselined: the marker is the path of the "
                     "verbatim memory mirror, and the hits in "
                     "this corpus sit in agent filings (notably "
                     "raw/filings/ of collaborating agents) whose "
                     "authors are DIRECTED to read that mirror — "
                     "their filings quote it by design. Benign "
                     "by direction; baselined with this note "
                     "(WikiCitadel v1).",
        "counts": {"fingerprints": len(fingerprints),
                   "matches_baselined": sum(per_class.values()),
                   "per_class": per_class},
        "carved_out_still_surfacing": carved,
        "fingerprints": fingerprints,
    }


def write_baseline(surfaces, path=BASELINE_PATH, generated=None):
    payload = build_baseline(surfaces,
                             generated or date.today().isoformat())
    Path(path).write_text(json.dumps(payload, indent=1) + "\n",
                          encoding="utf-8")
    return payload


def annotate_baseline(surfaces, baseline):
    """Split every finding into baselined vs new counts, in place
    (finding["baselined_count"] / finding["new_count"], surface
    totals, and a verdict that reflects NEW findings only).

    A finding is baselined only to the extent its matched lines'
    fingerprints are in the baseline. Carved-out classes, a
    missing baseline, and matches no single line accounts for
    (e.g. a shape spanning lines) all count as new — the safe
    direction."""
    index = baseline["index"] if baseline else {}
    for s in surfaces:
        groups = {}
        for lf in s.get("line_findings", []):
            key = (lf["file"], lf["pattern"], lf["line_sha256"])
            groups[key] = groups.get(key, 0) + lf["matches"]
        baselined_total = 0
        new_total = 0
        for f in s["findings"]:
            count = f["count"]
            baselined = 0
            if baseline is not None \
                    and f["pattern"] in BASELINABLE_PATTERNS:
                matched = 0
                for (file, pattern, digest), m in groups.items():
                    if file == f["file"] and pattern == f["pattern"]:
                        matched += min(
                            m, index.get((s["surface"], file,
                                          pattern, digest), 0))
                baselined = min(matched, count)
            f["baselined_count"] = baselined
            f["new_count"] = count - baselined
            baselined_total += baselined
            new_total += f["new_count"]
        s["baselined_total"] = baselined_total
        s["new_total"] = new_total
        if s["present"]:
            s["verdict"] = "findings" if new_total else "clean"
    return surfaces


def print_summary(surfaces, baseline):
    print("== Leak lint — export surfaces ==")
    if baseline is None:
        print("(no baseline checked in — every finding is new;"
              " regenerate with --write-baseline)")
    total_new = 0
    total_base = 0
    for s in surfaces:
        print(f"[{s['surface']}] {s['location']}")
        if not s["present"]:
            print("  not present — skipped")
            continue
        print(f"  files scanned: {s['files_scanned']}"
              f"   findings: {s['new_total']} new"
              f" ({s['baselined_total']} baselined)"
              f"   verdict: {s['verdict']}")
        total_new += s["new_total"]
        total_base += s["baselined_total"]
        for f in s["findings"]:
            if f["new_count"]:
                note = (f" (+{f['baselined_count']} baselined)"
                        if f["baselined_count"] else "")
                print(f"  - {f['file']}: {f['pattern']}"
                      f" x{f['new_count']}{note}")
    print(f"Overall: {overall_verdict(surfaces)}"
          f" — {total_new} new ({total_base} baselined)")


def main(argv):
    ap = argparse.ArgumentParser(
        description="Leak lint over the wiki's export surfaces "
                    "(Lens build, filings areas, newest take-home zip).")
    ap.add_argument("--lens-dir", default=None,
                    help="Lens build output directory "
                         "(default: /tmp/lens-brief when it exists)")
    ap.add_argument("--json", default=None,
                    help="also write the machine-readable result here")
    ap.add_argument("--write-baseline", action="store_true",
                    help="regenerate scripts/leak-baseline.json "
                         "from a fresh scan of the current corpus "
                         "(baselinable classes only; carved-out "
                         "classes are never baselined) and exit")
    args = ap.parse_args(argv[1:])

    lens_dir = None
    if args.lens_dir is not None:
        lens_dir = Path(args.lens_dir)
        if not lens_dir.is_dir():
            print(f"error: --lens-dir {args.lens_dir} is not a directory",
                  file=sys.stderr)
            return 2
    surfaces = collect_surfaces(lens_dir)
    if args.write_baseline:
        payload = write_baseline(surfaces)
        counts = payload["counts"]
        print(f"baseline written: {BASELINE_PATH}")
        print(f"  generated: {payload['generated']}"
              f"   fingerprints: {counts['fingerprints']}"
              f"   matches baselined: {counts['matches_baselined']}")
        for pattern, n in sorted(counts["per_class"].items()):
            print(f"  - {pattern}: {n}")
        if payload["carved_out_still_surfacing"]:
            print("  carved out (never baselined, still"
                  " surfacing):")
            for pattern, n in sorted(
                    payload["carved_out_still_surfacing"].items()):
                print(f"  - {pattern}: {n}")
        return 0
    baseline = load_baseline()
    annotate_baseline(surfaces, baseline)
    print_summary(surfaces, baseline)
    verdict = overall_verdict(surfaces)
    if args.json:
        payload = {"tool": "wiki_leak_lint", "verdict": verdict,
                   "baseline": {
                       "present": baseline is not None,
                       "generated": (baseline["meta"].get("generated")
                                     if baseline else None)},
                   "surfaces": surfaces}
        Path(args.json).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"json: {args.json}")
    return 3 if verdict == "findings" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
