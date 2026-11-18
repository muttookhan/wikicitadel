#!/usr/bin/env python3
"""wiki_opml.py — OPML 2.0 manual import/export for the clip/feed
registers (implementation wave W4, 2026-10-22; Round 13 filings:
"OPML 2.0 manual import/export" + "clip-time feed discovery" —
the discovery half lives in scripts/wiki_clip.py's
discover_feeds(), this module is the list-exchange half).

OPML 2.0 is a public specification (Dave Winer / UserLand);
this is a clean re-implementation from the spec — no code
copied from any reader. Royalty-free spec terms as opened in
the Round 13 filing.

THE SUBSCRIPTION SET. What exports is the union of:
  * evaluation/feed-subscriptions.jsonl — this tool's own
    append-only register (a header line, then one
    `subscription` event per imported feed; the fold takes the
    LATEST event per normalised feed URL, in the feed-clips
    register's discipline);
  * the distinct feeds of evaluation/feed-clips.jsonl, read
    through scripts/wiki_feed_register.py — the feeds items
    were actually clipped from (an explicit subscription record
    wins over the clip-derived one for the same feed).
A subscription here is a RECORD, never a standing watch:
import creates no subscription in the polling sense, this
module fetches NOTHING, and export reads only the two
registers (the Gap-9 boundary: no auto-watch, no background
anything — import and export are manual, file-handed acts).

A subscription record: {"feed", "title", "html_url",
"category"} — feed normalised by
wiki_feed_register.normalise_feed; title "" when none is
recorded (an OPML text/title equal to the feed URL reads back
as no title, which keeps the export->import round trip exact);
category a list of folder names, [] = top level.

IMPORT (a local file path only — never a URL):
  * the file is UNTRUSTED input: size-capped; DOCTYPE / ENTITY
    declarations refused outright (no XXE, no entity
    expansion — OPML needs neither); outline depth and count
    capped;
  * every candidate's title and category names pass the ingest
    injection gate — the gateway sanitiser, loaded exactly as
    scripts/wiki_convert.py loads it (wc._SANITIZE): a BLOCKED
    verdict refuses the feed; a FLAGGED verdict imports with
    the cleaned text and the findings named in the report; an
    unavailable gate is recorded as unavailable in the report,
    never silent (the converter's degraded-run discipline);
  * URLs must be http(s) with a host: a bad xmlUrl refuses the
    feed, a bad htmlUrl drops just that field (named in the
    report);
  * dedupe is the feed register's normalisation: a feed
    already in the set is reported already-known (with where
    it is known from) and never appended twice;
  * constructs this model does not carry are reported as
    UNMODELLED, by name, in the import report — never silently
    dropped.

EXPORT writes one OPML 2.0 document: head (title,
dateCreated in RFC 822 form), body of folder outlines for the
categories and type="rss" subscription outlines carrying
text / title / xmlUrl / htmlUrl.

    python3 scripts/wiki_opml.py [--root DIR]
        export [--out FILE] [--title TEXT]
        import FILE [--json]
        list [--json]

Exit: 0 ok · 1 door failure / refusal · 2 usage error.
Stdlib only; no network anywhere in this module.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wiki_feed_register as wfr  # noqa: E402  (normalisation + register)
import wiki_convert as wc  # noqa: E402  (the gate: wc._SANITIZE)

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = Path("evaluation/feed-subscriptions.jsonl")
HEADER = {
    "kind": "header", "register": "feed-subscriptions",
    "version": 1, "created": "2026-10-22",
    "purpose": "Append-only register of feed subscriptions "
               "landed by MANUAL OPML import (scripts/"
               "wiki_opml.py): a record of the subscription "
               "list, never a standing watch — nothing polls "
               "these feeds (Gap-9 boundary). States computed "
               "by folding events in order; never rewritten.",
    "maintenance": "Append-only via scripts/wiki_opml.py "
                   "import; states computed by folding events "
                   "in order; never rewritten.",
}

MAX_BYTES = 10_000_000
MAX_OUTLINES = 10_000
MAX_DEPTH = 32
FEED_TYPES = ("rss", "atom")
_MODELLED_ATTRS = {"text", "title", "xmlUrl", "htmlUrl", "type"}
_MODELLED_HEAD = {"title", "datecreated", "datemodified",
                  "ownername", "owneremail", "docs"}


class OpmlError(Exception):
    """A refusal or a door failure. Nothing is written."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _localname(tag):
    return tag.rsplit("}", 1)[-1].lower() \
        if isinstance(tag, str) else ""


# ------------------------------------------------------------ the register

def register_path(root: Path) -> Path:
    return root / REGISTER_REL


def read_subscription_events(root: Path) -> list[dict]:
    p = register_path(root)
    if not p.is_file():
        return []
    events = []
    for line in p.read_text(encoding="utf-8",
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn final line tolerated, register discipline
        if obj.get("kind") == "subscription":
            events.append(obj)
    return events


def fold_subscriptions(events: list[dict]) -> dict[str, dict]:
    """Latest event per normalised feed wins."""
    out: dict[str, dict] = {}
    for ev in events:
        feed = ev.get("feed")
        if not feed:
            continue
        out[feed] = {
            "feed": feed,
            "title": ev.get("title") or "",
            "html_url": ev.get("html_url"),
            "category": list(ev.get("category") or []),
            "known_from": "feed-subscriptions",
        }
    return out


def append_subscription(root: Path, record: dict,
                        source_name: str, ts: str = None) -> None:
    p = register_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    need_header = not p.is_file() or p.stat().st_size == 0
    event = {"kind": "subscription", "feed": record["feed"],
             "title": record["title"],
             "html_url": record["html_url"],
             "category": list(record["category"]),
             "imported_from": source_name, "ts": ts or _now()}
    with p.open("a", encoding="utf-8") as fh:
        if need_header:
            fh.write(json.dumps(HEADER, sort_keys=True) + "\n")
        fh.write(json.dumps(event, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def subscription_set(root: Path) -> list[dict]:
    """The wiki's feed/reading sources: clip-register feeds
    overlaid by the explicit subscription register, deduped by
    normalised feed URL, sorted by (category, feed)."""
    merged: dict[str, dict] = {}
    for item in wfr.fold(wfr.read_events(root)).values():
        feed = item.get("feed")
        if not feed:
            continue
        feed = wfr.normalise_feed(feed)
        merged.setdefault(feed, {
            "feed": feed, "title": "", "html_url": None,
            "category": [], "known_from": "feed-clips"})
    for feed, rec in fold_subscriptions(
            read_subscription_events(root)).items():
        merged[feed] = rec
    return sorted(merged.values(),
                  key=lambda r: (r["category"], r["feed"]))


# ------------------------------------------------------------ export

def _folder_tree(records: list[dict]) -> dict:
    """Nested {name: subtree} / {"": [records]} tree by category."""
    tree: dict = {"": []}
    for rec in records:
        node = tree
        for seg in rec["category"]:
            node = node.setdefault(seg, {"": []})
        node[""].append(rec)
    return tree


def _emit_outlines(parent: ET.Element, tree: dict) -> None:
    for name in sorted(k for k in tree if k != ""):
        folder = ET.SubElement(parent, "outline",
                               {"text": name, "title": name})
        _emit_outlines(folder, tree[name])
    for rec in sorted(tree[""], key=lambda r: r["feed"]):
        attrs = {"text": rec["title"] or rec["feed"],
                 "title": rec["title"] or rec["feed"],
                 "type": "rss", "xmlUrl": rec["feed"]}
        if rec["html_url"]:
            attrs["htmlUrl"] = rec["html_url"]
        ET.SubElement(parent, "outline", attrs)


def render_opml(records: list[dict],
                title: str = "LLM Wiki feed subscriptions",
                created: datetime = None) -> str:
    created = created or datetime.now(timezone.utc)
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = title
    ET.SubElement(head, "dateCreated").text = formatdate(
        created.timestamp(), usegmt=True)
    body = ET.SubElement(opml, "body")
    _emit_outlines(body, _folder_tree(records))
    ET.indent(opml, space="  ")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(opml, encoding="unicode") + "\n")


# ------------------------------------------------------------ import: parse

def parse_opml_bytes(data: bytes):
    """Defensive OPML parse. Returns (candidates, unmodelled,
    head) — candidates are RAW (pre-gate) dicts {xml_url,
    title, html_url, category}; unmodelled names every construct
    the model does not carry. Raises OpmlError on a refused or
    unreadable document."""
    if len(data) > MAX_BYTES:
        raise OpmlError(
            "door failure: OPML file is %d bytes, over the %d "
            "byte cap — refusing to parse it"
            % (len(data), MAX_BYTES))
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise OpmlError(
            "refused: DOCTYPE / ENTITY declarations are not "
            "accepted in OPML input (no external entities, no "
            "entity expansion — OPML needs neither)")
    try:
        root_el = ET.fromstring(data)
    except ET.ParseError as exc:
        raise OpmlError("door failure: file is not readable "
                        "XML: %s" % exc) from exc
    if _localname(root_el.tag) != "opml":
        raise OpmlError("door failure: root element is <%s>, "
                        "not <opml>" % _localname(root_el.tag))
    unmodelled: list[dict] = []
    head: dict = {}
    version = root_el.get("version")
    if version and version not in ("1.0", "1.1", "2.0"):
        unmodelled.append({
            "construct": "opml version", "name": version,
            "note": "the model carries OPML 2.0; the structure "
                    "was still read"})
    for attr in root_el.attrib:
        if attr != "version":
            unmodelled.append({"construct": "opml attribute",
                               "name": attr})
    head_el = body_el = None
    for child in root_el:
        name = _localname(child.tag)
        if name == "head":
            head_el = child
        elif name == "body":
            body_el = child
        else:
            unmodelled.append({"construct": "opml child element",
                               "name": name})
    if head_el is not None:
        for el in head_el:
            name = _localname(el.tag)
            if name in _MODELLED_HEAD:
                if name not in head:
                    head[name] = (el.text or "").strip()
            else:
                unmodelled.append({"construct": "head element",
                                   "name": name})
    if body_el is None:
        raise OpmlError("door failure: OPML document carries "
                        "no <body>")
    candidates: list[dict] = []
    counter = [0]

    def walk(el, category, depth):
        if depth > MAX_DEPTH:
            raise OpmlError(
                "refused: outline nesting deeper than %d "
                "levels" % MAX_DEPTH)
        for child in el:
            if _localname(child.tag) != "outline":
                unmodelled.append({
                    "construct": "body child element",
                    "name": _localname(child.tag)})
                continue
            counter[0] += 1
            if counter[0] > MAX_OUTLINES:
                raise OpmlError(
                    "refused: more than %d outlines" % MAX_OUTLINES)
            attrs = child.attrib
            label = attrs.get("text") or attrs.get("xmlUrl") or ""
            for attr in attrs:
                if attr not in _MODELLED_ATTRS:
                    unmodelled.append({
                        "construct": "outline attribute",
                        "name": attr, "outline": label})
            kids = [c for c in child
                    if _localname(c.tag) == "outline"]
            for c in child:
                if _localname(c.tag) != "outline":
                    unmodelled.append({
                        "construct": "outline child element",
                        "name": _localname(c.tag),
                        "outline": label})
            xml_url = (attrs.get("xmlUrl") or "").strip()
            if xml_url:
                otype = (attrs.get("type") or "").strip().lower()
                if otype and otype not in FEED_TYPES:
                    unmodelled.append({
                        "construct": "outline type",
                        "name": attrs.get("type"),
                        "outline": label,
                        "note": "not an rss/atom subscription "
                                "outline; not imported"})
                    continue
                title_attr = attrs.get("title")
                text_attr = attrs.get("text")
                if title_attr is not None \
                        and text_attr is not None \
                        and title_attr != text_attr:
                    unmodelled.append({
                        "construct": "separate text and title",
                        "outline": label,
                        "note": "the model carries one title; "
                                "the title attribute was used"})
                candidates.append({
                    "xml_url": xml_url,
                    "title": (title_attr if title_attr is not None
                              else text_attr) or "",
                    "html_url": (attrs.get("htmlUrl")
                                 or "").strip() or None,
                    "category": list(category)})
                if kids:
                    unmodelled.append({
                        "construct": "outlines nested under a "
                                     "subscription outline",
                        "outline": label,
                        "note": "read into the same category"})
                    walk(child, category, depth + 1)
            elif kids:
                seg = (attrs.get("text") or attrs.get("title")
                       or "").strip()
                if seg:
                    walk(child, category + [seg], depth + 1)
                else:
                    unmodelled.append({
                        "construct": "unnamed folder outline",
                        "note": "its children were read at the "
                                "parent level"})
                    walk(child, category, depth + 1)
            elif (attrs.get("type") or "").strip():
                unmodelled.append({
                    "construct": "outline type",
                    "name": attrs.get("type"),
                    "outline": label,
                    "note": "not an rss/atom subscription "
                            "outline; not imported"})
            else:
                unmodelled.append({
                    "construct": "outline with neither xmlUrl "
                                 "nor children (not a feed, not "
                                 "a folder)", "outline": label})

    walk(body_el, [], 0)
    return candidates, unmodelled, head


# ------------------------------------------------------------ import: the gate

def _gate_text(text: str):
    """Run one untrusted string through the ingest injection
    gate (the gateway sanitiser, via wiki_convert's loader).
    Returns (text_to_store, verdict, finding_kinds). A BLOCKED
    verdict returns (None, ...) — the caller refuses the feed.
    An unavailable gate passes the text through with the
    verdict recorded, per the converter's discipline."""
    san = wc._SANITIZE
    if san is None:
        return text, "unavailable", []
    scan = san.scan_text(text)
    kinds = sorted({f.get("kind", "?") for f in scan["findings"]})
    if scan["verdict"] == "blocked":
        return None, "blocked", kinds
    if scan["verdict"] == "flagged":
        cleaned, _ = san.clean_text(text)
        return cleaned.strip(), "flagged", kinds
    return text, "clean", kinds


def _valid_feed_url(url: str) -> bool:
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") \
        and bool(parts.hostname)


def import_opml(root: Path, path, now: str = None) -> dict:
    """Import one handed-in OPML file. Returns the import
    report; raises OpmlError on a door failure (nothing is
    written in that case)."""
    src = Path(path)
    try:
        data = src.read_bytes()
    except OSError as exc:
        raise OpmlError("door failure: cannot read %s: %s"
                        % (src, exc)) from exc
    if not data:
        raise OpmlError("door failure: %s is empty — refusing "
                        "to import an empty list" % src)
    candidates, unmodelled, head = parse_opml_bytes(data)
    existing = {r["feed"]: r for r in subscription_set(root)}
    report = {
        "tool": "scripts/wiki_opml.py", "kind": "opml-import-report",
        "file": src.name, "head": head,
        "gate": "available" if wc._SANITIZE is not None
                else "unavailable",
        "imported": [], "already_known": [], "refused": [],
        "unmodelled": unmodelled, "ts": now or _now(),
    }
    for cand in candidates:
        if not _valid_feed_url(cand["xml_url"]):
            report["refused"].append({
                "xml_url": cand["xml_url"],
                "reason": "xmlUrl is not an http(s) URL with "
                          "a host"})
            continue
        feed = wfr.normalise_feed(cand["xml_url"])
        title, verdict, kinds = _gate_text(cand["title"])
        if title is None:
            report["refused"].append({
                "feed": feed,
                "reason": "title blocked by the injection gate",
                "gate_findings": kinds})
            continue
        if title == cand["xml_url"] or title == feed:
            title = ""  # a title equal to the feed URL is no title
        category, cat_notes = [], []
        refused_cat = False
        for seg in cand["category"]:
            cleaned, seg_verdict, seg_kinds = _gate_text(seg)
            if cleaned is None:
                report["refused"].append({
                    "feed": feed,
                    "reason": "category name %r blocked by the "
                              "injection gate" % seg,
                    "gate_findings": seg_kinds})
                refused_cat = True
                break
            if seg_verdict == "flagged":
                cat_notes.append("category %r cleaned by the "
                                 "gate (%s)"
                                 % (seg, ", ".join(seg_kinds)))
            if cleaned:
                category.append(cleaned)
            else:
                cat_notes.append("category name %r emptied by "
                                 "the gate and dropped" % seg)
        if refused_cat:
            continue
        html_url = cand["html_url"]
        html_note = None
        if html_url is not None and not _valid_feed_url(html_url):
            html_note = ("htmlUrl %r is not an http(s) URL with "
                         "a host; the field was dropped"
                         % html_url)
            html_url = None
        if feed in existing:
            report["already_known"].append({
                "feed": feed,
                "known_from": existing[feed]["known_from"]})
            continue
        record = {"feed": feed, "title": title,
                  "html_url": html_url, "category": category}
        append_subscription(root, record, src.name, ts=report["ts"])
        existing[feed] = {**record, "known_from": "feed-subscriptions"}
        entry = {"feed": feed, "title": title,
                 "html_url": html_url, "category": category,
                 "gate_verdict": verdict}
        if kinds:
            entry["gate_findings"] = kinds
        if html_note:
            entry["notes"] = [html_note]
        if cat_notes:
            entry.setdefault("notes", []).extend(cat_notes)
        report["imported"].append(entry)
    report["stats"] = {
        "candidates": len(candidates),
        "imported": len(report["imported"]),
        "already_known": len(report["already_known"]),
        "refused": len(report["refused"]),
        "unmodelled": len(report["unmodelled"]),
    }
    return report


# ------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    ep = sub.add_parser("export")
    ep.add_argument("--out", default=None,
                    help="write the OPML here (default: stdout)")
    ep.add_argument("--title", default="LLM Wiki feed subscriptions")
    ip = sub.add_parser("import")
    ip.add_argument("file")
    ip.add_argument("--json", action="store_true")
    lp = sub.add_parser("list")
    lp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.cmd == "export":
            text = render_opml(subscription_set(root),
                               title=args.title)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                print("exported %d subscription(s) to %s"
                      % (len(subscription_set(root)), args.out))
            else:
                sys.stdout.write(text)
            return 0
        if args.cmd == "list":
            records = subscription_set(root)
            if args.json:
                print(json.dumps({"subscriptions": records},
                                 indent=2, sort_keys=True))
            else:
                for r in records:
                    cat = "/".join(r["category"]) or "-"
                    print("%s  [%s] %s" % (r["feed"], cat,
                                           r["title"] or ""))
                print("%d subscription(s)" % len(records))
            return 0
        if args.cmd == "import":
            if re.match(r"^https?://", args.file or "", re.I):
                print("wiki_opml: import is file-handed only — "
                      "give a local OPML file, never a URL",
                      file=sys.stderr)
                return 2
            report = import_opml(root, args.file)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                st = report["stats"]
                print("import %s: %d candidate(s) — %d imported, "
                      "%d already known, %d refused, %d "
                      "unmodelled construct(s); gate %s"
                      % (report["file"], st["candidates"],
                         st["imported"], st["already_known"],
                         st["refused"], st["unmodelled"],
                         report["gate"]))
                for e in report["imported"]:
                    print("  imported: %s" % e["feed"])
                for e in report["already_known"]:
                    print("  already known (%s): %s"
                          % (e["known_from"], e["feed"]))
                for e in report["refused"]:
                    print("  REFUSED: %s — %s"
                          % (e.get("feed") or e.get("xml_url"),
                             e["reason"]))
                for u in report["unmodelled"]:
                    print("  unmodelled: %s %s"
                          % (u["construct"], u.get("name")
                             or u.get("outline") or ""))
            return 0
    except OpmlError as exc:
        print("wiki_opml: %s" % exc, file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
