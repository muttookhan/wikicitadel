#!/usr/bin/env python3
"""Basis lines beside governed-vocabulary assignments.

Marathon R9 lane BA (ideas board R7 research, Tier A; pattern:
Mai, "Classification in a social world", CC BY 4.0): a governed
vocabulary assignment — a subject carrying a term from one of
this wiki's fixed vocabularies — currently renders as the label
alone wherever the assignments are listed. This module renders
each assignment WITH a `basis:` one-liner: the reason the term
means what it means here, taken from the vocabulary's own
existing text (a sensitivity class's meaning, a tag concept's
scopeNote, a notice's applicability statement) and, where the
assignment itself records one, the assignment's own basis.

Families, rendered in this order (sensitivity first, per the
board item):

  sensitivity  evaluation/sensitivity.json assignments[]:
               subject = the classified path, label = the
               class; basis = the assignment's own `basis`
               when recorded, else the class's `meaning`.
  tags         evaluation/tag-registry.jsonl concepts in live
               use on wiki pages: subject = the concept,
               label = its prefLabel; basis = its scopeNote,
               else its definition.
  notices      evaluation/notices.jsonl applications still in
               force: subject = the page, label = the notice
               id; basis = the notice's `applicability` text
               in evaluation/notice-vocabulary.json.

No vocabulary is changed and no new scheme is introduced: the
module only reads the existing registers and renders beside
them. `check` reports every assignment for which NO basis text
is available from those existing fields — an assignment whose
label would still stand alone.

Usage:
  python3 scripts/wiki_vocab_basis.py [render] [--root DIR]
  python3 scripts/wiki_vocab_basis.py check [--root DIR] [--json]
Exit: render 0; check 0 = every assignment has an available
basis, 1 = at least one lacks one, 2 = usage error.
Stdlib only. No model calls, no network, writes nothing.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FAMILY_ORDER = ("sensitivity", "tags", "notices")


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    out = []
    for line in lines:
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _one_line(text):
    return " ".join((text or "").split())


def _frontmatter_tags(root):
    """{tag: [page, ...]} from live wiki pages (best effort:
    the validator's own frontmatter parser when importable)."""
    usage = {}
    wiki = Path(root) / "wiki"
    if not wiki.is_dir():
        return usage
    parse = None
    try:
        spec = importlib.util.spec_from_file_location(
            "wiki_validate_for_basis",
            Path(__file__).resolve().parent / "wiki_validate.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        parse = (mod.parse_frontmatter, mod.as_list)
    except Exception:
        parse = None
    for page in sorted(wiki.rglob("*.md")):
        text = page.read_text(encoding="utf-8", errors="ignore")
        tags = []
        if parse:
            fields, _b = parse[0](text)
            if fields:
                tags = [str(t) for t in parse[1](fields.get("tags"))]
        else:
            m = re.search(r"^tags:\s*\[(.*?)\]\s*$", text, re.M)
            if m:
                tags = [t.strip().strip("'\"") for t in
                        m.group(1).split(",") if t.strip()]
        rel = page.relative_to(root).as_posix()
        for tag in tags:
            usage.setdefault(tag, []).append(rel)
    return usage


def collect_assignments(root):
    """(assignments, absent) for the root's registers.

    assignments: [{family, subject, label, basis,
    basis_source}] with basis "" when none is available.
    absent: [family names whose register is not present].
    """
    root = Path(root)
    assignments = []
    absent = []

    # --- sensitivity first -----------------------------------
    sens = _load_json(root / "evaluation" / "sensitivity.json")
    if sens is None:
        absent.append("sensitivity")
    else:
        meanings = {c.get("id"): c.get("meaning") or ""
                    for c in sens.get("classes") or []}
        for a in sens.get("assignments") or []:
            cls = a.get("class") or ""
            own = _one_line(a.get("basis"))
            if own:
                basis, src = own, "assignment basis"
            elif meanings.get(cls):
                basis = _one_line(meanings[cls])
                src = "class meaning"
            else:
                basis, src = "", ""
            assignments.append({
                "family": "sensitivity",
                "subject": a.get("path") or "",
                "label": cls, "basis": basis,
                "basis_source": src,
                "known_label": cls in meanings,
            })

    # --- tags -------------------------------------------------
    concepts = _load_jsonl(root / "evaluation" /
                           "tag-registry.jsonl")
    if concepts is None:
        absent.append("tags")
    else:
        usage = _frontmatter_tags(root)
        for row in concepts:
            if row.get("kind") != "concept":
                continue
            label = row.get("prefLabel") or row.get("id") or ""
            pages = usage.get(label)
            if pages is None:
                snap = (row.get("usage") or {}).get("pages") or []
                pages = snap
            if not pages:
                continue  # registered but never assigned
            scope = _one_line(row.get("scopeNote"))
            defin = _one_line(row.get("definition"))
            if scope:
                basis, src = scope, "concept scopeNote"
            elif defin:
                basis, src = defin, "concept definition"
            else:
                basis, src = "", ""
            assignments.append({
                "family": "tags",
                "subject": f"tag {label} "
                           f"({len(pages)} page(s))",
                "label": label, "basis": basis,
                "basis_source": src, "known_label": True,
            })

    # --- notices ----------------------------------------------
    vocab = _load_json(root / "evaluation" /
                       "notice-vocabulary.json")
    events = _load_jsonl(root / "evaluation" / "notices.jsonl")
    if vocab is None or events is None:
        absent.append("notices")
    else:
        by_id = {n.get("id"): n
                 for n in vocab.get("notices") or []}
        active = {}
        for ev in events:
            if ev.get("kind") == "applied":
                active[(ev.get("page"), ev.get("notice"))] = ev
            elif ev.get("kind") == "retired":
                active.pop((ev.get("page"), ev.get("notice")),
                           None)
        for (page, nid) in sorted(active):
            notice = by_id.get(nid)
            basis = _one_line(notice.get("applicability")) \
                if notice else ""
            assignments.append({
                "family": "notices",
                "subject": page or "",
                "label": nid or "", "basis": basis,
                "basis_source": "notice applicability"
                if basis else "",
                "known_label": notice is not None,
            })
    return assignments, absent


def lacking_basis(assignments):
    """Assignments whose label would still stand alone, plus
    assignments naming a label the vocabulary does not hold."""
    out = []
    for a in assignments:
        if not a["known_label"]:
            out.append({**a, "problem":
                        "label not in the vocabulary"})
        elif not a["basis"]:
            out.append({**a, "problem":
                        "no basis text in the vocabulary or "
                        "on the assignment"})
    return out


def render_lines(assignments, absent):
    lines = []
    by_family = {f: [a for a in assignments if a["family"] == f]
                 for f in FAMILY_ORDER}
    for fam in FAMILY_ORDER:
        rows = by_family[fam]
        if fam in absent:
            lines.append(f"== {fam} == register absent in this "
                         f"tree — no assignments rendered")
            continue
        lines.append(f"== {fam} == {len(rows)} assignment(s)")
        for a in rows:
            lines.append(f"{a['subject']} — {fam}: {a['label']}")
            if a["basis"]:
                lines.append(f"  basis: [{a['basis_source']}] "
                             f"{a['basis']}")
            else:
                lines.append("  basis: NONE AVAILABLE — this "
                             "assignment's label stands alone "
                             "(see check)")
    return lines


def main(argv):
    ap = argparse.ArgumentParser(
        description="Render basis lines beside governed-"
                    "vocabulary assignments, or check for "
                    "assignments lacking an available basis.")
    ap.add_argument("mode", nargs="?", default="render",
                    choices=("render", "check"))
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    assignments, absent = collect_assignments(Path(args.root))
    lacking = lacking_basis(assignments)
    if args.mode == "check":
        if args.json:
            print(json.dumps({
                "assignments": len(assignments),
                "absent_families": absent,
                "lacking_basis": lacking,
            }, indent=2, ensure_ascii=False))
        else:
            print(f"vocab-basis: {len(assignments)} "
                  f"assignment(s), {len(lacking)} lacking an "
                  f"available basis")
            for fam in absent:
                print(f"  [ABSENT] {fam} register not present "
                      f"in this tree")
            for a in lacking:
                print(f"  [LACKING] {a['family']}: "
                      f"{a['subject']} — {a['label']}: "
                      f"{a['problem']}")
        return 1 if lacking else 0
    if args.json:
        print(json.dumps({"assignments": assignments,
                          "absent_families": absent},
                         indent=2, ensure_ascii=False))
    else:
        print("\n".join(render_lines(assignments, absent)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
