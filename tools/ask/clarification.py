#!/usr/bin/env python3
"""Ask-door clarification — the reference interview (item 61).

Wave 10 synthesis, item 61 (wording governs): "before searching,
one assumption-free clarifying stem (situation / gap / intended
use) with the question paraphrased back for confirmation,
triggered only when the evidence measurably splits (wave 7's
gate, wave 9's wording — see C3); the asker's timing routes
instant vs queued."

C3's adjudication is the design: wave 9's FORM governs, wave 7's
facet machinery survives ONLY as the trigger. So this module has
two halves that never mix:

1. THE TRIGGER (mechanical, from the search layer). The probe
   retrieval the pickup already runs is measured for a SPLIT:

     Take the top TOP_K (= 8) results of `scripts/wiki_search.py`'s
     hybrid ranker (scores are max-normalised by the ranker, so
     masses are comparable). Assign each result to its topic
     community: the Lens build's own Louvain communities over its
     weighted affinity graph (`tools/lens/build_lens.py` — direct
     links, shared raw sources, common neighbours, same-type
     affinity; the clusters the Graph mode displays, ~10 over
     the corpus). Sum the scores per community. A SPLIT fires
     iff at least two communities are
     present AND the runner-up community holds at least
     MIN_SECOND_SHARE (= 0.30) of the top-K score mass AND the
     runner-up community's best single score is at least
     COMPARABLE_RATIO (= 0.70) of the leading community's best
     single score — material presence AND comparable strength:
     the evidence genuinely falls on both sides of a topic
     boundary, so an unclarified answer would silently pick a
     side. Anything less is one topic with a long tail: no
     clarification, straight to the answer — the common path pays
     nothing beyond the probe search it already ran.

   The split's internals (communities, pages, shares) are
   recorded on the clarification record for the run report.
   They are NEVER shown to the asker and never shape the
   question's wording — that is exactly the facet-chip failure
   C3 removed (wave 9A: closed menus smuggle the system's
   guesses into the ask).

2. THE FORM (wave 9, the reference interview). One clarifying
   exchange, in the interview craft's shape (RUSA 2023 §3.5;
   Ross & Dewdney via wave 9): the question paraphrased back for
   confirmation ("As I understand it, you're asking: … — is
   that the question?") plus ONE neutral stem inviting the
   asker's own words on the three sense-making facets —
   situation ("What are you working on?"), gap ("Where did you
   get stuck?"), intended use ("How would you use the answer?").
   No candidate interpretations are offered; the first plausible
   reading is a hypothesis handed back, not silently searched.

STATE. The clarification is a first-class state of the question,
not a side note. The pickup is a batch loop over the service's
question store and no live service exists in this environment to
test a round-trip against, so the round-trip is modelled on a
stored record: an append-only event log at
`wiki/access/clarifications-2026.jsonl` (the Q&A file's sibling),
folded by question id:

    (none) --clarification_asked--> clarifying
    clarifying --clarification_reply--> replied
    replied --clarification_closed--> closed (answered | abstained)

`route_question` is the state machine the pickup follows:
no state + split -> "clarify" (open the clarification, do NOT
answer, do NOT mark the question answered); clarifying ->
"await_reply" (skip quietly — never re-ask, never answer over
an open question); replied -> "answer" (compose with the reply
as added context; the Q&A record then carries the exchange
under its additive `clarification` field, and the pickup closes
the clarification with the outcome); closed -> "skip_closed";
no state + no split -> "answer" (the common path).

TIMING. The asker's timing (wave 9 find 12: Timing alone routes
"answer from what we hold" vs "go and get it") is stamped on the
clarification record as `timing`: what was asked (`asked`:
"now" | "queued" | null when the entry carries no timing) and
where it routed (`route`). The only live lane today is the
queued pickup — the instant lane (WebLLM) is an open owner
decision — so `route` is "queued" and, when "now" was asked,
the record says so plainly in `note` instead of pretending an
instant answer happened. The request is preserved for the day
the instant lane exists.

The gate is enforced by the tool, not by the pickup agent's
judgement: `open` re-runs the assessment and refuses to open a
clarification the evidence does not split for.

Usage:
  python3 tools/ask/clarification.py check --question "..."
  python3 tools/ask/clarification.py open --id <qid> \
      --question "..." --asker "..." --asked-at "..." \
      [--timing now|queued]
  python3 tools/ask/clarification.py state --id <qid>
  python3 tools/ask/clarification.py reply --id <qid> \
      --reply "..." [--by "..."]
  python3 tools/ask/clarification.py close --id <qid> \
      --outcome answered|abstained --answer-ref "<ref>"

  --store overrides the event-log path (tests use a temp file).
  --root overrides the repository root (the search corpus).

Pure stdlib; the search/graph imports load lazily by file path,
the way answer_contract.py loads the cite-lock module.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# --- The split definition (stated; see the module docstring) ---
TOP_K = 8                # evidence window over the hybrid ranking
MIN_SECOND_SHARE = 0.30  # runner-up community's min share of mass
COMPARABLE_RATIO = 0.70  # runner-up's best vs leader's best score

STORE_RELATIVE_PATH = "wiki/access/clarifications-2026.jsonl"

# The neutral stem: ONE invitation covering situation / gap /
# intended use, in the asker's own words (wave 9 find 11). It is
# deliberately constant — the craft is in its neutrality, and a
# stem generated from the evidence would smuggle the system's
# guess back in (C3).
STEM = ("It would help to know a little more, in your own words: "
        "what are you working on, where did you get stuck, and "
        "how would you use the answer?")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_store(root: Path | None = None) -> Path:
    return (root or repo_root()) / STORE_RELATIVE_PATH


# ---------------------------------------------------------------------------
# The trigger: split detection over real search signals
# ---------------------------------------------------------------------------

def detect_split(annotated: list[dict]) -> dict | None:
    """The pure gate. `annotated` is the top-K ranking as
    [{page, score, community, community_label}] in rank order.
    Returns the split record (the two leading communities with
    their pages, masses, shares and best scores, plus the
    thresholds applied) or None when the evidence does not
    measurably split."""
    if len(annotated) < 2:
        return None
    groups: dict = {}
    for r in annotated:
        g = groups.setdefault(r["community"], {
            "community": r["community"],
            "label": r.get("community_label"),
            "pages": [], "mass": 0.0, "top_score": 0.0})
        g["pages"].append(r["page"])
        g["mass"] += float(r["score"])
        g["top_score"] = max(g["top_score"], float(r["score"]))
    if len(groups) < 2:
        return None
    total = sum(g["mass"] for g in groups.values())
    if total <= 0:
        return None
    ranked = sorted(groups.values(),
                    key=lambda g: (-g["mass"], str(g["community"])))
    lead, second = ranked[0], ranked[1]
    for g in ranked:
        g["mass"] = round(g["mass"], 4)
        g["share"] = round(g["mass"] / total, 4)
        g["top_score"] = round(g["top_score"], 4)
    if second["share"] < MIN_SECOND_SHARE:
        return None
    if lead["top_score"] <= 0:
        return None
    if second["top_score"] < COMPARABLE_RATIO * lead["top_score"]:
        return None
    return {
        "communities": [
            {k: g[k] for k in ("community", "label", "pages",
                               "mass", "share", "top_score")}
            for g in (lead, second)],
        "other_communities": len(ranked) - 2,
        "top_k": len(annotated),
        "thresholds": {"min_second_share": MIN_SECOND_SHARE,
                       "comparable_ratio": COMPARABLE_RATIO,
                       "top_k": TOP_K},
    }


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def community_map(root: Path) -> dict:
    """{repo-relative page path: (community_id, community_label)}
    — the Lens build's topic communities, recomputed with the
    build's own construction (`tools/lens/build_lens.py`): pages
    parsed by lenslib, edges from written wikilinks + declared
    frontmatter links, pair weights 3.0·direct + 1.5·shared raw
    sources + 0.8·common neighbours + 0.5·same type over pairs
    that are directly linked, share a source, or have ≥2 common
    neighbours; the build's deterministic Louvain over those
    weights. Labels follow the Lens convention — "Cluster
    around <hub page title>", the hub being the community's
    most-connected member. Internal to the trigger: labels are
    for the run report, never for the asker. Structural pages
    (index/log) and access records are not Lens graph nodes and
    carry no community."""
    L = _load_module("lenslib_clar", root / "tools" / "lens" / "lenslib.py")
    bl = _load_module("build_lens_clar",
                      root / "tools" / "lens" / "build_lens.py")
    wiki = root / "wiki"
    raw = root / "raw"
    md_files = sorted(p for p in wiki.rglob("*.md") if p.is_file()
                      and "access" not in p.relative_to(wiki).parts[:-1])
    pages = []
    by_stem: dict = {}
    for p in md_files:
        fm, body, _text = L.parse_markdown_file(p)
        rel = str(p.relative_to(root))
        pages.append({"path": rel, "fm": fm, "body": body})
        by_stem.setdefault(p.stem, []).append(rel)
    used_ids: dict = {}
    for pg in pages:
        fm = pg["fm"]
        stem = Path(pg["path"]).stem
        pid = fm.get("id") or stem
        if pid in used_ids:
            ptype = str(fm.get("type") or "page").lower()
            candidate = f"{ptype}-{stem}"
            n = 2
            base = candidate
            while candidate in used_ids:
                candidate = f"{base}-{n}"
                n += 1
            pid = candidate
        used_ids[pid] = pg["path"]
        pg["id"] = pid
        pg["title"] = str(fm.get("title") or L.first_h1(pg["body"]) or stem)
        pg["type"] = str(fm.get("type") or "page")
        srcs = fm.get("sources") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        pg["sources_fm"] = [str(s) for s in srcs]
        pg["wikilinks_typed"] = L.extract_wikilinks_typed(pg["body"])
    route_by_stem: dict = {}
    for pg in pages:
        route_by_stem.setdefault(Path(pg["path"]).stem, pg["id"])
        route_by_stem[pg["id"]] = pg["id"]
    for pg in pages:
        route_by_stem[str(Path(pg["path"]).with_suffix(""))] = pg["id"]
    content = [pg for pg in pages if pg["id"] not in ("index", "log")]
    page_by_id = {pg["id"]: pg for pg in pages}
    raw_set = {str(p.relative_to(root))
               for p in raw.rglob("*") if p.is_file()}

    def is_page_citation(src: str) -> bool:
        # build_lens.citation_info: a sources[] entry that resolves
        # to a wiki page is a page citation; anything else is a raw
        # path (prefixed raw/ when not already).
        if not src.startswith("raw/"):
            return bool(route_by_stem.get(src)
                        or route_by_stem.get(Path(src).name))
        return False

    neighbours: dict = {}
    direct_pairs: set = set()

    def pair_key(a, b):
        return (a, b) if a <= b else (b, a)

    for pg in content:
        seen: set = set()
        targets = []
        for target, _anchor, _label, _section, ltype in pg["wikilinks_typed"]:
            dst = route_by_stem.get(target) \
                or route_by_stem.get(Path(target).name)
            if dst and dst != pg["id"] and (dst, ltype) not in seen:
                seen.add((dst, ltype))
                targets.append(dst)
        links_fm = pg["fm"].get("links") or {}
        if isinstance(links_fm, dict):
            for _relation, ts in links_fm.items():
                if isinstance(ts, str):
                    ts = [ts]
                for t in ts or []:
                    dst = route_by_stem.get(str(t)) \
                        or route_by_stem.get(Path(str(t)).name)
                    if dst:
                        targets.append(dst)
        for dst in targets:
            neighbours.setdefault(pg["id"], set()).add(dst)
            neighbours.setdefault(dst, set()).add(pg["id"])
            direct_pairs.add(pair_key(pg["id"], dst))
    sources_of: dict = {}
    for pg in content:
        raw_cites = set()
        for s in pg["sources_fm"]:
            if is_page_citation(s):
                continue
            rp = s if s.startswith("raw/") else f"raw/{s}"
            if rp in raw_set:
                raw_cites.add(rp)
        sources_of[pg["id"]] = raw_cites
    node_ids = [pg["id"] for pg in content]
    weights: dict = {}
    for i, a in enumerate(node_ids):
        for b in node_ids[i + 1:]:
            direct = 1 if pair_key(a, b) in direct_pairs else 0
            shared = len(sources_of[a] & sources_of[b])
            common = len(neighbours.get(a, set())
                         & neighbours.get(b, set()))
            affinity = 1 if page_by_id[a]["type"] == page_by_id[b]["type"] \
                else 0
            if direct or shared or common >= 2:
                weights[pair_key(a, b)] = 3.0 * direct + 1.5 * shared \
                    + 0.8 * common + 0.5 * affinity
    comm = bl.louvain(node_ids, weights)
    members: dict = {}
    for n in node_ids:
        members.setdefault(comm[n], []).append(n)
    labels = {}
    for c, mem in members.items():
        hub = max(mem, key=lambda n: len(neighbours.get(n, set())))
        labels[c] = f"Cluster around {page_by_id[hub]['title']}"
    return {pg["path"]: (comm[pg["id"]], labels[comm[pg["id"]]])
            for pg in content}


def assess_split(question: str, root: Path | None = None) -> dict:
    """Run the probe retrieval for `question` and measure the
    split. Returns {"split": bool, "results": [annotated top-K],
    "split_detail": <detect_split record or None>}."""
    root = root or repo_root()
    ws = _load_module("wiki_search_clar",
                      root / "scripts" / "wiki_search.py")
    cmap = community_map(root)
    docs = ws.collect_docs("wiki")
    terms = ws.tokenize(question)
    ranked = ws.hybrid_rank(terms, docs)
    annotated = []
    for score, p, _text, _detail in ranked[:TOP_K]:
        rel = str(p.relative_to(root)) if p.is_relative_to(root) \
            else str(p)
        cid, label = cmap.get(rel, (None, None))
        annotated.append({"page": rel, "score": round(score, 4),
                          "community": cid, "community_label": label})
    # Only community-bearing results measure the split: structural
    # pages (index/log) and access records are not topic evidence.
    measured = [r for r in annotated if r["community"] is not None]
    detail = detect_split(measured)
    return {"split": detail is not None, "results": annotated,
            "split_detail": detail}


# ---------------------------------------------------------------------------
# The form: paraphrase-back + the neutral stem (wave 9 wording)
# ---------------------------------------------------------------------------

def paraphrase_question(question: str) -> str:
    """The asker's own question handed back for confirmation —
    the first plausible interpretation treated as a hypothesis,
    not silently searched (wave 9 find 11). Mechanical on
    purpose: the question's own words, quoted, nothing added."""
    q = " ".join(str(question).split())
    return f'As I understand it, you\'re asking: "{q}" — is that the question?'


def clarification_text(question: str) -> str:
    """The one clarifying exchange: paraphrase-and-check plus the
    neutral stem. No split internals, no candidate readings, no
    facet menu (C3)."""
    return ("Before I search, let me make sure I look for the "
            "right thing.\n\n"
            + paraphrase_question(question)
            + "\n\n" + STEM)


# ---------------------------------------------------------------------------
# Timing: the asker's timing routes instant vs queued
# ---------------------------------------------------------------------------

def timing_route(entry: dict) -> dict:
    """Stamp how the question's timing routed. `asked` preserves
    the request ("now" | "queued" | None when the entry carries
    no timing); `route` is where it actually goes. The only live
    lane is the queued pickup (the instant lane is an open owner
    decision), so an instant request is recorded honestly as
    queued-with-the-request-noted, never faked as instant."""
    asked_raw = entry.get("timing")
    asked = str(asked_raw).strip().lower() if asked_raw else None
    if asked in ("now", "instant", "immediate"):
        return {"asked": "now", "route": "queued",
                "note": "instant requested; no instant lane is "
                        "built (open owner decision) — handled by "
                        "the queued pickup on its next cycle, with "
                        "the request recorded here"}
    if asked:
        return {"asked": "queued", "route": "queued", "note": None}
    return {"asked": None, "route": "queued",
            "note": "no timing on the question entry; the queued "
                    "pickup is the default lane"}


# ---------------------------------------------------------------------------
# The stored record: append-only events, folded by question id
# ---------------------------------------------------------------------------

def _append_event(store: Path, event: dict) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    with open(store, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_events(store: Path) -> list[dict]:
    if not store.exists():
        return []
    out = []
    for line in store.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def fold_state(events: list[dict], qid: str) -> dict | None:
    """The clarification state of one question: None (no
    clarification ever opened) or {status: clarifying | replied
    | closed, record, reply, outcome, answer_ref} folded from
    its events in order."""
    state = None
    for ev in events:
        if ev.get("id") != qid:
            continue
        kind = ev.get("event")
        if kind == "clarification_asked":
            state = {"status": "clarifying", "record": ev,
                     "reply": None, "outcome": None,
                     "answer_ref": None}
        elif kind == "clarification_reply" and state is not None:
            state["status"] = "replied"
            state["reply"] = ev.get("reply")
            state["reply_event"] = ev
        elif kind == "clarification_closed" and state is not None:
            state["status"] = "closed"
            state["outcome"] = ev.get("outcome")
            state["answer_ref"] = ev.get("answer_ref")
            state["close_event"] = ev
    return state


def open_clarification(store: Path, entry: dict, split_detail: dict,
                       clarified_at: str) -> dict:
    """Append the clarification_asked event for a question whose
    evidence split. The stored record carries the full exchange
    surface: the clarification text sent, the paraphrase, the
    stem, the split internals (report-only), the timing route,
    and the asker's reply slot (null until a reply event lands).
    Raises ValueError when a clarification is already open or
    the question was already closed through one."""
    qid = entry["id"]
    state = fold_state(load_events(store), qid)
    if state is not None:
        raise ValueError(
            f"question {qid} already has a clarification in state "
            f"{state['status']!r}; refusing to open a second one")
    record = {
        "event": "clarification_asked",
        "id": qid,
        "question": entry["question"],
        "asker": entry.get("asker"),
        "asked_at": entry.get("asked_at"),
        "clarified_at": clarified_at,
        "status": "clarifying",
        "paraphrase": paraphrase_question(entry["question"]),
        "stem": STEM,
        "clarification_text": clarification_text(entry["question"]),
        "split": split_detail,
        "timing": timing_route(entry),
        "reply": None,
    }
    _append_event(store, record)
    return record


def record_reply(store: Path, qid: str, reply: str,
                 replied_at: str, replied_by: str | None = None) -> dict:
    """Append the asker's reply — the reply slot filled. Raises
    ValueError unless a clarification is open and unanswered."""
    state = fold_state(load_events(store), qid)
    if state is None:
        raise ValueError(f"no clarification exists for question {qid}")
    if state["status"] != "clarifying":
        raise ValueError(
            f"clarification for {qid} is {state['status']!r}, not "
            "awaiting a reply")
    event = {"event": "clarification_reply", "id": qid,
             "status": "replied", "reply": reply,
             "replied_at": replied_at, "replied_by": replied_by}
    _append_event(store, event)
    return event


def close_clarification(store: Path, qid: str, outcome: str,
                        answer_ref: str, closed_at: str) -> dict:
    """Append the closing event once the pickup has recorded the
    answer (or abstention) the clarified question produced.
    `outcome` is "answered" or "abstained"; `answer_ref` is the
    Q&A record ref (wiki/access/qa-2026.jsonl#<id>)."""
    if outcome not in ("answered", "abstained"):
        raise ValueError(f"outcome must be answered|abstained, "
                         f"got {outcome!r}")
    state = fold_state(load_events(store), qid)
    if state is None:
        raise ValueError(f"no clarification exists for question {qid}")
    if state["status"] != "replied":
        raise ValueError(
            f"clarification for {qid} is {state['status']!r}, not "
            "replied — only a replied clarification can close")
    event = {"event": "clarification_closed", "id": qid,
             "status": "closed", "outcome": outcome,
             "answer_ref": answer_ref, "closed_at": closed_at}
    _append_event(store, event)
    return event


def route_question(state: dict | None, split: bool) -> str:
    """The pickup's state machine: clarify | await_reply | answer
    | skip_closed (see the module docstring)."""
    if state is None:
        return "clarify" if split else "answer"
    if state["status"] == "clarifying":
        return "await_reply"
    if state["status"] == "replied":
        return "answer"
    return "skip_closed"


def qa_clarification_field(state: dict) -> dict:
    """The additive `clarification` field a Q&A record carries
    when its answer followed a clarification: the paraphrase the
    asker confirmed and the reply they gave — the exchange on
    the record, so the answer's framing can show what was
    actually asked."""
    record = state["record"]
    return {"paraphrase": record["paraphrase"],
            "stem": record["stem"],
            "reply": state.get("reply"),
            "clarified_at": record["clarified_at"],
            "timing": record["timing"]}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Ask-door clarification gate + round-trip store "
                    "(item 61).")
    ap.add_argument("--store", default=None,
                    help="clarification event log (default: "
                         "wiki/access/clarifications-2026.jsonl)")
    ap.add_argument("--root", default=None,
                    help="repository root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="assess a question's evidence "
                                     "for a measurable split")
    p.add_argument("--question", required=True)

    p = sub.add_parser("open", help="open a clarification (the "
                                    "gate is re-run; no split, no "
                                    "clarification)")
    p.add_argument("--id", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--asker", default=None)
    p.add_argument("--asked-at", default=None)
    p.add_argument("--timing", default=None)

    p = sub.add_parser("state", help="print a question's folded "
                                     "clarification state")
    p.add_argument("--id", required=True)

    p = sub.add_parser("reply", help="record the asker's reply")
    p.add_argument("--id", required=True)
    p.add_argument("--reply", required=True)
    p.add_argument("--by", default=None)

    p = sub.add_parser("close", help="close a replied clarification "
                                     "with its answer outcome")
    p.add_argument("--id", required=True)
    p.add_argument("--outcome", required=True,
                   choices=("answered", "abstained"))
    p.add_argument("--answer-ref", required=True)

    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else repo_root()
    store = Path(args.store) if args.store else default_store(root)

    if args.cmd == "check":
        result = assess_split(args.question, root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "open":
        entry = {"id": args.id, "question": args.question,
                 "asker": args.asker, "asked_at": args.asked_at,
                 "timing": args.timing}
        result = assess_split(args.question, root)
        if not result["split"]:
            print(f"NO SPLIT: the evidence for question {args.id} "
                  "does not measurably split; no clarification "
                  "opened (straight to search).", file=sys.stderr)
            return 2
        try:
            record = open_clarification(store, entry,
                                        result["split_detail"],
                                        _now_iso())
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "state":
        state = fold_state(load_events(store), args.id)
        print(json.dumps(state, indent=2, ensure_ascii=False,
                         default=str))
        return 0
    if args.cmd == "reply":
        try:
            event = record_reply(store, args.id, args.reply,
                                 _now_iso(), args.by)
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(event, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "close":
        try:
            event = close_clarification(store, args.id, args.outcome,
                                         args.answer_ref, _now_iso())
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(event, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
