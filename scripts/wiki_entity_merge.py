#!/usr/bin/env python3
"""wiki_entity_merge.py — entity-resolution merge PROPOSALS.

Marathon Round 3, Lane TA5 (Tier A). Pattern: sage-wiki's
entity resolution, re-implemented from the idea (no code
copied): as a wiki grows, the same entity accretes two pages
under variant names ("Aster Vale" / "A. Vale" / "aster-vale")
and answers split across them. This tool finds candidate
duplicate ENTITY pages and files merge proposals — it NEVER
merges, renames, redirects or edits any page. A human (or a
reviewing agent) decides each pair.

Candidates (deterministic, all signals stated as evidence):
  alias-match     one page's frontmatter `aliases:` names the
                  other's title, stem or normalised name;
  name-similarity normalised titles score >= NAME_THRESHOLD
                  by difflib ratio, or their token sets score
                  >= TOKEN_THRESHOLD by Jaccard;
  stem-similarity the same two tests over file stems.
Corroborating evidence (reported, never required): shared
`sources:`, shared tags, and pages that link to both.

Suggested survivor (a suggestion only, reasons stated):
more sources wins, then the longer body, then the earlier
`created`, then the lexicographically smaller path.

Output: a filing pair under wiki/filings/ —
entity-merge-<date>.md (human-readable proposals) and
entity-merge-<date>.json (the manifest, kind
"entity-merge-proposals"). Exit codes: 0 ok (candidates or
none) · 2 usage error.

    python3 scripts/wiki_entity_merge.py [--root DIR]
                                         [--date YYYY-MM-DD]
                                         [--dry-run]

Stdlib only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NAME_THRESHOLD = 0.82    # difflib ratio on normalised titles
TOKEN_THRESHOLD = 0.6    # Jaccard on title/stem token sets

_spec = importlib.util.spec_from_file_location(
    "wiki_validate", Path(__file__).resolve().parent / "wiki_validate.py")
_wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wv)
parse_frontmatter, as_list = _wv.parse_frontmatter, _wv.as_list

TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalise(name: str) -> str:
    """A name reduced for comparison: lowercase tokens, single
    spaces. 'A. Vale' and 'a vale' normalise identically."""
    return " ".join(TOKEN_RE.findall(str(name).lower()))


def tokens(name: str) -> set[str]:
    return set(TOKEN_RE.findall(str(name).lower()))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def load_entities(root: Path) -> list[dict]:
    """Entity pages (wiki/entities/*.md) with the fields the
    detectors need, sorted by path for determinism."""
    out = []
    ent = Path(root) / "wiki" / "entities"
    if not ent.is_dir():
        return out
    for p in sorted(ent.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, body = parse_frontmatter(text)
        fields = fields or {}
        out.append({
            "rel": str(p.relative_to(root)),
            "stem": p.stem,
            "title": str(fields.get("title") or p.stem),
            "aliases": [str(a) for a in as_list(fields.get("aliases"))],
            "sources": sorted(str(s) for s in as_list(fields.get("sources"))),
            "tags": sorted(str(s) for s in as_list(fields.get("tags"))),
            "created": str(fields.get("created") or ""),
            "body_chars": len(body or ""),
            "body": body or "",
        })
    return out


def pair_signals(a: dict, b: dict) -> list[dict]:
    """The firing duplicate signals for one pair, strongest
    first. Empty list = not a candidate."""
    sig = []
    a_names = {normalise(a["title"]), normalise(a["stem"])}
    b_names = {normalise(b["title"]), normalise(b["stem"])}
    for alias in a["aliases"]:
        if normalise(alias) in b_names:
            sig.append({"signal": "alias-match",
                        "detail": f"{a['rel']} alias '{alias}' names {b['rel']}"})
    for alias in b["aliases"]:
        if normalise(alias) in a_names:
            sig.append({"signal": "alias-match",
                        "detail": f"{b['rel']} alias '{alias}' names {a['rel']}"})
    r = ratio(normalise(a["title"]), normalise(b["title"]))
    if r >= NAME_THRESHOLD:
        sig.append({"signal": "name-similarity",
                    "detail": f"title ratio {r:.2f} >= {NAME_THRESHOLD}"})
    j = jaccard(tokens(a["title"]), tokens(b["title"]))
    if j >= TOKEN_THRESHOLD:
        sig.append({"signal": "name-similarity",
                    "detail": f"title token Jaccard {j:.2f} >= {TOKEN_THRESHOLD}"})
    rs = ratio(normalise(a["stem"]), normalise(b["stem"]))
    if rs >= NAME_THRESHOLD:
        sig.append({"signal": "stem-similarity",
                    "detail": f"stem ratio {rs:.2f} >= {NAME_THRESHOLD}"})
    js = jaccard(tokens(a["stem"]), tokens(b["stem"]))
    if js >= TOKEN_THRESHOLD:
        sig.append({"signal": "stem-similarity",
                    "detail": f"stem token Jaccard {js:.2f} >= {TOKEN_THRESHOLD}"})
    return sig


def suggest_survivor(a: dict, b: dict) -> tuple[dict, dict, str]:
    """(survivor, other, reason) by the stated rule order:
    sources count, body length, earlier created, path."""
    key = lambda p: (-len(p["sources"]), -p["body_chars"],
                     p["created"] or "9999", p["rel"])
    survivor, other = (a, b) if key(a) <= key(b) else (b, a)
    if len(a["sources"]) != len(b["sources"]):
        reason = (f"more sources ({len(survivor['sources'])} vs "
                  f"{len(other['sources'])})")
    elif a["body_chars"] != b["body_chars"]:
        reason = (f"longer body ({survivor['body_chars']} vs "
                  f"{other['body_chars']} chars)")
    elif a["created"] != b["created"]:
        reason = f"earlier created ({survivor['created']})"
    else:
        reason = "lexicographically smaller path (final tie-break)"
    return survivor, other, reason


def find_candidates(root: Path) -> list[dict]:
    """All candidate duplicate pairs with evidence and a
    suggested survivor. Proposal dicts, sorted by pair."""
    entities = load_entities(root)
    # Pages linking to an entity stem, for co-link evidence.
    linkers: dict[str, set[str]] = {}
    wiki = Path(root) / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            rel = str(p.relative_to(root))
            text = p.read_text(encoding="utf-8", errors="ignore")
            for target in re.findall(r"\[\[([^\]|#]+)", text):
                stem = Path(target).stem
                linkers.setdefault(stem, set()).add(rel)
    out = []
    for i, a in enumerate(entities):
        for b in entities[i + 1:]:
            sig = pair_signals(a, b)
            if not sig:
                continue
            survivor, other, reason = suggest_survivor(a, b)
            pid = hashlib.sha1(
                f"merge|{a['rel']}|{b['rel']}".encode()).hexdigest()[:8]
            out.append({
                "id": f"entity-merge-{pid}",
                "kind": "entity-merge-proposal",
                "status": "proposed",
                "pair": [a["rel"], b["rel"]],
                "signals": sig,
                "evidence": {
                    "shared_sources": sorted(set(a["sources"])
                                             & set(b["sources"])),
                    "shared_tags": sorted(set(a["tags"]) & set(b["tags"])),
                    "co_linkers": sorted(
                        linkers.get(a["stem"], set())
                        & linkers.get(b["stem"], set())),
                },
                "suggested_survivor": survivor["rel"],
                "suggested_absorbed": other["rel"],
                "survivor_reason": reason,
            })
    out.sort(key=lambda p: p["pair"])
    return out


def analyse(root: Path, today: date | None = None) -> dict:
    today = today or date.today()
    proposals = find_candidates(root)
    return {
        "tool": "scripts/wiki_entity_merge.py",
        "kind": "entity-merge-proposals",
        "pattern": "sage-wiki entity resolution — proposals "
                   "only; this tool never merges",
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "date": today.isoformat(),
        "stats": {"entity_pages": len(load_entities(root)),
                  "proposals": len(proposals)},
        "proposals": proposals,
    }


def render_filing(manifest: dict) -> str:
    d = manifest["date"]
    lines = [
        "---",
        f"title: Entity merge proposals — {d}",
        "type: query",
        f"created: {d}",
        f"updated: {d}",
        "sources: []",
        "tags: [entity-merge, proposal, filings]",
        "status: draft",
        "stage: seedling",
        f"planted: {d}",
        f"tended: {d}",
        "work_type: record",
        "---",
        "",
        f"# Entity merge proposals — {d}",
        "",
        "> [!warning] PROPOSALS ONLY — nothing has been merged",
        "> Generated by `scripts/wiki_entity_merge.py` "
        "(Marathon R3 TA5; sage-wiki pattern). Each pair below "
        "is a candidate duplicate with its evidence. A reviewer "
        "decides; any real merge is a separate, recorded act.",
        "",
        f"Scanned {manifest['stats']['entity_pages']} entity "
        f"page(s) → {manifest['stats']['proposals']} candidate "
        f"pair(s).",
        "",
    ]
    if not manifest["proposals"]:
        lines += ["No candidate duplicate pairs this run.", ""]
    for p in manifest["proposals"]:
        lines += [f"## {p['id']}: {p['pair'][0]} + {p['pair'][1]}", "",
                  f"Suggested survivor: **{p['suggested_survivor']}** "
                  f"({p['survivor_reason']}); suggested absorbed: "
                  f"{p['suggested_absorbed']}.", "",
                  "Signals:"]
        lines += [f"- {s['signal']}: {s['detail']}" for s in p["signals"]]
        lines += ["", f"Evidence: `{json.dumps(p['evidence'], sort_keys=True)}`", ""]
    return "\n".join(lines)


def write_filing(root: Path, manifest: dict) -> tuple[Path, Path]:
    base = Path(root) / "wiki" / "filings" / f"entity-merge-{manifest['date']}"
    md_path, json_path = base.with_suffix(".md"), base.with_suffix(".json")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_filing(manifest), encoding="utf-8")
    json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)
                         + "\n", encoding="utf-8")
    return md_path, json_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the manifest JSON; write nothing")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    today = date.fromisoformat(args.date) if args.date else date.today()
    manifest = analyse(root, today=today)
    if args.dry_run:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    md_path, json_path = write_filing(root, manifest)
    print(f"entity merge: {manifest['stats']['entity_pages']} entity "
          f"page(s) -> {manifest['stats']['proposals']} proposal(s)")
    for p in manifest["proposals"]:
        print(f"  {p['id']}: {p['pair'][0]} + {p['pair'][1]} "
              f"-> survivor {p['suggested_survivor']}")
    print(f"filing:   {md_path.relative_to(root)}")
    print(f"manifest: {json_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
