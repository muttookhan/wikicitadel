#!/usr/bin/env python3
"""wiki_link_embedding_eval.py - link-graph evaluation harness.

Marathon R13 lane BB (ideas board line 203, deep-study batch 8,
Tier A): the OpenKE PATTERN, reduced honestly to what stdlib
offline machinery can claim - a link-prediction EVALUATION over
the wiki's own wikilink graph. OFFLINE and REPORT-ONLY, stated
on the report's face: no external ML stack, no embedding model
is trained; the scorer is the simple stated baseline below.
Deterministic holdout: edges sorted, every 5th edge held out.
For each held-out (source, target), all non-neighbour pages are
ranked by the baseline scorer; Hits@10 and MRR are computed,
and the top-ranked held-out-style candidates from the FULL
graph are listed as suggested missing links FOR HUMAN REVIEW.
Suggestions NEVER write to the wiki and nothing is auto-applied;
this tool writes only the two report files it is told to write.
Baseline scorer (stated): score(s, t) = 2 * common-neighbours
+ adamic-adar sum over common neighbours + 0.001 * degree(t)
(preferential-attachment tiebreak). Usage:
  run --out-json FILE --out-md FILE [--wiki-dir DIR] [--top N]
Exit 0 whenever the report is produced. Stdlib only.
"""
import argparse, json, math, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[\[([^\]|#]+)")


def build_graph(wiki_dir):
    pages = {}
    for p in sorted(Path(wiki_dir).rglob("*.md")):
        pages[p.stem] = p
    graph = {stem: set() for stem in pages}
    for stem, p in pages.items():
        text = p.read_text(encoding="utf-8", errors="replace")
        for target in LINK_RE.findall(text):
            t = target.split("/")[-1].strip()
            if t in graph and t != stem:
                graph[stem].add(t)
    return graph


def score(graph, s, t):
    ns, nt = graph.get(s, set()), graph.get(t, set())
    common = ns & nt
    aa = sum(1.0 / math.log(len(graph[c])) for c in common
             if len(graph[c]) > 1)
    return 2 * len(common) + aa + 0.001 * len(nt)


def evaluate(graph, holdout_every=5):
    edges = sorted((s, t) for s in graph for t in graph[s])
    held = [e for i, e in enumerate(edges) if i % holdout_every == 0]
    train = {s: set(v) for s, v in graph.items()}
    for s, t in held:
        train[s].discard(t)
    hits, rr_sum, ranks = 0, 0.0, []
    for s, t in held:
        cands = [c for c in graph if c != s and c not in train[s]]
        ranked = sorted(cands, key=lambda c: (-score(train, s, c), c))
        rank = ranked.index(t) + 1 if t in ranked else len(ranked) + 1
        ranks.append(rank)
        if rank <= 10:
            hits += 1
        rr_sum += 1.0 / rank
    n = len(held)
    return {"edges_total": len(edges), "held_out": n,
            "hits_at_10": (hits / n if n else 0.0),
            "mrr": (rr_sum / n if n else 0.0), "ranks": ranks}


def suggestions(graph, top=20):
    out = []
    for s in sorted(graph):
        cands = [c for c in graph if c != s and c not in graph[s]]
        ranked = sorted(cands, key=lambda c: (-score(graph, s, c), c))
        for c in ranked[:3]:
            sc = score(graph, s, c)
            if sc > 0:
                out.append({"source": s, "candidate": c,
                            "score": round(sc, 4)})
    out.sort(key=lambda r: (-r["score"], r["source"], r["candidate"]))
    return out[:top]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out-json", required=True)
    r.add_argument("--out-md", required=True)
    r.add_argument("--wiki-dir", default=None)
    r.add_argument("--top", type=int, default=20)
    a = ap.parse_args(argv)
    graph = build_graph(a.wiki_dir or (ROOT / "wiki"))
    ev = evaluate(graph)
    sugg = suggestions(graph, a.top)
    report = {"tool": "link-embedding-eval",
              "pattern": "OpenKE pattern, batch 8 - offline, "
                         "report-only; NO embedding model trained; "
                         "baseline scorer as documented in the "
                         "module docstring",
              "report_only": True, "auto_applied": False,
              "pages": len(graph), **ev, "suggestions": sugg}
    Path(a.out_json).write_text(json.dumps(report, indent=2) + "\n",
                                encoding="utf-8")
    lines = ["# Link-graph evaluation report (REPORT-ONLY)", "",
             "Suggestions below are FOR HUMAN REVIEW ONLY. They "
             "NEVER write to the wiki; nothing is auto-applied. "
             "No embedding model was trained: metrics use the "
             "stated stdlib baseline scorer (common neighbours + "
             "Adamic-Adar + degree tiebreak) over a deterministic "
             "held-out split of the wiki's own link graph.", "",
             f"- Pages: {report['pages']}",
             f"- Edges total: {ev['edges_total']}",
             f"- Held out: {ev['held_out']}",
             f"- Hits@10: {ev['hits_at_10']:.4f}",
             f"- MRR: {ev['mrr']:.4f}", "",
             "## Suggested missing links (human review only)", ""]
    for s in sugg:
        lines.append(f"- [[{s['source']}]] -> [[{s['candidate']}]]"
                     f" (score {s['score']})")
    Path(a.out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"pages={report['pages']} edges={ev['edges_total']} "
          f"hits@10={ev['hits_at_10']:.4f} mrr={ev['mrr']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
