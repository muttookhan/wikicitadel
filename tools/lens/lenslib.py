"""Shared library for the WikiCitadel Lens compiler.

One parser for the wiki corpus: YAML frontmatter, body structure,
wikilinks, typed links, citations, ledes. The Lens builder (and any
future lint that adopts the shared edge table) reads through here so
links are derived exactly once, one way — the blueprint's §1.4
contract.

Also carries the reference BM25 implementation used for the Lens
search postings. It is deliberately a faithful port of
scripts/wiki_search.py (same tokenizer, same constants, same IDF,
same snippet rule, same tie-break) so the build-time parity check
compares two executions of one algorithm, not two algorithms.
"""

import datetime
import difflib
import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

# --------------------------------------------------------------------------
# Tokenizer + BM25 — ported verbatim in behaviour from scripts/wiki_search.py
# --------------------------------------------------------------------------

K1 = 1.5
B = 0.75
TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str):
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def bm25_idf(n, df):
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))


def make_snippet(text: str, query_terms, width: int = 170) -> str:
    """Identical rule to scripts/wiki_search.py: best line by distinct
    query terms, then total occurrences, then earliest."""
    qset = set(query_terms)
    best_line = None
    best_key = None
    for pos, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        toks = tokenize(line)
        distinct = len(qset & set(toks))
        if distinct == 0:
            continue
        key = (distinct, sum(1 for t in toks if t in qset), -pos)
        if best_key is None or key > best_key:
            best_key = key
            best_line = line
    if best_line is None:
        return "(match in token stream; no single line holds a query term)"
    line = best_line
    if len(line) <= width:
        return line
    m = None
    for match in TOKEN_RE.finditer(line.lower()):
        if match.group(0) in qset:
            m = match
            break
    if m is None:
        return line[:width] + "…"
    start = max(0, m.start() - width // 3)
    end = start + width
    out = line[start:end]
    if start > 0:
        out = "…" + out
    if end < len(line):
        out = out + "…"
    return out


# Title/stem boost — mirror of scripts/wiki_search.py (Marathon
# R3 TB7): exact title/stem match +10, stemmed match +5, added in
# hybrid_rank after the rerank stage, before severance.
TITLE_EXACT_BOOST = 10.0
TITLE_STEM_BOOST = 5.0


def stem_token(tok: str) -> str:
    """Mirror of wiki_search.py stem_token (suffix rules only)."""
    t = tok.lower()
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    elif len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("es") and not t.endswith("ss"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    if len(t) > 3 and t[-1] == t[-2] and t[-1] not in "aeiou":
        t = t[:-1]
    return t


def title_match_kind(query_terms, title, stem):
    """Mirror of wiki_search.py title_match_kind."""
    q = [str(t).lower() for t in query_terms]
    if not q:
        return None
    title_toks = tokenize(title or "")
    stem_toks = tokenize((stem or "").replace("-", " "))
    if q == title_toks or q == stem_toks:
        return "exact"
    q_stems = {stem_token(t) for t in q}
    for toks in (title_toks, stem_toks):
        if toks and q_stems == {stem_token(t) for t in toks}:
            return "stem"
    return None


def title_boost_value(query_terms, title, stem):
    kind = title_match_kind(query_terms, title, stem)
    if kind == "exact":
        return TITLE_EXACT_BOOST, kind
    if kind == "stem":
        return TITLE_STEM_BOOST, kind
    return 0.0, None


class PostingsIndex:
    """Precomputed BM25 index over a fixed document list.

    docs: list of dicts with keys: key (stable string used for
    tie-breaking, matching the reference script's path ordering),
    text (the exact text the reference script would tokenize).
    """

    def __init__(self, docs, severance=None):
        self.docs = docs
        # Retrieval severance (item 20): the parsed severance
        # list (evaluation/retrieval-severance.json) or None.
        # hybrid_rank consults it exactly as scripts/wiki_search.py
        # does; None keeps the pre-severance behaviour.
        self._sev_page_entries = []
        self._sev_claim_entries = []
        if severance:
            for e in severance.get("entries") or []:
                if e.get("kind") == "page":
                    self._sev_page_entries.append(e)
                else:
                    self._sev_claim_entries.append(e)
        self.last_severance = {"applied": bool(severance),
                               "excluded": []}
        self.n = len(docs)
        self.df = Counter()
        self.postings = {}  # term -> list of [doc_idx, tf]
        self.doc_len = []
        total = 0
        for i, d in enumerate(docs):
            toks = tokenize(d["text"])
            self.doc_len.append(len(toks))
            total += len(toks)
            tf = Counter(toks)
            for term, f in tf.items():
                self.df[term] += 1
                self.postings.setdefault(term, []).append([i, f])
        self.avgdl = total / self.n if self.n else 1.0

    def rank(self, query_terms):
        """Reference-identical scoring. Returns [(score, doc_idx)]
        sorted by (-score, doc key), score > 0 only."""
        idf = {}
        for term in set(query_terms):
            d = self.df.get(term, 0)
            idf[term] = bm25_idf(self.n, d)
        scores = defaultdict(float)
        for term in query_terms:
            for i, f in self.postings.get(term, []):
                dl = self.doc_len[i]
                denom = f + K1 * (1.0 - B + B * dl / self.avgdl)
                scores[i] += idf[term] * (f * (K1 + 1.0)) / denom
        out = [(s, i) for i, s in scores.items() if s > 0]
        out.sort(key=lambda r: (-r[0], self.docs[r[1]]["key"]))
        return out

    def to_json(self):
        return {
            "n": self.n,
            "avgdl": self.avgdl,
            "df": dict(self.df),
            "doc_len": self.doc_len,
            "postings": self.postings,
        }

    def hybrid_rank(self, query_terms, adj):
        """BM25 + personalized-PageRank hybrid — a faithful mirror of
        scripts/wiki_search.py hybrid_rank() (same constants, same
        combination, same inclusion floor, same tie-break). The build
        parity-checks this against the reference implementation, so
        the two cannot drift. `adj`: {doc_idx: sorted [doc_idx]}
        over this index's doc list (built by the reference module's
        build_link_graph, so graph construction is shared, not
        mirrored). Returns [(score, doc_idx, detail)]."""
        base = self.rank(query_terms)
        if not base:
            return []
        bm25_by_idx = {i: s for s, i in base}
        seeds = {i: s for s, i in base[:PPR_SEEDS]}
        ppr = personalized_pagerank(adj, seeds)
        max_b = max(bm25_by_idx.values())
        max_p = max(ppr.values()) if ppr else 0.0
        out = []
        for i in range(self.n):
            b = bm25_by_idx.get(i, 0.0)
            pr = ppr.get(i, 0.0)
            if self.docs[i].get("structural"):
                # Structural pages (index/log) walk but do not
                # receive the PPR component — mirror of
                # wiki_search.py STRUCTURAL_PATHS.
                pr = 0.0
            if b <= 0 and not (max_p > 0 and pr >= PPR_GRAPH_FLOOR * max_p):
                continue
            score = (b / max_b if max_b else 0.0) \
                + HYBRID_ALPHA * (pr / max_p if max_p else 0.0)
            via = "both" if b > 0 and pr > 0 else ("bm25" if b > 0 else "graph")
            out.append((score, i,
                        {"bm25": round(b, 4), "ppr": round(pr, 6), "via": via}))
        out.sort(key=lambda r: (-r[0], self.docs[r[1]]["key"]))
        if not out:
            return out

        # --- Stage 3: temporal component (intent-gated) ---
        # Mirror of wiki_search.py hybrid_rank stage 3.
        temp_by_idx = {}
        if temporal_intent(query_terms):
            cand = [i for _s, i, _d in out]

            def _date_key(i):
                d = doc_date(self.docs[i]["text"])
                return (d is not None, d or "", bm25_by_idx.get(i, 0.0))

            t_order = sorted(sorted(cand, key=lambda i: self.docs[i]["key"]),
                             key=_date_key, reverse=True)
            n_cand = len(cand)
            for r, i in enumerate(t_order):
                temp_by_idx[i] = 1.0 - r / n_cand

        # --- Stage 4: coverage rerank over the stage-2 order ---
        qset = set(query_terms)
        max_s = out[0][0]
        final = []
        for pos, (score, i, detail) in enumerate(out):
            # Final blend renormalisation (mirror of
            # wiki_search.py stage 4): the abstention tau is
            # calibrated to this absolute scale.
            ns = score / max_s if max_s else 0.0
            t = temp_by_idx.get(i, 0.0)
            ns += TEMPORAL_W * t
            mult = 1.0
            if pos < RERANK_POOL and qset:
                text = self.docs[i]["text"]
                lead = set(tokenize(text)[:RERANK_LEAD_TOKENS])
                cov = len(qset & lead) / len(qset)
                title_toks = set(tokenize(doc_title(text)))
                t_frac = len(qset & title_toks) / len(qset)
                mult = 1.0 + RERANK_COVERAGE_W * cov + RERANK_TITLE_W * t_frac
                ns *= mult
            # Stage 4b: the title/stem boost (mirror of
            # wiki_search.py: the boost is the final term of
            # the "hybrid-current" rank expression).
            boost, match_kind = title_boost_value(
                query_terms, doc_title(self.docs[i]["text"]),
                Path(self.docs[i]["key"]).stem)
            ns += boost
            detail = dict(detail, temporal=round(t, 4), rerank=round(mult, 4),
                          title_boost=boost, title_match=match_kind,
                          rank_expression="hybrid-current")
            final.append((ns, i, detail))
        final.sort(key=lambda r: (-r[0], self.docs[r[1]]["key"]))

        # --- Stage 5: retrieval severance (item 20) ---
        # Mirror of wiki_search.py hybrid_rank stage 5: severed
        # pages, and carriers of a severed claim the query hunts,
        # are excluded after every ranking stage.
        self.last_severance = {
            "applied": bool(self._sev_page_entries
                            or self._sev_claim_entries),
            "excluded": []}
        if self._sev_page_entries or self._sev_claim_entries:
            q_matched = [e for e in self._sev_claim_entries
                         if _sev_query_matches(query_terms, e)]
            kept = []
            for item in final:
                _score, i, _detail = item
                rel = _sev_relpath(self.docs[i]["key"])
                hit_ids = [e["id"] for e in self._sev_page_entries
                           if e.get("page") == rel]
                if not hit_ids and q_matched:
                    tokens = tokenize(self.docs[i]["text"])
                    hit_ids = [e["id"] for e in q_matched
                               if _sev_text_matches(tokens, e)]
                if hit_ids:
                    self.last_severance["excluded"].append(
                        {"path": rel, "entries": hit_ids})
                else:
                    kept.append(item)
            final = kept
        return final


# Hybrid constants — mirror scripts/wiki_search.py EXACTLY (the
# Lens build parity-checks the hybrid ranking; drift fails there).
HYBRID_ALPHA = 0.6
PPR_DAMPING = 0.85
PPR_SEEDS = 10
PPR_GRAPH_FLOOR = 0.01
RERANK_COVERAGE_W = 0.25
RERANK_TITLE_W = 0.15
RERANK_POOL = 25
RERANK_LEAD_TOKENS = 400
TEMPORAL_W = 0.3

# Temporal/rerank helpers — mirrors of the same-named functions in
# scripts/wiki_search.py (identical regexes, identical rules).
TEMPORAL_TERMS = {
    "latest", "recent", "recently", "newest", "current", "currently",
    "now", "today", "yesterday", "when", "last", "since", "before",
    "after", "during",
}
MONTH_TERMS = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
}
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})", re.M)
FM_DATE_RE = re.compile(r"^(updated|created):\s*(\d{4}-\d{2}-\d{2})", re.M)
TITLE_RE = re.compile(r"^title:\s*\"?([^\"\n]+)\"?\s*$", re.M)
H1_RE = re.compile(r"^#\s+(.+)$", re.M)


def doc_date(text: str):
    head = text[:3000]
    fm = {}
    for key, val in FM_DATE_RE.findall(head):
        fm.setdefault(key, val)
    if "updated" in fm:
        return fm["updated"]
    if "created" in fm:
        return fm["created"]
    m = DATE_RE.search(head)
    return m.group(1) if m else None


def doc_title(text: str) -> str:
    m = TITLE_RE.search(text[:3000])
    if m:
        return m.group(1).strip()
    m = H1_RE.search(text)
    return m.group(1).strip() if m else ""


def temporal_intent(query_terms) -> bool:
    qset = set(query_terms)
    if qset & TEMPORAL_TERMS or qset & MONTH_TERMS:
        return True
    return any(YEAR_RE.match(t) for t in qset)


def personalized_pagerank(adj, seeds, damping=PPR_DAMPING,
                          tol=1e-7, max_iter=200):
    """Power-iteration PPR, mirroring scripts/wiki_search.py:
    dangling nodes redistribute over the seed distribution."""
    n = len(adj)
    if n == 0 or not seeds:
        return {}
    total = float(sum(seeds.values())) or 1.0
    teleport = {i: seeds.get(i, 0.0) / total for i in adj}
    rank = dict(teleport)
    for _ in range(max_iter):
        dangling = sum(rank[i] for i in adj if not adj[i])
        new = {}
        for i in adj:
            incoming = 0.0
            for j in adj[i]:
                if adj[j]:
                    incoming += rank[j] / len(adj[j])
            new[i] = (1.0 - damping) * teleport[i] \
                + damping * (incoming + dangling * teleport[i])
        delta = sum(abs(new[i] - rank[i]) for i in adj)
        rank = new
        if delta < tol:
            break
    return rank


# --------------------------------------------------------------------------
# Retrieval severance (item 20) — mirrors of the same-named helpers
# in scripts/wiki_search.py (identical rules: cue phrases as
# contiguous token subsequences; distinctive terms at 4/5 presence
# for a TEXT match, at >= half (min 3) for a QUERY match). The one
# asymmetry is path resolution: an index doc is identified by its
# "key" (a filesystem path as built), so the repo-relative page
# path is recovered by suffix before comparison.
# --------------------------------------------------------------------------

def _sev_phrase_hit(tokens, phrase):
    n = len(phrase)
    if n == 0 or n > len(tokens):
        return False
    phrase = list(phrase)
    return any(tokens[i:i + n] == phrase
               for i in range(len(tokens) - n + 1))


def _sev_terms_present(tokens, terms):
    have = set(tokens)
    return sum(1 for t in terms if t in have)


def _sev_text_matches(tokens, entry):
    cues = entry.get("cues") or {}
    for phrase in cues.get("phrases") or []:
        if _sev_phrase_hit(tokens, phrase):
            return True
    terms = cues.get("terms") or []
    if terms and _sev_terms_present(tokens, terms) * 5 \
            >= len(terms) * 4:
        return True
    return False


def _sev_query_matches(query_terms, entry):
    cues = entry.get("cues") or {}
    for phrase in cues.get("phrases") or []:
        if _sev_phrase_hit(query_terms, phrase):
            return True
    terms = cues.get("terms") or []
    if terms:
        need = max(3, (len(terms) + 1) // 2)
        if _sev_terms_present(query_terms, terms) >= need:
            return True
    return False


def _sev_relpath(key):
    """Repo-relative path of an index doc from its key: the key
    may be the repo-relative path itself or a filesystem path
    ending in it (the build passes str(path))."""
    k = str(key).replace("\\", "/")
    for anchor in ("/wiki/", "/raw/"):
        idx = k.find(anchor)
        if idx != -1:
            return k[idx + 1:]
    return k


# ---------------------------------------------------------------------------
# Freshness at the moment of use (consolidated-queue item 46, 2026-10-20)
#
# Trusted staleness is the failure mode (wave-8 survey, Rivera's
# second-brain post-mortem): the system does not get abandoned,
# it gets quietly wrong while still trusted. The guard is
# making staleness visible AT THE MOMENT OF USE — when a result
# or an evidence passage is displayed, its verification state
# travels with it, instead of being discoverable only by
# opening the page or reading the nightly filing.
#
# The annotation is computed once per page from the signals
# the wiki already keeps:
#
#   * `verified_until` frontmatter — the owner's attestation
#     (the lint lanes' attestation rule): current until the
#     date, overdue after it;
#   * the re-verification schedule (scripts/wiki_reverify.py's
#     FSRS fold, mirrored below): a claim page whose next
#     check is due or overdue today;
#   * supersession on the page's own face: frontmatter
#     `status: superseded / deprecated / tombstoned`, a
#     `superseded_by` pointer, a tombstone's `replaced_by`;
#   * source standing — item 33's fold of the treatment and
#     source-grades registers (mirrored below from
#     tools/ask/standing.py).
#
# A page with NO signal produces NO line. Silence means "no
# adverse signal on record" — it is NOT an attestation of
# freshness, and no surface may render it as one.
#
# tools/lens/lenslib.py mirrors this section (the same
# discipline as the ranking and severance mirrors);
# scripts/tests/test_freshness.py runs both implementations
# over fixtures and the real corpus and pins the agreement —
# same page, same record.
# ---------------------------------------------------------------------------

FRESHNESS_TREATMENT_REL = "evaluation/treatment-register.jsonl"
FRESHNESS_GRADES_REL = "evaluation/source-grades.jsonl"
FRESHNESS_HISTORY_REL = "evaluation/reverify-history.jsonl"

_FRESH_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
_FRESH_FM_LINE_RE = re.compile(r"^([A-Za-z_]+):\s*(.*)$")
# Aliased so the two mirrors' bodies stay line-for-line equal
# (wiki_search imports the names; lenslib has the module).
_fresh_date = datetime.date
_fresh_datetime = datetime.datetime
_fresh_timedelta = datetime.timedelta

# Standing severities + tiers — mirror of tools/ask/standing.py.
_FRESH_TREATMENT_SEVERITY = {"followed": -1, "questioned": 1,
                             "caution": 2, "negative": 3}
_FRESH_INTEGRITY_SEVERITY = {"established": -1, "unremarkable": 0,
                             "questioned": 2, "compromised": 3}
_FRESH_PRECISION_SEVERITY = {"exact": -1, "careful": 0,
                             "loose": 2, "error-prone": 3}
_FRESH_TIER_NAMES = {0: "strongest", 1: "neutral",
                     2: "weakened", 3: "negative"}

# Re-verification schedule constants — mirror of
# scripts/wiki_reverify.py (a documented simplification of
# FSRS-6; the constants are policy, stated there).
_FRESH_D_START = 5.0
_FRESH_D_MIN, _FRESH_D_MAX = 1.0, 10.0
_FRESH_D_STEP = {"pass": -0.3, "changed": 0.4, "fail": 0.8}
_FRESH_S_START = 7.0
_FRESH_S_FLOOR = 1.0
_FRESH_S_FACTOR = {"changed": 0.7, "fail": 0.3}
_FRESH_OUTCOMES = ("pass", "fail", "changed")


def _fresh_parse_date(value):
    """ISO date or datetime -> date; None when unparseable.
    Mirror of scripts/wiki_validate.py parse_date."""
    if value is None:
        return None
    if isinstance(value, _fresh_date) \
            and not isinstance(value, _fresh_datetime):
        return value
    v = str(value).strip()
    if not v:
        return None
    try:
        return _fresh_date.fromisoformat(v[:10])
    except ValueError:
        pass
    try:
        return _fresh_datetime.fromisoformat(
            v.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _fresh_fields(text):
    """The frontmatter scalars of a page, read with the same
    line rule scripts/wiki_validate.py's parse_frontmatter
    uses for scalars. Both freshness mirrors use THIS
    extractor for the keys they read — not their hosts'
    general parsers — so the two cannot disagree on them.
    List values are kept raw (freshness reads scalars only)."""
    if not text:
        return {}
    m = _FRESH_FM_RE.match(text)
    if not m:
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        km = _FRESH_FM_LINE_RE.match(line)
        if not km or km.group(1) in fields:
            continue
        val = km.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            fields[km.group(1)] = val
        else:
            fields[km.group(1)] = val.strip("\"'")
    return fields


def _fresh_read_jsonl(path):
    """Parse a JSONL register; [] when absent/unreadable."""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        lines = p.read_text(
            encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _fresh_fold_history(events):
    """Mirror of wiki_reverify.fold_history: fold one claim's
    verification events into (difficulty, stability)."""
    d, s = _FRESH_D_START, _FRESH_S_START
    for ev in sorted(events, key=lambda e: str(e.get("date") or "")):
        outcome = ev.get("outcome")
        if outcome not in _FRESH_OUTCOMES:
            continue
        d = min(_FRESH_D_MAX,
                max(_FRESH_D_MIN, d + _FRESH_D_STEP[outcome]))
        if outcome == "pass":
            s = s * (2.0 - 0.08 * d)
        else:
            s = max(_FRESH_S_FLOOR, s * _FRESH_S_FACTOR[outcome])
    return d, s


def _fresh_claim_due(fields, events, today):
    """{"due": iso, "status": "due" | "overdue"} when one
    claim's re-verification falls due today or earlier, else
    None. Mirror of wiki_reverify.claim_schedule's due
    computation (next check at anchor + round(stability)
    days; the anchor is the latest verification date, else
    the claim's as_of / updated / created)."""
    _d, s = _fresh_fold_history(events)
    dated = [e for e in events if _fresh_parse_date(e.get("date"))]
    if dated:
        anchor = max(_fresh_parse_date(e["date"]) for e in dated)
    else:
        anchor = None
        for key in ("as_of", "updated", "created"):
            if fields.get(key):
                anchor = _fresh_parse_date(fields[key])
                if anchor:
                    break
    if anchor is None:
        return None
    due = anchor + _fresh_timedelta(days=max(1, round(s)))
    if due < today:
        return {"due": due.isoformat(), "status": "overdue"}
    if due == today:
        return {"due": due.isoformat(), "status": "due"}
    return None


def freshness_due_map(root, today):
    """{repo-relative path: {"due", "status"}} for the claim
    pages on the re-verification due list today. The registry
    rule mirrors wiki_reverify.claim_pages: wiki pages
    carrying `claim:` frontmatter, excluding wiki/access/,
    the index and the log."""
    root = Path(root)
    wiki = root / "wiki"
    if not wiki.exists():
        return {}
    by_claim = {}
    for ev in _fresh_read_jsonl(root / FRESHNESS_HISTORY_REL):
        by_claim.setdefault(ev.get("claim"), []).append(ev)
    out = {}
    for p in sorted(wiki.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("wiki/access/") or rel in (
                "wiki/index.md", "wiki/log.md"):
            continue
        fields = _fresh_fields(
            p.read_text(encoding="utf-8", errors="ignore"))
        if not fields.get("claim"):
            continue
        got = _fresh_claim_due(fields, by_claim.get(rel, []), today)
        if got:
            out[rel] = got
    return out


def _fresh_page_key(page):
    """Mirror of tools/ask/standing.py page_key: the path
    under wiki/ without the .md suffix."""
    p = str(page or "").strip().replace("\\", "/")
    if p.endswith(".md"):
        p = p[:-3]
    if p.startswith("wiki/"):
        p = p[len("wiki/"):]
    return p


def _fresh_tier_for(severity):
    if severity < 0:
        return 0
    if severity == 0:
        return 1
    if severity <= 2:
        return 2
    return 3


def _fresh_fold_standings(treatment_rows, grade_rows):
    """Mirror of tools/ask/standing.py fold_standings: per-page
    standing from the treatment register (the strongest
    signal governs) and the source-grades register (latest
    grade per axis; the weaker axis governs the ordering
    severity — the axes are merged for ordering only, and
    the label names the governing signal)."""
    signals = {}

    def add(key, severity, order, text):
        if key:
            signals.setdefault(key, []).append(
                (severity, order, text))

    for row in treatment_rows or []:
        if row.get("kind") != "treatment":
            continue
        subject = row.get("subject") or {}
        grade = row.get("grade")
        if grade not in _FRESH_TREATMENT_SEVERITY:
            continue
        scope = "claim-scoped" if subject.get("claim") else "page"
        add(_fresh_page_key(subject.get("page")),
            _FRESH_TREATMENT_SEVERITY[grade], 0,
            "treatment %s (%s, %s)" % (grade, row.get("id"), scope))
    latest_grades = {}
    for row in grade_rows or []:
        if row.get("kind") != "grade":
            continue
        latest_grades[(row.get("source"), row.get("axis"))] = row
    for row in latest_grades.values():
        axis = row.get("axis")
        grade = row.get("grade")
        table = (_FRESH_INTEGRITY_SEVERITY if axis == "integrity"
                 else _FRESH_PRECISION_SEVERITY
                 if axis == "precision" else None)
        if table is None or grade not in table:
            continue
        add(_fresh_page_key(row.get("source")), table[grade],
            1 if axis == "integrity" else 2,
            "%s %s" % (axis, grade))
    standings = {}
    for key, entries in signals.items():
        severity = max(e[0] for e in entries)
        governing = min(
            (e for e in entries if e[0] == severity),
            key=lambda e: e[1])
        tier = _fresh_tier_for(severity)
        standings[key] = {
            "tier": tier,
            "severity": severity,
            "negative": tier == 3,
            "label": "%s — %s" % (_FRESH_TIER_NAMES[tier],
                                  governing[2]),
            "signals": [e[2] for e in sorted(
                entries, key=lambda e: (-e[0], e[1]))],
        }
    return standings


def freshness_standings(root):
    """The item-33 standings map folded from a repository
    root's registers; {} when the registers are absent."""
    root = Path(root)
    return _fresh_fold_standings(
        _fresh_read_jsonl(root / FRESHNESS_TREATMENT_REL),
        _fresh_read_jsonl(root / FRESHNESS_GRADES_REL))


def load_freshness_signals(root, today=None):
    """The annotation's inputs for one repository, loaded
    once: {"due": freshness_due_map(...), "standings":
    freshness_standings(...)}. Absent registers contribute
    nothing — a page simply carries no signal from that
    source, exactly as before this section existed."""
    today = today or _fresh_date.today()
    return {"due": freshness_due_map(root, today),
            "standings": freshness_standings(root)}


_FRESH_EMPTY_VALUES = ("", "null", "none", "~", "[]")


def _fresh_pointer(fields, name):
    """A frontmatter pointer's wikilink target (brackets, a
    leading wiki/ and a trailing .md stripped), or None when
    the field is absent or carries an empty value."""
    raw = fields.get(name)
    if raw is None \
            or str(raw).strip().lower() in _FRESH_EMPTY_VALUES:
        return None
    v = str(raw).strip().strip("[]").strip()
    if v.startswith("wiki/"):
        v = v[len("wiki/"):]
    if v.endswith(".md"):
        v = v[:-3]
    return v or None


def freshness_record(rel, text, today=None, signals=None):
    """The freshness record for one page:

        {"verified_until": "YYYY-MM-DD" | None,
         "overdue": bool,   # attestation passed, or the page
                            # is on the reverify due list
         "superseded": bool,
         "superseded_by": target | None,
         "standing": standing | None,   # the item-33 fold,
                            # present when the page has
                            # standing signals on record
         "line": str | None}   # the one-line rendering;
                            # None = no signal, render nothing

    `rel` is the repo-relative path (wiki/... or raw/...);
    `signals` comes from load_freshness_signals — when
    omitted, an empty-signals record is computed (frontmatter
    signals only)."""
    today = today or _fresh_date.today()
    if signals is None:
        signals = {"due": {}, "standings": {}}
    fields = _fresh_fields(text)
    parts = []
    vu = _fresh_parse_date(fields.get("verified_until"))
    verified_until = vu.isoformat() if vu else None
    overdue = False
    if vu is not None:
        if vu < today:
            overdue = True
            parts.append(
                f"⚠ verification overdue since {verified_until}")
        else:
            parts.append(f"verified until {verified_until}")
    due = (signals.get("due") or {}).get(rel)
    if due:
        overdue = True
        parts.append(f"⚠ re-verification due {due['due']}")
    status = str(fields.get("status") or "").strip().lower()
    target = _fresh_pointer(fields, "superseded_by")
    if target is None and status == "tombstoned":
        target = _fresh_pointer(fields, "replaced_by")
    superseded = bool(target) or status in (
        "superseded", "deprecated", "tombstoned")
    if target:
        parts.append(f"superseded by [[{target}]]")
    elif status == "superseded":
        parts.append("marked superseded")
    elif status == "deprecated":
        parts.append("marked deprecated")
    elif status == "tombstoned":
        parts.append("tombstoned")
    standing = (signals.get("standings") or {}).get(
        _fresh_page_key(rel))
    if standing is not None and standing.get("tier") != 1:
        parts.append(f"source standing: {standing['label']}")
    return {"verified_until": verified_until,
            "overdue": overdue,
            "superseded": superseded,
            "superseded_by": target,
            "standing": standing,
            "line": " · ".join(parts) if parts else None}


def freshness_line(record):
    """The one-line rendering of a freshness record, or None
    when the page carries no signal (render nothing)."""
    return record.get("line") if record else None


# --------------------------------------------------------------------------
# Frontmatter + page parsing (the one shared parser)
# --------------------------------------------------------------------------

FM_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "section"


def parse_markdown_file(path: Path):
    """Return (frontmatter dict, body str, raw text str)."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm = {}
    body = text
    m = FM_RE.match(text)
    if m:
        try:
            loaded = yaml.safe_load(m.group(1))
            if isinstance(loaded, dict):
                fm = loaded
        except yaml.YAMLError:
            fm = {}
        body = text[m.end():]
    return fm, body, text


def first_h1(body: str):
    for line in body.splitlines():
        m = re.match(r"^#\s+(.*)", line)
        if m:
            return m.group(1).strip()
    return None


def extract_lede(body: str, limit: int = 320):
    """First real paragraph as plain text (the card/briefing lede).

    Skips headings, lists, tables, code, callouts, images, and
    bolded '**Raw record:**'-style metadata lines."""
    para = []
    in_code = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not s:
            if para:
                break
            continue
        if s.startswith(("#", "-", "*", ">", "|", "![", "---", "===")):
            if para:
                break
            continue
        if re.match(r"^\d+\.\s", s):
            if para:
                break
            continue
        if s.startswith("**") and ("**" in s[2:]) and len(s) < 120 and s.endswith("**"):
            # a standalone bold label line, not prose
            if para:
                break
            continue
        para.append(s)
    if not para:
        return None
    text = " ".join(para)
    text = WIKILINK_RE.sub(lambda m: (m.group(3) or m.group(1)).strip(), text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut + "…"
    return text or None


def extract_wikilinks(body: str):
    """Body wikilinks outside fenced code and inline code spans:
    [(target, anchor, label)]. A `[[wikilink]]` quoted in backticks
    is an example of the syntax, not a link."""
    out = []
    in_code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        line = re.sub(r"`[^`\n]*`", "", line)
        for m in WIKILINK_RE.finditer(line):
            out.append((m.group(1).strip(), m.group(2), (m.group(3) or m.group(1)).strip()))
    return out


def page_headings(body: str):
    heads = []
    in_code = False
    seen = Counter()
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = HEADING_RE.match(line)
        if m:
            text = re.sub(r"\*\*|`", "", m.group(2)).strip()
            anchor = slugify(text)
            seen[anchor] += 1
            if seen[anchor] > 1:
                anchor = f"{anchor}-{seen[anchor]}"
            heads.append({"level": len(m.group(1)), "text": text, "anchor": anchor})
    return heads


# --------------------------------------------------------------------------
# Markdown -> HTML (deterministic, stdlib only)
# --------------------------------------------------------------------------

CODE_PH = "\x00CODE{}\x00"
WL_PH = "\x00WL{}\x00"


def _inline(text, wikilinks_out):
    """Inline formatting. Wikilinks become placeholders resolved by
    the caller (which owns the route map); returns HTML string.
    Inline code spans are lifted out first so that syntax quoted in
    backticks (e.g. `[[wikilink]]`) is never treated as a link."""
    text = html.escape(text, quote=False)

    code_spans = []

    def code_lift(m):
        code_spans.append(m.group(1))
        return f"\x00IC{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", code_lift, text)

    def wl_sub(m):
        target = html.unescape(m.group(1)).strip()
        anchor = m.group(2)
        label = html.unescape(m.group(3) or m.group(1)).strip()
        wikilinks_out.append((target, anchor, label))
        return WL_PH.format(len(wikilinks_out) - 1)

    text = WIKILINK_RE.sub(wl_sub, text)
    # markdown links (external)
    def md_link(m):
        label, url = m.group(1), m.group(2)
        if re.match(r"^(https?://|mailto:)", url):
            return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{label}</a>'
        return label

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", md_link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<em>\1</em>", text)

    def code_restore(m):
        return f"<code>{code_spans[int(m.group(1))]}</code>"

    text = re.sub(r"\x00IC(\d+)\x00", code_restore, text)
    return text


def render_markdown(body: str):
    """Render markdown body to HTML.

    Returns (html, wikilinks) where wikilinks is the ordered list of
    (target, anchor, label) matching the WL placeholders in the HTML.
    The caller replaces placeholders with resolved links/chips.
    """
    wikilinks = []
    code_blocks = []

    # Pass 1: lift fenced code blocks.
    lines = body.splitlines()
    lifted = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            code_blocks.append("\n".join(buf))
            lifted.append(CODE_PH.format(len(code_blocks) - 1))
        else:
            lifted.append(lines[i])
            i += 1

    out = []
    i = 0
    n = len(lifted)

    def is_table_row(s):
        return s.strip().startswith("|") and s.strip().endswith("|")

    def split_row(s):
        # Split on '|' except pipes inside [[wikilinks]]: a labelled
        # wikilink is one cell (live-query tables put one in the
        # title column). For rows without wikilinks this is exactly
        # the old strip-and-split behaviour.
        t = s.strip().strip("|")
        cells, buf, depth, i = [], [], 0, 0
        while i < len(t):
            if t.startswith("[[", i):
                depth += 1
                buf.append("[[")
                i += 2
                continue
            if t.startswith("]]", i) and depth:
                depth -= 1
                buf.append("]]")
                i += 2
                continue
            if t[i] == "|" and depth == 0:
                cells.append("".join(buf))
                buf = []
                i += 1
                continue
            buf.append(t[i])
            i += 1
        cells.append("".join(buf))
        return [c.strip() for c in cells]

    while i < n:
        line = lifted[i]
        s = line.strip()

        if re.fullmatch(r"\x00CODE\d+\x00", s):
            idx = int(s[5:-1])
            out.append(f"<pre><code>{html.escape(code_blocks[idx])}</code></pre>")
            i += 1
            continue
        if not s:
            i += 1
            continue
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            raw_text = re.sub(r"\*\*|`", "", m.group(2)).strip()
            anchor = slugify(raw_text)
            out.append(f'<h{level} id="{anchor}">{_inline(m.group(2), wikilinks)}</h{level}>')
            i += 1
            continue
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            out.append("<hr>")
            i += 1
            continue
        # Table: header row + separator row
        if is_table_row(line) and i + 1 < n and is_table_row(lifted[i + 1]) and re.search(r"\|[\s:|-]+\|", lifted[i + 1]):
            head = split_row(line)
            i += 2
            rows = []
            while i < n and is_table_row(lifted[i]):
                rows.append(split_row(lifted[i]))
                i += 1
            thead = "".join(f"<th>{_inline(c, wikilinks)}</th>" for c in head)
            tbody = ""
            for r in rows:
                cells = "".join(f"<td>{_inline(c, wikilinks)}</td>" for c in r)
                tbody += f"<tr>{cells}</tr>"
            out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
            continue
        # Blockquote / callout
        if s.startswith(">"):
            buf = []
            while i < n and lifted[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lifted[i]))
                i += 1
            first = buf[0].strip() if buf else ""
            cm = re.match(r"\[!(\w+)\]\s*(.*)", first)

            def join_paras(lines):
                paras, cur = [], []
                for b in lines:
                    if b.strip():
                        cur.append(b.strip())
                    elif cur:
                        paras.append(" ".join(cur))
                        cur = []
                if cur:
                    paras.append(" ".join(cur))
                return paras

            if cm:
                # The marker line carries kind + title only; the body is
                # every following line. (Joining first and dropping the
                # first paragraph would eat body text that shares a
                # paragraph with the marker line.)
                kind = cm.group(1).lower()
                title = cm.group(2) or kind.capitalize()
                inner = f'<p class="callout-title">{_inline(title, wikilinks)}</p>'
                inner += "".join(f"<p>{_inline(p, wikilinks)}</p>" for p in join_paras(buf[1:]))
                out.append(f'<div class="callout callout-{html.escape(kind)}">{inner}</div>')
            else:
                inner = "".join(f"<p>{_inline(p, wikilinks)}</p>" for p in join_paras(buf))
                out.append(f"<blockquote>{inner}</blockquote>")
            continue
        # Lists (flat + one nesting level by indent)
        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            items = []
            while i < n and re.match(r"^\s*([-*+]|\d+\.)\s+", lifted[i]):
                items.append(lifted[i])
                i += 1
            ordered = bool(re.match(r"^\s*\d+\.\s+", items[0]))
            tag = "ol" if ordered else "ul"
            lis = ""
            for it in items:
                content = re.sub(r"^\s*([-*+]|\d+\.)\s+", "", it)
                content = re.sub(r"^\[ \]\s+", "☐ ", content)
                content = re.sub(r"^\[[xX]\]\s+", "☑ ", content)
                lis += f"<li>{_inline(content, wikilinks)}</li>"
            out.append(f"<{tag}>{lis}</{tag}>")
            continue
        # Image on its own line -> a figure. The caption
        # convention: the line IMMEDIATELY after the image line,
        # when it is a single italic line (*caption* / _caption_)
        # or starts "Caption:", is the figure's caption — it is
        # consumed (not also rendered as a paragraph) and becomes
        # the <figcaption>. The alt text stays on the <img> as its
        # accessible name either way; without a caption line the
        # figure carries no <figcaption>.
        im = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", s)
        if im:
            caption = None
            if i + 1 < n:
                cm = re.match(
                    r"^\s*(?:\*(?P<i1>[^*]+)\*|_(?P<i2>[^_]+)_"
                    r"|Caption:\s*(?P<i3>.+))\s*$", lifted[i + 1])
                if cm:
                    caption = (cm.group("i1") or cm.group("i2")
                               or cm.group("i3") or "").strip() \
                        or None
            img = (f'<img alt="{html.escape(im.group(1), quote=True)}" '
                   f'src="{html.escape(im.group(2), quote=True)}" '
                   f'loading="lazy">')
            if caption:
                out.append(
                    f'<figure class="page-figure">{img}'
                    f'<figcaption>{_inline(caption, wikilinks)}'
                    f'</figcaption></figure>')
                i += 2
            else:
                out.append(f'<figure class="page-figure">{img}</figure>')
                i += 1
            continue
        # Paragraph: gather until blank or block start
        buf = [line]
        i += 1
        while i < n:
            nxt = lifted[i]
            ns = nxt.strip()
            if not ns or HEADING_RE.match(nxt) or ns.startswith(">") or is_table_row(nxt) \
               or re.match(r"^\s*([-*+]|\d+\.)\s+", nxt) or re.fullmatch(r"\x00CODE\d+\x00", ns) \
               or re.match(r"^\s*(-{3,}|\*{3,})\s*$", nxt):
                break
            buf.append(nxt)
            i += 1
        out.append(f"<p>{_inline(' '.join(x.strip() for x in buf), wikilinks)}</p>")

    return "\n".join(out), wikilinks


def resolve_wikilinks(html_text, wikilinks, route_by_stem):
    """Replace WL placeholders with route links or missing-page chips.
    route_by_stem: stem/target string -> page id or None."""

    def sub(m):
        idx = int(m.group(1))
        target, anchor, label = wikilinks[idx]
        pid = route_by_stem.get(target) or route_by_stem.get(Path(target).name)
        label_e = html.escape(label)
        if pid:
            href = f"#/read/{pid}"
            if anchor:
                href += f"#{slugify(anchor)}"
            return f'<a class="wl" href="{href}">{label_e}</a>'
        return f'<span class="wl-missing" title="No page exists for this link yet">{label_e}</span>'

    return re.sub(r"\x00WL(\d+)\x00", sub, html_text)


# --------------------------------------------------------------------------
# Live queries over markdown — ```wiki-query blocks (the build)
# --------------------------------------------------------------------------
# A wiki page may embed a fenced block whose info string is
# `wiki-query`. The block holds a tiny declarative query over page
# metadata; at page render the block is replaced by the computed
# list or table, so standing pages (current-state, indexes,
# decision lists) can carry self-updating lists instead of
# hand-maintained ones.
#
# HONEST SCOPE: the Lens is a static build, so "live" means
# evaluated at build time against the whole corpus and re-evaluated
# on every rebuild (the Lens rebuilds on every push). Between
# builds, a rendered list is a snapshot of the corpus at the build
# stamp — it does not change on its own.
#
# Pattern: Dataview-style live queries (blacksmithgu/obsidian-
# dataview, GPL — idea only, re-implemented here) and SilverBullet
# Objects/Space Lua (MIT), per the wave-1 survey shortlist.
#
# GRAMMAR — one directive per line, `key: value`; blank lines and
# lines starting with `#` are ignored; every directive at most once:
#
#   format: list | table      output shape (default: list)
#   fields: title, updated    comma list of shown fields (default:
#                             title). Allowed: title, type, section,
#                             status, created, updated, as_of, tags.
#                             In a list, `title` is the link and the
#                             other fields follow as "field value"
#                             pairs; in a table they are columns and
#                             the title cell links to the page.
#   type: <value>             keep pages whose frontmatter type
#                             equals the value (case-insensitive)
#   status: <value>           same, for the lifecycle status
#   section: <name>           keep pages in wiki/<name>/ (a page
#                             directly under wiki/ has section
#                             "wiki")
#   tags: a, b                keep pages carrying ALL these tags
#   links_to: <target>        keep pages whose body links to the
#                             target — a page stem (`collaborator-filings`)
#                             or a path (`wiki/filings/collaborator-filings`)
#   created_after / created_before / updated_after /
#   updated_before / as_of_after / as_of_before: YYYY-MM-DD
#                             inclusive date bounds on the
#                             frontmatter field; a page without the
#                             field never matches a bound on it
#   sort: <field> [asc|desc]  field as in `fields` (default:
#                             title asc). Pages missing the sort
#                             field sort last, by title.
#   limit: <positive integer> cap the rows (default: no cap)
#
# All filters combine with AND. A page never lists itself. A block
# that fails to parse renders a visible warning callout naming the
# problem — never a build failure, never silence. A query with no
# matches renders a one-line note saying so.


class WikiQueryError(Exception):
    """A wiki-query block is malformed; the message is written for
    the page author and is rendered visibly in place of the block."""


_WQ_FIELDS = ("title", "type", "section", "status", "created",
              "updated", "as_of", "tags")
_WQ_DATE_KEYS = ("created_after", "created_before", "updated_after",
                 "updated_before", "as_of_after", "as_of_before")
_WQ_KEYS = ({"format", "fields", "sort", "limit", "type", "status",
             "section", "tags", "links_to"} | set(_WQ_DATE_KEYS))
_WQ_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_WQ_FENCE_RE = re.compile(r"^```\s*wiki-query\s*$")


def norm_link_target(target) -> str:
    """Normalise a wikilink target for comparison: strip, drop a
    trailing .md. Case is preserved (page stems are lowercase by
    schema convention)."""
    t = str(target).strip()
    if t.endswith(".md"):
        t = t[:-3]
    return t


def parse_wiki_query(text: str) -> dict:
    """Parse one wiki-query block's text into a spec dict.
    Raises WikiQueryError with an author-readable message."""
    spec = {"format": "list", "fields": ["title"], "filters": {},
            "sort": ("title", "asc"), "limit": None}
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise WikiQueryError(f"line is not 'key: value': {line!r}")
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key not in _WQ_KEYS:
            raise WikiQueryError(
                f"unknown directive {key!r} — allowed: "
                + ", ".join(sorted(_WQ_KEYS)))
        if key in seen:
            raise WikiQueryError(f"directive {key!r} is given twice")
        seen.add(key)
        if not value:
            raise WikiQueryError(f"directive {key!r} has no value")
        if key == "format":
            if value.lower() not in ("list", "table"):
                raise WikiQueryError(
                    f"format must be 'list' or 'table', got {value!r}")
            spec["format"] = value.lower()
        elif key == "fields":
            fields = [f.strip().lower() for f in value.split(",") if f.strip()]
            bad = [f for f in fields if f not in _WQ_FIELDS]
            if bad:
                raise WikiQueryError(
                    f"unknown field(s) {', '.join(bad)} — allowed: "
                    + ", ".join(_WQ_FIELDS))
            if not fields:
                raise WikiQueryError("fields names no field")
            spec["fields"] = fields
        elif key == "sort":
            parts = value.split()
            field = parts[0].lower()
            if field not in _WQ_FIELDS:
                raise WikiQueryError(
                    f"cannot sort by {parts[0]!r} — allowed: "
                    + ", ".join(_WQ_FIELDS))
            direction = "asc"
            if len(parts) == 2:
                if parts[1].lower() not in ("asc", "desc"):
                    raise WikiQueryError(
                        f"sort direction must be 'asc' or 'desc', "
                        f"got {parts[1]!r}")
                direction = parts[1].lower()
            elif len(parts) > 2:
                raise WikiQueryError(f"sort takes '<field> [asc|desc]', got {value!r}")
            spec["sort"] = (field, direction)
        elif key == "limit":
            try:
                n = int(value)
            except ValueError:
                raise WikiQueryError(f"limit must be a whole number, got {value!r}")
            if n < 1:
                raise WikiQueryError(f"limit must be at least 1, got {n}")
            spec["limit"] = n
        elif key == "tags":
            tags = [t.strip() for t in value.split(",") if t.strip()]
            if not tags:
                raise WikiQueryError("tags names no tag")
            spec["filters"]["tags"] = tags
        elif key in _WQ_DATE_KEYS:
            if not _WQ_DATE_RE.fullmatch(value):
                raise WikiQueryError(
                    f"{key} needs a YYYY-MM-DD date, got {value!r}")
            try:
                datetime.date.fromisoformat(value)
            except ValueError:
                raise WikiQueryError(f"{key} is not a real date: {value!r}")
            spec["filters"][key] = value
        else:  # type, status, section, links_to
            spec["filters"][key] = value
    return spec


def run_wiki_query(spec: dict, pages, self_id=None):
    """Evaluate a parsed spec against the page index.

    `pages` is a list of dicts with keys: id, link (repo-relative
    path without .md), title, type, section, status, tags (list),
    created, updated, as_of (YYYY-MM-DD strings, '' when absent),
    links (set of normalised outgoing link targets, each target
    stored both as written and by bare stem). Returns the matching
    page dicts, sorted and limited per the spec."""
    f = spec["filters"]
    rows = []
    for pg in pages:
        if self_id is not None and pg.get("id") == self_id:
            continue
        if "type" in f and str(pg.get("type") or "").lower() != f["type"].lower():
            continue
        if "status" in f and str(pg.get("status") or "").lower() != f["status"].lower():
            continue
        if "section" in f and str(pg.get("section") or "") != f["section"]:
            continue
        if "tags" in f:
            have = {str(t).lower() for t in (pg.get("tags") or [])}
            if not all(t.lower() in have for t in f["tags"]):
                continue
        if "links_to" in f:
            want = norm_link_target(f["links_to"])
            have = pg.get("links") or set()
            if want not in have and want.rsplit("/", 1)[-1] not in have:
                continue
        keep = True
        for key in _WQ_DATE_KEYS:
            if key not in f:
                continue
            field, _, bound = key.rpartition("_")
            val = str(pg.get(field) or "")[:10]
            if not _WQ_DATE_RE.fullmatch(val):
                keep = False
                break
            if bound == "after" and val < f[key]:
                keep = False
                break
            if bound == "before" and val > f[key]:
                keep = False
                break
        if keep:
            rows.append(pg)
    field, direction = spec["sort"]

    def sort_value(pg):
        if field == "tags":
            v = ", ".join(str(t) for t in (pg.get("tags") or []))
        else:
            v = str(pg.get(field) or "")
        return v.lower()

    present = [pg for pg in rows if sort_value(pg)]
    missing = [pg for pg in rows if not sort_value(pg)]
    present.sort(key=lambda pg: (sort_value(pg),
                                 str(pg.get("title") or "").lower()),
                 reverse=(direction == "desc"))
    missing.sort(key=lambda pg: str(pg.get("title") or "").lower())
    rows = present + missing
    if spec["limit"] is not None:
        rows = rows[:spec["limit"]]
    return rows


def _wq_cell(text) -> str:
    # The table renderer splits cells on '|'; a title carrying one
    # would break the row, so it is flattened before rendering.
    return str(text).replace("|", "/")


def _wq_field_value(pg, field) -> str:
    if field == "tags":
        return ", ".join(str(t) for t in (pg.get("tags") or [])) or "—"
    return str(pg.get(field) or "") or "—"


def render_wiki_query(spec: dict, rows) -> str:
    """Render evaluated rows as markdown (a list or a table) for
    substitution into the page body before markdown rendering, so
    the links resolve through the normal wikilink path."""
    fields = spec["fields"]
    if not rows:
        return ("_Live query: no pages match "
                "(evaluated at Lens build time)._")
    if spec["format"] == "table":
        head = ["As of" if f == "as_of" else f.capitalize() for f in fields]
        lines = ["| " + " | ".join(head) + " |",
                 "|" + " --- |" * len(fields)]
        for pg in rows:
            cells = []
            for fld in fields:
                if fld == "title":
                    cells.append(f"[[{pg['link']}|{_wq_cell(pg.get('title') or pg['link'])}]]")
                else:
                    cells.append(_wq_cell(_wq_field_value(pg, fld)))
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)
    out = []
    for pg in rows:
        item = f"- [[{pg['link']}|{_wq_cell(pg.get('title') or pg['link'])}]]"
        extras = []
        for fld in fields:
            if fld == "title":
                continue
            v = _wq_field_value(pg, fld)
            if v != "—":
                extras.append(f"{fld} {v}")
        if extras:
            item += " — " + " · ".join(extras)
        out.append(item)
    return "\n".join(out)


def _wq_error_note(message: str) -> str:
    return ("> [!warning] Live query error\n"
            f"> {message} Fix the wiki-query block on this page; "
            "it renders again on the next Lens build.")


def expand_wiki_queries(body: str, pages, self_id=None) -> str:
    """Replace every ```wiki-query block in a page body with its
    evaluated markdown. A malformed block is replaced by a visible
    warning callout — expansion never raises and never drops the
    block silently. All other fenced blocks pass through untouched.
    """
    lines = body.splitlines()
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if _WQ_FENCE_RE.match(lines[i].strip()):
            buf = []
            i += 1
            closed = False
            while i < n:
                if lines[i].strip().startswith("```"):
                    closed = True
                    i += 1
                    break
                buf.append(lines[i])
                i += 1
            if not closed:
                out.append(_wq_error_note(
                    "The wiki-query fence is never closed."))
                out.extend(buf)
                continue
            try:
                spec = parse_wiki_query("\n".join(buf))
                rows = run_wiki_query(spec, pages, self_id=self_id)
                out.append(render_wiki_query(spec, rows))
            except WikiQueryError as e:
                out.append(_wq_error_note(str(e)))
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# --------------------------------------------------------------------------
# Graph analytics (the build): typed link edges, co-citation,
# label-propagation communities, link prediction, graph report data.
#
# Patterns, re-implemented natively (no code copied):
# - wiki-to-graph (PyPI; licence not stated -> idea only): a link's
#   type is inferred from the heading it sits under.
# - zby/commonplace (MIT): the typed-link vocabulary — a link can
#   ground, contradict, extend or exemplify, not merely "mention".
# - Obsidian Graph Analysis plugin (licence not seen -> algorithms
#   only): co-citation panels with the citing sentences, Adamic-Adar
#   / Common-Neighbours link prediction as a "missing link?" lane,
#   label-propagation community detection.
# - Graphify-Labs/graphify (Apache-2.0): edges tagged EXTRACTED vs
#   INFERRED (that tagging lives in build_lens.py) and a periodic
#   GRAPH_REPORT — god nodes, communities, surprising connections,
#   suggested questions (the report is assembled in build_lens.py
#   from the functions here).
#
# Everything in this section is deterministic: sorted iteration
# everywhere, fixed tie-breaks, no randomness, no wall clock. Same
# corpus in => same artefacts out.
# --------------------------------------------------------------------------

# The closed link-type vocabulary. A wikilink's type is inferred
# from the heading it sits under (SECTION_TYPE_RULES below); a link
# under no matching heading is a plain "mentions".
LINK_TYPES = ("grounds", "contradicts", "extends", "exemplifies",
              "supersedes", "mentions")

# Heading keyword rules, in PRIORITY order (first match wins).
# A keyword matches when it appears at a word start in the
# lowercased heading text (a stem match: "contradict" matches
# "Contradictions", "extend" matches "Extensions"), so keywords
# never fire inside unrelated words — "tension" does not match
# "Extensions", "sources" does not match "Resources", "ground"
# does not match "Background". The order is deliberate: a
# contradiction signal is the most specific claim a heading can
# make about its links, so it outranks the grounding vocabulary
# ("Contradictions in the evidence" -> contradicts); "extends"
# keywords are the weakest, most generic signal, so they sit last
# before the default. This table is the whole mapping — it is
# reproduced in tools/lens/README.md as well.
SECTION_TYPE_RULES = (
    ("contradicts", ("contradict", "conflict", "disagree", "dispute",
                     "contested", "tension")),
    ("supersedes", ("supersede", "replaces", "replaced by",
                    "deprecated", "obsolete", "retired")),
    ("grounds", ("evidence", "ground", "basis", "provenance",
                 "citation", "sources")),
    ("exemplifies", ("example", "exemplif", "illustrat", "case study",
                     "instance")),
    ("extends", ("extend", "extens", "elaborat", "builds on",
                 "built on", "expansion", "follow-up", "followup")),
)


def infer_link_type(heading):
    """The link type a heading implies: one of LINK_TYPES.
    `heading` is the raw heading text (or None before the first
    heading); matching is on the lowercased text, rules in priority
    order, default "mentions"."""
    if not heading:
        return "mentions"
    h = heading.lower()
    for ltype, keywords in SECTION_TYPE_RULES:
        if any(re.search(r"\b" + re.escape(k), h) for k in keywords):
            return ltype
    return "mentions"


def _clean_heading(text):
    return re.sub(r"\*\*|`", "", text).strip()


def extract_wikilinks_typed(body: str):
    """Wikilinks with their section context:
    [(target, anchor, label, heading, link_type)] in body order.
    `heading` is the text of the nearest preceding markdown heading
    (any level), cleaned the way page_headings cleans it, or None
    before the first heading. Same exclusions as extract_wikilinks:
    fenced code blocks and inline code spans never yield links."""
    out = []
    in_code = False
    heading = None
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        hm = HEADING_RE.match(line)
        if hm:
            heading = _clean_heading(hm.group(2))
            # Fall through: a heading line can itself carry a link
            # (extract_wikilinks counts it), typed by its own text.
        stripped = re.sub(r"`[^`\n]*`", "", line)
        for m in WIKILINK_RE.finditer(stripped):
            target = m.group(1).strip()
            out.append((target, m.group(2),
                        (m.group(3) or m.group(1)).strip(),
                        heading, infer_link_type(heading)))
    return out


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _sentence_display(raw):
    """Readable plain text of one raw sentence chunk: wikilinks
    become their labels, emphasis/code markers and list/quote
    markers are stripped, whitespace collapsed, length capped."""
    t = WIKILINK_RE.sub(lambda m: (m.group(3) or m.group(1)).strip(), raw)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = t.replace("**", "").replace("`", "")
    t = re.sub(r"^\s*(?:>\s*|[-*]\s+|\d+\.\s+)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > 240:
        t = t[:240].rsplit(" ", 1)[0] + "…"
    return t


def extract_link_sentences(body: str):
    """Sentences that carry wikilinks: [(sentence_text, [targets])]
    in body order. A "sentence" is a run of text on one line up to a
    ., ! or ? boundary (abbreviations split naively — this feeds an
    evidence display, not a parser). Heading lines and table rows
    are skipped: a heading is not a citing sentence, and a table
    row's cells are not one sentence. Fenced code and inline code
    spans never yield links (same rule as extract_wikilinks)."""
    out = []
    in_code = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s:
            continue
        if s.startswith("#") or s.startswith("|"):
            continue
        for chunk in _SENTENCE_SPLIT_RE.split(line):
            stripped = re.sub(r"`[^`\n]*`", "", chunk)
            targets = [m.group(1).strip()
                       for m in WIKILINK_RE.finditer(stripped)]
            if targets:
                out.append((_sentence_display(chunk), targets))
    return out


def cocitation_index(citers, sentence_pairs, max_others=8,
                     max_sentences=3):
    """Co-citation, the Graph Analysis way: two pages are co-cited
    when some third page links to both. `citers` maps a page id to
    the set of page ids linking TO it; `sentence_pairs` is an
    iterable of (citing_id, a, b, sentence_text) with a < b — the
    sentences in which the two links appear together, the strongest
    evidence, shown verbatim in the panel.

    Returns {page_id: [{other, shared_citers, citers, sentences:
    [{by, text}]}]} — symmetric by construction: per page, entries
    are ranked by shared-citer count, then sentence count, then
    id, capped at max_others, and then any entry whose reverse did
    not survive the other page's cap is dropped, so a listed pair
    is always listed from both sides. Sentences deduplicated,
    sorted by citing page then text, capped at max_sentences."""
    pair_sentences = {}
    for citing, a, b, text in sentence_pairs:
        if a == b:
            continue
        key = (a, b) if a < b else (b, a)
        pair_sentences.setdefault(key, set()).add((citing, text))
    per_page = {}
    pages = sorted(citers)
    for i, a in enumerate(pages):
        for b in pages[i + 1:]:
            shared = sorted(citers[a] & citers[b])
            if not shared:
                continue
            sents = sorted(pair_sentences.get((a, b), ()))
            entry = {"shared_citers": len(shared), "citers": shared,
                     "sentences": [{"by": by, "text": text}
                                   for by, text in sents[:max_sentences]]}
            per_page.setdefault(a, []).append({"other": b, **entry})
            per_page.setdefault(b, []).append({"other": a, **entry})
    for pid, entries in per_page.items():
        entries.sort(key=lambda e: (-e["shared_citers"],
                                    -len(e["sentences"]), e["other"]))
        per_page[pid] = entries[:max_others]
    # Mutual filter: an entry survives only if the reverse entry
    # survived the other page's cap too (one pass suffices — both
    # directions are judged against the same capped lists).
    listed = {pid: {e["other"] for e in entries}
              for pid, entries in per_page.items()}
    out = {}
    for pid in sorted(per_page):
        kept = [e for e in per_page[pid]
                if pid in listed.get(e["other"], ())]
        if kept:
            out[pid] = kept
    return out


def label_propagation(nodes, weights, max_passes=100):
    """Label-propagation community detection over the weighted
    undirected graph. `weights` maps (a, b) sorted tuples (a != b)
    to weights. Deterministic by construction: every node starts
    with its own id as its label; passes visit nodes in sorted
    order and update in place; a node adopts the label with the
    greatest total incident weight, keeping its current label on a
    tie when the current label is among the leaders, else taking
    the smallest leading label. Stops when a full pass changes
    nothing (or max_passes is hit). Communities are renumbered by
    smallest member id, the build's standing convention.
    Returns {node: community_id} covering every node exactly once."""
    nodes = sorted(nodes)
    adj = {n: {} for n in nodes}
    for (a, b), w in weights.items():
        if a == b or a not in adj or b not in adj:
            continue
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[b].get(a, 0.0) + w
    label = {n: n for n in nodes}
    for _ in range(max_passes):
        changed = False
        for n in nodes:
            if not adj[n]:
                continue
            sums = {}
            for nb, w in adj[n].items():
                sums[label[nb]] = sums.get(label[nb], 0.0) + w
            best = max(sums.values())
            leaders = [lab for lab, s in sums.items()
                       if s >= best - 1e-12]
            if label[n] in leaders:
                continue
            new = min(leaders)
            if new != label[n]:
                label[n] = new
                changed = True
        if not changed:
            break
    remap = {}
    for n in nodes:
        lab = label[n]
        if lab not in remap:
            remap[lab] = len(remap)
    return {n: remap[label[n]] for n in nodes}


def link_suggestions(neighbours, top_n=12):
    """Link prediction — the "missing link?" lane. For every pair
    of pages with NO direct link but at least one common neighbour,
    score Adamic-Adar: sum over common neighbours z of
    1 / ln(degree(z)) (rare neighbours are stronger evidence than
    hubs). `neighbours` maps page id -> set of page ids (the
    undirected direct-link adjacency). Ranked by score, then
    common-neighbour count, then the pair itself; capped at top_n.
    These are computed suggestions about the graph's shape — never
    claims, and nothing here writes to any page."""
    import math
    common = {}
    for z in sorted(neighbours):
        ns = sorted(neighbours[z])
        for i, a in enumerate(ns):
            for b in ns[i + 1:]:
                common.setdefault((a, b), []).append(z)
    out = []
    for (a, b), zs in common.items():
        if b in neighbours.get(a, ()):
            continue  # already linked — not a suggestion
        score = 0.0
        for z in zs:  # zs is in sorted order by construction
            deg = len(neighbours.get(z, ()))
            if deg > 1:
                score += 1.0 / math.log(deg)
        out.append({"a": a, "b": b, "adamic_adar": round(score, 4),
                    "common_neighbours": len(zs),
                    "shared_neighbours": zs[:8]})
    out.sort(key=lambda e: (-e["adamic_adar"], -e["common_neighbours"],
                            e["a"], e["b"]))
    return out[:top_n]


# --------------------------------------------------------------------------
# Staged gateway proposals — proposal diff view (wave-3 item C2)
# --------------------------------------------------------------------------
# The gateway stages proposed page changes as file pairs in
# staging/proposed/: a full proposed page text (<id>.md) beside a
# manifest (<id>.json) carrying proposer, scope, the content hash the
# promotion gate binds to (recorded here as the plan hash), staged
# date and the gateway's own check verdicts. The Lens renders the
# DRAFT proposals as per-hunk diffs against the current pages —
# display only: decisions are made in chat, never in the portal, so
# this artefact carries no control surface of any kind.
#
# Graceful by construction: a missing staging dir, a legacy staged
# file without a manifest (the pre-gateway Ask filings), a malformed
# manifest, and an already-decided proposal (state != draft) are all
# recorded in the artefact (skipped / excluded lists) instead of
# failing the build.

PROPOSALS_NOTE = "Decisions are made in chat — this view only displays."


def unified_diff_hunks(old_lines, new_lines, context=3):
    """Per-hunk unified diff of two line lists.

    Returns (hunks, n_added, n_removed); each hunk is
    {"header": "@@ -a,b +c,d @@ ...", "lines": [{"kind", "text"}]}
    with kind one of context / add / del / meta (the "\\ No newline"
    marker). An empty old_lines yields the single all-additions hunk
    difflib produces for a new file — new-page proposals need no
    special case.
    """
    hunks = []
    cur = None
    n_add = n_del = 0
    for line in difflib.unified_diff(old_lines, new_lines,
                                     lineterm="", n=context):
        if line.startswith("@@"):
            cur = {"header": line, "lines": []}
            hunks.append(cur)
        elif cur is None:
            continue  # the --- / +++ file header lines
        elif line.startswith("\\"):
            cur["lines"].append({"kind": "meta", "text": line[1:].strip()})
        else:
            kind = {" ": "context", "+": "add", "-": "del"}.get(line[:1],
                                                                "context")
            if kind == "add":
                n_add += 1
            elif kind == "del":
                n_del += 1
            cur["lines"].append({"kind": kind, "text": line[1:]})
    return hunks, n_add, n_del


def _eval_gate_verdict(manifest):
    """The eval-gate verdict recorded on a manifest, if any.

    the build's gate binds its verdict at promotion time; a staged
    manifest may carry it under an eval* key. Absent (the normal case
    today) -> None, and the view simply shows nothing.
    """
    for key in ("eval_gate", "evalgate", "eval_verdict"):
        val = manifest.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            for sub in ("verdict", "status", "result"):
                if val.get(sub):
                    return str(val[sub])
            return "recorded"
        return str(val)
    return None


def build_proposals_artefact(repo, id_by_path):
    """Read repo/staging/proposed/ and build the proposals artefact.

    id_by_path maps repo-relative page paths (e.g.
    "wiki/sources/expert-branches.md") to Lens page ids, for linking
    a proposal's target to its current page. Draft proposals are
    returned oldest first (the queue discipline of the gateway).
    """
    staging = Path(repo) / "staging" / "proposed"
    artefact = {"note": PROPOSALS_NOTE,
                "source_dir": "staging/proposed",
                "source_present": staging.is_dir(),
                "proposals": [], "skipped": [], "excluded": []}
    if not staging.is_dir():
        artefact["source_note"] = (
            "staging/proposed/ is absent from this build tree, so no "
            "staged proposals can be shown.")
        return artefact
    md_files = {p.stem: p for p in sorted(staging.glob("*.md"))}
    json_files = {p.stem: p for p in sorted(staging.glob("*.json"))}
    for stem in sorted(set(md_files) | set(json_files)):
        if stem not in json_files:
            artefact["skipped"].append({
                "file": md_files[stem].name,
                "reason": "no JSON manifest beside it — pre-gateway "
                          "staging shape (an Ask filing), not a gateway "
                          "change proposal"})
            continue
        if stem not in md_files:
            artefact["skipped"].append({
                "file": json_files[stem].name,
                "reason": "manifest without a proposal body file"})
            continue
        try:
            manifest = json.loads(json_files[stem].read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest is not a JSON object")
        except Exception as exc:
            artefact["skipped"].append({
                "file": json_files[stem].name,
                "reason": f"manifest unreadable ({exc})"})
            continue
        pid = str(manifest.get("proposal_id") or stem)
        state = str(manifest.get("state") or "")
        if state != "draft":
            artefact["excluded"].append({
                "proposal_id": pid, "state": state,
                "reason": f"state is {state!r}, not 'draft' — already "
                          "decided, not awaiting a ruling"})
            continue
        target = str(manifest.get("target_path") or "")
        if not target:
            artefact["skipped"].append({
                "file": json_files[stem].name,
                "reason": "manifest carries no target_path"})
            continue
        proposed_text = md_files[stem].read_text(encoding="utf-8")
        target_file = Path(repo) / target
        is_new = not target_file.is_file()
        current_text = ("" if is_new
                        else target_file.read_text(encoding="utf-8"))
        hunks, n_add, n_del = unified_diff_hunks(
            current_text.splitlines(), proposed_text.splitlines())
        san = manifest.get("sanitiser")
        dfn = manifest.get("defense")
        prof = manifest.get("profile_check")
        artefact["proposals"].append({
            "proposal_id": pid,
            "state": state,
            "submitted_by": manifest.get("submitted_by"),
            "submitted_at": manifest.get("submitted_at"),
            "session_id": manifest.get("session_id"),
            "task_ref": manifest.get("task_ref"),
            "target_path": target,
            "target_id": id_by_path.get(target),
            "is_new": is_new,
            "sha256": manifest.get("sha256"),
            "bytes": manifest.get("bytes"),
            "cites": manifest.get("cites") or [],
            "sanitiser_verdict": (san.get("verdict")
                                  if isinstance(san, dict) else None),
            "defense_verdict": (dfn.get("verdict")
                                if isinstance(dfn, dict) else None),
            "profile_check": (
                {"mode": prof.get("mode"), "profile": prof.get("profile"),
                 "violations": len(prof.get("violations") or [])}
                if isinstance(prof, dict) and prof else None),
            "eval_gate_verdict": _eval_gate_verdict(manifest),
            "diff": {"hunks": hunks, "added": n_add, "removed": n_del},
        })
    artefact["proposals"].sort(
        key=lambda p: (str(p.get("submitted_at") or ""), p["proposal_id"]))
    return artefact


# --------------------------------------------------------------------------
# Misc helpers
# --------------------------------------------------------------------------

def sha256_file(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def plain_text(body: str):
    """Rough plain text of a markdown body (frontmatter already
    stripped) for card/search display."""
    t = re.sub(r"```.*?```", " ", body, flags=re.S)
    t = WIKILINK_RE.sub(lambda m: (m.group(3) or m.group(1)), t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[#>*|`_]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


# ---------------------------------------------------------------------------
# Surfaces (consolidated-queue the surfaces build, 2026-10-20): facets (item 56),
# passage-level results (item 57), corpus-vocabulary suggestions +
# the relaxation ladder's data (item 59). Everything here is
# computed at build from the corpus itself; assets/app.js mirrors
# the counting/selection rules for the client, and
# scripts/tests/test_lens_surfaces.py pins both sides.
# ---------------------------------------------------------------------------

# The facet dimensions the corpus already carries, in rail order.
# key -> (label, frontmatter field). "tags" resolves through the
# Phase-6 tag registry (an altLabel counts under its prefLabel).
FACET_DIMS = [
    ("type", "Class"),
    ("work_type", "Work type"),
    ("stage", "Stage"),
    ("status", "Status"),
    ("tags", "Tags"),
]


def load_tag_registry(root):
    """The Phase-6 tag registry (evaluation/tag-registry.jsonl)
    reduced to what the surfaces need: the concept list, a
    label -> prefLabel resolution map (prefLabels and altLabels),
    and prefLabel -> broader prefLabel (first broader, or None).
    An absent/unreadable registry yields empty structures — tags
    then facet under their literal strings, exactly as written."""
    out = {"concepts": [], "resolve": {}, "broader": {}}
    path = Path(root) / "evaluation" / "tag-registry.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") != "concept":
            continue
        pref = row.get("prefLabel") or row.get("id")
        if not pref:
            continue
        alts = [str(a) for a in (row.get("altLabels") or [])]
        broader = row.get("broader") or []
        out["concepts"].append(
            {"pref": pref, "alt": alts,
             "broader": str(broader[0]) if broader else None,
             "status": row.get("status") or "preferred"})
        out["resolve"][pref] = pref
        for a in alts:
            out["resolve"][a] = pref
        out["broader"][pref] = str(broader[0]) if broader else None
    return out


def doc_facets(fm, registry=None):
    """One search doc's facet values: {dim: [value, ...]}.
    Class always has exactly one value (the frontmatter type,
    defaulting to "page"); work_type / stage / status contribute
    their value when present and nothing when absent (an absent
    dimension is not a value — the page simply is not narrowed
    by it); tags resolve through the registry to prefLabels."""
    fm = fm or {}
    resolve = (registry or {}).get("resolve") or {}
    out = {"type": [str(fm.get("type") or "page")]}
    for dim in ("work_type", "stage", "status"):
        v = str(fm.get(dim) or "").strip()
        out[dim] = [v] if v else []
    tags = []
    for t in fm.get("tags") or []:
        t = str(t)
        pref = resolve.get(t, t)
        if pref not in tags:
            tags.append(pref)
    out["tags"] = tags
    return out


def facet_schema(docs_facets):
    """The rail schema over the whole search corpus:
    [{key, label, values: [{value, count}]}] — corpus counts,
    values ordered by (-count, value). The client recomputes
    counts over the live result pool with facet_counts(); this
    schema is what exists, before any query."""
    schema = []
    for key, label in FACET_DIMS:
        counts = Counter()
        for facets in docs_facets:
            for v in facets.get(key) or []:
                counts[v] += 1
        schema.append({"key": key, "label": label, "values": [
            {"value": v, "count": c}
            for v, c in sorted(counts.items(),
                               key=lambda kv: (-kv[1], kv[0]))]})
    return schema


def facet_passes(facets, filters):
    """Does one doc pass the active filter stack? filters:
    {dim: set(values)} — within a dimension the values OR,
    across dimensions they AND (faceted navigation, not
    parametric search). Empty/absent dimensions do not filter."""
    for dim, wanted in (filters or {}).items():
        if not wanted:
            continue
        if not (set(facets.get(dim) or []) & set(wanted)):
            return False
    return True


def facet_counts(pool_facets, filters):
    """Query-preview counts (wave-7 find 1: the count IS the
    interface). For each dimension, the count beside a value is
    the number of pool docs that would remain if that value
    were selected GIVEN the other dimensions' filters — the
    dimension's own filter is excluded from its counts, so a
    searcher can always see the shape of the set before
    committing, and a value that would yield zero is known
    before it is clicked (the client greys it; it is never a
    dead end). Returns {dim: {value: count}} with every value
    present in the pool named, zeroes included."""
    filters = filters or {}
    out = {}
    for dim, _label in FACET_DIMS:
        others = {d: w for d, w in filters.items() if d != dim}
        counts = Counter()
        for facets in pool_facets:
            if facet_passes(facets, others):
                for v in facets.get(dim) or []:
                    counts[v] += 1
        for facets in pool_facets:
            for v in facets.get(dim) or []:
                counts.setdefault(v, 0)
        out[dim] = dict(counts)
    return out


def sectionize(body: str):
    """Split a page body into sections at its headings:
    [{heading, anchor, level, text}] — text is plain text.
    Anchors use slugify(heading) exactly as render_markdown
    emits them in the page HTML ids, so a deep link
    (#/read/<id>/<anchor>) lands on the rendered heading.
    Content before the first heading is the lede section
    (heading "", anchor "")."""
    sections = []
    cur = {"heading": "", "anchor": "", "level": 0, "lines": []}
    in_code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            cur["lines"].append(line)
            continue
        m = None if in_code else HEADING_RE.match(line)
        if m:
            sections.append(cur)
            text = re.sub(r"\*\*|`", "", m.group(2)).strip()
            level = len(m.group(1))
            # A level-1 heading is the page title: the reading
            # view strips it (the page itself is the link), so
            # its section carries no deep-link anchor.
            cur = {"heading": text,
                   "anchor": slugify(text) if level > 1 else "",
                   "level": level, "lines": []}
        else:
            cur["lines"].append(line)
    sections.append(cur)
    out = []
    for s in sections:
        # Paragraphs survive as units (pick_passage scores them):
        # plain-text each paragraph, rejoin on blank lines.
        paras = [plain_text(p)
                 for p in re.split(r"\n\s*\n", "\n".join(s["lines"]))]
        out.append({"heading": s["heading"], "anchor": s["anchor"],
                    "level": s["level"],
                    "text": "\n\n".join(p for p in paras if p)})
    return out


def pick_passage(sections, query_terms, width=420):
    """The matched passage for a search result (item 57): the
    paragraph — across the page's sections — holding the most
    distinct query terms (ties: most total occurrences, then
    earliest in the page), windowed around its first hit when
    long. Returns {text, heading, anchor} or None when no
    paragraph holds a query term. Mirrored in assets/app.js."""
    qset = set(query_terms)
    best = None
    best_key = None
    pos = 0
    for sec in sections:
        for para in re.split(r"\n\s*\n", sec["text"]):
            para = para.strip()
            if para:
                toks = tokenize(para)
                distinct = len(qset & set(toks))
                if distinct:
                    key = (distinct,
                           sum(1 for t in toks if t in qset), -pos)
                    if best_key is None or key > best_key:
                        best_key = key
                        best = (para, sec)
            pos += 1
    if best is None:
        return None
    para, sec = best
    if len(para) > width:
        lower = para.lower()
        mpos = -1
        for m in TOKEN_RE.finditer(lower):
            if m.group(0) in qset:
                mpos = m.start()
                break
        if mpos >= 0:
            start = max(0, mpos - width // 3)
            para = para[start:start + width]
            if start > 0:
                para = "…" + para
            if start + width < len(best[0]):
                para += "…"
    return {"text": para, "heading": sec["heading"],
            "anchor": sec["anchor"]}


def build_vocabulary(pages, registry=None):
    """The corpus's own phrase vocabulary for suggestions
    (item 59): page titles, page headings, and the tag
    registry's labels — nothing from any outside dictionary.
    pages: [{id, title, headings: [{text}]}]. Returns
    [{text, kind, id}] with kind page | heading | tag."""
    out = []
    seen = set()

    def add(text, kind, pid=None):
        text = str(text or "").strip()
        key = (text.lower(), kind, pid)
        if text and key not in seen:
            seen.add(key)
            row = {"text": text, "kind": kind}
            if pid:
                row["id"] = pid
            out.append(row)

    for pg in pages:
        add(pg.get("title"), "page", pg.get("id"))
        for h in pg.get("headings") or []:
            add(h.get("text"), "heading", pg.get("id"))
    for c in (registry or {}).get("concepts") or []:
        add(c.get("pref"), "tag")
        for a in c.get("alt") or []:
            add(a, "tag")
    return out


def _levenshtein(a, b, cap=2):
    """Edit distance, banded at cap+1 (anything above cap is
    reported as cap+1): the suggestion rule only ever asks
    "within 2 edits?"."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        row_min = cur[0]
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1))
            cur.append(v)
            row_min = min(row_min, v)
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[len(b)]


def suggest_terms(token, df, limit=3):
    """Did-you-mean candidates for one query token, drawn ONLY
    from the corpus's own term dictionary (the index's df keys —
    wave-7 find 4: candidates are terms that actually occur, so
    a suggestion is guaranteed to return results). Rule: edit
    distance <= 2, ranked by (distance, -df, term). Mirrored
    in assets/app.js."""
    token = token.lower()
    cands = []
    for term, d in (df or {}).items():
        if term == token or abs(len(term) - len(token)) > 2:
            continue
        dist = _levenshtein(token, term, cap=2)
        if dist <= 2:
            cands.append((dist, -d, term))
    cands.sort()
    return [t for _dist, _nd, t in cands[:limit]]


# ---------------------------------------------------------------------------
# Standing queries (consolidated-queue the surfaces build item 60; the saved
# failed searches of item 58). The register is a small file in the
# wiki — evaluation/standing-queries.jsonl, one JSON object per
# line:
#
#   {"id": "sq-0001", "name": <owner's name for the query>,
#    "query": <the search string>, "saved_from": "zero-results" |
#    "manual" | ..., "created_at": <ISO stamp>,
#    "last_looked_at": <build stamp> | null,
#    "last_looked_head": <short HEAD> | null,
#    "seen": {<page id>: <sha256 of the page's search text>},
#    "advances": <int>, "paused": <bool, optional>}
#
# Filed through scripts/wiki_standing_queries.py (the agent path —
# the Lens itself is read-only). Re-run at build time by
# standing_queries_report() below.
# ---------------------------------------------------------------------------

STANDING_QUERIES_REL = "evaluation/standing-queries.jsonl"
STANDING_QUERY_HIT_CAP = 10   # find 17: the delivery shape is capped
STANDING_QUERY_LINE_CAP = 5   # new pages named on one Briefing line


def standing_query_sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def load_standing_queries(root):
    """Read the standing-query register. A missing file means no
    watches have been filed yet — an empty list, not an error.
    Malformed lines are skipped, never fatal."""
    path = Path(root) / STANDING_QUERIES_REL
    records = []
    if not path.is_file():
        return records
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("id") and rec.get("query"):
            records.append(rec)
    return records


def write_standing_queries(root, records):
    """Write the register back (one JSON object per line, keys
    sorted — stable bytes for an unchanged register)."""
    path = Path(root) / STANDING_QUERIES_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True)
             for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""),
                    encoding="utf-8")


def run_standing_query(index, adj, doc_meta, query,
                       cap=STANDING_QUERY_HIT_CAP):
    """Re-run one saved query over the current corpus with the same
    hybrid ranking the Lens search artefacts carry. Hits are real
    (routed) pages only, best first, capped."""
    hits = []
    for _score, i, _detail in index.hybrid_rank(tokenize(query), adj):
        meta = doc_meta[i]
        if not meta.get("id"):
            continue
        hits.append({"id": meta["id"], "title": meta["title"],
                     "path": meta["path"]})
        if len(hits) >= cap:
            break
    return hits


def standing_queries_report(records, index, adj, doc_meta, texts,
                            generated_at, head_short):
    """Diff every register record against the current corpus.

    texts: the search texts, parallel to doc_meta (their sha256 is
    the change signal). Returns (lines, out_records, advanced_ids):
    lines feed the Briefing's standing-queries section;
    out_records is the register after any stamp advances;
    advanced_ids names the records this build advanced.

    Stamp discipline: a record's last-looked stamp advances ONLY
    in a build that reports the query — its first build (which sets
    the baseline: everything currently matching is the starting
    point, reported as a baseline, NOT as "new") or a build that
    found new/changed hits to report. The caller writes the
    advanced register back to the repo file, so an advance is a
    visible change in the working tree that the next commit
    carries — never a silent mutation. A build that finds nothing
    new leaves the register byte-identical. Paused records are
    reported as paused and never re-run or advanced."""
    text_by_id = {}
    for meta, text in zip(doc_meta, texts):
        if meta.get("id") and meta["id"] not in text_by_id:
            text_by_id[meta["id"]] = text
    lines, out_records, advanced = [], [], []
    for rec in records:
        r = dict(rec)
        line = {"id": r.get("id"), "name": r.get("name") or r.get("query"),
                "query": r.get("query"),
                "saved_from": r.get("saved_from"),
                "created_at": r.get("created_at"),
                "paused": bool(r.get("paused")),
                "baseline": False, "since": r.get("last_looked_at"),
                "total_hits": None, "new_count": 0, "new_pages": []}
        if r.get("paused"):
            lines.append(line)
            out_records.append(r)
            continue
        hits = run_standing_query(index, adj, doc_meta, r["query"])
        snapshot = {h["id"]: standing_query_sha(text_by_id.get(h["id"], ""))
                    for h in hits}
        line["total_hits"] = len(hits)
        if not r.get("last_looked_at"):
            # First build since filing: set the baseline. What
            # matches now is the starting point, not news.
            line["baseline"] = True
            r["seen"] = snapshot
            r["last_looked_at"] = generated_at
            r["last_looked_head"] = head_short
            r["advances"] = int(r.get("advances") or 0) + 1
            advanced.append(r.get("id"))
        else:
            seen = r.get("seen") or {}
            for h in hits:
                if h["id"] not in seen:
                    line["new_pages"].append({**h, "kind": "new"})
                elif seen[h["id"]] != snapshot[h["id"]]:
                    line["new_pages"].append({**h, "kind": "changed"})
            line["new_count"] = len(line["new_pages"])
            line["new_pages"] = line["new_pages"][:STANDING_QUERY_LINE_CAP]
            if line["new_count"]:
                r["seen"] = snapshot
                r["last_looked_at"] = generated_at
                r["last_looked_head"] = head_short
                r["advances"] = int(r.get("advances") or 0) + 1
                advanced.append(r.get("id"))
        lines.append(line)
        out_records.append(r)
    return lines, out_records, advanced


# ---------------------------------------------------------------------------
# Trails + source-adjacent evidence (consolidated-queue item 62,
# 2026-10-20). Two build-time artefacts over machinery the wiki
# already has:
#
# (a) TRAILS — reading paths as first-class Lens objects. A trail
# is an ordered path over the built typed-edge graph: pages, with
# the edge type named at each hop. Definitions live as data in
# tools/lens/trails.json (authored trails only — nothing here is
# auto-generated or presented as curated that a person did not
# author). build_trails_artefact validates every hop against the
# build's edge table (a wikilink/typed edge, or a citation edge
# to a page, whose `type` equals the step's `via`); a trail with
# a missing page or a hop the graph does not carry is DROPPED
# with its reasons on the artefact — never rendered as if it
# still walked. A trail is serialised in the URL (Matuschak's
# stacked-notes form, wave 7): #/trails/<id>?stack=<p1,p2,...>
# &at=<n> — the stack in the address IS the trail's state, so a
# link resumes the walk exactly where it was left.
#
# (b) SOURCE-ADJACENT EVIDENCE — the Ask door's claim <-> passage
# pairing (batch 2.1) extended to ordinary reading.
# load_citation_lockfile reads evaluation/citation-lockfile.json
# (wiki_cite_lock, lockfile v2) and returns, per wiki page, the
# claims whose markers are locked, each with the VERBATIM
# passage the lockfile's TextQuoteSelector recorded. The
# reading view pairs claim and passage from this data only: a
# claim whose passage the lockfile cannot produce appears
# NOWHERE in the pairing — never a paraphrase dressed as a
# quote.
# ---------------------------------------------------------------------------

TRAILS_REGISTER_REL = "tools/lens/trails.json"
TRAILS_NOTE = (
    "Authored reading paths over the typed-edge graph. Every hop "
    "names the edge type walked; the build validates each hop "
    "against the edge table, and a trail whose hop no longer "
    "exists is dropped, with its reason, rather than rendered.")


def load_trails_register(repo):
    """The authored trails register (tools/lens/trails.json) as
    data: {"trails": [...]} — an absent or unreadable register
    yields an empty list, never an error (the view degrades to
    its empty note)."""
    path = Path(repo) / TRAILS_REGISTER_REL
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    trails = data.get("trails") if isinstance(data, dict) else None
    return trails if isinstance(trails, list) else []


def trail_url(trail_id, page_ids, at=0):
    """Serialise a trail walk into its Lens URL (the canonical
    form app.js mirrors): the ordered page stack in the query,
    `at` the current step. A trail link is resumable and
    shareable inside the portal because the stack — not server
    state — carries the walk."""
    from urllib.parse import quote
    stack = ",".join(quote(str(p), safe="") for p in page_ids)
    return f"#/trails/{quote(str(trail_id), safe='')}?stack={stack}&at={int(at)}"


def parse_trail_url(url):
    """Parse a trail URL back into {trail_id, stack, at} — the
    inverse of trail_url. Tolerant of a missing query (stack
    empty, at 0) and of a full href (anything before the # is
    ignored). Returns None when the URL is not a trails URL."""
    from urllib.parse import unquote
    if not isinstance(url, str) or "#/trails/" not in url:
        return None
    rest = url.split("#/trails/", 1)[1]
    path, _, query = rest.partition("?")
    trail_id = unquote(path.split("/")[0])
    if not trail_id:
        return None
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[k] = v
    stack = [unquote(p) for p in params.get("stack", "").split(",")
             if p]
    try:
        at = int(params.get("at", 0))
    except (TypeError, ValueError):
        at = 0
    return {"trail_id": trail_id, "stack": stack,
            "at": max(0, at)}


def build_trails_artefact(repo, page_by_id, edges):
    """Validate the authored trails register against the built
    graph and enrich it for rendering. `page_by_id` maps Lens
    page ids to their page dicts (title/type/section); `edges`
    is the build's edge table. Returns {"note", "trails",
    "dropped"}: each rendered trail's steps carry the page's
    title/type/section beside the authored note and the `via`
    edge type; each dropped trail names every defect found."""
    walkable = {}
    for e in edges:
        if e.get("kind") in ("wikilink", "typed", "citation"):
            walkable.setdefault((e["src"], e["dst"]), set()).add(
                e.get("type"))
    artefact = {"note": TRAILS_NOTE, "register": TRAILS_REGISTER_REL,
                "trails": [], "dropped": []}
    for trail in load_trails_register(repo):
        if not isinstance(trail, dict):
            continue
        tid = str(trail.get("id") or "")
        steps_in = trail.get("steps") or []
        problems = []
        if not tid:
            problems.append("trail carries no id")
        if len(steps_in) < 2:
            problems.append("a trail needs at least two steps")
        steps = []
        prev = None
        for i, step in enumerate(steps_in):
            if not isinstance(step, dict):
                problems.append(f"step {i + 1} is not an object")
                continue
            pid = str(step.get("page") or "")
            pg = page_by_id.get(pid)
            if pg is None:
                problems.append(f"step {i + 1}: no page {pid!r} "
                                "in this build")
                prev = pid
                continue
            via = step.get("via")
            if i == 0:
                if via:
                    problems.append("the first step carries a `via` "
                                    "but walks no hop")
            else:
                types = walkable.get((prev, pid), set())
                if not via:
                    problems.append(f"step {i + 1} ({pid}): no `via` "
                                    "edge type named")
                elif via not in types:
                    problems.append(
                        f"step {i + 1} ({pid}): no {via!r} edge "
                        f"{prev} -> {pid} in the graph"
                        + (f" (carries: {sorted(types)})" if types
                           else " (no edge at all)"))
            steps.append({"page": pid, "title": pg["title"],
                          "type": pg["type"],
                          "section": pg.get("section"),
                          "via": via if i else None,
                          "note": step.get("note") or ""})
            prev = pid
        if problems:
            artefact["dropped"].append(
                {"id": tid or "(unnamed)", "title": trail.get("title"),
                 "reasons": problems})
            continue
        artefact["trails"].append({
            "id": tid, "title": trail.get("title") or tid,
            "summary": trail.get("summary") or "",
            "authored": trail.get("authored"),
            "steps": steps})
    return artefact


CITATION_LOCKFILE_REL = "evaluation/citation-lockfile.json"


def load_citation_lockfile(repo):
    """{repo-relative page path: [pairing, ...]} from the
    citation lockfile, pairings in page-line order. A pairing is
    {cite_id, claim, source, range, quote, page_line} where
    `quote` is the lockfile's TextQuoteSelector `exact` —
    VERBATIM, or the entry is omitted entirely: a citation whose
    passage the lockfile cannot produce pairs with nothing
    (item 62's rule — never a paraphrase dressed as a quote).
    An absent lockfile yields {}."""
    path = Path(repo) / CITATION_LOCKFILE_REL
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict = {}
    for entry in data.get("citations") or []:
        if not isinstance(entry, dict):
            continue
        selector = entry.get("selector") or {}
        quote_text = selector.get("exact")
        if not isinstance(quote_text, str) or not quote_text.strip():
            continue
        page = entry.get("page")
        if not page:
            continue
        out.setdefault(page, []).append({
            "cite_id": entry.get("id"),
            "claim": entry.get("claim"),
            "source": entry.get("source"),
            "range": entry.get("range"),
            "quote": quote_text,
            "page_line": entry.get("page_line"),
        })
    for pairings in out.values():
        pairings.sort(key=lambda pr: (pr["page_line"] is None,
                                      pr["page_line"] or 0))
    return out
