#!/usr/bin/env python3
"""wiki_synthetic_slices.py — synthetic evaluation slices over
the REAL corpus (build list 2026-10-22, wave 3: "Synthetic
episodic + multi-hop + table-task eval slices").

What this is: a DETERMINISTIC generator of evaluation questions
derived from the corpus's own structure — page titles, section
headings, frontmatter claims, wikilink chains, dated log
entries, and Markdown tables — plus zero-match hallucination
probes. Every question carries its derivation: the rule that
produced it and the anchor (page / heading / chain / log entry
/ table row) whose structure makes the must-cite answer correct
BY CONSTRUCTION. A question whose derivation is ambiguous — two
pages equally entitled to be its answer — is EXCLUDED and
counted, never emitted: a synthetic question with a contestable
answer is worse than none.

What this is NOT: a substitute for the hand-written sets. The
golden set (15, owner-frozen), the extended set, the conflict
slice, and the abstention battery are PROTECTED — this tool
never writes to them, its ids live in the disjoint SQ-
namespace, and a test asserts the namespaces never collide.
Synthetic questions are EASIER by nature (the answer is
structurally near the question), so their scores are reported
in their own artefact, per class, and are NEVER pooled with
hand-written scores. The slice's value is regression BREADTH:
a ranking or packing change that breaks structure-derived
retrieval shows up here even when the small hand-written sets
still pass.

Classes (derivation rules):
  title     — "Which page carries the title '<T>'?" The exact-
              title/stem boost is a stated ranker input, so a
              title lookup is a real probe. Excluded when
              another page's title token set covers this
              title's (superset/duplicate titles).
  heading   — "According to '<T>', what is covered under
              '<H>'?" Answer = the first prose sentence of the
              page carrying every content token of H (the
              Giskard RAGET answerability check, Apache-2.0 —
              pattern credited, code ours). Excluded when
              another page carries the same heading under a
              title whose tokens cover this page's.
  claim     — frontmatter `claim:` pages: "According to <T>,
              is the following claim supported: <claim>" —
              the eval-draft question form; the claim is the
              expected answer by construction.
  multihop  — MultiHop-RAG (MIT) bridge pattern: A links to B,
              B links onward to C (C not a direct link of A),
              and C covers heading H. must-cite = C, the page
              holding the answer; B is an acceptable cite (the
              bridge). Excluded when two of B's out-neighbours
              cover H — the hop would not decide the answer.
  episodic  — episodic-memory-benchmark pattern: a dated
              `## [YYYY-MM-DD] ingest | <title>` log entry maps
              to exactly one page created that date whose
              title shares >= 2 content tokens with the entry
              title. Zero matches and >= 2 matches are both
              excluded and counted separately.
  table     — LangChain Benchmarks' table-task pattern with
              the table-summarisation trick: the answer is one
              cell of a Markdown table — "In the table on
              '<T>' (section '<H>'), what is the <last column>
              for <first column> '<key>'?" Excluded when the
              row key + column pair occurs in another page's
              table.
  zeromatch — a real page title with its rarest content token
              replaced by a coined word VERIFIED ABSENT from
              the corpus vocabulary (and from the hand-written
              question files). Expected: abstention. Scored
              against the battery's own rule — the pipeline
              would abstain iff the house top-1 hybrid score
              is below tau (read from evaluation/extended-
              baseline.json, the battery's source).

Harness registration: scoring runs through the bakeoff
pattern — scripts/wiki_bakeoff.py's ConfigRunner("house") +
run_bench_instrument over the slice — and the report carries
a bakeoff-style row identity (sha256 over the canonical JSON
of slice hash + config spec + corpus state + figures). The
bakeoff ledger and the frozen v1 criteria are NOT touched:
this is a separate row family, labelled synthetic. Whether
synthetic rows deserve criteria of their own is a v2
question for the meta-benchmark, noted in the report.

Determinism: same corpus state -> byte-identical slice file
and score report. No randomness, no wall clock anywhere in
the outputs; corpus state enters only as the git HEAD the
slice was derived from. Caps per class keep the slice a
stated breadth sample: kept questions are the first N in
(page path, anchor) order — path order, not a random sample,
and the header says so.

Usage:
  python3 scripts/wiki_synthetic_slices.py generate [--out F]
  python3 scripts/wiki_synthetic_slices.py score    [--slice F]
  python3 scripts/wiki_synthetic_slices.py check    [--slice F]

Stdlib only (house modules loaded by path, the bakeoff way).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EVAL = ROOT / "evaluation"
DEFAULT_SLICE = EVAL / "synthetic-questions.jsonl"
REPORT_JSON = EVAL / "synthetic-slices-report.json"
REPORT_MD = EVAL / "synthetic-slices-report.md"
PROTECTED = ("golden-questions.jsonl", "extended-questions.jsonl",
             "conflict-questions.jsonl", "abstention-battery.jsonl")
GENERATOR = "wiki_synthetic_slices v1"

CAPS = {"title": 60, "heading": 100, "claim": None, "multihop": 50,
        "episodic": 50, "table": 30, "zeromatch": 24}
CLASS_ORDER = ("title", "heading", "claim", "multihop",
               "episodic", "table", "zeromatch")

BIAS_STATEMENT = (
    "SYNTHETIC SLICE — read before citing any figure. These "
    "questions were generated deterministically from the "
    "corpus's own structure, so the answer is structurally "
    "near the question by construction: this slice is EASIER "
    "than the hand-written golden/extended sets and its "
    "scores must never be pooled with theirs. Its value is "
    "regression breadth — breadth the 15-question golden set "
    "cannot give — not difficulty. Per-class figures only; "
    "the overall synthetic figure is a summary of this slice, "
    "not a corpus quality score.")

STOP = frozenset("""
a an the and or of to in on for with by from at as is are was were be
been it its this that these those what which who whom when where why
how does do did has have had not no yes into over under between
about against through during before after above below out up down
""".split())

# Coined words for the zeromatch class; each is verified absent
# from the corpus vocabulary at generation time (a candidate
# found present is skipped, and the skip is counted).
NONCES = ("quorble", "zepharium", "talvindra", "ossimere",
          "brankelow", "nuverra", "ostricade", "melphor",
          "quandrixel", "solvaneer", "trellimorph", "uvandrel")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load("wiki_search", "wiki_search.py")
wv = _load("wiki_validate", "wiki_validate.py")


# ---------------------------------------------------------------------------
# Corpus model
# ---------------------------------------------------------------------------

def content_tokens(text):
    """Content-bearing tokens: alphabetic-containing, len >= 3,
    not stopwords. ws.tokenize already lowercases/splits."""
    out = []
    for tok in ws.tokenize(text or ""):
        if len(tok) >= 3 and any(c.isalpha() for c in tok) \
                and tok not in STOP:
            out.append(tok)
    return out


def norm_text(s):
    return " ".join((s or "").lower().split())


class Page:
    def __init__(self, rel, text):
        self.rel = rel
        self.text = text
        fields, body = wv.parse_frontmatter(text)
        self.fields = fields or {}
        self.body = body or ""
        self.title = (str(self.fields.get("title")).strip()
                      if self.fields.get("title")
                      else Path(rel).stem)
        self.title_tokens = content_tokens(self.title)
        self.created = (str(self.fields.get("created")).strip()
                        if self.fields.get("created") else None)
        self._headings = None
        self._sentences = None

    def headings(self):
        """## and ### headings in body order, fences stripped.
        Memoised — the class builders consult headings inside
        nested scans."""
        if self._headings is not None:
            return self._headings
        body = ws.FENCE_RE.sub("", self.body)
        out = []
        for line in body.splitlines():
            m = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
            if m:
                out.append(m.group(1).strip())
        self._headings = out
        return out

    def sentences(self):
        """Prose sentences (the eval-draft discipline: fenced
        code, headings, tables and callouts are not prose).
        Memoised, like headings()."""
        if self._sentences is not None:
            return self._sentences
        text = ws.FENCE_RE.sub("", self.body)
        out = []
        for block in re.split(r"\n\s*\n", text):
            lines = [ln.strip() for ln in block.splitlines()
                     if ln.strip()]
            if not lines or lines[0].startswith(("#", "|", "> [!")):
                continue
            joined = " ".join(re.sub(r"^>\s?", "", ln)
                              for ln in lines)
            joined = re.sub(r"^[-*]\s+", "", joined)
            for sent in re.split(r"(?<=[.!?])\s+", joined):
                sent = sent.strip()
                if len(sent) >= 40:
                    out.append(sent)
        self._sentences = out
        return out

    def out_links(self, by_key):
        """Directed wikilink targets (doc indices), resolved
        with build_link_graph's precedence over stripped body."""
        body = ws.CODESPAN_RE.sub(
            "", ws.FENCE_RE.sub("", self.text))
        out = []
        for target in ws.LINK_RE.findall(body):
            t = target.strip()
            if not t:
                continue
            j = by_key.get(t) or by_key.get(Path(t).name)
            if j is not None:
                out.append(j)
        return out


def load_pages(root=ROOT):
    if Path(root) == ROOT:
        docs = ws.collect_docs("wiki")
    else:
        # Mirror collect_docs("wiki") over an arbitrary root
        # (test fixtures): same sorted rglob, same read mode.
        base = Path(root) / "wiki"
        docs = [(p, p.read_text(encoding="utf-8",
                                errors="ignore"))
                for p in ws.iter_md(base)]
    pages = []
    for path, text in docs:
        rel = str(Path(path).relative_to(root))
        pages.append(Page(rel, text))
    pages.sort(key=lambda p: p.rel)
    return pages


def link_resolver(pages):
    by_key = {}
    for i, p in enumerate(pages):
        by_key.setdefault(Path(p.rel).stem, i)
        by_key.setdefault(str(Path(p.rel).with_suffix("")), i)
    return by_key


STRUCTURAL = {"wiki/index.md", "wiki/log.md"}


# ---------------------------------------------------------------------------
# Question classes — each returns (kept, excluded{reason: n})
# ---------------------------------------------------------------------------

def q_title(pages):
    kept, excluded = [], {}
    def ex(r): excluded[r] = excluded.get(r, 0) + 1
    for p in pages:
        if p.rel in STRUCTURAL:
            continue
        toks = set(p.title_tokens)
        if len(toks) < 2:
            ex("title-too-few-content-tokens"); continue
        clash = False
        for other in pages:
            if other is p:
                continue
            otoks = set(other.title_tokens)
            if otoks and toks <= otoks:
                clash = True; break
        if clash:
            ex("title-covered-by-another-title"); continue
        kept.append({
            "class": "title",
            "question": f"Which wiki page carries the title "
                        f"'{p.title}'?",
            "expected_answer": p.title,
            "must_cite": [p.rel], "acceptable_cites": [],
            "derivation": {
                "rule": "title: the page whose frontmatter title "
                        "is quoted verbatim; excluded when "
                        "another page's title token set covers "
                        "this title's",
                "anchor": {"page": p.rel, "title": p.title}},
        })
    return kept, excluded


def _rag_sentence(page, heading):
    """First prose sentence carrying every content token of the
    heading (len > 2) — the RAGET answerability check."""
    need = [t for t in content_tokens(heading) if len(t) > 2]
    if not need:
        return None
    for sent in page.sentences():
        low = norm_text(sent)
        if all(t in low for t in need):
            return sent
    return None


def q_heading(pages):
    kept, excluded = [], {}
    def ex(r): excluded[r] = excluded.get(r, 0) + 1
    heads_by_page = {p.rel: p.headings() for p in pages}
    for p in pages:
        if p.rel in STRUCTURAL:
            continue
        seen = set()
        for h in heads_by_page[p.rel]:
            nh = norm_text(h)
            if nh in seen or nh == norm_text(p.title):
                continue
            seen.add(nh)
            if len(content_tokens(h)) < 2:
                ex("heading-too-few-content-tokens"); continue
            sent = _rag_sentence(p, h)
            if sent is None:
                ex("heading-no-answerable-sentence"); continue
            clash = False
            for other in pages:
                if other is p:
                    continue
                if nh in [norm_text(x)
                          for x in heads_by_page[other.rel]] \
                        and set(p.title_tokens) \
                        <= set(other.title_tokens):
                    clash = True; break
            if clash:
                ex("heading-shared-under-covering-title")
                continue
            kept.append({
                "class": "heading",
                "question": f"According to '{p.title}', what is "
                            f"covered under '{h}'?",
                "expected_answer": sent,
                "must_cite": [p.rel], "acceptable_cites": [],
                "derivation": {
                    "rule": "heading: the section heading quoted "
                            "verbatim; expected answer is the "
                            "first prose sentence carrying all "
                            "of the heading's content tokens "
                            "(RAGET answerability)",
                    "anchor": {"page": p.rel, "heading": h}},
            })
    return kept, excluded


def q_claim(pages):
    kept, excluded = [], {}
    def ex(r): excluded[r] = excluded.get(r, 0) + 1
    seen_claims = {}
    for p in pages:
        claim = p.fields.get("claim")
        if not isinstance(claim, str) or len(claim.strip()) < 25:
            continue
        claim = claim.strip()
        nc = norm_text(claim)
        if nc in seen_claims:
            ex("claim-duplicated-on-another-page"); continue
        seen_claims[nc] = p.rel
        kept.append({
            "class": "claim",
            "question": f"According to {p.title}, is the "
                        f"following claim supported: {claim}",
            "expected_answer": claim,
            "must_cite": [p.rel], "acceptable_cites": [],
            "derivation": {
                "rule": "claim: the page's frontmatter claim: "
                        "field, quoted verbatim (the eval-draft "
                        "question form); the claim is the "
                        "expected answer by construction",
                "anchor": {"page": p.rel, "claim": claim}},
        })
    return kept, excluded


def q_multihop(pages):
    kept, excluded = [], {}
    def ex(r): excluded[r] = excluded.get(r, 0) + 1
    by_key = link_resolver(pages)
    outs = {i: sorted(set(p.out_links(by_key)) - {i})
            for i, p in enumerate(pages)}
    for ai, a in enumerate(pages):
        for bi in outs[ai]:
            b = pages[bi]
            for ci in outs[bi]:
                if ci == ai or ci in outs[ai]:
                    continue
                c = pages[ci]
                seen_h = set()
                for h in c.headings():
                    nh = norm_text(h)
                    if nh in seen_h:
                        continue
                    seen_h.add(nh)
                    if len(content_tokens(h)) < 2:
                        continue
                    rivals = [j for j in outs[bi]
                              if j != ci and nh in
                              [norm_text(x) for x in
                               pages[j].headings()]]
                    if rivals:
                        ex("multihop-hop-does-not-decide")
                        continue
                    sent = _rag_sentence(c, h)
                    if sent is None:
                        ex("multihop-no-answerable-sentence")
                        continue
                    kept.append({
                        "class": "multihop",
                        "question": f"The page '{a.title}' "
                            f"links to '{b.title}', which links "
                            f"onward. Which page reached that "
                            f"way covers '{h}', and what does "
                            f"it state there?",
                        "expected_answer": sent,
                        "must_cite": [c.rel],
                        "acceptable_cites": [b.rel],
                        "derivation": {
                            "rule": "multihop: A->B->C wikilink "
                                    "bridge (MultiHop-RAG "
                                    "pattern); C is not a "
                                    "direct link of A; excluded "
                                    "when another of B's "
                                    "out-neighbours also "
                                    "covers the heading",
                            "anchor": {"chain": [a.rel, b.rel,
                                                 c.rel],
                                       "heading": h}},
                    })
    return kept, excluded


LOG_ENTRY_RE = re.compile(
    r"^## \[(\d{4}-\d{2}-\d{2})\] (\w+) \| (.+)$", re.M)


def q_episodic(pages, log_text):
    kept, excluded = [], {}
    def ex(r): excluded[r] = excluded.get(r, 0) + 1
    by_created = {}
    for p in pages:
        if p.created and p.rel not in STRUCTURAL:
            by_created.setdefault(p.created, []).append(p)
    for date, kind, title in LOG_ENTRY_RE.findall(log_text):
        if kind != "ingest":
            continue
        terms = set(content_tokens(title))
        if len(terms) < 2:
            ex("episodic-entry-too-few-content-tokens")
            continue
        cands = [p for p in by_created.get(date, [])
                 if len(terms & set(p.title_tokens)) >= 2]
        if not cands:
            ex("episodic-no-page-created-that-date-matches")
            continue
        if len(cands) > 1:
            ex("episodic-ambiguous-two-pages-entitled")
            continue
        p = cands[0]
        kept.append({
            "class": "episodic",
            "question": f"What was ingested into the wiki on "
                        f"{date} concerning {title.strip()}?",
            "expected_answer": p.title,
            "must_cite": [p.rel], "acceptable_cites": [],
            "derivation": {
                "rule": "episodic: the dated log ingest entry "
                        "maps to exactly one page created that "
                        "date sharing >= 2 title content tokens "
                        "with the entry title",
                "anchor": {"log_entry": {"date": date,
                                         "title": title.strip()},
                           "page": p.rel,
                           "page_created": p.created}},
        })
    return kept, excluded


def _tables_of(page):
    """Yield (section_heading, header_cells, rows) for each
    well-formed pipe table in the body (fences stripped)."""
    body = ws.FENCE_RE.sub("", page.body)
    lines = body.splitlines()
    section = page.title
    i = 0
    while i < len(lines):
        m = re.match(r"^#{2,3}\s+(.+?)\s*$", lines[i])
        if m:
            section = m.group(1).strip()
        if lines[i].strip().startswith("|") \
                and i + 1 < len(lines) \
                and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            header = [c.strip() for c in
                      lines[i].strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) \
                    and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in
                         lines[j].strip().strip("|").split("|")]
                if len(cells) == len(header):
                    rows.append(cells)
                j += 1
            if len(header) >= 2 and len(rows) >= 2:
                yield section, header, rows
            i = j
            continue
        i += 1


def q_table(pages):
    kept, excluded = [], {}
    def ex(r): excluded[r] = excluded.get(r, 0) + 1
    all_tables = []
    for p in pages:
        if p.rel in STRUCTURAL:
            continue
        for section, header, rows in _tables_of(p):
            all_tables.append((p, section, header, rows))
    key_seen = {}
    for p, section, header, rows in all_tables:
        for row in rows:
            sig = (norm_text(row[0]), norm_text(header[-1]))
            key_seen.setdefault(sig, set()).add(p.rel)
    for p, section, header, rows in all_tables:
        for row in rows:
            key, value = row[0], row[-1]
            if not key or len(value) < 3:
                ex("table-cell-too-thin"); continue
            sig = (norm_text(key), norm_text(header[-1]))
            if len(key_seen.get(sig, ())) > 1:
                ex("table-key-column-pair-on-another-page")
                continue
            if sum(1 for r in rows
                   if norm_text(r[0]) == norm_text(key)) > 1:
                ex("table-key-repeated-in-table"); continue
            kept.append({
                "class": "table",
                "question": f"In the table on '{p.title}' "
                    f"(section '{section}'), what is the "
                    f"{header[-1]} for {header[0]} '{key}'?",
                "expected_answer": value,
                "must_cite": [p.rel], "acceptable_cites": [],
                "derivation": {
                    "rule": "table: one cell of a Markdown "
                            "table (the table-summarisation "
                            "pattern — the answer is the cell "
                            "verbatim); excluded when the "
                            "row-key + value-column pair "
                            "occurs on another page",
                    "anchor": {"page": p.rel, "section": section,
                               "row_key": key,
                               "column": header[-1]}},
            })
    return kept, excluded


def corpus_vocab(pages, extra_texts=()):
    vocab = set()
    for p in pages:
        vocab |= set(ws.tokenize(p.text))
    for t in extra_texts:
        vocab |= set(ws.tokenize(t))
    return vocab


def q_zeromatch(pages, vocab):
    kept, excluded = [], {}
    def ex(r): excluded[r] = excluded.get(r, 0) + 1
    df = {}
    for p in pages:
        for tok in set(content_tokens(p.text)):
            df[tok] = df.get(tok, 0) + 1
    nonces = [n for n in NONCES if n not in vocab]
    if len(nonces) < len(NONCES):
        excluded["zeromatch-nonce-found-in-corpus"] = \
            len(NONCES) - len(nonces)
    if not nonces:
        return kept, excluded
    n_i = 0
    for p in pages:
        if p.rel in STRUCTURAL or len(p.title_tokens) < 3:
            continue
        rare = min(set(p.title_tokens),
                   key=lambda t: (df.get(t, 0), t))
        nonce = nonces[n_i % len(nonces)]
        n_i += 1
        mutated = re.sub(re.escape(rare),
                         lambda _m: nonce, p.title, count=1,
                         flags=re.I)
        if mutated == p.title:
            ex("zeromatch-mutation-did-not-apply"); continue
        kept.append({
            "class": "zeromatch",
            "question": f"What does the wiki record about "
                        f"{mutated}?",
            "expected_answer": "",
            "must_cite": [], "acceptable_cites": [],
            "expected_abstain": True,
            "derivation": {
                "rule": "zeromatch: a real page title with "
                        "its rarest content token replaced "
                        "by a coined word verified absent "
                        "from the corpus vocabulary; the "
                        "correct behaviour is abstention",
                "anchor": {"home_page": p.rel,
                           "mutated_token": rare,
                           "nonce": nonce,
                           "mutated_title": mutated}},
        })
    return kept, excluded


BUILDERS = {"title": q_title, "heading": q_heading,
            "claim": q_claim, "multihop": q_multihop,
            "table": q_table}


def build_slice(pages, log_text, protected_text):
    vocab = corpus_vocab(pages, [protected_text])
    per_class, excluded_all = {}, {}
    for cls in CLASS_ORDER:
        if cls == "episodic":
            kept, ex = q_episodic(pages, log_text)
        elif cls == "zeromatch":
            kept, ex = q_zeromatch(pages, vocab)
        else:
            kept, ex = BUILDERS[cls](pages)
        kept.sort(key=lambda q: (
            q["must_cite"][0] if q["must_cite"]
            else q["derivation"]["anchor"].get("home_page", ""),
            json.dumps(q["derivation"]["anchor"],
                       sort_keys=True)))
        cap = CAPS[cls]
        if cap is not None and len(kept) > cap:
            ex["over-cap"] = ex.get("over-cap", 0) \
                + (len(kept) - cap)
            kept = kept[:cap]
        per_class[cls] = kept
        excluded_all[cls] = ex
    rows, n = [], 0
    for cls in CLASS_ORDER:
        for q in per_class[cls]:
            n += 1
            row = {"id": f"SQ-{n:04d}", "synthetic": True,
                   "class": q["class"], "route":
                   "abstain" if q["class"] == "zeromatch"
                   else "exact",
                   "question": q["question"],
                   "expected_answer": q["expected_answer"],
                   "must_cite": q["must_cite"],
                   "acceptable_cites": q["acceptable_cites"],
                   "forbidden_claims": [],
                   "expected_abstain":
                   bool(q.get("expected_abstain", False)),
                   "derivation": q["derivation"],
                   "generator": GENERATOR}
            rows.append(row)
    return rows, excluded_all


def git_head():
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


def slice_text(rows, excluded, head, docs_n):
    header = {
        "kind": "header", "set": "synthetic-slices",
        "synthetic": True, "version": 1,
        "generated_by":
            "scripts/wiki_synthetic_slices.py (deterministic; "
            "same corpus state -> byte-identical file)",
        "generator": GENERATOR,
        "corpus_head": head, "corpus_docs": docs_n,
        "bias_statement": BIAS_STATEMENT,
        "credits": "Patterns: MultiHop-RAG (MIT) bridge "
                   "questions; episodic-memory-benchmark "
                   "dated-episode + zero-match probes; "
                   "LangChain Benchmarks table tasks; Giskard "
                   "RAGET (Apache-2.0) answerability check. "
                   "Adapted with credit; all code is this "
                   "tree's own.",
        "protected_sets_untouched": list(PROTECTED),
        "caps": CAPS,
        "selection": "kept questions are the first N in "
                     "(page path, anchor) order per class — "
                     "a breadth sample, not a random sample",
        "counts": {}, "excluded": excluded,
    }
    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    header["counts"] = counts
    lines = [json.dumps(header, ensure_ascii=False,
                        sort_keys=True)]
    for r in rows:
        lines.append(json.dumps(r, ensure_ascii=False,
                                sort_keys=True))
    return "\n".join(lines) + "\n", header


def load_slice(path):
    recs = [json.loads(ln) for ln in
            Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    header = recs[0] if recs and recs[0].get("kind") == "header" \
        else {}
    rows = [r for r in recs if r.get("kind") != "header"]
    return header, rows


def protected_ids(root=ROOT):
    ids = set()
    for name in PROTECTED:
        p = root / "evaluation" / name
        if not p.is_file():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                rec = json.loads(ln)
                if rec.get("id"):
                    ids.add(rec["id"])
    return ids


def cmd_generate(out_path):
    pages = load_pages()
    log_text = (ROOT / "wiki" / "log.md").read_text(
        encoding="utf-8")
    protected_text = ""
    for name in PROTECTED:
        p = EVAL / name
        if p.is_file():
            protected_text += p.read_text(encoding="utf-8")
    rows, excluded = build_slice(pages, log_text, protected_text)
    text, header = slice_text(rows, excluded, git_head(),
                              len(pages))
    out_path = Path(out_path)
    out_path.write_text(text, encoding="utf-8")
    print(f"questions={len(rows)} by class={header['counts']}")
    print(f"excluded={json.dumps(excluded, sort_keys=True)}")
    print(f"wrote {out_path}")
    return 0


def cmd_check(slice_path):
    problems = []
    header, rows = load_slice(slice_path)
    if not header.get("synthetic"):
        problems.append("header does not declare synthetic: true")
    pids = protected_ids()
    seen = set()
    vocab = None
    pages = load_pages()
    rels = {p.rel for p in pages}
    for r in rows:
        if not r.get("synthetic"):
            problems.append(f"{r.get('id')}: not synthetic")
        if r["id"] in seen:
            problems.append(f"{r['id']}: duplicate id")
        seen.add(r["id"])
        if r["id"] in pids:
            problems.append(
                f"{r['id']}: COLLIDES with a hand-written id")
        if not r["id"].startswith("SQ-"):
            problems.append(f"{r['id']}: outside the SQ- "
                            "namespace")
        if "derivation" not in r:
            problems.append(f"{r['id']}: no derivation")
        for mc in r.get("must_cite") or []:
            if mc not in rels:
                problems.append(f"{r['id']}: must_cite {mc} "
                                "does not resolve")
        if r["class"] == "zeromatch":
            nonce = r["derivation"]["anchor"]["nonce"]
            if vocab is None:
                vocab = corpus_vocab(pages)
            if nonce in vocab:
                problems.append(f"{r['id']}: nonce {nonce} IS "
                                "in the corpus vocabulary")
    for cls in CLASS_ORDER:
        n = sum(1 for r in rows if r["class"] == cls)
        cap = CAPS[cls]
        if cap is not None and n > cap:
            problems.append(f"class {cls}: {n} rows over cap "
                            f"{cap}")
    if problems:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    print(f"check OK: {len(rows)} synthetic questions, ids "
          f"disjoint from {len(pids)} hand-written ids, all "
          "must_cite resolve, all rows carry derivations")
    return 0


def cmd_score(slice_path):
    bakeoff = _load("wiki_bakeoff", "wiki_bakeoff.py")
    header, rows = load_slice(slice_path)
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    runner = bakeoff.ConfigRunner("house", docs, adj)
    by_class = {}
    for r in rows:
        by_class.setdefault(r["class"], []).append(r)
    # One ranking pass over all citation classes; per-class
    # aggregates are grouped from the same uniform rows, so
    # the classes and the overall figure can never disagree
    # about a ranking.
    cite_rows = [q for q in rows if q["class"] != "zeromatch"]
    results, per_q_all, overall = {}, {}, None
    if cite_rows:
        overall, urows, _lat = bakeoff.run_bench_instrument(
            runner, cite_rows)
        cls_of = {q["id"]: q["class"] for q in cite_rows}
        grouped = {}
        for u in urows:
            grouped.setdefault(cls_of[u["id"]], []).append(u)
        for cls in CLASS_ORDER:
            if cls in grouped:
                results[cls] = bakeoff.aggregate_bench_rows(
                    grouped[cls])
                per_q_all[cls] = grouped[cls]
    tau = None
    baseline = EVAL / "extended-baseline.json"
    if baseline.is_file():
        tau = json.loads(baseline.read_text(
            encoding="utf-8")).get("abstain_threshold")
    zm_rows, zm_pass = [], 0
    for q in by_class.get("zeromatch", []):
        ranked = runner.rank(ws.tokenize(q["question"]))
        top1 = ranked[0] if ranked else (None, None)
        home = q["derivation"]["anchor"]["home_page"]
        home_rank = next((i + 1 for i, (_s, p) in
                          enumerate(ranked) if p == home), None)
        would_abstain = (not ranked) or (
            tau is not None and top1[0] is not None
            and top1[0] < tau)
        zm_pass += 1 if would_abstain else 0
        zm_rows.append({"id": q["id"],
                        "top1_path": top1[1],
                        "top1_score": (round(top1[0], 4)
                                       if top1[0] is not None
                                       else None),
                        "home_page": home,
                        "home_rank": home_rank,
                        "would_abstain": would_abstain})
    slice_sha = hashlib.sha256(
        Path(slice_path).read_bytes()).hexdigest()
    core = {"slice_sha256": slice_sha,
            "config": {"name": "house", "spec": runner.spec},
            "corpus": {"git_head": git_head(),
                       "docs": len(docs)},
            "per_class": results, "overall": overall,
            "zeromatch": {"n": len(zm_rows), "would_abstain":
                          zm_pass}}
    report = {
        "kind": "synthetic-slices-report", "version": 1,
        "row_family": "synthetic-slices",
        "bias_statement": BIAS_STATEMENT,
        "never_pooled": "These figures are reported ONLY "
                        "here; they are not inputs to the "
                        "bakeoff ledger, the meta-benchmark "
                        "criteria, or any hand-written set's "
                        "score.",
        "slice": {"file": "evaluation/synthetic-questions"
                          ".jsonl",
                  "sha256": slice_sha,
                  "questions": len(rows),
                  "counts": header.get("counts"),
                  "excluded": header.get("excluded")},
        "config": {"name": "house", "spec": runner.spec},
        "corpus": {"git_head": git_head(),
                   "dirty": bakeoff.git_dirty(),
                   "docs": len(docs), "scope": "wiki/"},
        "per_class": results,
        "overall_synthetic": overall,
        "zeromatch": {"tau": tau,
                      "tau_source": "evaluation/extended-"
                                    "baseline.json "
                                    "abstain_threshold (the "
                                    "battery's own source)",
                      "n": len(zm_rows),
                      "would_abstain": zm_pass,
                      "rate": (round(zm_pass / len(zm_rows), 4)
                               if zm_rows else None),
                      "per_question": zm_rows},
        "per_question": per_q_all,
        "criteria_note": "No criteria judge this row family: "
                         "the meta-benchmark's frozen v1 "
                         "covers the hand-written instruments "
                         "only. Whether synthetic slices "
                         "deserve criteria (e.g. a regression "
                         "floor per class) is a v2 question "
                         "for the owner/meta-benchmark, "
                         "recorded here, not decided.",
        "row_identity": bakeoff.sha256_text(
            bakeoff.canonical(core)),
    }
    REPORT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    lines = ["# Synthetic evaluation slices — report", "",
             "> " + BIAS_STATEMENT, "",
             f"Slice: `evaluation/synthetic-questions.jsonl` "
             f"(sha256 {slice_sha[:12]}…, {len(rows)} "
             f"questions) · config: house · corpus: "
             f"{len(docs)} docs @ {git_head()}", "",
             "## Per-class results (house configuration)", "",
             "| class | questions | cov@1 | cov@3 | cov@10 "
             "| hit@10 | MRR |",
             "|---|---|---|---|---|---|---|"]
    for cls in CLASS_ORDER:
        if cls in results:
            a = results[cls]
            c = a["citation_coverage"]
            lines.append(
                f"| {cls} | {a['questions']} | {c['@1']} "
                f"| {c['@3']} | {c['@10']} "
                f"| {a['hit_rate_topk']} "
                f"| {a['mrr_must_cite']} |")
    if overall:
        c = overall["citation_coverage"]
        lines.append(
            f"| **all synthetic (citation classes)** "
            f"| {overall['questions']} | {c['@1']} | {c['@3']} "
            f"| {c['@10']} | {overall['hit_rate_topk']} "
            f"| {overall['mrr_must_cite']} |")
    lines += ["",
              f"## Zero-match probes "
              f"({len(zm_rows)} questions, tau = {tau})", "",
              f"Would abstain (top-1 score < tau): {zm_pass}"
              f" / {len(zm_rows)}"
              + (f" = {report['zeromatch']['rate']}"
                 if zm_rows else ""), "",
              "## Notes", "",
              "- " + report["criteria_note"],
              "- Excluded-at-generation counts (ambiguous / "
              "unanswerable derivations) are in the slice "
              "file's header — the slice reports what it "
              "refused to ask, not only what it asked.", ""]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"per-class: {json.dumps(results, sort_keys=True)}")
    print(f"zeromatch: {zm_pass}/{len(zm_rows)} would abstain "
          f"(tau={tau})")
    print(f"wrote {REPORT_JSON.relative_to(ROOT)} + "
          f"{REPORT_MD.relative_to(ROOT)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Synthetic evaluation slices over the "
                    "real corpus.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", default=str(DEFAULT_SLICE))
    s = sub.add_parser("score")
    s.add_argument("--slice", default=str(DEFAULT_SLICE))
    c = sub.add_parser("check")
    c.add_argument("--slice", default=str(DEFAULT_SLICE))
    args = ap.parse_args(argv)
    if args.cmd == "generate":
        return cmd_generate(args.out)
    if args.cmd == "score":
        return cmd_score(args.slice)
    return cmd_check(args.slice)


if __name__ == "__main__":
    raise SystemExit(main())
