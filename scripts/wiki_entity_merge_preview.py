#!/usr/bin/env python3
"""wiki_entity_merge_preview.py — entity-merge DRY-RUN preview.

Tonight's implementation wave, item W5 (2026-10-22). Pattern:
Zotero's duplicate handling (one master record; fields
reconciled field-by-field; the merged record keeps all
collections and tags; citations follow the merge; a human
picks the match — merge, never delete), ThinkWiki / docmancer
consolidation proposals that wait for review. Clean
re-implementation from the ideas; no code copied.

This is the PREVIEW half of the built proposals tool
(scripts/wiki_entity_merge.py). That tool proposes candidate
pairs; this tool takes ONE pair a human has picked — survivor
A, absorbed B — and reports everything a merge WOULD touch,
so the decision is made on complete evidence:

  frontmatter   every field of A and B side by side: same /
                survivor-only / absorbed-only / CONFLICT
                (both values shown, never resolved here);
                list fields (sources, tags, aliases) with
                their overlap and the union the merged record
                would carry;
  sections      B's body sections that would append to A and
                headings present in both (would combine);
  references    found by actually scanning the corpus —
                inbound wikilinks to B (would retarget to A),
                B's outbound links (duplicates vs new for A),
                prose mentions of B's title, path mentions,
                the index listing, log / ledger / filings
                references, claims stated on B, claims
                elsewhere mentioning B, citations on B (body
                markers + citation-lockfile records), pages
                naming B in `sources:`, graph edges in / out /
                source / co-citation, the alias register and
                the canonical-names register, and evaluation
                register mentions. EVERY category is reported,
                zero counts included: an empty category is
                evidence, not an oversight.

READ-ONLY BY CONSTRUCTION: the tool never writes into the
wiki tree. Output goes to stdout, or to --out — which is
refused when it resolves inside the tree. Log and ledger
references are history: a real merge never rewrites them,
and the preview says so.

Deterministic: same corpus + same pair + same --date gives
identical bytes (no wall-clock anywhere in the output).

    python3 scripts/wiki_entity_merge_preview.py SURVIVOR \
        ABSORBED [--root DIR] [--date YYYY-MM-DD] \
        [--format md|json] [--out FILE] [--suggest]

SURVIVOR / ABSORBED are entity page paths
(wiki/entities/grok.md) or bare stems (grok). --suggest
re-orders the pair by the proposals tool's survivor rule
(sources, body length, created, path) and states the reason;
without it the human's order stands exactly as given.

Stdlib only. Exit codes: 0 ok · 2 usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_wv = _load("wiki_validate")
parse_frontmatter, as_list = _wv.parse_frontmatter, _wv.as_list
_em = _load("wiki_entity_merge")
load_entities, suggest_survivor = _em.load_entities, _em.suggest_survivor

LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\]]+)(?:#L(\d+)(?:-L(\d+))?)?\]")


# ---------------------------------------------------------------- helpers

def resolve_entity(root: Path, arg: str, entities: list[dict]) -> dict:
    """A CLI pair member: a repo-relative path or a bare stem."""
    arg = arg.replace("\\", "/")
    for e in entities:
        if arg in (e["rel"], e["stem"], f"{e['stem']}.md"):
            return e
    raise SystemExit(f"error: no entity page matches {arg!r} "
                     f"(entities: {', '.join(e['rel'] for e in entities)})")


def headings(body: str) -> list[str]:
    """## / ### section headings of a page body, in order."""
    return [m.group(1).strip() for m in
            re.finditer(r"^#{2,3}\s+(.+?)\s*$", body or "", re.M)]


def link_targets(text: str) -> list[tuple[int, str, str]]:
    """(line, raw target, resolved stem) per wikilink."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in LINK_RE.finditer(line):
            raw = m.group(1).split("|")[0].split("#")[0].strip()
            out.append((i, m.group(1), Path(raw).stem if raw else ""))
    return out


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def lines_matching(path: Path, *needles: str) -> list[int]:
    """1-based line numbers containing any needle (case-sensitive)."""
    if not path.is_file():
        return []
    return [i for i, line in enumerate(read_text(path).splitlines(), 1)
            if any(n in line for n in needles)]


# ---------------------------------------------------------------- frontmatter

def field_rows(a: dict, b: dict) -> list[dict]:
    """Field-by-field comparison over the union of both pages'
    frontmatter keys. Conflicts are presented, never resolved."""
    fa, fb = a["fields"], b["fields"]
    rows = []
    for key in sorted(set(fa) | set(fb)):
        va, vb = fa.get(key), fb.get(key)
        row = {"field": key, "survivor": va, "absorbed": vb}
        if isinstance(va, list) or isinstance(vb, list):
            la = [str(x) for x in as_list(va)]
            lb = [str(x) for x in as_list(vb)]
            row.update({
                "kind": "list",
                "relation": ("same" if la == lb else "differs"),
                "shared": sorted(set(la) & set(lb)),
                "survivor_only": sorted(set(la) - set(lb)),
                "absorbed_only": sorted(set(lb) - set(la)),
                "merged_union": sorted(set(la) | set(lb)),
            })
        elif va is None:
            row.update({"kind": "scalar", "relation": "absorbed-only"})
        elif vb is None:
            row.update({"kind": "scalar", "relation": "survivor-only"})
        elif str(va) == str(vb):
            row.update({"kind": "scalar", "relation": "same"})
        else:
            row.update({"kind": "scalar", "relation": "CONFLICT"})
        rows.append(row)
    return rows


# ---------------------------------------------------------------- scan

def scan(root: Path, a: dict, b: dict) -> dict:
    wiki = root / "wiki"
    pages = sorted(wiki.rglob("*.md")) if wiki.is_dir() else []
    texts = {str(p.relative_to(root)): read_text(p) for p in pages}

    b_stem, b_title, b_rel = b["stem"], b["title"], b["rel"]
    title_re = re.compile(re.escape(b_title), re.I) if b_title else None

    inbound, outbound_new, outbound_dup = [], [], []
    mentions, path_mentions = [], []
    sources_field_refs = []
    a_targets = {stem for _, _, stem in link_targets(a["body"])}
    for rel, text in texts.items():
        if rel == b_rel:
            continue
        fields, body = parse_frontmatter(text)
        fields = fields or {}
        if b_rel in [str(s) for s in as_list(fields.get("sources"))]:
            sources_field_refs.append(rel)
        hit_lines = [ln for ln, raw, stem in link_targets(text)
                     if stem == b_stem]
        if hit_lines:
            inbound.append({"page": rel, "lines": hit_lines,
                            "count": len(hit_lines),
                            "from_survivor": rel == a["rel"]})
        if title_re:
            prose = LINK_RE.sub("", text)
            mlines = [i for i, line in enumerate(prose.splitlines(), 1)
                      if title_re.search(line)]
            if mlines:
                mentions.append({"page": rel, "lines": mlines,
                                 "count": len(mlines)})
        plines = [i for i, line in enumerate(text.splitlines(), 1)
                  if b_rel in line and i not in hit_lines]
        if plines:
            path_mentions.append({"page": rel, "lines": plines,
                                  "count": len(plines)})

    for ln, raw, stem in link_targets(b["body"]):
        (outbound_dup if stem in a_targets else outbound_new).append(
            {"line": ln, "target": raw, "stem": stem})

    # claims: stated on B (frontmatter + claim index) and
    # claims elsewhere whose text mentions B's title.
    claims_on, claims_mentioning = [], []
    if b["fields"].get("claim"):
        claims_on.append({"where": b_rel, "claim": b["fields"]["claim"],
                          "as_of": b["fields"].get("as_of")})
    idx = root / "evaluation" / "claim-index.jsonl"
    if idx.is_file():
        for line in read_text(idx).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("claim_id") == b_rel:
                claims_on.append({"where": "evaluation/claim-index.jsonl",
                                  "claim": row.get("text"),
                                  "as_of": row.get("stated")})
            elif title_re and title_re.search(str(row.get("text") or "")):
                claims_mentioning.append(
                    {"claim_id": row.get("claim_id"),
                     "text": row.get("text")})

    # citations on B: body markers + lockfile records.
    cites = [{"line": i, "source": m.group(1),
              "range": [m.group(2), m.group(3)]}
             for i, line in enumerate(b["body"].splitlines(), 1)
             for m in CITE_RE.finditer(line)]
    lock_records = []
    lock = root / "evaluation" / "citation-lockfile.json"
    if lock.is_file():
        data = json.loads(read_text(lock))
        lock_records = [{"id": c.get("id"), "source": c.get("source"),
                         "page_line": c.get("page_line")}
                        for c in data.get("citations", [])
                        if c.get("page") == b_rel]

    # registers + record surfaces (history: never rewritten).
    alias_hits = []
    aliases_path = root / "evaluation" / "entity-aliases.json"
    if aliases_path.is_file():
        reg = json.loads(read_text(aliases_path)).get("aliases", {})
        alias_hits = [{"alias": k, "target": v} for k, v in
                      sorted(reg.items())
                      if b_stem in (k, v) or b_title in (k, v)]
    canon_hits = []
    canon_path = root / "evaluation" / "canonical-names.json"
    if canon_path.is_file():
        for entry in json.loads(read_text(canon_path)).get(
                "canonical_names", []):
            names = [entry.get("canonical", "")] + entry.get("variants", [])
            if b_title in names:
                canon_hits.append(entry)

    eval_mentions = []
    ev = root / "evaluation"
    if ev.is_dir():
        for p in sorted(ev.rglob("*")):
            if p.is_file() and p.suffix in (".json", ".jsonl", ".md"):
                lines = lines_matching(p, b_rel)
                if lines:
                    eval_mentions.append(
                        {"file": str(p.relative_to(root)),
                         "lines": lines, "count": len(lines)})

    b_sources = set(b["sources"])
    co_citation = []
    for rel, text in texts.items():
        if rel in (a["rel"], b_rel):
            continue
        fields, _ = parse_frontmatter(text)
        shared = sorted(b_sources & {str(s) for s in
                                     as_list((fields or {}).get("sources"))})
        if shared:
            co_citation.append({"page": rel, "shared_sources": shared})

    return {
        "inbound_wikilinks": inbound,
        "outbound_links": {"would_duplicate": outbound_dup,
                           "would_be_new": outbound_new},
        "prose_mentions": mentions,
        "path_mentions": path_mentions,
        "sources_field_refs": sources_field_refs,
        "index_listing": lines_matching(wiki / "index.md", b_rel,
                                        f"[[{b_stem}]]"),
        "log_references": lines_matching(wiki / "log.md", b_rel),
        "ledger_references": [
            {"file": str(p.relative_to(root)),
             "lines": lines_matching(p, b_rel)}
            for p in sorted((wiki / "rules").glob("*.md"))
            if lines_matching(p, b_rel)] if (wiki / "rules").is_dir()
            else [],
        "filings_references": [
            {"file": str(p.relative_to(root)),
             "lines": lines_matching(p, b_rel)}
            for p in sorted((wiki / "filings").rglob("*"))
            if p.is_file() and p.suffix in (".md", ".json")
            and lines_matching(p, b_rel)],
        "conversation_log_mentions": lines_matching(
            root / "CONVERSATION-LOG.md", b_rel),
        "claims_on_absorbed": claims_on,
        "claims_mentioning_absorbed": claims_mentioning,
        "citations_on_absorbed": {"body_markers": cites,
                                  "lockfile_records": lock_records},
        "alias_register": alias_hits,
        "canonical_names": canon_hits,
        "evaluation_mentions": eval_mentions,
        "graph": {
            "edges_in": sorted({e["page"] for e in inbound}),
            "edges_out_new": sorted({e["stem"] for e in outbound_new}),
            "edges_out_duplicate": sorted({e["stem"]
                                           for e in outbound_dup}),
            "source_edges_moving": b["sources"],
            "source_edges_shared_with_survivor": sorted(
                b_sources & set(a["sources"])),
            "co_citation_partners": co_citation,
        },
    }


# ---------------------------------------------------------------- preview

def build_preview(root: Path, survivor: dict, absorbed: dict,
                  today: date, suggest_reason: str | None = None) -> dict:
    for e in (survivor, absorbed):
        text = read_text(root / e["rel"])
        fields, body = parse_frontmatter(text)
        e["fields"] = fields or {}
        e["body"] = body or ""
    found = scan(root, survivor, absorbed)
    a_heads, b_heads = headings(survivor["body"]), headings(absorbed["body"])
    b_alias_additions = sorted(
        {absorbed["title"], *absorbed["aliases"]}
        - set(survivor["aliases"]) - {survivor["title"]})
    counts = {
        "inbound_link_pages": len(found["inbound_wikilinks"]),
        "inbound_links": sum(e["count"]
                             for e in found["inbound_wikilinks"]),
        "prose_mention_pages": len(found["prose_mentions"]),
        "claims_on_absorbed": len(found["claims_on_absorbed"]),
        "claims_mentioning_absorbed": len(
            found["claims_mentioning_absorbed"]),
        "citation_markers": len(found["citations_on_absorbed"]
                                ["body_markers"]),
        "citation_lockfile_records": len(found["citations_on_absorbed"]
                                         ["lockfile_records"]),
        "conflicts": sum(1 for r in field_rows(survivor, absorbed)
                         if r["relation"] == "CONFLICT"),
    }
    return {
        "tool": "scripts/wiki_entity_merge_preview.py",
        "kind": "entity-merge-preview",
        "pattern": "Zotero duplicate handling + ThinkWiki/docmancer "
                   "review-first consolidation — preview only; "
                   "merge, never delete; a human decides",
        "status": "awaiting-review",
        "date": today.isoformat(),
        "pair": {"survivor": survivor["rel"],
                 "absorbed": absorbed["rel"],
                 "survivor_title": survivor["title"],
                 "absorbed_title": absorbed["title"],
                 "survivor_basis": (suggest_reason or
                                    "as given by the reviewer")},
        "merge_never_delete": (
            f"{absorbed['rel']} is never deleted. On an approved "
            f"merge it would be replaced by a redirect stub naming "
            f"{survivor['rel']}; its title and aliases join the "
            f"survivor's alias list; its claims and citations "
            f"follow the merge; the log and ledgers keep their "
            f"history untouched."),
        "would_add_aliases": b_alias_additions,
        "frontmatter": field_rows(survivor, absorbed),
        "sections": {
            "survivor": a_heads,
            "absorbed": b_heads,
            "only_in_absorbed_would_append": [h for h in b_heads
                                              if h not in a_heads],
            "in_both_would_combine": [h for h in b_heads if h in a_heads],
        },
        "references": found,
        "counts": counts,
    }


# ---------------------------------------------------------------- render

def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def render_md(p: dict) -> str:
    d = p["date"]
    pair = p["pair"]
    L = ["---",
         f"title: Entity merge preview — {pair['absorbed_title']} "
         f"into {pair['survivor_title']}",
         "type: query",
         f"created: {d}",
         f"updated: {d}",
         "sources: []",
         "tags: [entity-merge, preview, filings]",
         "status: draft",
         "stage: seedling",
         f"planted: {d}",
         f"tended: {d}",
         "work_type: record",
         "---",
         "",
         f"# Entity merge preview — {pair['absorbed']} → "
         f"{pair['survivor']}",
         "",
         "> [!warning] DRY RUN — nothing has been merged",
         "> Generated by `scripts/wiki_entity_merge_preview.py` "
         "(implementation wave W5, 2026-10-22; Zotero duplicate-"
         "handling pattern). A reviewer decides; any real merge "
         "is a separate, recorded act.",
         "",
         f"Survivor: **{pair['survivor']}** ({pair['survivor_basis']}). "
         f"Absorbed: **{pair['absorbed']}**.",
         "",
         p["merge_never_delete"],
         "",
         "## Frontmatter, field by field",
         "",
         "| field | survivor | absorbed | relation |",
         "|---|---|---|---|"]
    for r in p["frontmatter"]:
        L.append(f"| {r['field']} | {_fmt(r['survivor'])} | "
                 f"{_fmt(r['absorbed'])} | {r['relation']} |")
        if r["kind"] == "list" and r["relation"] == "differs":
            L.append(f"  - shared: {_fmt(r['shared'])}; survivor-only: "
                     f"{_fmt(r['survivor_only'])}; absorbed-only: "
                     f"{_fmt(r['absorbed_only'])}; merged record "
                     f"would carry: {_fmt(r['merged_union'])}")
    L += ["",
          f"Aliases the survivor would gain: "
          f"{_fmt(p['would_add_aliases'])}",
          "",
          "## Sections",
          "",
          f"Would append (only in absorbed): "
          f"{_fmt(p['sections']['only_in_absorbed_would_append'])}",
          f"Would combine (in both): "
          f"{_fmt(p['sections']['in_both_would_combine'])}",
          "",
          "## References (scanned, zeros included)",
          ""]
    ref = p["references"]
    L.append(f"- Inbound wikilinks to the absorbed page: "
             f"{p['counts']['inbound_links']} link(s) on "
             f"{p['counts']['inbound_link_pages']} page(s) — would "
             f"retarget to the survivor:")
    for e in ref["inbound_wikilinks"]:
        mark = " (the survivor itself)" if e["from_survivor"] else ""
        L.append(f"  - {e['page']} lines {e['lines']}{mark}")
    L.append(f"- Outbound links of the absorbed page: "
             f"{len(ref['outbound_links']['would_be_new'])} new for "
             f"the survivor, "
             f"{len(ref['outbound_links']['would_duplicate'])} "
             f"already linked by the survivor.")
    L.append(f"- Prose mentions of the absorbed title: "
             f"{p['counts']['prose_mention_pages']} page(s).")
    for e in ref["prose_mentions"]:
        L.append(f"  - {e['page']} lines {e['lines']}")
    L.append(f"- Path mentions (non-link): "
             f"{len(ref['path_mentions'])} page(s).")
    L.append(f"- Pages naming the absorbed page in `sources:`: "
             f"{len(ref['sources_field_refs'])} "
             f"{_fmt(ref['sources_field_refs'])}")
    L.append(f"- Index listing lines: "
             f"{_fmt(ref['index_listing'])}")
    L.append(f"- Log references (history — never rewritten): "
             f"{len(ref['log_references'])} line(s).")
    L.append(f"- Ledger references (history — never rewritten): "
             f"{len(ref['ledger_references'])} file(s).")
    L.append(f"- Filings references: "
             f"{len(ref['filings_references'])} file(s).")
    L.append(f"- Conversation-log mentions (verbatim history): "
             f"{len(ref['conversation_log_mentions'])} line(s).")
    L.append(f"- Claims stated on the absorbed page: "
             f"{p['counts']['claims_on_absorbed']} — would move "
             f"to the survivor.")
    L.append(f"- Claims elsewhere mentioning the absorbed title: "
             f"{p['counts']['claims_mentioning_absorbed']}.")
    L.append(f"- Citations on the absorbed page: "
             f"{p['counts']['citation_markers']} body marker(s), "
             f"{p['counts']['citation_lockfile_records']} lockfile "
             f"record(s) — citations follow the merge.")
    L.append(f"- Alias register entries: "
             f"{len(ref['alias_register'])}; canonical-names "
             f"entries: {len(ref['canonical_names'])}.")
    L.append(f"- Evaluation registers mentioning the absorbed "
             f"path: {len(ref['evaluation_mentions'])} file(s).")
    g = ref["graph"]
    L.append(f"- Graph: edges in from {_fmt(g['edges_in'])}; "
             f"source (citation) edges moving: "
             f"{_fmt(g['source_edges_moving'])}; co-citation "
             f"partners: {len(g['co_citation_partners'])}.")
    L += ["",
          f"Frontmatter conflicts presented, unresolved: "
          f"{p['counts']['conflicts']}.",
          ""]
    return "\n".join(L)


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("survivor")
    ap.add_argument("absorbed")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--date", default=None)
    ap.add_argument("--format", choices=("md", "json"), default="md")
    ap.add_argument("--out", default=None,
                    help="write here instead of stdout; must be "
                         "OUTSIDE the wiki tree (read-only tool)")
    ap.add_argument("--suggest", action="store_true",
                    help="re-order the pair by the proposals "
                         "tool's survivor rule, stating why")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    entities = load_entities(root)
    if len(entities) < 2:
        print("error: fewer than two entity pages", file=sys.stderr)
        return 2
    a = resolve_entity(root, args.survivor, entities)
    b = resolve_entity(root, args.absorbed, entities)
    if a["rel"] == b["rel"]:
        print("error: survivor and absorbed are the same page",
              file=sys.stderr)
        return 2
    reason = None
    if args.suggest:
        s, o, reason = suggest_survivor(a, b)
        a, b = s, o
        reason = f"suggested by the proposals rule: {reason}"
    today = date.fromisoformat(args.date) if args.date else date.today()
    preview = build_preview(root, dict(a), dict(b), today,
                            suggest_reason=reason)
    out = (render_md(preview) if args.format == "md"
           else json.dumps(preview, indent=2, sort_keys=True) + "\n")
    if args.out:
        dest = Path(args.out).resolve()
        if dest == root or root in dest.parents:
            print("error: --out is inside the wiki tree; this tool "
                  "is read-only over the corpus", file=sys.stderr)
            return 2
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, encoding="utf-8")
        print(f"preview: {preview['pair']['absorbed']} -> "
              f"{preview['pair']['survivor']} "
              f"({preview['counts']['conflicts']} conflict(s), "
              f"{preview['counts']['inbound_links']} inbound "
              f"link(s)) -> {dest}")
    else:
        print(out, end="" if out.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
