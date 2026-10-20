#!/usr/bin/env python3
"""Type-of-work labels for the LLM Wiki (WikiCitadel v1;
Trust Project type-of-work labels via the survey).

Every compiled page can carry two frontmatter fields the
`status` and `confidence` axes do not express:

  work_type: record | synthesis | advice | speculation
             — WHAT KIND OF WORK the page is. A record states
             what happened or what a source says; a synthesis
             compiles several sources into one reasoned
             account; advice tells agents (or the owner) what
             to do; speculation proposes something not yet
             built or decided.
  methods:   a one-line note saying how the page was made.
             Required by the convention for synthesis and
             advice pages (the pages whose reasoning a reader
             must be able to audit); optional elsewhere.

This tool PROPOSES a work_type for every page from observable
signals only (path, frontmatter type, sources count, inline
claim-citation count, tags) and files the proposals as a
dated filing under wiki/filings/ for review. Proposing
changes nothing.

Applying the backfill is a separate, recorded act:

  python3 scripts/wiki_worktypes.py            # propose -> filing
  python3 scripts/wiki_worktypes.py --apply    # apply latest filing

Apply adds ONLY the proposed frontmatter lines to each page
(`work_type`, and `methods` where the proposal carries one);
a field a page already carries is never overwritten — least
of all an existing `work_type` — and every body is
hash-checked before and after. The application is recorded
in the filing itself and in its JSON manifest. Structural
pages with no frontmatter (wiki/index.md, wiki/log.md) carry
no work_type and are listed as such. Pages created after the
proposals were filed are classified on the spot at apply time
by the same rules and recorded in the filing as late
arrivals.

Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
FILINGS = WIKI / "filings"

WORK_TYPES = ("record", "synthesis", "advice", "speculation")
FIELDS = ("work_type", "methods")

FM_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


# ---------------------------------------------------------------- parsing

def split_frontmatter(text: str):
    """(fm_text, body) or (None, text) when no frontmatter block."""
    m = FM_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def parse_fields(fm_text: str):
    """Minimal YAML-subset parse: top-level keys; `sources` and
    `tags` collected as lists. Mirrors scripts/wiki_stages.py."""
    fields = {}
    lists = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        km = KEY_RE.match(lines[i])
        if not km:
            i += 1
            continue
        name, val = km.group(1), km.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            items = [s.strip().strip("\"'") for s in inner.split(",")] if inner else []
            if name in ("sources", "tags"):
                lists[name] = items
            fields[name] = items
        elif val:
            if name in ("sources", "tags"):
                lists[name] = [val.strip("\"'")]
            fields[name] = val.strip("\"'")
        else:
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                items.append(re.sub(r"^\s+-\s+", "", lines[j]).strip().strip("\"'"))
                j += 1
            if name in ("sources", "tags"):
                lists[name] = items
            fields[name] = items if items else None
            i = j - 1 if items else i
        i += 1
    return fields, lists.get("sources", []), lists.get("tags", [])


# ---------------------------------------------------------------- signals

def page_signals(path: Path):
    """Observable signals for one page, or None when it has no
    frontmatter (structural pages carry no work_type)."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm_text, body = split_frontmatter(text)
    if fm_text is None:
        return None
    fields, sources, tags = parse_fields(fm_text)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "type": str(fields.get("type") or ""),
        "status": str(fields.get("status") or ""),
        "tags": [str(t).lower() for t in tags],
        "sources_n": len(sources),
        "cites_n": body.count("^[cite:"),
        "existing": {k: fields.get(k) for k in FIELDS
                     if fields.get(k) not in (None, "")},
    }


def methods_for(work_type: str, sig) -> str | None:
    """The one-line methods note a proposal carries. Required
    for synthesis and advice (the auditable-reasoning kinds);
    not proposed for record or speculation pages."""
    if work_type == "synthesis":
        if sig["sources_n"]:
            return (f"Compiled from the {sig['sources_n']} source(s) "
                    "listed in frontmatter, correlated across the "
                    "pages it cites; the reasoning is stated on "
                    "the page.")
        return ("Compiled from the wiki pages it links; no raw "
                "sources are listed in frontmatter.")
    if work_type == "advice":
        return ("Standing guidance compiled from the source(s) "
                "listed in frontmatter; in force until the owner "
                "rules otherwise.")
    return None


def classify(sig):
    """Deterministic work_type from signals. First match wins;
    the order matters (a special page's purpose beats its
    directory; a decision record beats its section).

    Returns (work_type, reason).
    """
    rel = sig["path"]
    stem = Path(rel).stem
    section = Path(rel).parts[1] if len(Path(rel).parts) > 2 else ""

    if sig["existing"].get("work_type"):
        return (str(sig["existing"]["work_type"]),
                "already carries a work_type — never overwritten")
    if rel == "wiki/ideas.md":
        return "advice", ("the owner's ideas board — proposals and "
                          "recommendations awaiting his ruling")
    if rel == "wiki/overview.md":
        return "synthesis", "the living synthesis across all sources"
    if sig["type"] == "decision" or "decision" in stem:
        return "record", "a record of decisions taken"
    if section == "filings":
        return "record", "a filing — the record of a run, queue or proposal"
    if section == "talk":
        return "record", "a dispute record kept beside its page"
    if section in ("entities", "concepts"):
        return "record", "a reference entry — what the record says"
    if section == "rules":
        if stem.endswith("ledger"):
            return "record", "an append-only ledger"
        return "advice", "a standing rule — instructions agents work under"
    if section == "sources":
        if sig["sources_n"] <= 1:
            return "record", (f"single-source summary "
                              f"({sig['sources_n']} source(s)) — restates "
                              "one source")
        return "synthesis", (f"compiles {sig['sources_n']} sources into "
                             "one account")
    if section == "syntheses":
        if "design" in sig["tags"] or "design" in stem:
            return "speculation", ("a design proposal for a system not "
                                   "built or decided")
        return "synthesis", "a synthesis page — several sources, one account"
    if section == "queries":
        if sig["sources_n"] >= 3 and sig["cites_n"] >= 5:
            return "synthesis", (f"a compiled answer — {sig['sources_n']} "
                                  f"sources, {sig['cites_n']} claim "
                                  "citations")
        return "record", "a filed report, queue or check result"
    if sig["type"] == "synthesis":
        return "synthesis", "frontmatter type is synthesis"
    return "record", "default — a page of record"


def iter_corpus():
    """The Lens page corpus: wiki/**/*.md outside wiki/access/."""
    return sorted(p for p in WIKI.rglob("*.md")
                  if p.is_file() and "access" not in p.relative_to(WIKI).parts)


# ---------------------------------------------------------------- propose

def propose():
    rows, structural = [], []
    for p in iter_corpus():
        sig = page_signals(p)
        if sig is None:
            structural.append(p.relative_to(ROOT).as_posix())
            continue
        work_type, reason = classify(sig)
        rows.append({**sig, "work_type": work_type, "reason": reason,
                     "methods": methods_for(work_type, sig),
                     "existing": sig.pop("existing")})
    dist = {w: sum(1 for r in rows if r["work_type"] == w)
            for w in WORK_TYPES}
    return rows, structural, dist


def filing_paths(today: date):
    stem = f"worktype-backfill-{today.isoformat()}"
    return FILINGS / f"{stem}.md", FILINGS / f"{stem}.json"


def write_filing(rows, structural, dist, today: date):
    md_path, json_path = filing_paths(today)
    dist_line = " · ".join(f"{w} {dist[w]}" for w in WORK_TYPES)
    lines = [
        "---",
        f"title: Type-of-work backfill — {today.isoformat()} (proposals)",
        "type: query",
        f"created: {today.isoformat()}",
        f"updated: {today.isoformat()}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [work-types, labels, filings, proposal]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Type-of-work backfill — {today.isoformat()}",
        "",
        "> [!warning] PROPOSALS — review before applying",
        "> Generated by `scripts/wiki_worktypes.py` "
        "(WikiCitadel v1: type-of-work labels; Trust",
        "> Project pattern via the survey). Every label",
        "> below is PROPOSED from observable signals only (path,",
        "> frontmatter type, sources count, claim citations,",
        "> tags). **No page has been changed by this filing.**",
        "> Applying it (`wiki_worktypes.py --apply`) is a separate",
        "> recorded act that adds only the `work_type` line — and",
        "> a one-line `methods` note where the proposal carries",
        "> one (synthesis and advice pages) — and appends its",
        "> record to this filing. An existing `work_type` is never",
        "> overwritten.",
        "",
        f"Scale this run: {len(rows)} pages with frontmatter "
        f"proposed ({dist_line}); {len(structural)} structural "
        "page(s) carry no frontmatter and no work_type.",
        "",
        "The rules, first match wins: the ideas board is advice",
        "and the overview is synthesis by purpose; a decisions",
        "page is a record; filings, talk pages and entity/concept",
        "entries are records; rules pages are advice (a ledger is",
        "a record); a source page is a record when it restates one",
        "source and a synthesis when it compiles several; a",
        "synthesis page tagged or named as a design for an unbuilt",
        "system is speculation; a query page is a synthesis only",
        "when it compiles 3+ sources with 5+ claim citations,",
        "otherwise a record of a report or check.",
        "",
        "| Page | Type | Sources | Cites | Proposed | Why |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['path']}` | {r['type']} | {r['sources_n']} | "
            f"{r['cites_n']} | **{r['work_type']}** | {r['reason']} |")
    if structural:
        lines += ["", "## Structural pages — no work_type", ""]
        for s in structural:
            lines.append(f"- `{s}` — no frontmatter; carries no "
                         "work_type by design.")
    lines += [
        "",
        "## This filing's own work_type",
        "",
        "This filing did not exist when the corpus was scanned. On",
        "application it is classified on the spot by the same rules",
        "(a filing — a record) and receives its label then; the",
        "application record below says which.",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "kind": "worktype-backfill",
        "generated_at": today.isoformat(),
        "distribution": dist,
        "structural_no_worktype": structural,
        "proposals": [
            {k: r[k] for k in ("path", "work_type", "methods", "reason",
                               "sources_n", "cites_n")}
            for r in rows
        ],
        "applied_at": None,
        "application": None,
    }
    json_path.write_text(json.dumps(manifest, indent=2) + "\n",
                         encoding="utf-8")
    return md_path, json_path


# ---------------------------------------------------------------- apply

def add_worktype_fields(text: str, values: dict):
    """Insert any missing work_type/methods lines at the end of
    the frontmatter block. Returns (new_text, added_keys). The
    body is never touched; existing keys are never overwritten."""
    m = FM_RE.match(text)
    if not m:
        return text, []
    fm_text = m.group(1)
    present = set()
    for line in fm_text.splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):", line)
        if km:
            present.add(km.group(1))
    added = []
    new_lines = []
    for key in FIELDS:
        if key not in present and values.get(key):
            new_lines.append(f"{key}: {values[key]}")
            added.append(key)
    if not added:
        return text, []
    new_fm = fm_text.rstrip("\n") + "\n" + "\n".join(new_lines)
    return text[:m.start(1)] + new_fm + text[m.end(1):], added


def body_hash(text: str):
    _, body = split_frontmatter(text)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def apply(manifest_path: Path, today: date):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    applied, skipped, changed_pages = [], [], []
    for prop in manifest["proposals"]:
        p = ROOT / prop["path"]
        text = p.read_text(encoding="utf-8")
        before = body_hash(text)
        new_text, added = add_worktype_fields(
            text, {k: prop.get(k) for k in FIELDS})
        if not added:
            skipped.append({"path": prop["path"],
                            "why": "fields already present"})
            continue
        assert body_hash(new_text) == before, \
            f"body changed for {prop['path']}"
        p.write_text(new_text, encoding="utf-8")
        applied.append({"path": prop["path"],
                        "work_type": prop["work_type"], "added": added})
        changed_pages.append(prop["path"])

    # The filing itself: classify on the spot by the same rules.
    md_path = manifest_path.with_suffix(".md")
    filing_note = None
    if md_path.exists():
        sig = page_signals(md_path)
        if sig is not None:
            work_type, reason = classify(sig)
            values = {"work_type": work_type,
                      "methods": methods_for(work_type, sig)}
            text = md_path.read_text(encoding="utf-8")
            new_text, added = add_worktype_fields(text, values)
            if added:
                md_path.write_text(new_text, encoding="utf-8")
                changed_pages.append(
                    md_path.relative_to(ROOT).as_posix())
            filing_note = {"work_type": work_type, "reason": reason,
                           "added": added}

    # Late arrivals: pages created after the proposals were filed
    # are classified on the spot by the same rules and recorded.
    known = {prop["path"] for prop in manifest["proposals"]}
    known.add(md_path.relative_to(ROOT).as_posix())
    late = []
    for p in iter_corpus():
        rel = p.relative_to(ROOT).as_posix()
        if rel in known:
            continue
        sig = page_signals(p)
        if sig is None:
            continue  # structural — no work_type by design
        work_type, reason = classify(sig)
        text = p.read_text(encoding="utf-8")
        before = body_hash(text)
        new_text, added = add_worktype_fields(
            text, {"work_type": work_type,
                   "methods": methods_for(work_type, sig)})
        if added:
            assert body_hash(new_text) == before, \
                f"body changed for {rel}"
            p.write_text(new_text, encoding="utf-8")
            changed_pages.append(rel)
        late.append({"path": rel, "work_type": work_type,
                     "reason": reason, "added": added})

    dist = {w: 0 for w in WORK_TYPES}
    for prop in manifest["proposals"]:
        dist[prop["work_type"]] += 1
    if filing_note:
        dist[filing_note["work_type"]] += 1
    for item in late:
        dist[item["work_type"]] += 1

    record = {
        "applied_at": today.isoformat(),
        "pages_changed": len(changed_pages),
        "skipped": skipped,
        "distribution_after": dist,
        "filing_itself": filing_note,
        "late_arrivals": late,
    }
    manifest["applied_at"] = today.isoformat()
    manifest["application"] = record
    history = manifest.get("applications") or []
    history.append(record)
    manifest["applications"] = history
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")

    with md_path.open("a", encoding="utf-8") as fh:
        fh.write("\n## Application record\n\n")
        fh.write(f"Applied {today.isoformat()} by "
                 f"`scripts/wiki_worktypes.py --apply`: frontmatter "
                 f"lines added to {len(changed_pages)} page(s); "
                 f"{len(skipped)} page(s) skipped (fields already "
                 "present). No page body was changed — bodies were "
                 "hash-checked before and after.\n\n")
        fh.write("Distribution after application: " +
                 " · ".join(f"{w} {dist[w]}" for w in WORK_TYPES) +
                 " (including this filing).\n")
        if filing_note:
            fh.write(f"\nThis filing's own work_type: "
                     f"**{filing_note['work_type']}** "
                     f"({filing_note['reason']}).\n")
        if late:
            fh.write("\nLate arrivals — pages created after these "
                     "proposals were filed, classified on the spot "
                     "by the same rules:\n\n")
            for item in late:
                fh.write(f"- `{item['path']}` — "
                         f"**{item['work_type']}** "
                         f"({item['reason']})\n")
        if skipped:
            fh.write("\nSkipped:\n\n")
            for s in skipped:
                fh.write(f"- `{s['path']}` — {s['why']}\n")
    return record


# ---------------------------------------------------------------- main

def latest_manifest():
    files = sorted(FILINGS.glob("worktype-backfill-*.json"))
    return files[-1] if files else None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="apply the latest filing's proposals "
                         "(frontmatter lines only)")
    ap.add_argument("--from", dest="manifest", default=None,
                    help="manifest JSON to apply (default: latest "
                         "filing)")
    args = ap.parse_args(argv)
    today = date.today()

    if args.apply:
        manifest_path = (Path(args.manifest) if args.manifest
                         else latest_manifest())
        if manifest_path is None or not manifest_path.exists():
            print("no worktype-backfill manifest found — run "
                  "without --apply first", file=sys.stderr)
            return 2
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        record = apply(manifest_path, today)
        print(f"Applied: {record['pages_changed']} page(s) changed; "
              f"distribution {record['distribution_after']}")
        return 0

    rows, structural, dist = propose()
    md_path, json_path = write_filing(rows, structural, dist, today)
    print(f"Proposed work types for {len(rows)} pages: " +
          " · ".join(f"{w} {dist[w]}" for w in WORK_TYPES))
    print(f"Filing: {md_path.relative_to(ROOT)} (+ {json_path.name})")
    print("No page has been changed. Apply with: "
          "python3 scripts/wiki_worktypes.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
