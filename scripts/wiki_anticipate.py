#!/usr/bin/env python3
"""Anticipatory sweep for the LLM Wiki — sleep-time compute
for the standing questions and the predictable queries.

WikiCitadel v1, from the academic lane of the
feature survey: Sleep-time Compute (arXiv:2504.13171) —
precompute answers to the predictable questions while the
system is idle, instead of deriving everything at ask time
(~5x test-time saving on predictable queries). The nightly
sweep already tidies; this pass makes the idle time produce
tomorrow's first answers.

What "precompute" means here, stated honestly: NO prose
answers are generated — there is no LLM in this script.
Precompute = (1) the standing answers, carried verbatim with
their as-of stamp, assembled beside the fresh evidence that
has accumulated since, and (2) retrieval packets: for each
predicted query, the hybrid search (scripts/wiki_search.py,
the same engine the Lens parity-checks against) is run NOW,
at sweep time, and its evidence pack — top pages, scores,
snippets, and what was left out and why — is saved, so a
later real Ask on that question starts from a warm packet
instead of a cold search. When the morning reader (or the
Ask pickup) opens the briefing, the predictable questions
are already worked as far as determinism can work them.

Two artefacts, written beside each other:

  wiki/filings/anticipated-<date>.md
    The briefing. For each of the six standing questions of
    [[current-state]] (wiki/syntheses/current-state.md):
    the standing answer quoted verbatim under its page's
    as-of stamp, then a **Fresh evidence** block assembled
    deterministically from the wiki's own artefacts —
    the log tail (wiki/log.md), the Ideas board's Waiting
    list (wiki/ideas.md), the Ask door's Q&A log
    (wiki/access/qa.jsonl), and the latest extended
    eval (evaluation/results/extended-latest.json). The
    evidence blocks are assemblies, labelled as such:
    items are extracted and listed, never interpreted into
    new prose. Then the predicted queries with their top
    pages (the full packets live in the JSON).

  wiki/filings/anticipated-<date>-packets.json
    The machine-readable packets: one evidence pack per
    predicted query, in wiki_search.py's own pack shape
    (included pages with scores and snippets, omitted pages
    with reasons), so the Ask pickup can load a warm packet
    by matching the incoming question to a predicted query.

Predicted queries, in priority order (the paper's point is
that the predictable set is small and stable): the six
standing questions verbatim; the Ask log's own questions
(asked once, likely asked again); the Ideas Waiting items
(the owner's pending calls, phrased as topics); and the
most recent log entries' titles (what changed is what gets
asked about). Capped at --max-packets (default 10), deduped
by normalised text.

Wiring (documented for the integrator; this script edits no
cron): in the nightly sweep, after the lint/drift steps, run
  python3 scripts/wiki_anticipate.py
The morning briefing then opens with the anticipated file;
the Ask pickup may consult the packets JSON before running a
cold search.

Usage:
  python3 scripts/wiki_anticipate.py [--date D]
      [--max-packets N] [--out-dir DIR]

Stdlib only (wiki_search / wiki_validate imported
in-process). Importable: build_briefing(root, run_date,
max_packets) returns (briefing_markdown, packets_dict).
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SCRIPTS = ROOT / "scripts"

CURRENT_STATE = WIKI / "syntheses" / "current-state.md"
IDEAS = WIKI / "ideas.md"
LOG = WIKI / "log.md"
QA_LOG = WIKI / "access" / "qa.jsonl"
EVAL_LATEST = ROOT / "evaluation" / "results" / "extended-latest.json"
CASES = ROOT / "evaluation" / "contradiction-cases.jsonl"
STAGING = ROOT / "staging" / "proposed"

Q_HEADING_RE = re.compile(r"^## Q(\d+)\.\s*(.+?)\s*$")
AS_OF_RE = re.compile(r"\*\*As of:\s*([^*]+)\*\*")
LOG_ENTRY_RE = re.compile(
    r"^## \[(\d{4}-\d{2}-\d{2})\] (\S+) \| (.*)$")
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
WIKI_QUERY_FENCE_RE = re.compile(
    r"```wiki-query\n.*?\n```", re.DOTALL)
BLOCKER_MARKERS = ("blocked", "waiting on", "owner's hands",
                   "only the owner", "passkey", "captcha",
                   "in the owner's hands", "owner can")
LIVE_KINDS = ("setup", "build", "feature")


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wsearch = _load("wiki_search")
wvalidate = _load("wiki_validate")
parse_frontmatter = wvalidate.parse_frontmatter


# -- artefact readers -------------------------------------------------------

def read_current_state(path=CURRENT_STATE):
    """Parse the standing-question page: {as_of, updated,
    questions: [{n, question, answer}]}. The live-query fence
    in Q6 is replaced by a note (its table is computed at
    Lens build time; a snapshot of markdown cannot carry it).
    Returns None when the page is absent."""
    if not Path(path).is_file():
        return None
    text = Path(path).read_text(encoding="utf-8",
                                errors="ignore")
    fields, _body = parse_frontmatter(text)
    m = AS_OF_RE.search(text)
    as_of = m.group(1).strip() if m else None
    questions = []
    current = None
    for raw in text.splitlines():
        qm = Q_HEADING_RE.match(raw)
        if qm:
            if current:
                questions.append(current)
            current = {"n": int(qm.group(1)),
                       "question": qm.group(2).strip(),
                       "lines": []}
            continue
        if raw.startswith("## ") and current is not None:
            questions.append(current)
            current = None
            continue
        if current is not None:
            current["lines"].append(raw)
    if current:
        questions.append(current)
    for q in questions:
        answer = "\n".join(q.pop("lines")).strip()
        answer = WIKI_QUERY_FENCE_RE.sub(
            "*(Live-query table omitted from this snapshot — "
            "it is computed when the Lens is built.)*", answer)
        q["answer"] = answer
    return {"as_of": as_of,
            "updated": (fields or {}).get("updated"),
            "questions": questions}


def parse_log(path=LOG):
    """Log entries in file order: [{date, kind, title, body,
    first_line}] (the log is append-only, newest last)."""
    entries = []
    if not Path(path).is_file():
        return entries
    current = None
    for raw in Path(path).read_text(
            encoding="utf-8", errors="ignore").splitlines():
        m = LOG_ENTRY_RE.match(raw)
        if m:
            if current:
                entries.append(current)
            current = {"date": m.group(1), "kind": m.group(2),
                       "title": m.group(3).strip(),
                       "body_lines": []}
        elif current is not None:
            current["body_lines"].append(raw)
    if current:
        entries.append(current)
    for entry in entries:
        body_lines = entry.pop("body_lines")
        entry["body"] = "\n".join(body_lines)
        first = next((ln.strip() for ln in body_lines
                      if ln.strip()), "")
        entry["first_line"] = first[:160]
    return entries


def parse_ideas_waiting(path=IDEAS):
    """The Ideas board's Waiting list: the bold lead (or the
    plain head) of each top-level bullet under
    '## Waiting for your call', up to '## Approved'.
    Returns [{lead, text}] in page order."""
    if not Path(path).is_file():
        return []
    text = Path(path).read_text(encoding="utf-8",
                                errors="ignore")
    lines = text.splitlines()
    items = []
    in_waiting = False
    current = None
    for raw in lines:
        if raw.startswith("## "):
            if in_waiting:
                break
            if "Waiting for your call" in raw:
                in_waiting = True
            continue
        if not in_waiting:
            continue
        if raw.startswith("- "):
            if current:
                items.append(current)
            current = raw[2:].strip()
        elif current is not None and raw.strip() \
                and not raw.startswith((" ", "\t")):
            # A non-indented line ends the bullet list item;
            # wrapped bullet text is indented in this file's
            # style only rarely — treat plain lines as prose
            # separators and close the current item.
            items.append(current)
            current = None
    if current:
        items.append(current)
    out = []
    for item in items:
        m = re.match(r"\*\*(.+?)\*\*", item)
        lead = m.group(1).strip() if m else item.split(" — ")[0]
        out.append({"lead": lead.strip(), "text": item})
    return out


def read_qa_log(path=QA_LOG):
    records = []
    if not Path(path).is_file():
        return records
    for line in Path(path).read_text(
            encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def read_eval_latest(path=EVAL_LATEST):
    if not Path(path).is_file():
        return None
    try:
        return json.loads(Path(path).read_text(
            encoding="utf-8"))
    except ValueError:
        return None


def open_cases_count(path=CASES):
    """Folded open Cases, mirroring scripts/wiki_cases.py's
    fold (an opening line with status open and no ruling
    line for its id)."""
    openings, ruled = {}, set()
    if not Path(path).is_file():
        return 0
    for line in Path(path).read_text(
            encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("kind") == "case":
            openings[entry.get("case_id")] = entry.get("status")
        elif entry.get("kind") == "ruling":
            ruled.add(entry.get("case_id"))
    return sum(1 for cid, st in openings.items()
               if st == "open" and cid not in ruled)


def staged_proposals(staging=STAGING):
    """Staged proposal files present (prop-*.md). The refine
    loop also parks qa-*.md artefacts in the same directory;
    those are not proposals and are not counted. Presence is
    reported, not review status — whether a proposal was
    later promoted is the gateway store's record, not this
    assembly's to interpret."""
    if not Path(staging).is_dir():
        return []
    return sorted(p.name for p in Path(staging).glob("prop-*.md"))


def page_type_counts(wiki=WIKI):
    counts = {}
    total = 0
    if not Path(wiki).is_dir():
        return counts, total
    for path in sorted(Path(wiki).rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
        except OSError:
            continue
        fields, _body = parse_frontmatter(text)
        kind = (fields or {}).get("type") or "(none)"
        counts[str(kind)] = counts.get(str(kind), 0) + 1
        total += 1
    return counts, total


# -- fresh evidence per standing question ----------------------------------

def _fmt_eval(eval_latest):
    if not eval_latest:
        return ["Extended eval: no latest result on file"
                " (`evaluation/results/extended-latest.json`"
                " absent) — nothing assembled."]
    agg = eval_latest.get("aggregates") or {}
    cov = (agg.get("citation_coverage") or {}).get("@10")
    lines = [
        f"Extended eval (generated"
        f" {eval_latest.get('generated_at', 'unknown')}, engine"
        f" {eval_latest.get('engine', '?')}, corpus"
        f" {eval_latest.get('corpus_docs', '?')} docs):"
        f" citation coverage @10 **{cov}**, hit rate"
        f" {agg.get('hit_rate_topk')}, MRR"
        f" {agg.get('mrr_must_cite')} over"
        f" {agg.get('questions', '?')} questions."]
    by_class = eval_latest.get("by_class") or {}
    if by_class:
        weakest = min(
            by_class.items(),
            key=lambda kv: (kv[1].get("citation_coverage")
                            or {}).get("@10", 1.0))
        lines.append(
            f"Weakest class by coverage @10:"
            f" **{weakest[0]}** at"
            f" {(weakest[1].get('citation_coverage') or {}).get('@10')}"
            f" — the class the standing answers lean on least"
            f" safely.")
    return lines


def fresh_evidence(n, ctx):
    """Assembled evidence bullets for standing question n.
    Every bullet is an extraction from a named artefact —
    labelled assembly, never interpretation."""
    entries = ctx["log_entries"]
    if n == 1:
        counts, total = ctx["type_counts"], ctx["page_total"]
        by_type = ", ".join(f"{k} {v}" for k, v in
                            sorted(counts.items()))
        latest = entries[-1] if entries else None
        lines = [f"Corpus at assembly: **{total} wiki pages**"
                 f" ({by_type}).",
                 f"Log: {len(entries)} entries; latest"
                 f" {latest['date'] if latest else '—'} —"
                 f" {latest['title'] if latest else '—'}.",
                 f"Ask log: {len(ctx['qa'])} recorded"
                 f" question(s)."]
        lines += _fmt_eval(ctx["eval_latest"])
        return lines
    if n == 2:
        lines = []
        pending = [r for r in ctx["qa"]
                   if r.get("status") != "answered"]
        abstained = [r for r in ctx["qa"] if r.get("abstained")]
        if pending:
            lines += [f"Ask log — unanswered:"
                      f" “{r.get('question', '')}”"
                      for r in pending]
        if abstained:
            lines += [f"Ask log — abstained:"
                      f" “{r.get('question', '')}”"
                      for r in abstained]
        hits = []
        for entry in entries[-12:]:
            text = (entry["title"] + " " + entry["body"]).lower()
            if any(m in text for m in BLOCKER_MARKERS):
                hits.append(entry)
        lines += [f"Log (recent) — blocker-shaped entry:"
                  f" [{e['date']}] {e['title']}" for e in hits]
        if not lines:
            lines.append("No blocker-shaped evidence found in"
                         " the artefacts this run (Ask log has"
                         " no pending or abstained questions;"
                         " recent log entries carry no blocker"
                         " markers).")
        return lines
    if n == 3:
        lines = [f"Ideas board — **{len(ctx['waiting'])}"
                 f" item(s) waiting** for the owner's call:"]
        lines += [w["lead"] for w in ctx["waiting"]]
        staged = ctx["staged"]
        lines.append(
            f"Staged proposal files present in"
            f" `staging/proposed/`: **{len(staged)}**"
            + (f" ({', '.join(staged)})" if staged else "")
            + " — presence only; review status is the gateway"
            " store's record.")
        lines.append(
            f"Contradiction Cases open: **{ctx['open_cases']}**"
            f" (the adjudication queue's first port of call is"
            f" `wiki/filings/adjudication-queue-*.md`).")
        return lines
    if n == 4:
        lines = []
        for entry in reversed(entries):
            if entry["kind"] in LIVE_KINDS:
                lines.append(f"[{entry['date']}] {entry['kind']}"
                             f" — {entry['title']}")
            if len(lines) >= 5:
                break
        if ctx["eval_latest"]:
            lines.append(
                f"Latest extended eval:"
                f" {ctx['eval_latest'].get('generated_at')} —"
                f" the search the Lens serves is measured, not"
                f" assumed.")
        if ctx["qa"]:
            last = ctx["qa"][-1]
            lines.append(
                f"Ask door: last recorded answer"
                f" {last.get('answered_at', '—')} for"
                f" “{last.get('question', '')}”.")
        return lines or ["No setup/build entries in the log."]
    if n == 5:
        lines = []
        # The standing page states its clocks in prose dates
        # ("Oct 31, 2026"), not ISO dates; extract its bold
        # clock leads verbatim rather than re-deriving them.
        state = ctx["state"] or {}
        q5 = next((q for q in state.get("questions", [])
                   if q["n"] == 5), None)
        if q5:
            for raw in q5["answer"].splitlines():
                m = re.match(r"^-\s*\*\*(.+?)\*\*\s*—?\s*(.*)$",
                             raw)
                if m:
                    lines.append(
                        f"Standing page's clock, verbatim:"
                        f" **{m.group(1)}**"
                        + (f" — {m.group(2)}" if m.group(2)
                           else ""))
        dated = []
        seen = set()
        horizon = ctx["run_date"] + timedelta(days=60)
        for source, text in (("wiki/log.md", ctx["log_text"]),
                             ("wiki/ideas.md", ctx["ideas_text"])):
            for ln, raw in enumerate(text.splitlines(), 1):
                for m in DATE_RE.finditer(raw):
                    try:
                        when = date(int(m.group(1)),
                                    int(m.group(2)),
                                    int(m.group(3)))
                    except ValueError:
                        continue
                    if ctx["run_date"] < when <= horizon:
                        item = raw.strip()[:140]
                        key = (when.isoformat(), item)
                        if key in seen:
                            continue
                        seen.add(key)
                        dated.append((when.isoformat(),
                                      f"{when.isoformat()} —"
                                      f" {item} ({source}:{ln})"))
        dated.sort()
        lines += [text for _d, text in dated[:12]]
        return lines or ["No clocks extracted: the standing"
                         " page carries no bold clock leads and"
                         " no ISO-dated items fall in the next"
                         " 60 days in the log or the Ideas"
                         " board."]
    if n == 6:
        return [f"[{e['date']}] {e['kind']} — {e['title']}"
                + (f" — {e['first_line']}" if e["first_line"]
                   else "")
                for e in entries[-8:]]
    return []


# -- predicted queries + packets ---------------------------------------------

def predicted_queries(ctx, max_packets):
    out = []
    seen = set()

    def add(query, source):
        key = re.sub(r"\s+", " ", query.lower()).strip()
        if not key or key in seen or len(out) >= max_packets:
            return
        seen.add(key)
        out.append({"query": query, "source": source})

    for q in ctx["state"]["questions"]:
        add(q["question"], "standing-question")
    for record in reversed(ctx["qa"]):
        add(record.get("question", ""), "ask-log")
    for item in ctx["waiting"]:
        add(item["lead"], "ideas-waiting")
    for entry in reversed(ctx["log_entries"]):
        add(entry["title"], "log-title")
    return out


def build_packets(queries, root=ROOT):
    docs = wsearch.collect_docs("wiki")
    adj = wsearch.build_link_graph(docs)
    packets = []
    for item in queries:
        terms = wsearch.tokenize(item["query"])
        ranked = wsearch.hybrid_rank(terms, docs, adj)
        pack = wsearch.build_evidence_pack(
            item["query"], terms, ranked, 5, "wiki",
            len(docs))
        pack["predicted_from"] = item["source"]
        packets.append(pack)
    return {"engine": "hybrid (bm25 + personalized pagerank"
            " over wikilinks)",
            "corpus_docs": len(docs), "packets": packets}


# -- assembly -----------------------------------------------------------------

def gather_context(root, run_date):
    wiki = root / "wiki"
    state = read_current_state(
        wiki / "syntheses" / "current-state.md")
    log_entries = parse_log(wiki / "log.md")
    waiting = parse_ideas_waiting(wiki / "ideas.md")
    qa = read_qa_log(wiki / "access" / "qa.jsonl")
    eval_latest = read_eval_latest(
        root / "evaluation" / "results" / "extended-latest.json")
    counts, total = page_type_counts(wiki)
    log_text = ""
    if (wiki / "log.md").is_file():
        log_text = (wiki / "log.md").read_text(
            encoding="utf-8", errors="ignore")
    ideas_text = ""
    if (wiki / "ideas.md").is_file():
        ideas_text = (wiki / "ideas.md").read_text(
            encoding="utf-8", errors="ignore")
    return {"state": state, "log_entries": log_entries,
            "waiting": waiting, "qa": qa,
            "eval_latest": eval_latest,
            "type_counts": counts, "page_total": total,
            "open_cases": open_cases_count(
                root / "evaluation" / "contradiction-cases.jsonl"),
            "staged": staged_proposals(root / "staging"
                                       / "proposed"),
            "log_text": log_text, "ideas_text": ideas_text,
            "run_date": run_date}


def build_briefing(root=ROOT, run_date=None, max_packets=10):
    """Returns (markdown, packets_dict). Raises ValueError
    when the standing-question page is missing — there is
    nothing to anticipate from."""
    run_date = run_date or date.today()
    ctx = gather_context(root, run_date)
    if not ctx["state"]:
        raise ValueError(
            "wiki/syntheses/current-state.md not found — the"
            " standing questions live there; nothing to"
            " anticipate without it")
    queries = predicted_queries(ctx, max_packets)
    packets = build_packets(queries, root)
    packets_out = {"generated_for": run_date.isoformat(),
                   "as_of": run_date.isoformat(),
                   **packets}
    state = ctx["state"]
    stamp = (state["as_of"] or (
        f"page updated {state['updated']}" if state["updated"]
        else "unstamped")).rstrip(".")
    lines = [
        "---",
        f"title: Anticipated briefing — {run_date.isoformat()}",
        "type: query",
        f"created: {run_date.isoformat()}",
        f"updated: {run_date.isoformat()}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [anticipatory, briefing, filings]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Anticipated briefing — {run_date.isoformat()}",
        "",
        "Generated by the anticipatory sweep"
        " (`scripts/wiki_anticipate.py`; Sleep-time Compute,"
        " arXiv:2504.13171) while the wiki was idle, so the"
        " predictable questions are already worked when they"
        " are asked. **What precompute means here, honestly:**"
        " no prose answers were generated — there is no LLM in"
        " the loop. The standing answers below are"
        " [[current-state]]'s own text, quoted verbatim under"
        " its as-of stamp; the **Fresh evidence** blocks are"
        " deterministic assemblies from the wiki's artefacts"
        " (items extracted and listed, never interpreted into"
        " new prose); and the predicted queries at the end"
        " carry retrieval packets computed now, at sweep"
        " time, so a later real Ask starts warm. Nothing in"
        " this file is canonical — [[current-state]] remains"
        " the standing page, and this briefing is a dated"
        " snapshot beside it.",
        "",
        "Assembled from the wiki's own artefacts:"
        " `wiki/syntheses/current-state.md`, `wiki/log.md`,"
        " `wiki/ideas.md`, `wiki/access/qa.jsonl`,"
        " `evaluation/results/extended-latest.json`,"
        " `evaluation/contradiction-cases.jsonl`, and the"
        " staged proposals in `staging/proposed/`.",
        "",
        "## The standing questions",
        "",
    ]
    for q in state["questions"]:
        lines += [f"### Q{q['n']}. {q['question']}", "",
                  f"*Standing answer — [[current-state]], as of"
                  f" {stamp}:*", "", q["answer"], "",
                  "**Fresh evidence** (assembled from the"
                  " artefacts at sweep time):", ""]
        lines += [f"- {b}" for b in fresh_evidence(q["n"], ctx)]
        lines.append("")
    lines += ["## Predicted queries — warm packets", "",
              "The predictable set, in priority order: the"
              " standing questions themselves, the Ask log's"
              " own questions, the Ideas Waiting items, and"
              " the recent log titles. Full evidence packs"
              " (top pages, scores, snippets, and what was"
              f" left out and why) are in"
              f" `wiki/filings/anticipated-"
              f"{run_date.isoformat()}-packets.json`."
              " Packet as-of: "
              f"{run_date.isoformat()} — a packet is a draft"
              " whose verification state is checked at the"
              " moment of use (synthesis contradiction C9),"
              " so each packet item below carries its"
              " freshness line where its page has one"
              " .", ""]
    for pack in packets["packets"]:
        tops = ", ".join(
            f"`{inc['path']}`" for inc in pack["included"][:3])
        lines.append(
            f"- **{pack['query']}** (predicted from:"
            f" {pack['predicted_from']}) — top pages: {tops}")
        for inc in pack["included"]:
            fresh = inc.get("freshness") or {}
            if fresh.get("line"):
                lines.append(
                    f"  - freshness — `{inc['path']}`:"
                    f" {fresh['line']}")
    lines += ["",
              "## How this is used",
              "",
              "The morning reader opens this file first. The"
              " Ask pickup, when a question matches a predicted"
              " query, starts from its packet instead of a cold"
              " search — and still verifies against the live"
              " pages before answering: a packet is a head"
              " start, not an answer.", ""]
    return "\n".join(lines), packets_out


def main(argv):
    ap = argparse.ArgumentParser(
        description="Anticipatory sweep: precompute the"
                    " standing-question briefing and the"
                    " predicted-query retrieval packets.")
    ap.add_argument("--date", default=None,
                    help="artefact date (default: today)")
    ap.add_argument("--max-packets", type=int, default=10,
                    help="cap on predicted queries (default 10)")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default:"
                         " wiki/filings)")
    args = ap.parse_args(argv[1:])

    run_date = (date.fromisoformat(args.date) if args.date
                else date.today())
    try:
        markdown, packets = build_briefing(
            ROOT, run_date, args.max_packets)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir) if args.out_dir \
        else WIKI / "filings"
    out_dir.mkdir(parents=True, exist_ok=True)
    briefing_path = out_dir / f"anticipated-{run_date}.md"
    packets_path = out_dir / f"anticipated-{run_date}-packets.json"
    briefing_path.write_text(markdown, encoding="utf-8")
    packets_path.write_text(
        json.dumps(packets, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"wrote {briefing_path}")
    print(f"wrote {packets_path}")
    print(f"packets: {len(packets['packets'])} predicted"
          f" queries over {packets['corpus_docs']} docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
