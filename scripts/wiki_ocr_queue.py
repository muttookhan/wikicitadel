#!/usr/bin/env python3
"""OCR verification queue — the trust half of machine-read text
(WikiCitadel v1).

Pattern: ABBYY FineReader's Verification workflow
(capture survey, find 18): OCR output is treated as guilty
until verified, one uncertain unit at a time — low-confidence
words are queued beside the original, a verifier accepts a
suggestion, corrects the reading, or Skips (Skip means
"checked, kept as-is" — the check itself is the record), and
confirmed names go into a project dictionary so they stop
flagging. Translated here from words on scanned pages to any
machine extraction this wiki ingests:

  - An extraction is registered when it is INGESTED, with the
    confidence the extractor actually reported — per page or
    per span/word, exactly as reported. An extractor that
    reports no confidence (pypdf's embedded-text extraction
    reports none) registers at confidence "unknown". A number
    is never invented to fill the gap: unknown confidence is
    itself the finding, and it queues like a low one.
  - CONFIDENCE_THRESHOLD = 0.90 (stated policy, below): a
    unit whose reported confidence is at or above it is
    recorded as above-threshold and never queues. Below it —
    or unknown — the unit is OPEN: unverified machine text.
  - The compiled-layer rule: a wiki page may not rest a cited
    claim on unverified extraction. `check` joins the register
    to the compiled pages citing each queued source (front-
    matter `sources:` or an inline ^[cite:] marker) and FLAGS
    the reliance. It surfaces only; it never edits a page.
  - Verification is a human act recorded on the register:
    `verify` (outcome "confirmed" — the text matches the
    original; or "kept" — ABBYY's Skip: checked, kept as-is),
    `reject` (the reading is wrong; the corrected text's
    location is REQUIRED and recorded — the bad reading is
    never silently overwritten, the rejection event is the
    correction's provenance). Verification resolves units;
    it does not rewrite the register: every transition is an
    appended event, and a resolved unit cannot be re-verified.
  - The project dictionary: `dict-add` records a confirmed
    word once; a queued unit whose whole text is that word is
    thereafter computed as dictionary-cleared instead of open
    (explicit verify/reject events on it still govern).

Register: evaluation/ocr-queue.jsonl — append-only, one JSON
object per line: a header, then events:

    {"kind": "enqueued", "id": "ocr-0001", "date": ...,
     "source": "raw/<path>", "method": "ocr" |
     "embedded-text" | "machine-transcription" | "other",
     "tool": <name or null>, "sensitivity": <class id or
     "unclassified">, "note": ...,
     "units": [{"unit": "p1", "locator": {"page": 1},
                "text": <optional, for word/span units>,
                "chars": <optional int>,
                "confidence": 0.87 | "unknown"}, ...]}
    {"kind": "verified", "id": ..., "unit": <unit id> | null,
     "units": [unit ids resolved], "date": ..., "by": ...,
     "outcome": "confirmed" | "kept", "note": ...}
    {"kind": "rejected", "id": ..., "unit": ... | null,
     "units": [...], "date": ..., "by": ...,
     "corrected_text_at": "raw/<path>", "note": ...}
    {"kind": "dictionary-add", "word": ..., "date": ...,
     "by": ..., "note": ...}

Unit states are COMPUTED by folding the events in order —
the events are the record; the fold is a view. Precedence:
rejected > verified > dictionary > above-threshold > open.

The ingest sidecar carries the same honesty one step earlier:
scripts/wiki_convert.py records an `extraction` block in every
<out>.ingest.json (method, the confidence the extractor
reported or "unknown", and the state — machine-unverified for
the guessing kinds: OCR and PDF embedded-text). An ingest that
produced machine-unverified text registers it here at ingest
time (`enqueue --from-sidecar <sidecar>` does it in one step).

Usage:
  python3 scripts/wiki_ocr_queue.py enqueue --source raw/<p>
      --method embedded-text [--tool pypdf]
      [--units units.json] [--confidence 0.87|unknown]
      [--note ...] [--date YYYY-MM-DD] [--root PATH]
  python3 scripts/wiki_ocr_queue.py enqueue --from-sidecar <p>
  python3 scripts/wiki_ocr_queue.py list [--json]
  python3 scripts/wiki_ocr_queue.py check [--json]
  python3 scripts/wiki_ocr_queue.py verify <id> [--unit p3]
      --by <who> [--outcome confirmed|kept] [--note ...]
  python3 scripts/wiki_ocr_queue.py reject <id> [--unit p3]
      --by <who> --corrected-text-at raw/<p> [--note ...]
  python3 scripts/wiki_ocr_queue.py dict-add <word> --by <who>
  python3 scripts/wiki_ocr_queue.py dict-list
Exit: 0 = ok (check: no flags); 1 = check found flags;
2 = usage error or a refused act. Stdlib only.
"""
import argparse
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import wiki_validate as wv  # noqa: E402  (frontmatter parser)

# Stated policy: a reported confidence at or above this value
# is recorded as above-threshold and never queues; below it —
# and "unknown", which cannot be shown to clear it — queues.
CONFIDENCE_THRESHOLD = 0.90

REGISTER_REL = "evaluation/ocr-queue.jsonl"
METHODS = ("ocr", "embedded-text", "machine-transcription",
           "other")
STRUCTURAL = {"wiki/index.md", "wiki/log.md"}
CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)")

HEADER = {
    "kind": "header",
    "register": "ocr-queue",
    "version": 1,
    "created": "WikiCitadel v1",
    "purpose": "The verification queue for machine-extracted "
               "text (WikiCitadel v1; "
               "pattern: ABBYY FineReader Verification, "
               "capture survey find 18). Every extraction an "
               "ingest relies on is registered with the "
               "confidence its extractor actually reported; "
               "units below CONFIDENCE_THRESHOLD (0.90) — and "
               "units whose extractor reported no confidence "
               "('unknown') — stand OPEN (unverified) until a "
               "human verifies or rejects them on this "
               "register. The compiled layer may not rest a "
               "cited claim on open units; "
               "scripts/wiki_ocr_queue.py check flags the "
               "reliance.",
    "maintenance": "Append-only, maintained with "
                   "scripts/wiki_ocr_queue.py (enqueue / verify "
                   "/ reject / dict-add append events; nothing "
                   "is rewritten or deleted — a rejection "
                   "records the corrected text's location "
                   "instead of overwriting the reading). Unit "
                   "states are computed by folding the events; "
                   "where this register and wiki/log.md "
                   "disagree, the human record governs.",
    "judgement_calls": [
        "Confidence is recorded exactly as the extractor "
        "reported it. pypdf (the wiki's only PDF extraction "
        "path, scripts/wiki_convert.py) reports no confidence "
        "at all, so embedded-text extractions register at "
        "'unknown' — unknown is treated as unverified, never "
        "as a number invented to clear the threshold.",
        "Skip is a verification outcome, not an omission: "
        "verify --outcome kept records ABBYY's Skip ('checked, "
        "kept as-is') as a human act with a verifier and a "
        "date, distinct from 'confirmed'.",
        "The dictionary clears a unit only when the unit's "
        "whole recorded text is the dictionary word — names "
        "stop flagging; passages do not get cleared by "
        "vocabulary.",
    ],
}


class QueueError(Exception):
    pass


# ------------------------------------------------------------ register

def register_path(root):
    return Path(root) / REGISTER_REL


def read_events(root):
    p = register_path(root)
    if not p.is_file():
        return []
    events = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def append_event(root, event):
    p = register_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if not p.is_file() or not p.read_text(encoding="utf-8").strip():
        lines.append(json.dumps(HEADER, ensure_ascii=False))
    lines.append(json.dumps(event, ensure_ascii=False))
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _next_id(events):
    top = 0
    for ev in events:
        m = re.fullmatch(r"ocr-(\d+)", str(ev.get("id") or ""))
        if m:
            top = max(top, int(m.group(1)))
    return f"ocr-{top + 1:04d}"


def dictionary_of(events):
    return {str(ev.get("word") or "").strip().casefold()
            for ev in events if ev.get("kind") == "dictionary-add"}


def _unit_disposition(unit, dictionary):
    conf = unit.get("confidence")
    if isinstance(conf, (int, float)) \
            and conf >= CONFIDENCE_THRESHOLD:
        return "above-threshold"
    text = str(unit.get("text") or "").strip().casefold()
    if text and text in dictionary:
        return "dictionary"
    return "open"


def fold(events):
    """Fold the register into entries with computed unit
    states. Returns (entries, dictionary) — entries is a list
    of dicts in enqueue order; each unit gains 'state' plus
    the resolving event's fields where one applies."""
    dictionary = dictionary_of(events)
    entries = []
    by_id = {}
    for ev in events:
        kind = ev.get("kind")
        if kind == "enqueued":
            entry = {
                "id": ev["id"], "source": ev.get("source"),
                "method": ev.get("method"),
                "tool": ev.get("tool"),
                "sensitivity": ev.get("sensitivity"),
                "date": ev.get("date"), "note": ev.get("note"),
                "units": {},
            }
            for u in ev.get("units") or []:
                rec = dict(u)
                rec["state"] = _unit_disposition(u, dictionary)
                entry["units"][u["unit"]] = rec
            entries.append(entry)
            by_id[entry["id"]] = entry
        elif kind in ("verified", "rejected"):
            entry = by_id.get(ev.get("id") or "")
            if entry is None:
                continue
            for uid in ev.get("units") or []:
                rec = entry["units"].get(uid)
                if rec is None:
                    continue
                if kind == "verified":
                    rec["state"] = ("verified-kept"
                                    if ev.get("outcome") == "kept"
                                    else "verified-confirmed")
                else:
                    rec["state"] = "rejected"
                    rec["corrected_text_at"] = \
                        ev.get("corrected_text_at")
                rec["by"] = ev.get("by")
                rec["resolved_date"] = ev.get("date")
    return entries, dictionary


def sensitivity_of(root, source_rel):
    """The source's sensitivity class from
    evaluation/sensitivity.json , by longest-prefix
    assignment match; 'unclassified' when none applies or the
    register is unreadable — unclassified is a state of its
    own, never read as a clearance."""
    reg = Path(root) / "evaluation" / "sensitivity.json"
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unclassified"
    best = None
    for a in data.get("assignments") or []:
        path = str(a.get("path") or "")
        if source_rel == path.rstrip("/") \
                or source_rel.startswith(path):
            if best is None or len(path) > len(best[0]):
                best = (path, a.get("class"))
    return best[1] if best else "unclassified"


# -------------------------------------------------------------- enqueue

def _check_confidence(value, where):
    if value == "unknown":
        return "unknown"
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise QueueError(
            f"{where}: confidence {value!r} is neither a "
            f"number nor 'unknown' — record what the extractor "
            f"reported, or 'unknown' when it reported nothing")
    if not 0.0 <= num <= 1.0:
        raise QueueError(
            f"{where}: confidence {num} outside [0, 1]")
    return num


def build_units(args):
    if args.units:
        try:
            raw = json.loads(
                Path(args.units).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise QueueError(f"--units: cannot read {args.units}"
                             f": {exc}")
        if not isinstance(raw, list) or not raw:
            raise QueueError("--units: expected a non-empty "
                             "JSON list of unit objects")
        units, seen = [], set()
        for i, u in enumerate(raw):
            if not isinstance(u, dict) or not u.get("unit"):
                raise QueueError(
                    f"--units[{i}]: each unit needs a 'unit' id")
            if u["unit"] in seen:
                raise QueueError(
                    f"--units: duplicate unit id {u['unit']!r}")
            seen.add(u["unit"])
            rec = {"unit": u["unit"],
                   "locator": u.get("locator") or {},
                   "confidence": _check_confidence(
                       u.get("confidence", "unknown"),
                       f"--units[{i}]")}
            if u.get("text") is not None:
                rec["text"] = u["text"]
            if u.get("chars") is not None:
                rec["chars"] = u["chars"]
            units.append(rec)
        return units
    return [{"unit": "whole",
             "locator": {"scope": "whole-source"},
             "confidence": _check_confidence(
                 args.confidence, "--confidence")}]


def cmd_enqueue(root, args):
    if args.from_sidecar:
        return _enqueue_from_sidecar(root, args)
    source = args.source
    if not source:
        raise QueueError("enqueue needs --source (or "
                         "--from-sidecar)")
    if args.method not in METHODS:
        raise QueueError(f"--method must be one of {METHODS}")
    if not (Path(root) / source).is_file():
        raise QueueError(
            f"source not on disk: {source} — the register "
            f"names only extractions of files the wiki holds")
    units = build_units(args)
    events = read_events(root)
    event = {
        "kind": "enqueued", "id": _next_id(events),
        "date": args.date or _date.today().isoformat(),
        "source": source, "method": args.method,
        "tool": args.tool,
        "sensitivity": sensitivity_of(root, source),
        "note": args.note, "units": units,
    }
    append_event(root, event)
    entries, _d = fold(read_events(root))
    entry = entries[-1]
    counts = _state_counts(entry)
    print(f"enqueued {event['id']}: {source} "
          f"({args.method}) — {len(units)} unit(s): "
          + _counts_text(counts))
    return 0


def _enqueue_from_sidecar(root, args):
    sc = Path(args.from_sidecar)
    if not sc.is_file():
        raise QueueError(f"no such sidecar: {sc}")
    try:
        data = json.loads(sc.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise QueueError(f"sidecar is not JSON: {exc}")
    ext = data.get("extraction") or {}
    if ext.get("state") != "machine-unverified":
        raise QueueError(
            f"sidecar extraction state is "
            f"{ext.get('state')!r}, not 'machine-unverified' — "
            f"only the guessing kinds (OCR, embedded-text) "
            f"queue; structural extraction and native text "
            f"have nothing to verify against an original")
    original = data.get("source") or ""
    op = Path(original)
    try:
        source = op.resolve().relative_to(
            Path(root).resolve()).as_posix()
    except ValueError:
        source = original
    if not (Path(root) / source).is_file():
        raise QueueError(
            f"sidecar's source not on disk under the root: "
            f"{original}")
    sub = argparse.Namespace(
        source=source, method=ext.get("method") or "other",
        tool=ext.get("tool"), units=None,
        confidence=ext.get("confidence", "unknown"),
        note=(args.note or
              f"registered from ingest sidecar {sc.name}"),
        date=args.date, from_sidecar=None)
    if sub.method not in METHODS:
        sub.method = "other"
    return cmd_enqueue(root, sub)


# ---------------------------------------------------------------- list

def _state_counts(entry):
    counts = {}
    for rec in entry["units"].values():
        counts[rec["state"]] = counts.get(rec["state"], 0) + 1
    return counts


def _counts_text(counts):
    order = ["open", "verified-confirmed", "verified-kept",
             "rejected", "above-threshold", "dictionary"]
    parts = [f"{counts[s]} {s}" for s in order if counts.get(s)]
    return " · ".join(parts) if parts else "no units"


def cmd_list(root, args):
    entries, dictionary = fold(read_events(root))
    if args.json:
        out = {"threshold": CONFIDENCE_THRESHOLD,
               "dictionary_words": len(dictionary),
               "entries": [
                   {"id": e["id"], "source": e["source"],
                    "method": e["method"], "tool": e["tool"],
                    "sensitivity": e["sensitivity"],
                    "date": e["date"],
                    "counts": _state_counts(e)}
                   for e in entries]}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"OCR verification queue — {len(entries)} entr"
          f"{'y' if len(entries) == 1 else 'ies'}, "
          f"dictionary {len(dictionary)} word(s), "
          f"threshold {CONFIDENCE_THRESHOLD}")
    if not entries:
        print("  register is empty — no extraction has been "
              "queued")
    for e in entries:
        print(f"  {e['id']}  {e['source']}  "
              f"[{e['method']}"
              f"{'/' + e['tool'] if e['tool'] else ''}]  "
              + _counts_text(_state_counts(e)))
    return 0


# --------------------------------------------------------------- check

def _cited_sources(root):
    """Map raw source path -> set of compiled pages citing it,
    by frontmatter `sources:` (exact path or stem match) or an
    inline ^[cite: <path>...] marker. The compiled layer is
    wiki/ minus the two structural files."""
    raw_files = {}
    raw_dir = Path(root) / "raw"
    if raw_dir.is_dir():
        for p in raw_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                raw_files.setdefault(p.stem, []).append(rel)
    cited = {}
    wiki_dir = Path(root) / "wiki"
    if not wiki_dir.is_dir():
        return cited
    for p in sorted(wiki_dir.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel in STRUCTURAL:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, _body = wv.parse_frontmatter(text)
        targets = set()
        for entry in wv.as_list((fields or {}).get("sources")):
            entry = str(entry).strip()
            if (Path(root) / entry).is_file() \
                    and entry.startswith("raw/"):
                targets.add(entry)
            else:
                for cand in raw_files.get(
                        Path(entry).stem, []):
                    targets.add(cand)
        for m in CITE_RE.finditer(text):
            if m.group(1).startswith("raw/"):
                targets.add(m.group(1))
        for t in targets:
            cited.setdefault(t, set()).add(rel)
    return cited


def run_check(root):
    events = read_events(root)
    entries, _d = fold(events)
    cited = _cited_sources(root)
    report = {"entries": len(entries), "open_units": 0,
              "flags": [], "open_uncited": []}
    for e in entries:
        counts = _state_counts(e)
        open_n = counts.get("open", 0)
        if not open_n:
            continue
        report["open_units"] += open_n
        pages = sorted(cited.get(e["source"], set()))
        if pages:
            report["flags"].append({
                "entry": e["id"], "source": e["source"],
                "method": e["method"],
                "open_units": open_n,
                "total_units": len(e["units"]),
                "pages": pages})
        else:
            report["open_uncited"].append({
                "entry": e["id"], "source": e["source"],
                "open_units": open_n})
    return report


def cmd_check(root, args):
    report = run_check(root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report["flags"] else 0
    print(f"OCR verification queue — check "
          f"({report['entries']} entr"
          f"{'y' if report['entries'] == 1 else 'ies'}, "
          f"{report['open_units']} open unit(s))")
    if report["flags"]:
        print("FLAGS — compiled pages resting cited claims on "
              "UNVERIFIED extraction:")
        for f in report["flags"]:
            print(f"  - {f['source']} [{f['entry']}, "
                  f"{f['method']}]: {f['open_units']} of "
                  f"{f['total_units']} unit(s) unverified; "
                  f"cited by:")
            for page in f["pages"]:
                print(f"      {page}")
    else:
        print("  no compiled page rests on unverified "
              "extraction")
    for o in report["open_uncited"]:
        print(f"  open, not yet cited by any compiled page: "
              f"{o['source']} [{o['entry']}] — "
              f"{o['open_units']} unit(s) awaiting verification")
    return 1 if report["flags"] else 0


# ---------------------------------------------------- verify / reject

def _resolve_targets(root, entry_id, unit_id):
    entries, _d = fold(read_events(root))
    entry = next((e for e in entries if e["id"] == entry_id),
                 None)
    if entry is None:
        raise QueueError(f"no queue entry {entry_id!r}")
    if unit_id:
        rec = entry["units"].get(unit_id)
        if rec is None:
            raise QueueError(
                f"entry {entry_id} has no unit {unit_id!r}")
        targets = [unit_id]
    else:
        targets = [u for u, r in entry["units"].items()
                   if r["state"] == "open"]
        if not targets:
            raise QueueError(
                f"entry {entry_id} has no open units — "
                f"nothing to resolve")
    for uid in targets:
        state = entry["units"][uid]["state"]
        if state != "open":
            raise QueueError(
                f"unit {entry_id}/{uid} is already {state} — "
                f"a resolved unit is not re-resolved; the "
                f"register is append-only and the earlier "
                f"event stands")
    return targets


def cmd_verify(root, args):
    targets = _resolve_targets(root, args.id, args.unit)
    event = {"kind": "verified", "id": args.id,
             "unit": args.unit, "units": targets,
             "date": args.date or _date.today().isoformat(),
             "by": args.by, "outcome": args.outcome,
             "note": args.note}
    append_event(root, event)
    print(f"verified {args.id}: {len(targets)} unit(s) "
          f"({args.outcome}) by {args.by}")
    return 0


def cmd_reject(root, args):
    if not args.corrected_text_at:
        raise QueueError(
            "reject requires --corrected-text-at: the "
            "corrected text's location is the correction's "
            "provenance — a reading is never just deleted")
    if not (Path(root) / args.corrected_text_at).is_file():
        raise QueueError(
            f"corrected text not on disk: "
            f"{args.corrected_text_at}")
    targets = _resolve_targets(root, args.id, args.unit)
    event = {"kind": "rejected", "id": args.id,
             "unit": args.unit, "units": targets,
             "date": args.date or _date.today().isoformat(),
             "by": args.by,
             "corrected_text_at": args.corrected_text_at,
             "note": args.note}
    append_event(root, event)
    print(f"rejected {args.id}: {len(targets)} unit(s) by "
          f"{args.by}; corrected text at "
          f"{args.corrected_text_at}")
    return 0


# ----------------------------------------------------------- dictionary

def cmd_dict_add(root, args):
    word = args.word.strip()
    if not word or len(word.split()) != 1:
        raise QueueError("dict-add takes a single word — the "
                         "dictionary clears word units, not "
                         "phrases")
    append_event(root, {
        "kind": "dictionary-add", "word": word,
        "date": args.date or _date.today().isoformat(),
        "by": args.by, "note": args.note})
    print(f"dictionary: added {word!r} (by {args.by})")
    return 0


def cmd_dict_list(root, args):
    _e, dictionary = fold(read_events(root))
    print(f"project dictionary — {len(dictionary)} word(s)")
    for w in sorted(dictionary):
        print(f"  {w}")
    return 0


# ----------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="repo root (default: the checkout "
                    "holding this script)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("enqueue")
    p.add_argument("--source", default=None)
    p.add_argument("--method", default=None)
    p.add_argument("--tool", default=None)
    p.add_argument("--units", default=None,
                   help="JSON file: list of unit objects "
                   "{unit, locator, text?, chars?, confidence}")
    p.add_argument("--confidence", default="unknown")
    p.add_argument("--from-sidecar", default=None,
                   help="register from an ingest sidecar's "
                   "extraction block instead")
    p.add_argument("--note", default=None)
    p.add_argument("--date", default=None)

    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("check")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("verify")
    p.add_argument("id")
    p.add_argument("--unit", default=None)
    p.add_argument("--by", required=True)
    p.add_argument("--outcome", default="confirmed",
                   choices=("confirmed", "kept"))
    p.add_argument("--note", default=None)
    p.add_argument("--date", default=None)

    p = sub.add_parser("reject")
    p.add_argument("id")
    p.add_argument("--unit", default=None)
    p.add_argument("--by", required=True)
    p.add_argument("--corrected-text-at", default=None)
    p.add_argument("--note", default=None)
    p.add_argument("--date", default=None)

    p = sub.add_parser("dict-add")
    p.add_argument("word")
    p.add_argument("--by", required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--date", default=None)

    sub.add_parser("dict-list")

    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else DEFAULT_ROOT
    try:
        if args.cmd == "enqueue":
            return cmd_enqueue(root, args)
        if args.cmd == "list":
            return cmd_list(root, args)
        if args.cmd == "check":
            return cmd_check(root, args)
        if args.cmd == "verify":
            return cmd_verify(root, args)
        if args.cmd == "reject":
            return cmd_reject(root, args)
        if args.cmd == "dict-add":
            return cmd_dict_add(root, args)
        if args.cmd == "dict-list":
            return cmd_dict_list(root, args)
    except QueueError as exc:
        print(f"wiki_ocr_queue: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
