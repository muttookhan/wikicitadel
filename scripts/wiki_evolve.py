#!/usr/bin/env python3
"""wiki_evolve.py — neighbour-evolution proposals.

Pattern: agiresearch/A-mem (MIT) evolves
the framing of memories linked to a newly inserted note, so old
pages do not silently go stale. A-mem rewrites its neighbours
automatically; OUR adaptation is deliberately weaker in power and
stronger in governance: this tool NEVER edits a neighbour. It
computes deterministic staleness signals for the changed page's
linked neighbours and emits a PROPOSAL into gateway staging for
each suspect neighbour — the proposal carries the neighbour's
current text plus a framing-review note naming the signals, and a
human reviewer decides, edits, and promotes (or rejects) through
the ordinary gateway path.

Signals (all deterministic):
  predates-change   the neighbour's `updated` is older than the
                    changed page's `updated`;
  evidence-divergence
                    the changed page cites sources the neighbour
                    does not — new evidence its framing may not
                    reflect;
  vocabulary-gap    content terms from the changed page's title
                    and claim appear nowhere in the neighbour.

A proposal is emitted only when at least one of the first two
(temporal/evidence) signals fires.

    python3 scripts/wiki_evolve.py wiki/concepts/some-page.md
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "gateway"))

from gateway.config import Config  # noqa: E402
from gateway.store import GatewayStore  # noqa: E402
from gateway import profile as profile_mod  # noqa: E402

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = set("""the a an and or of to in is are was were be been for on
with as by at from this that it its has have had not no do does did will
would can could should may might must shall than then so such into over
under more most other some any only also just very""".split())


def content_terms(text: str):
    return {t for t in TOKEN_RE.findall(text.lower())
            if len(t) >= 3 and t not in STOPWORDS}


def signals_for(store: GatewayStore, changed_rel: str,
                neighbour_rel: str) -> list[dict]:
    changed = store.read_page(changed_rel)
    neighbour = store.read_page(neighbour_rel)
    cf = profile_mod.frontmatter_of(changed) or {}
    nf = profile_mod.frontmatter_of(neighbour) or {}
    out = []
    cu, nu = str(cf.get("updated") or ""), str(nf.get("updated") or "")
    if cu and nu and nu < cu:
        out.append({"signal": "predates-change",
                    "detail": f"neighbour updated {nu}, changed page "
                              f"updated {cu}"})
    c_sources = set(cf.get("sources") or [])
    n_sources = set(nf.get("sources") or [])
    # Divergence is only meaningful between evidence-bearing
    # pages: a neighbour that cites nothing (overview, structural
    # pages) diverges from everything and means nothing by it.
    if c_sources and n_sources:
        new_evidence = sorted(c_sources - n_sources)
        if new_evidence:
            out.append({"signal": "evidence-divergence",
                        "detail": "changed page cites source(s) the "
                                  "neighbour does not: "
                                  + ", ".join(new_evidence[:5])})
    title_terms = content_terms(str(cf.get("title") or "")) \
        | content_terms(str(cf.get("claim") or ""))
    if title_terms:
        missing = sorted(title_terms - content_terms(neighbour))
        if missing and len(missing) >= max(1, len(title_terms) // 2):
            out.append({"signal": "vocabulary-gap",
                        "detail": "changed page's framing terms absent "
                                  "from the neighbour: "
                                  + ", ".join(missing[:8])})
    return out


def proposal_content(store: GatewayStore, changed_rel: str,
                     neighbour_rel: str, signals: list[dict]) -> str:
    neighbour = store.read_page(neighbour_rel)
    cf = profile_mod.frontmatter_of(store.read_page(changed_rel)) or {}
    lines = [neighbour.rstrip(),
             "",
             "---",
             "",
             "## Framing review — machine proposal (wiki-evolve)",
             "",
             f"This section was appended mechanically by "
             f"`scripts/wiki_evolve.py` (WikiCitadel v1; "
             f"pattern: agiresearch/A-mem, MIT) because "
             f"[[{Path(changed_rel).stem}]] changed "
             f"(updated {cf.get('updated')}). The page above is "
             f"UNEDITED: this proposal asks a human reviewer to "
             f"check whether its framing has gone stale in light "
             f"of that change, make any real edit by hand in "
             f"staging, and only then promote.",
             "",
             "Signals:"]
    for s in signals:
        lines.append(f"- **{s['signal']}** — {s['detail']}")
    lines.append("")
    # Premortem placeholder : the premortem is
    # written in a SEPARATE pass, by hand, before the
    # proposal is put to the owner; until then the staged
    # proposal carries this explicit NOT YET WRITTEN marker,
    # and scripts/wiki_decision_gate.py names every staged
    # proposal still carrying only the placeholder.
    lines += [
        "---",
        "",
        "## Premortem (not yet written)",
        "",
        "**NOT YET WRITTEN.** Before this proposal is put to "
        "the owner, a separate pass replaces this placeholder "
        "with a written premortem (format: "
        "`templates/proposal.md`): the heading becomes "
        "`## Premortem (YYYY-MM-DD)`, the premise is stated — "
        "\"It is <date, ~6 months on> and this failed. The "
        "reasons were:\" — and 3–7 concrete, past-tense "
        "reasons follow, each closed by the mitigation that "
        "designs against it or an explicit accepted-risk "
        "note. The exercise generates reasons; it does not "
        "raise correctness by any measured percentage "
        "(Klein's famous 30% is the increase in reasons "
        "*generated* under prospective hindsight — Mitchell, "
        "Russo & Pennington 1989 — whose design carried no "
        "accuracy check).",
        "",
    ]
    return "\n".join(lines)


def evolve(store: GatewayStore, changed_rel: str, actor: str = "wiki-evolve",
           max_proposals: int = 5) -> list[dict]:
    graph = store.graph_neighbors(changed_rel)
    neighbours = sorted(set(graph["inbound"]) | set(graph["outbound"]))
    emitted = []
    for rel in neighbours:
        if len(emitted) >= max_proposals:
            break
        # Structural pages (catalog, ledger) and access records
        # have no framing to go stale.
        if rel in ("wiki/index.md", "wiki/log.md") \
                or rel.startswith("wiki/access/"):
            continue
        sigs = signals_for(store, changed_rel, rel)
        kinds = {s["signal"] for s in sigs}
        # An anchor is required: the neighbour predates the change,
        # or new evidence arrived AND the framing vocabulary moved.
        anchored = "predates-change" in kinds or (
            "evidence-divergence" in kinds and "vocabulary-gap" in kinds)
        if not anchored:
            continue
        content = proposal_content(store, changed_rel, rel, sigs)
        meta = store.stage_proposal(
            actor=actor, session_id=f"wiki-evolve-{date.today()}",
            target_path=rel, content=content,
            cites=[changed_rel, rel],
            direction_source={"kind": "tooling",
                              "ref": "scripts/wiki_evolve.py"},
            task_ref="phase2-item4-neighbour-evolution")
        emitted.append({"neighbour": rel, "signals": sigs,
                        "proposal_id": meta["proposal_id"],
                        "state": meta["state"]})
    return emitted


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("page", help="repo-relative path of the changed page")
    ap.add_argument("--max", type=int, default=5)
    args = ap.parse_args(argv)
    env = {
        "GATEWAY_WIKI_ROOT": str(ROOT),
        "GATEWAY_STAGING_DIR": str(ROOT / "staging"),
    }
    store = GatewayStore(Config(env=env))
    emitted = evolve(store, args.page, max_proposals=args.max)
    if not emitted:
        print(f"no stale neighbours found for {args.page}")
        return 0
    for e in emitted:
        sig = ", ".join(s["signal"] for s in e["signals"])
        print(f"{e['neighbour']}: proposal {e['proposal_id']} "
              f"({e['state']}) — {sig}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
