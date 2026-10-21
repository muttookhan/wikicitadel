#!/usr/bin/env python3
"""Expiring intentions (Marathon R3 lane TB1, row 4).

Pattern adapted with credit from Hy Memory 2.0 (Tencent
Hunyuan, Apache-2.0 per its LICENSE): prospective
intention-type memories carry an expiry, after which they are
automatically demoted to ordinary facts.

Here: a wiki page is an INTENTION claim when its frontmatter
carries ``claim_type: intention`` (or ``type: intention``)
together with a ``claim:`` and an ``expires: YYYY-MM-DD``.
While unexpired it stands as an intention
(``intention_status: active``, the default when the field is
absent). Once ``expires`` passes, the claim DEMOTES: it stops
standing as a live intention and becomes an ordinary recorded
fact.

Modes (a claims-tool mode, beside scripts/wiki_claims.py):

  list            List every intention claim under --root
                  with its expiry and status as of --as-of
                  (default: today). Read-only.
  demote          DRY-RUN by default: report the expired,
                  not-yet-demoted intentions. With --apply,
                  append one demotion event per claim to
                  ``evaluation/intention-demotions.jsonl``
                  under --root AND set ``intention_status:
                  demoted`` + ``demoted: <date>`` in the page's
                  frontmatter. --apply is the only writing
                  mode, and it writes only under --root — the
                  tests point --root at fixture trees, never at
                  the live tree.

Exit 0 = ok (expired-but-undemoted intentions in list/dry-run
are findings, printed, not failures); 1 = a demote --apply
found a page it could not update; 2 = usage error.
Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

EVENTS_REL = "evaluation/intention-demotions.jsonl"


def _load_validate():
    path = Path(__file__).resolve().parent / "wiki_validate.py"
    spec = importlib.util.spec_from_file_location("wiki_validate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_wv = _load_validate()
parse_frontmatter = _wv.parse_frontmatter
parse_date = _wv.parse_date


def intention_pages(root: Path):
    """[(rel, fields)] for intention claims under *root*/wiki."""
    wiki = Path(root) / "wiki"
    out = []
    if not wiki.is_dir():
        return out
    for p in sorted(wiki.rglob("*.md")):
        fields, _body = parse_frontmatter(
            p.read_text(encoding="utf-8", errors="ignore"))
        if not fields:
            continue
        kind = str(fields.get("claim_type") or fields.get("type") or "")
        if kind != "intention" or not fields.get("claim"):
            continue
        out.append((p.relative_to(root).as_posix(), fields, p))
    return out


def status_of(fields: dict, as_of: date) -> dict:
    """One intention's standing as of *as_of*."""
    expires_raw = fields.get("expires")
    expires = parse_date(str(expires_raw)) if expires_raw else None
    recorded = str(fields.get("intention_status") or "active")
    expired = expires is not None and expires < as_of
    return {
        "expires": str(expires_raw) if expires_raw else None,
        "expires_valid": expires is not None,
        "recorded_status": recorded,
        "expired": expired,
        "demotion_due": expired and recorded != "demoted",
        "effective_status": "demoted" if (recorded == "demoted" or expired)
                            else "active",
    }


def list_intentions(root: Path, as_of: date) -> list:
    rows = []
    for rel, fields, _p in intention_pages(root):
        row = {"page": rel, "claim": str(fields.get("claim"))}
        row.update(status_of(fields, as_of))
        rows.append(row)
    return rows


def _set_fm(text: str, updates: dict) -> str:
    """Set scalar frontmatter fields, preserving the rest
    (same discipline as wiki_claims._set_fm_fields)."""
    m = re.match(r"^(---\n)(.*?)(\n---\n?)", text, re.S)
    if not m:
        raise ValueError("page has no frontmatter block")
    head, fm, tail = m.group(1), m.group(2), m.group(3)
    lines = fm.split("\n")
    remaining = dict(updates)
    for i, line in enumerate(lines):
        km = re.match(r"^([A-Za-z_]+):", line)
        if km and km.group(1) in remaining:
            lines[i] = f"{km.group(1)}: {remaining.pop(km.group(1))}"
    for key in ("intention_status", "demoted"):
        if key in remaining:
            lines.append(f"{key}: {remaining.pop(key)}")
    return head + "\n".join(lines) + tail + text[m.end():]


def demote(root: Path, as_of: date, apply: bool) -> dict:
    """Demote every due intention under *root* (or report them).

    Returns {"due": [...], "events": [...], "applied": bool}.
    With apply=False nothing is written anywhere.
    """
    root = Path(root)
    due = [r for r in list_intentions(root, as_of) if r["demotion_due"]]
    events = [{
        "kind": "intention-demotion",
        "page": r["page"],
        "claim": r["claim"],
        "expires": r["expires"],
        "demoted_on": as_of.isoformat(),
        "from_status": "active",
        "to_status": "demoted",
    } for r in due]
    if apply and events:
        by_rel = {rel: p for rel, _f, p in intention_pages(root)}
        for event in events:
            page_path = by_rel[event["page"]]
            text = page_path.read_text(encoding="utf-8")
            page_path.write_text(_set_fm(text, {
                "intention_status": "demoted",
                "demoted": as_of.isoformat(),
            }), encoding="utf-8")
        events_path = root / EVENTS_REL
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(events_path, "a", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"due": due, "events": events, "applied": bool(apply and events)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--as-of", default=None,
                    help="YYYY-MM-DD (default: today)")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list intention claims + status")
    p_dem = sub.add_parser("demote", help="demote expired intentions")
    p_dem.add_argument("--apply", action="store_true",
                       help="write demotion events + page updates "
                            "(default: dry run)")
    args = ap.parse_args(argv)
    as_of = parse_date(args.as_of) if args.as_of else date.today()
    if as_of is None:
        print(f"--as-of {args.as_of!r} is not an ISO date", file=sys.stderr)
        return 2
    root = Path(args.root)
    if args.cmd == "list":
        rows = list_intentions(root, as_of)
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['page']}: {r['effective_status']} "
                      f"(expires {r['expires']}) — {r['claim']}")
            print(f"{len(rows)} intention claim(s), "
                  f"{sum(1 for r in rows if r['demotion_due'])} "
                  f"demotion(s) due")
        return 0
    result = demote(root, as_of, args.apply)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        verb = "demoted" if args.apply else "would demote (dry run)"
        print(f"{verb}: {len(result['events'])} intention(s)")
        for e in result["events"]:
            print(f"  {e['page']} (expired {e['expires']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
