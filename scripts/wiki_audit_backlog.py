#!/usr/bin/env python3
"""Backlog + never-retrieved audit (WikiCitadel v1).

The collector's fallacy, measured (survey find 1, Tietze:
having a text at hand is not knowing it; find 24, Obst: "too many
documents, not enough readers"). This wiki's standing rule is the
same distinction: a source mirrored into raw/ is PRESERVED, not
known — known means compiled into the wiki layer. This tool turns
that rule, and Obst's three audit questions, into numbers computed
from the tree itself — never from another tool's summary:

  (a) the INGEST BACKLOG: raw files in the provenance manifest
      that no compiled page lists in its frontmatter `sources:`
      — the validator's own coverage accounting (its parser, its
      resolvers, its exemptions), re-run here. Split by whether
      the file is at least mentioned in some page BODY (an inline
      cite marker or a plain path mention — cited, but not
      compiled into) or cited nowhere at all. Exempted files are
      flagged with the exemption rule that covers them: an
      exemption is a disposition, not a compilation. Backlog
      entries are aged by ingest date (git first-add date; a
      YYYY-MM-DD filename prefix is the fallback, and the basis
      is printed per entry).
  (b) the NEVER-RETRIEVED audit: compiled pages appearing in NO
      retrieval record we hold — the retrieval baseline's probe
      top-10s (evaluation/retrieval-baseline.json) and the Ask
      door's answer citations (wiki/access/qa-*.jsonl). Both
      records are SAMPLES, so the filing says "no retrieval on
      the available records", never "never used". Cross-tabulated
      by growth stage and work_type: a seedling with no retrieval
      is young; an evergreen with none is a finding.
  (c) OBST's three questions as the frame: how many did we
      CAPTURE (raw files preserved), how many did we COMPILE
      (wiki pages), how many have ever been RETRIEVED (pages
      with a retrieval record). Three numbers, honestly derived.

Measurement only: no page is edited. The first audit is filed at
wiki/filings/backlog-audit-<date>.md.

Usage:
  python3 scripts/wiki_audit_backlog.py [--root DIR]
          [--date YYYY-MM-DD] [--out FILE] [--no-write]

Exit 0 = audit computed and filed (or printed); 2 = usage error
(missing manifest/tree). Stdlib only.
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRUCTURAL = {"wiki/index.md", "wiki/log.md"}
DATE_PREFIX = re.compile(r"(\d{4}-\d{2}-\d{2})")


# ------------------------------------------------------------ validator

def load_validator(root: Path):
    """Import scripts/wiki_validate.py with its path globals
    re-pointed at `root`, so the coverage accounting used here is
    the validator's own (parser, resolvers, exemptions)."""
    spec = importlib.util.spec_from_file_location(
        "wiki_validate_for_audit", Path(__file__).parent / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    mod.WIKI = root / "wiki"
    mod.RAW = root / "raw"
    mod.RAW_SOURCES = root / "raw" / "sources"
    mod.MANIFEST_PATH = mod.RAW_SOURCES / "provenance-manifest.json"
    mod.NOTE_PATH = mod.RAW_SOURCES / "tools-record.md"
    return mod


# ------------------------------------------------------------ ingest age

def git_add_dates(root: Path):
    """{repo-relative path: first-add date} from one git pass.

    Empty dict when git or the history is unavailable — callers
    fall back to filename date prefixes."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--diff-filter=A",
             "--format=@@@%cs", "--name-only", "--", "raw/"],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    dates, current = {}, None
    for line in out.stdout.splitlines():
        if line.startswith("@@@"):
            try:
                current = date.fromisoformat(line[3:].strip())
            except ValueError:
                current = None
        elif line.strip() and current is not None:
            rel = line.strip()
            if rel not in dates or current < dates[rel]:
                dates[rel] = current
    return dates


def filename_date(rel: str):
    m = DATE_PREFIX.search(Path(rel).name)
    if not m:
        m = DATE_PREFIX.search(rel)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def ingest_date(rel, git_dates):
    """-> (date or None, basis)."""
    if rel in git_dates:
        return git_dates[rel], "git first-add"
    d = filename_date(rel)
    if d is not None:
        return d, "filename prefix"
    return None, "unknown"


def age_bucket(days):
    if days is None:
        return "unknown date"
    if days <= 0:
        return "0 days (today)"
    if days <= 3:
        return "1–3 days"
    if days <= 7:
        return "4–7 days"
    return "8+ days"


# ------------------------------------------------------------ retrieval

def resolve_qa_citation(citation, res):
    """Resolve an Ask-door citation (a page stem or path fragment)
    to a repo-relative page path, via the validator's resolvers."""
    cands = []
    for key in (citation, f"wiki/{citation}"):
        hit = res.by_path.get(key)
        if hit is not None:
            cands.append(hit)
    for key in (citation, Path(citation).name):
        cands.extend(res.by_stem.get(key, []))
    uniq = sorted({p.as_posix() for p in cands})
    return uniq[0] if len(uniq) == 1 else None


def load_retrieval_records(root: Path, res):
    """-> (retrieved_pages, probe_count, qa_count, qa_cited_pages).

    retrieved_pages: repo-relative wiki/ paths with at least one
    retrieval record (baseline probe top-10 or Ask-door citation).
    """
    retrieved, qa_cited = set(), set()
    probes = 0
    baseline_path = root / "evaluation" / "retrieval-baseline.json"
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        per_query = baseline.get("per_query") or {}
        probes = len(per_query)
        for rec in per_query.values():
            for path in rec.get("top10") or []:
                if path.startswith("wiki/"):
                    retrieved.add(path)
    qa_count = 0
    access = root / "wiki" / "access"
    if access.exists():
        for qa_file in sorted(access.glob("qa-*.jsonl")):
            for line in qa_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                qa_count += 1
                for cit in rec.get("citations") or []:
                    resolved = resolve_qa_citation(cit, res)
                    if resolved:
                        qa_cited.add(resolved)
                        retrieved.add(resolved)
    return retrieved, probes, qa_count, qa_cited


# ------------------------------------------------------------ the audit

def run_audit(root: Path, as_of: date):
    if not (root / "wiki").exists() or not (root / "raw").exists():
        raise SystemExit(f"usage error: {root} is not a wiki tree")
    v = load_validator(root)
    res = v.Resolvers()

    # ---- pages: fields, bodies, and the validator's `cited` set
    page_fields, bodies, cited = {}, {}, set()
    for p in res.pages:
        rel_page = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, body = v.parse_frontmatter(text)
        page_fields[rel_page] = fields or {}
        bodies[rel_page] = body if fields is not None else text
        if rel_page in STRUCTURAL or fields is None:
            continue
        for entry in v.as_list(fields.get("sources")):
            _st, resolved, _d = res.resolve_source(entry)
            if resolved:
                cited.add(resolved)

    # ---- the preserved universe: the provenance manifest
    manifest_path = root / "raw" / "sources" / "provenance-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_files = sorted((manifest.get("files") or {}).keys())
        universe_basis = (f"provenance manifest "
                          f"(generated {manifest.get('generated_at')})")
    else:
        manifest_files = sorted(
            p.relative_to(root).as_posix()
            for p in (root / "raw").rglob("*") if p.is_file())
        universe_basis = "live disk scan (no provenance manifest found)"
    disk_files = sorted(
        p.relative_to(root).as_posix()
        for p in (root / "raw").rglob("*") if p.is_file())
    unmanifested = [rel for rel in disk_files
                    if rel not in set(manifest_files)
                    and rel != "raw/sources/provenance-manifest.json"]

    rules, _note_found = v.load_exemptions()
    git_dates = git_add_dates(root)

    # ---- (a) the ingest backlog
    backlog = []
    for rel in manifest_files:
        if rel in cited:
            continue
        mentioned = any(rel in body for body in bodies.values())
        d, basis = ingest_date(rel, git_dates)
        backlog.append({
            "path": rel,
            "class": "cited-but-not-compiled" if mentioned else "uncited",
            "exemption": v.exemption_for(rel, rules),
            "ingest_date": d.isoformat() if d else None,
            "ingest_basis": basis,
            "age_days": (as_of - d).days if d else None,
        })
    backlog.sort(key=lambda e: (e["ingest_date"] is None,
                                e["ingest_date"] or "", e["path"]))

    # ---- (b) never retrieved
    compiled_pages = sorted(rel for rel in page_fields
                            if rel not in STRUCTURAL)
    retrieved, probes, qa_count, qa_cited = load_retrieval_records(root, res)
    retrieved_compiled = sorted(set(compiled_pages) & retrieved)
    never = []
    for rel in compiled_pages:
        if rel in retrieved:
            continue
        fields = page_fields.get(rel) or {}
        never.append({
            "path": rel,
            "created": fields.get("created"),
            "stage": fields.get("stage") or "(unstaged)",
            "work_type": fields.get("work_type") or "(untyped)",
        })
    never.sort(key=lambda e: (str(e["created"] or "9999"), e["path"]))
    stage_counts = Counter(e["stage"] for e in never)
    worktype_counts = Counter(e["work_type"] for e in never)
    crosstab = Counter((e["stage"], e["work_type"]) for e in never)

    # ---- (c) Obst's three numbers
    obst = {"captured": len(manifest_files),
            "compiled": len(compiled_pages),
            "retrieved": len(retrieved_compiled)}

    return {
        "as_of": as_of.isoformat(),
        "universe_basis": universe_basis,
        "cited_count": len([r for r in manifest_files if r in cited]),
        "backlog": backlog,
        "backlog_classes": dict(Counter(e["class"] for e in backlog)),
        "backlog_exempted": sum(1 for e in backlog if e["exemption"]),
        "age_buckets": dict(Counter(age_bucket(e["age_days"])
                                    for e in backlog)),
        "unmanifested": unmanifested,
        "probes": probes,
        "qa_count": qa_count,
        "qa_cited_pages": sorted(qa_cited),
        "retrieved_compiled": retrieved_compiled,
        "never": never,
        "stage_counts": dict(stage_counts),
        "worktype_counts": dict(worktype_counts),
        "crosstab": {f"{s} × {w}": n for (s, w), n in
                     sorted(crosstab.items())},
        "obst": obst,
    }


# ------------------------------------------------------------ rendering

def pct(part, whole):
    return f"{(100.0 * part / whole):.1f}%" if whole else "—"


def render(a, as_of: date):
    obst, backlog, never = a["obst"], a["backlog"], a["never"]
    lines = [
        "---",
        f'title: "Backlog + never-retrieved audit — {as_of.isoformat()}"',
        "type: query",
        f"created: {as_of.isoformat()}",
        f"updated: {as_of.isoformat()}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [audit, backlog, retrieval, filings]",
        "status: draft",
        "confidence: observed",
        "stage: seedling",
        f"planted: {as_of.isoformat()}",
        f"tended: {as_of.isoformat()}",
        "work_type: record",
        "---",
        "",
        f"# Backlog + never-retrieved audit — {as_of.isoformat()}",
        "",
        "> [!note] MEASUREMENT ONLY — nothing applied",
        "> Generated by `scripts/wiki_audit_backlog.py` from the tree"
        " itself (the validator's own coverage accounting, the"
        " retrieval baseline, and the Ask-door log). No page has"
        " been changed by this audit; it names the pile so the pile"
        " cannot grow invisibly (the survey, finds 1 + 24).",
        "",
        "## Obst's three questions",
        "",
        "Marcus Obst's audit of any vault (survey find 24): what did"
        " we capture, what did we compile, what has ever been"
        " retrieved — \"the rest is dead weight with good metadata.\"",
        " Our form of the three numbers:",
        "",
        "| Question | Count |",
        "|---|---|",
        f"| Captured — raw files preserved (preserved ≠ known) |"
        f" {obst['captured']} |",
        f"| Compiled — wiki pages written from them |"
        f" {obst['compiled']} |",
        f"| Retrieved — compiled pages with a retrieval record |"
        f" {obst['retrieved']} |",
        "",
        f"Compiled/captured: {pct(obst['compiled'], obst['captured'])}"
        f" · retrieved/compiled:"
        f" {pct(obst['retrieved'], obst['compiled'])}.",
        "",
        "## (a) The ingest backlog — preserved, not yet compiled",
        "",
        f"Universe: {a['universe_basis']}. Of"
        f" {a['obst']['captured']} preserved files,"
        f" {a['cited_count']} are listed in at least one page's"
        " frontmatter `sources:` (compiled into, by the validator's"
        f" accounting) and **{len(backlog)} are in the backlog**:"
        " preserved but not compiled into any page.",
        "",
        "| Backlog class | Count |",
        "|---|---|",
        f"| Cited in a page body (cite marker or path mention) but"
        f" not compiled into |"
        f" {a['backlog_classes'].get('cited-but-not-compiled', 0)} |",
        f"| Cited nowhere in the wiki layer |"
        f" {a['backlog_classes'].get('uncited', 0)} |",
        f"| — of the backlog, covered by a coverage exemption"
        f" (a disposition, not a compilation) |"
        f" {a['backlog_exempted']} |",
        "",
        "Backlog by age (ingest date: git first-add where the"
        " history knows it, else the filename's date prefix):",
        "",
        "| Age | Count |",
        "|---|---|",
    ]
    for bucket in ("0 days (today)", "1–3 days", "4–7 days",
                   "8+ days", "unknown date"):
        if bucket in a["age_buckets"]:
            lines.append(f"| {bucket} | {a['age_buckets'][bucket]} |")
    lines += ["", "The backlog, oldest first:", "",
              "| Raw file | Class | Exemption | Ingested | Age (days) |",
              "|---|---|---|---|---|"]
    for e in backlog:
        lines.append(
            f"| `{e['path']}` | {e['class']} |"
            f" {('`' + e['exemption'] + '`') if e['exemption'] else '—'}"
            f" | {e['ingest_date'] or 'unknown'}"
            f" ({e['ingest_basis']}) |"
            f" {e['age_days'] if e['age_days'] is not None else '—'} |")
    if a["unmanifested"]:
        lines += ["",
                  "On disk under `raw/` but not yet in the provenance"
                  " manifest (preserved on disk, not yet in the"
                  " accounting):",
                  ""]
        lines += [f"- `{rel}`" for rel in a["unmanifested"]]
    lines += [
        "",
        "## (b) Never retrieved — no retrieval on the available records",
        "",
        "The records are samples, and this filing says exactly what"
        " they support: a page below has **no retrieval on the"
        " available records** — it does not say the page was never"
        f" used. The records: {a['probes']} baseline probes (golden"
        " + extended sets; a page counts as retrieved if it appears"
        f" in any probe's top-10) and {a['qa_count']} Ask-door"
        " questions (a page counts if an answer cited it).",
        "",
        f"**{len(never)} of {obst['compiled']} compiled pages have"
        " no retrieval record.** Cross-tabulated by growth stage"
        " and work type — a seedling with no retrieval is young;"
        " an evergreen with none is a finding:",
        "",
        "| Stage | Never retrieved |",
        "|---|---|",
    ]
    for stage, n in sorted(a["stage_counts"].items(),
                           key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {stage} | {n} |")
    lines += ["", "| Work type | Never retrieved |", "|---|---|"]
    for wt, n in sorted(a["worktype_counts"].items(),
                        key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {wt} | {n} |")
    lines += ["", "| Stage × work type | Count |", "|---|---|"]
    for cell, n in a["crosstab"].items():
        lines.append(f"| {cell} | {n} |")
    lines += ["", "The pages, oldest first:", "",
              "| Page | Created | Stage | Work type |",
              "|---|---|---|---|"]
    for e in never:
        lines.append(f"| `{e['path']}` | {e['created'] or '—'} |"
                     f" {e['stage']} | {e['work_type']} |")
    lines += [
        "",
        "## Method",
        "",
        "- Coverage accounting is the validator's own"
        " (`scripts/wiki_validate.py`: frontmatter `sources:`"
        " resolved by its resolvers; exemptions from the"
        " engineering note's Coverage exemptions section), re-run"
        " from the tree — not copied from any tool's printed"
        " summary.",
        "- \"Compiled into\" means listed in a page's frontmatter"
        " sources. A body mention is weaker evidence and is"
        " reported as its own class, never merged into it.",
        "- Retrieval counts a page once whether it was retrieved"
        " once or a hundred times; this audit measures the"
        " complement of retrieval, not its volume.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--date", default=None,
                    help="audit date (default: today)")
    ap.add_argument("--out", type=Path, default=None,
                    help="filing path (default:"
                         " wiki/filings/backlog-audit-<date>.md)")
    ap.add_argument("--no-write", action="store_true",
                    help="print the filing instead of writing it")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    as_of = date.fromisoformat(args.date) if args.date else date.today()
    a = run_audit(root, as_of)
    text = render(a, as_of)
    obst = a["obst"]
    print(f"Obst: captured {obst['captured']} · compiled"
          f" {obst['compiled']} · retrieved {obst['retrieved']}")
    print(f"Backlog: {len(a['backlog'])} preserved-not-compiled"
          f" ({a['backlog_classes']}); never retrieved:"
          f" {len(a['never'])} of {obst['compiled']} pages")
    if args.no_write:
        print(text)
        return 0
    out = args.out or (root / "wiki" / "filings" /
                       f"backlog-audit-{as_of.isoformat()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Filed: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
