#!/usr/bin/env python3
"""wiki_edge_labels.py — edge provenance labels: backfill
report + check (build wave 1, item W1.8).

The label model lives in tools/lens/lenslib.py (the
edge-label section): every typed edge carries a three-way
provenance label (EXTRACTED / INFERRED / AMBIGUOUS), a
confidence in [0, 1] and a polarity. New edges are labelled
at creation by the traversal door (scripts/wiki_traverse.py)
and the Lens build; this tool is the BACKFILL side for the
edges that already exist: it enumerates the corpus's edges
through the door, applies the same rules plus the
directed-pair conflict pass, and reports what label each
existing edge WOULD carry and which rule assigned it. It
rewrites nothing — no page, register or artefact is edited;
the report is the deliverable, and consumers pick the labels
up at their next build.

Commands:
  report [--root DIR] [--out DIR]
      Print the report summary; with --out, also write
      edge-label-backfill-report.json (the full edge list)
      and edge-label-backfill-report.md (the readable form)
      into DIR.
  check [--root DIR]
      Exit 0 when every door edge carries a label from the
      closed set with a confidence in [0, 1]; 1 otherwise
      (the failures are printed). Unlabeled edges are a
      finding here, never an error anywhere else: labels are
      additive metadata.

Exit: 0 ok, 1 check failed, 2 usage error. Stdlib only, no
network. Patterns credited in lenslib's edge-label header:
the three-way tag is the legal-graphify-skill's idea
(dual-licensed MIT OR Apache-2.0, adapt-with-credit),
generalised with PENgram's type+provenance lesson and Typed
Graph's signed relations; all code here is our own.
"""
import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RULES = {
    "citation-frontmatter":
        "kind citation: the frontmatter `sources:` entry is "
        "written in the page and hash-locked — EXTRACTED, 1.0.",
    "declared-frontmatter":
        "kind typed: the author declared the relation in "
        "frontmatter (`links:` or a relation-vocabulary "
        "field) — EXTRACTED, 1.0.",
    "verbatim-link":
        "kind wikilink, type mentions: the link is verbatim "
        "and asserts nothing beyond its presence — "
        "EXTRACTED, 1.0.",
    "heading-inferred-type":
        "kind wikilink with a specific type: the link is "
        "verbatim but its type came from the heading rule — "
        "INFERRED, 0.75.",
    "conflicting-typed-pair":
        "the directed pair asserts two or more distinct "
        "specific types; neither governs — AMBIGUOUS, 0.5.",
    "derived":
        "an edge kind no page writes — INFERRED at the base "
        "signal confidence.",
}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rule_for(kind, relation):
    """The assignment rule that labels one door edge (before
    the conflict pass)."""
    if kind == "citation":
        return "citation-frontmatter"
    if kind == "typed":
        return "declared-frontmatter"
    if kind == "wikilink":
        return "verbatim-link" if (relation or "mentions") \
            == "mentions" else "heading-inferred-type"
    return "derived"


def labelled_edges(root):
    """(edges, conflicts) for the corpus under `root`: the
    door's edges with their labels and assigning rules, after
    the directed-pair conflict pass; conflicts lists each
    directed pair that carries two or more distinct specific
    types. Edge dicts are copies — the door's own output is
    never mutated."""
    root = Path(root)
    traverse = _load("wiki_traverse_for_labels",
                     root / "scripts" / "wiki_traverse.py")
    lens = _load("lenslib_for_labels",
                 root / "tools" / "lens" / "lenslib.py")
    _pages, _keys, door_edges = traverse.page_graph(root)
    edges = []
    for e in door_edges:
        lab = {"provenance": e.get("provenance"),
               "confidence": e.get("confidence"),
               "polarity": e.get("polarity")}
        if lab["provenance"] is None:
            lab = lens.edge_label(e.get("kind"),
                                  e.get("relation"))
        edges.append({"src": e["src"], "dst": e["dst"],
                      "kind": e["kind"],
                      "relation": e["relation"],
                      "rule": rule_for(e.get("kind"),
                                       e.get("relation")),
                      **lab})
    before = {(e["src"], e["dst"], e["kind"], e["relation"]):
              e["provenance"] for e in edges}
    lens.apply_directed_pair_conflicts(edges)
    conflicts = {}
    for e in edges:
        key = (e["src"], e["dst"], e["kind"], e["relation"])
        if before.get(key) != e["provenance"] \
                and e["provenance"] == "AMBIGUOUS":
            e["rule"] = "conflicting-typed-pair"
            conflicts.setdefault((e["src"], e["dst"]), set()).add(
                e["relation"])
    conflict_rows = [{"src": s, "dst": d, "types": sorted(ts)}
                     for (s, d), ts in sorted(conflicts.items())]
    edges.sort(key=lambda e: (e["src"], e["dst"], e["kind"],
                              e["relation"]))
    return edges, conflict_rows


def build_report(root):
    edges, conflicts = labelled_edges(root)
    return {
        "kind": "edge-label-backfill-report",
        "item": "W1.8 edge confidence labels",
        "model": "tools/lens/lenslib.py edge-label section "
                 "(EXTRACTED / INFERRED / AMBIGUOUS + "
                 "confidence + polarity)",
        "rules": RULES,
        "counts": {
            "edges": len(edges),
            "by_provenance": dict(sorted(Counter(
                e["provenance"] for e in edges).items())),
            "by_rule": dict(sorted(Counter(
                e["rule"] for e in edges).items())),
            "by_kind": dict(sorted(Counter(
                e["kind"] for e in edges).items())),
            "conflicting_pairs": len(conflicts),
        },
        "conflicts": conflicts,
        "edges": edges,
    }


def report_md(report):
    c = report["counts"]
    lines = ["# Edge-label backfill report (W1.8)", "",
             "Every existing typed edge in the corpus, the "
             "provenance label it would carry under the "
             "lenslib edge-label model, and the rule that "
             "assigned it. A report, not a rewrite: no page or "
             "register was edited; consumers pick the labels "
             "up at their next build (the traversal door and "
             "the Lens build already emit them).", "",
             f"- Edges enumerated (the traversal door's full "
             f"edge table, citation edges included): "
             f"**{c['edges']}**",
             f"- Conflicting directed pairs (AMBIGUOUS): "
             f"**{c['conflicting_pairs']}**", "",
             "## By provenance", "",
             "| Provenance | Edges |", "|---|---|"]
    for k, v in c["by_provenance"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## By assigning rule", "",
              "| Rule | Edges | What it means |", "|---|---|---|"]
    for k, v in c["by_rule"].items():
        lines.append(f"| {k} | {v} | {report['rules'][k]} |")
    lines += ["", "## Conflicting directed pairs", ""]
    if report["conflicts"]:
        lines += ["| Source | Target | Types asserted |",
                  "|---|---|---|"]
        for row in report["conflicts"]:
            lines.append(f"| {row['src']} | {row['dst']} | "
                         f"{', '.join(row['types'])} |")
    else:
        lines.append("None: no directed pair asserts two "
                     "distinct specific types.")
    lines += ["", "The full per-edge list (src, dst, kind, "
              "relation, provenance, confidence, polarity, "
              "rule) is in edge-label-backfill-report.json "
              "beside this file.", ""]
    return "\n".join(lines)


def cmd_report(args):
    report = build_report(args.root)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "edge-label-backfill-report.json").write_text(
            json.dumps(report, indent=1, ensure_ascii=False,
                       sort_keys=True) + "\n", encoding="utf-8")
        (out / "edge-label-backfill-report.md").write_text(
            report_md(report), encoding="utf-8")
        print(f"wrote {out}/edge-label-backfill-report.json "
              f"+ .md")
    c = report["counts"]
    print(f"edges {c['edges']} · by provenance "
          f"{c['by_provenance']} · conflicting pairs "
          f"{c['conflicting_pairs']}")
    return 0


def cmd_check(args):
    lens = _load("lenslib_for_labels_check",
                 Path(args.root) / "tools" / "lens"
                 / "lenslib.py")
    edges, _conflicts = labelled_edges(args.root)
    bad = []
    for e in edges:
        if e["provenance"] not in lens.EDGE_PROVENANCE_LABELS:
            bad.append(f"{e['src']} -> {e['dst']}: provenance "
                       f"{e['provenance']!r} outside the "
                       f"closed label set")
        if not isinstance(e["confidence"], (int, float)) \
                or not 0.0 <= e["confidence"] <= 1.0:
            bad.append(f"{e['src']} -> {e['dst']}: confidence "
                       f"{e['confidence']!r} outside [0, 1]")
    if bad:
        for b in bad[:50]:
            print(f"FAIL {b}")
        print(f"check: {len(bad)} labelling failure(s) over "
              f"{len(edges)} edges")
        return 1
    print(f"check: all {len(edges)} edges carry a closed-set "
          f"label with a confidence in [0, 1]")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Edge provenance labels: backfill report "
                    "+ check (W1.8).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("report", "check"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=str(ROOT))
        if name == "report":
            p.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    return {"report": cmd_report, "check": cmd_check}[args.cmd](
        args)


if __name__ == "__main__":
    sys.exit(main())
