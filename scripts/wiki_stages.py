#!/usr/bin/env python3
"""Growth stages for the LLM Wiki (item: page growth-stage
labels, digital-garden tradition).

Every wiki page carries three frontmatter fields:

  stage:   seedling | budding | evergreen  — the page's MATURITY,
           a third axis beside `status` (lifecycle) and
           `confidence` (evidence strength), never conflated
           with either (see AGENTS.md, "Page conventions").
  planted: the date the page was created.
  tended:  the date of the page's last substantive edit.

  seedling  = new or thin — little or no sourcing yet, or just
              planted and unproven.
  budding   = sourced and still growing.
  evergreen = settled and maintained — well-sourced, claim-level
              citations present, tended recently; or a claim page
              whose outcomes have made it a rule.

This tool PROPOSES a stage for every page from observable signals
only (frontmatter sources count, inline claim-citation count,
page age, days since `updated`, claim outcome status) and files
the proposals as a dated filing under wiki/filings/ for review.
Proposing changes nothing.

Applying the backfill is a separate, recorded act:

  python3 scripts/wiki_stages.py            # propose -> filing
  python3 scripts/wiki_stages.py --apply    # apply latest filing

Apply adds ONLY the three frontmatter lines to each page (pages
that already carry any of the fields are skipped for that field;
nothing else in the file changes — the body is hash-checked
before and after). The application is recorded in the filing
itself and in its JSON manifest. Structural pages with no
frontmatter (wiki/index.md, wiki/log.md) carry no stage and are
listed as such. Pages created after the proposals were filed
are classified on the spot at apply time by the same rules and
recorded in the filing as late arrivals — a growing wiki does
not wait for the next day's filing to be staged.

Stdlib only.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
FILINGS = WIKI / "filings"

STAGES = ("seedling", "budding", "evergreen")
FIELDS = ("stage", "planted", "tended")

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
    """Minimal YAML-subset parse: top-level keys; `sources` counted.

    Returns (fields dict of raw scalars, sources list). Mirrors the
    subset scripts/wiki_validate.py accepts: flow lists, block
    lists, plain scalars.
    """
    fields = {}
    sources = []
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
            if name == "sources":
                sources = items
            fields[name] = items
        elif val:
            if name == "sources":
                sources = [val.strip("\"'")]
            fields[name] = val.strip("\"'")
        else:
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s+-\s+", lines[j]):
                items.append(re.sub(r"^\s+-\s+", "", lines[j]).strip().strip("\"'"))
                j += 1
            if name == "sources":
                sources = items
            fields[name] = items if items else None
            i = j - 1 if items else i
        i += 1
    return fields, sources


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
        if value is None:
            return None
    v = str(value).strip()
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------- signals

_git_cache = {}


def git_dates(rel_path: str):
    """(first_commit_date, last_commit_date) for a repo path, or
    (None, None) when git has nothing to say."""
    if rel_path in _git_cache:
        return _git_cache[rel_path]
    first = last = None
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "log", "--format=%cI", "--", rel_path],
            capture_output=True, text=True, timeout=30)
        stamps = [ln[:10] for ln in r.stdout.splitlines() if ln.strip()]
        if stamps:
            last = date.fromisoformat(stamps[0])
            first = date.fromisoformat(stamps[-1])
    except Exception:
        first = last = None
    _git_cache[rel_path] = (first, last)
    return first, last


def page_signals(path: Path, today: date):
    """Observable signals for one page, or None when it has no
    frontmatter (structural pages carry no stage)."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm_text, body = split_frontmatter(text)
    if fm_text is None:
        return None
    fields, sources = parse_fields(fm_text)
    rel = path.relative_to(ROOT).as_posix()
    g_first, g_last = git_dates(rel)
    planted = parse_date(fields.get("created")) or g_first or today
    tended = parse_date(fields.get("updated")) or g_last or planted
    return {
        "path": rel,
        "type": str(fields.get("type") or ""),
        "status": str(fields.get("status") or ""),
        "sources_n": len(sources),
        "cites_n": body.count("^[cite:"),
        "body_chars": len(body),
        "outcome_status": str(fields.get("outcome_status") or ""),
        "planted": planted.isoformat(),
        "tended": tended.isoformat(),
        "age_days": (today - planted).days,
        "tended_days": (today - tended).days,
        "existing": {k: fields.get(k) for k in FIELDS
                     if fields.get(k) not in (None, "")},
    }


def classify(sig):
    """Deterministic stage from signals. First match wins; the
    order matters (settled beats new when the evidence is strong).

    Returns (stage, reason).
    """
    if sig["outcome_status"] == "rule" and sig["sources_n"] >= 1:
        return "evergreen", "claim page settled as a rule by recorded outcomes"
    if sig["sources_n"] >= 3 and sig["cites_n"] >= 1 and sig["tended_days"] <= 14:
        return "evergreen", (f"{sig['sources_n']} sources, {sig['cites_n']} claim "
                              f"citation(s), tended {sig['tended_days']}d ago")
    if sig["sources_n"] == 0:
        return "seedling", "no sources cited"
    if sig["age_days"] <= 1 and sig["cites_n"] == 0:
        return "seedling", f"planted {sig['age_days']}d ago, no claim citations yet"
    if sig["sources_n"] <= 1 and sig["cites_n"] == 0 and sig["body_chars"] < 1500:
        return "seedling", (f"thin stub: {sig['sources_n']} source(s), "
                            f"{sig['body_chars']} body chars")
    return "budding", (f"{sig['sources_n']} source(s), {sig['cites_n']} claim "
                       f"citation(s) — sourced, still growing")


def iter_corpus():
    """The Lens page corpus: wiki/**/*.md outside wiki/access/."""
    return sorted(p for p in WIKI.rglob("*.md")
                  if p.is_file() and "access" not in p.relative_to(WIKI).parts)


# ---------------------------------------------------------------- propose

def propose(today: date):
    rows, structural = [], []
    for p in iter_corpus():
        sig = page_signals(p, today)
        if sig is None:
            structural.append(p.relative_to(ROOT).as_posix())
            continue
        stage, reason = classify(sig)
        rows.append({**sig, "stage": stage, "reason": reason,
                     "existing": sig.pop("existing")})
    dist = {s: sum(1 for r in rows if r["stage"] == s) for s in STAGES}
    return rows, structural, dist


def filing_paths(today: date):
    stem = f"stage-backfill-{today.isoformat()}"
    return FILINGS / f"{stem}.md", FILINGS / f"{stem}.json"


def write_filing(rows, structural, dist, today: date):
    md_path, json_path = filing_paths(today)
    lines = [
        "---",
        f"title: Growth-stage backfill — {today.isoformat()} (proposals)",
        "type: query",
        f"created: {today.isoformat()}",
        f"updated: {today.isoformat()}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [stages, growth, filings, proposal]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Growth-stage backfill — {today.isoformat()}",
        "",
        "> [!warning] PROPOSALS — review before applying",
        "> Generated by `scripts/wiki_stages.py` (item: page",
        "> growth-stage labels; digital-garden tradition). Every stage",
        "> below is PROPOSED from observable signals only (sources",
        "> count, inline claim citations, age, days since `updated`,",
        "> claim outcome status). **No page has been changed by this",
        "> filing.** Applying it (`wiki_stages.py --apply`) is a",
        "> separate recorded act that adds only the `stage` /",
        "> `planted` / `tended` frontmatter lines to each page, and",
        "> appends its record to this filing.",
        "",
        f"Scale this run: {len(rows)} pages with frontmatter proposed "
        f"(seedling {dist['seedling']} · budding {dist['budding']} · "
        f"evergreen {dist['evergreen']}); {len(structural)} structural "
        "page(s) carry no frontmatter and no stage.",
        "",
        "The rules, first match wins: a claim page settled as a rule",
        "by outcomes is evergreen; 3+ sources with claim citations and",
        "tended within 14 days is evergreen; no sources is a seedling;",
        "planted within a day with no claim citations is a seedling;",
        "a thin stub (≤1 source, no claim citations, <1500 body chars)",
        "is a seedling; everything else is budding.",
        "",
        "| Page | Type | Sources | Cites | Age (d) | Tended (d ago) | Proposed | Why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['path']}` | {r['type']} | {r['sources_n']} | {r['cites_n']} "
            f"| {r['age_days']} | {r['tended_days']} | **{r['stage']}** | {r['reason']} |")
    if structural:
        lines += ["", "## Structural pages — no stage", ""]
        for s in structural:
            lines.append(f"- `{s}` — no frontmatter; carries no stage by design.")
    lines += [
        "",
        "## This filing's own stage",
        "",
        "This filing did not exist when the corpus was scanned. On",
        "application it is classified on the spot by the same rules",
        "(1 source, no claim citations, planted today) and receives",
        "its stage then; the application record below says which.",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "kind": "stage-backfill",
        "generated_at": today.isoformat(),
        "distribution": dist,
        "structural_no_stage": structural,
        "proposals": [
            {k: r[k] for k in ("path", "stage", "planted", "tended", "reason",
                               "sources_n", "cites_n")}
            for r in rows
        ],
        "applied_at": None,
        "application": None,
    }
    json_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path


# ---------------------------------------------------------------- apply

def add_stage_fields(text: str, values: dict):
    """Insert any missing stage/planted/tended lines at the end of
    the frontmatter block. Returns (new_text, added_keys). The body
    is never touched; existing keys are never overwritten."""
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
        new_text, added = add_stage_fields(
            text, {k: prop[k] for k in FIELDS})
        if not added:
            skipped.append({"path": prop["path"], "why": "fields already present"})
            continue
        assert body_hash(new_text) == before, f"body changed for {prop['path']}"
        p.write_text(new_text, encoding="utf-8")
        applied.append({"path": prop["path"], "stage": prop["stage"],
                        "added": added})
        changed_pages.append(prop["path"])

    # The filing itself: classify on the spot by the same rules.
    md_path = manifest_path.with_suffix(".md")
    filing_note = None
    if md_path.exists():
        sig = page_signals(md_path, today)
        if sig is not None:
            stage, reason = classify(sig)
            text = md_path.read_text(encoding="utf-8")
            new_text, added = add_stage_fields(
                text, {"stage": stage, "planted": today.isoformat(),
                       "tended": today.isoformat()})
            if added:
                md_path.write_text(new_text, encoding="utf-8")
                changed_pages.append(md_path.relative_to(ROOT).as_posix())
            filing_note = {"stage": stage, "reason": reason, "added": added}

    # Late arrivals: pages created after the proposals were filed
    # (a busy wiki grows between propose and apply) are classified
    # on the spot by the same rules and recorded as such.
    known = {prop["path"] for prop in manifest["proposals"]}
    known.add(md_path.relative_to(ROOT).as_posix())
    late = []
    for p in iter_corpus():
        rel = p.relative_to(ROOT).as_posix()
        if rel in known:
            continue
        sig = page_signals(p, today)
        if sig is None:
            continue  # structural — no stage by design
        stage, reason = classify(sig)
        text = p.read_text(encoding="utf-8")
        before = body_hash(text)
        new_text, added = add_stage_fields(
            text, {"stage": stage, "planted": sig["planted"],
                   "tended": sig["tended"]})
        if added:
            assert body_hash(new_text) == before, f"body changed for {rel}"
            p.write_text(new_text, encoding="utf-8")
            changed_pages.append(rel)
        late.append({"path": rel, "stage": stage, "reason": reason,
                     "added": added})

    dist = {s: 0 for s in STAGES}
    for prop in manifest["proposals"]:
        dist[prop["stage"]] += 1
    if filing_note:
        dist[filing_note["stage"]] += 1
    for item in late:
        dist[item["stage"]] += 1

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
        fh.write(f"Applied {today.isoformat()} by `scripts/wiki_stages.py "
                 f"--apply`: frontmatter lines added to "
                 f"{len(changed_pages)} page(s); {len(skipped)} page(s) "
                 "skipped (fields already present). No page body was "
                 "changed — bodies were hash-checked before and after.\n\n")
        fh.write(f"Distribution after application: seedling "
                 f"{dist['seedling']} · budding {dist['budding']} · "
                 f"evergreen {dist['evergreen']} (including this filing).\n")
        if filing_note:
            fh.write(f"\nThis filing's own stage: **{filing_note['stage']}** "
                     f"({filing_note['reason']}).\n")
        if late:
            fh.write("\nLate arrivals — pages created after these "
                     "proposals were filed, classified on the spot by "
                     "the same rules:\n\n")
            for item in late:
                fh.write(f"- `{item['path']}` — **{item['stage']}** "
                         f"({item['reason']})\n")
        if skipped:
            fh.write("\nSkipped:\n\n")
            for s in skipped:
                fh.write(f"- `{s['path']}` — {s['why']}\n")
    return record


# ---------------------------------------------------------------- main

def latest_manifest():
    files = sorted(FILINGS.glob("stage-backfill-*.json"))
    return files[-1] if files else None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="apply the latest filing's proposals "
                         "(frontmatter lines only)")
    ap.add_argument("--from", dest="manifest", default=None,
                    help="manifest JSON to apply (default: latest filing)")
    args = ap.parse_args(argv)
    today = date.today()

    if args.apply:
        manifest_path = Path(args.manifest) if args.manifest else latest_manifest()
        if manifest_path is None or not manifest_path.exists():
            print("no stage-backfill manifest found — run without "
                  "--apply first", file=sys.stderr)
            return 2
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        record = apply(manifest_path, today)
        print(f"Applied: {record['pages_changed']} page(s) changed; "
              f"distribution {record['distribution_after']}")
        return 0

    rows, structural, dist = propose(today)
    md_path, json_path = write_filing(rows, structural, dist, today)
    print(f"Proposed stages for {len(rows)} pages: "
          f"seedling {dist['seedling']} · budding {dist['budding']} · "
          f"evergreen {dist['evergreen']}")
    print(f"Filing: {md_path.relative_to(ROOT)} (+ {json_path.name})")
    print("No page has been changed. Apply with: "
          "python3 scripts/wiki_stages.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
