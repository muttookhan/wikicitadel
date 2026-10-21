#!/usr/bin/env python3
"""Pre-action failure-history precheck (projectmem-style).

Marathon R9 lane BA (ideas board R7 deep-dive, Tier A;
pattern: projectmem, MIT): before editing a page or path,
one report surfaces everything this wiki has already logged
about failing there — its logged issues, failed attempts and
fixes — so the next edit starts from the record instead of
repeating it. The report reads the three registers where
failures already live:

  corrections ledger   wiki/rules/corrections-ledger.md —
      entries whose heading or body names the target (the
      record that was wrong, and the standing rule the
      correction left);
  post-mortems         evaluation/post-mortems.jsonl —
      entries naming the target in see_also, trigger_ref,
      title or what_happened (the failure, its root-cause
      class, and the rule changed);
  reflexion notes      the `- [date] reflexion | ...` notes
      appended to wiki pages and wiki/log.md by
      scripts/wiki_reflexion.py — notes whose block names
      the target (what failed, its cause class, and the
      fixed do-differently line).

Matching: the target as given (a repo-relative path), its
file stem, and path suffixes all count; stem matches are
word-bounded so a short stem cannot swallow unrelated pages.

REPORT-ONLY: this tool reads the registers and writes
nothing — no page, register or note is created, edited or
annotated by running it. A register a tree does not carry
is reported absent, never treated as empty-and-clean; a
target with no hits is reported as having no recorded
failure history, which is a statement about the registers,
not about the target.

Usage:
  python3 scripts/wiki_precheck.py <page-or-path>
          [--root DIR] [--json]
Exit: 0 = report printed (hits or none); 2 = usage error.
Stdlib only. No model calls, no network.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def target_variants(target):
    """(paths, stem) for a target: the path as given (with
    and without a leading wiki/), plus its file stem."""
    t = target.strip().strip("/")
    paths = {t}
    if t.startswith("wiki/"):
        paths.add(t[len("wiki/"):])
    stem = Path(t).stem
    return sorted(paths), stem


def _mentions(text, paths, stem):
    if not text:
        return False
    low = text.lower()
    for p in paths:
        if p and p.lower() in low:
            return True
    if stem and len(stem) >= 4:
        if re.search(r"(?<![a-z0-9])" + re.escape(stem.lower())
                     + r"(?![a-z0-9])", low):
            return True
    return False


def ledger_hits(root, paths, stem):
    ledger = Path(root) / "wiki" / "rules" / \
        "corrections-ledger.md"
    if not ledger.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        "wiki_corrections_for_precheck",
        Path(__file__).resolve().parent / "wiki_corrections.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = ledger.read_text(encoding="utf-8")
    entries, classifications = mod.parse_ledger(text)
    # Entry bodies: split the text on entry headings, in order.
    chunks = re.split(r"^### \d{4}-\d{2}-\d{2} — .*$", text,
                      flags=re.M)
    bodies = chunks[1:1 + len(entries)]
    hits = []
    for entry, body in zip(entries, bodies):
        key = entry["date"] + " " + mod._norm_title(
            entry["title"])
        rule = (classifications.get(key) or {}).get("rule")
        haystack = entry["title"] + "\n" + body
        if _mentions(haystack, paths, stem):
            hits.append({
                "date": entry["date"], "title": entry["title"],
                "standing_rule": rule,
                "kind": (classifications.get(key) or {}).get(
                    "kind"),
            })
    return hits


def postmortem_hits(root, paths, stem):
    register = Path(root) / "evaluation" / "post-mortems.jsonl"
    if not register.is_file():
        return None
    hits = []
    for line in register.read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        fields = [row.get("title") or "",
                  row.get("trigger_ref") or "",
                  row.get("what_happened") or ""]
        fields += [str(s) for s in row.get("see_also") or []]
        if any(_mentions(f, paths, stem) for f in fields):
            hits.append({
                "id": row.get("id"), "date": row.get("date"),
                "title": row.get("title"),
                "root_cause_class": row.get(
                    "root_cause_class"),
                "rule_changed": row.get("rule_changed"),
            })
    return hits


REFLEXION_RE = re.compile(
    r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*reflexion\s*\|\s*(.*)$")


def reflexion_hits(root, paths, stem):
    wiki = Path(root) / "wiki"
    if not wiki.is_dir():
        return None
    hits = []
    for page in sorted(wiki.rglob("*.md")):
        lines = page.read_text(encoding="utf-8",
                               errors="ignore").splitlines()
        i = 0
        while i < len(lines):
            m = REFLEXION_RE.match(lines[i].strip())
            if not m:
                i += 1
                continue
            block = [lines[i]]
            j = i + 1
            while j < len(lines) and (lines[j].startswith(
                    (" ", "\t", "- Failed", "- Cause",
                     "- Evidence", "- Do differently"))
                    or lines[j].strip().startswith("- ")):
                block.append(lines[j])
                j += 1
                if len(block) > 6:
                    break
            text = "\n".join(block)
            if _mentions(text, paths, stem):
                hits.append({
                    "date": m.group(1),
                    "subject": m.group(2).strip(),
                    "page": page.relative_to(root).as_posix(),
                    "note": " ".join(text.split()),
                })
            i = j if j > i else i + 1
    return hits


def build_report(root, target):
    root = Path(root)
    paths, stem = target_variants(target)
    ledger = ledger_hits(root, paths, stem)
    postmortems = postmortem_hits(root, paths, stem)
    reflexion = reflexion_hits(root, paths, stem)
    return {
        "target": target,
        "corrections_ledger": ledger,
        "post_mortems": postmortems,
        "reflexion_notes": reflexion,
        "total_hits": sum(len(h) for h in
                          (ledger, postmortems, reflexion)
                          if h),
    }


def render_text(rep):
    lines = [f"Pre-action failure-history precheck — "
             f"{rep['target']}"]
    total = rep["total_hits"]
    if total == 0:
        lines.append("No recorded failure history for this "
                     "target in the registers read. (That is "
                     "a statement about the registers, not "
                     "about the target.)")
    sections = (
        ("corrections_ledger", "Corrections ledger entries"),
        ("post_mortems", "Failure post-mortems"),
        ("reflexion_notes", "Reflexion notes"),
    )
    for key, title in sections:
        hits = rep[key]
        lines.append("")
        if hits is None:
            lines.append(f"{title}: register absent in this "
                         f"tree — not read, not treated as "
                         f"clean.")
            continue
        lines.append(f"{title}: {len(hits)} hit(s)")
        for h in hits:
            if key == "corrections_ledger":
                lines.append(f"  - {h['date']} — {h['title']} "
                             f"[kind: {h['kind']}; standing "
                             f"rule: {h['standing_rule']}]")
            elif key == "post_mortems":
                lines.append(f"  - {h['id']} ({h['date']}) — "
                             f"{h['title']} [root cause: "
                             f"{h['root_cause_class']}]")
                if h["rule_changed"]:
                    lines.append(f"      rule changed: "
                                 f"{h['rule_changed']}")
            else:
                lines.append(f"  - [{h['date']}] {h['subject']} "
                             f"(on {h['page']})")
                lines.append(f"      {h['note']}")
    lines.append("")
    lines.append("Report only — nothing was written.")
    return "\n".join(lines) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Surface a page/path's logged failure "
                    "history before editing it (report-only).")
    ap.add_argument("target", help="repo-relative page/path, "
                                   "or a page stem")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    if not args.target.strip():
        print("precheck: empty target", file=sys.stderr)
        return 2
    rep = build_report(Path(args.root), args.target)
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(render_text(rep), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
