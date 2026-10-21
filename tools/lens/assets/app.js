/* WikiCitadel Lens — client.
   All data is precomputed at build (window.LENS_* artefacts).
   This file renders the seven reading modes + Search + Black Box
   from those artefacts. It writes nothing anywhere; actions arrive
   through the gateway. */
"use strict";

const PAGES = window.LENS_PAGES || {};
const GRAPH = window.LENS_GRAPH || { nodes: [], edges: [], communities: [], insights: { surprising: [], gaps: [] }, cocitations: {}, missing_links: [] };
const GRAPH_REPORT = window.LENS_GRAPH_REPORT || { god_nodes: [], communities: [], missing_links: [], typed_edges: { counts: {} }, suggested_questions: [] };
const MODES = window.LENS_MODES || {};
const SEARCH = window.LENS_SEARCH || { docs: [], texts: [], plain: [], sections: [], index: { n: 0, avgdl: 1, df: {}, doc_len: [], postings: {} }, index_entries: [], exact: { pages: [], raw: [] }, graph_adj: [], facets: [], severance: null, vocab: [], tags: { resolve: {}, broader: {}, concepts: [] } };
const TIMELINE = MODES.timeline || { events: [] };
const DECISIONS = MODES.decisions || { decisions: [], open_items: [], refinements: "" };
const CARDS = MODES.cards || { cards: [] };
const BRIEFING = MODES.briefing || { stats: {}, health: {}, lint: {}, lint_items: {}, deltas: [], waiting_on_you: [] };
const BLACKBOX = MODES.blackbox || { gateway_ledger: { status: "not-started", entries_checked: 0 }, watcher_ledger: { status: "not-started", entries_checked: 0 }, sessions: [], denials: [], unattributed: [], watcher_gaps: [], note: "" };
const HEAD_SHORT = (window.LENS_ROUTES && window.LENS_ROUTES.git_head_short) || "";
const GENERATED_AT = (window.LENS_ROUTES && window.LENS_ROUTES.generated_at) || "";
const KNOWLEDGE = window.LENS_KNOWLEDGE || { groups: [], record: { pages: [] }, files: [], total: 0 };
let QA_HISTORY = (window.LENS_QA && window.LENS_QA.entries) || [];
const PROPOSALS = window.LENS_PROPOSALS || { proposals: [], skipped: [], excluded: [], note: "" };
const TRAILS = window.LENS_TRAILS || { trails: [], dropped: [], note: "" };
const MEMORY = window.LENS_MEMORY || { claims: [], claim_history: {}, connections: [], ask_events: [] };
const FEEDBACK = window.LENS_FEEDBACK || { total: 0, pages: [], corrections: [] };
const PAGE_BY_PATH = {};
for (const _pid of Object.keys(PAGES)) PAGE_BY_PATH[PAGES[_pid].path] = _pid;
function pageLinkByPath(path, label) {
  const pid = PAGE_BY_PATH[path];
  return pid ? pageLink(pid, label) : `<span class="mono">${esc(label || path)}</span>`;
}
const STANDING = BRIEFING.standing_queries || [];
const STATE = MODES.state || { matrix: null, lifecycle: null, argdown: null };
const HONESTY = BRIEFING.honesty || null;

const canvas = document.getElementById("canvas");
const inspectorCtx = document.getElementById("inspector-context");
const treeEl = document.getElementById("tree");

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function pageLink(id, label) {
  const p = PAGES[id];
  return `<a href="#/read/${encodeURIComponent(id)}">${esc(label || (p ? p.title : id))}</a>`;
}
function chip(kind, label) { return `<span class="chip chip-${kind}">${esc(label)}</span>`; }
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

/* ---------------- Graph adjacency (shared) ---------------- */
const ADJ = {};
for (const e of GRAPH.edges) {
  (ADJ[e.a] = ADJ[e.a] || []).push({ other: e.b, ...e });
  (ADJ[e.b] = ADJ[e.b] || []).push({ other: e.a, ...e });
}
for (const k of Object.keys(ADJ)) ADJ[k].sort((x, y) => y.weight - x.weight);
function signalWords(e) {
  const parts = [];
  if (e.epistemic) parts.push(e.epistemic);
  parts.push(e.direct ? "linked directly" : "no direct link");
  if (e.types) {
    const ts = Object.entries(e.types).sort((x, y) => y[1] - x[1] || (x[0] < y[0] ? -1 : 1))
      .map(([t, c]) => (c > 1 ? `${t} ×${c}` : t)).join(", ");
    if (ts) parts.push(`typed: ${ts}`);
  }
  if (e.shared_sources) parts.push(`share ${e.shared_sources} source${e.shared_sources > 1 ? "s" : ""}`);
  if (e.common_neighbours) parts.push(`${e.common_neighbours} common neighbour${e.common_neighbours > 1 ? "s" : ""}`);
  if (e.type_affinity) parts.push("same type");
  return parts.join(" · ");
}

/* ---------------- Search (reference BM25 port) ---------------- */
const TOKEN_RE = /[a-z0-9]+/g;
/* CJK search-mode segmentation -- mirror of lenslib.py tokenize
 * (Marathon Round 4; Kagome search-mode pattern, MIT, our own
 * code): a CJK run indexes BOTH whole and as character bigrams,
 * so a page retrieves on the whole compound and on any partial
 * compound of 2+ characters. A lone CJK character indexes as
 * itself. Non-CJK behaviour is unchanged. */
const CJK_CLASS = "\u3400-\u4dbf\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3";
const TOKEN_SCAN_RE = new RegExp("[a-z0-9]+|[" + CJK_CLASS + "]+", "g");
const CJK_RE = new RegExp("^[" + CJK_CLASS + "]");
function cjkSegment(run) {
  if (run.length <= 1) return run ? [run] : [];
  const out = [run];
  for (let i = 0; i < run.length - 1; i++) out.push(run.slice(i, i + 2));
  return out;
}
function tokenize(text) {
  const out = [];
  for (const tok of (String(text).toLowerCase().match(TOKEN_SCAN_RE) || [])) {
    if (CJK_RE.test(tok)) out.push(...cjkSegment(tok));
    else if (tok.length >= 2) out.push(tok);
  }
  return out;
}
function firstTermOffset(lineLower, qset) {
  for (const m of lineLower.matchAll(/[a-z0-9]+/g)) { if (qset.has(m[0])) return m.index; }
  let best = -1;
  for (const t of qset) { const h = t ? lineLower.indexOf(t) : -1; if (h >= 0 && (best < 0 || h < best)) best = h; }
  return best;
}
/* ---------------- Retrieval severance (fold-in 1, the surfaces build) -------
 * The browser ranker gains the severance behaviour the Python
 * search already has (consolidated-queue item 20, stage 5): the
 * severance list ships in the build artefacts (SEARCH.severance,
 * the same evaluation/retrieval-severance.json the Python index
 * is built with) and both ranked lanes exclude — never merely
 * demote — a result whose page carries a page-level entry, or
 * whose text carries a severed claim the query itself hunts.
 * The helpers mirror lenslib's _sev_* rules exactly (cue phrases
 * as contiguous token subsequences; distinctive terms at 4/5
 * presence for a TEXT match, at >= half (min 3) for a QUERY
 * match), and the exclusion is recorded on LAST_SEVERANCE —
 * reported, never silent. */
let LAST_SEVERANCE = { applied: false, excluded: [] };
function lensLastSeverance() { return LAST_SEVERANCE; }
const _sevTokCache = new Map();
function _sevDocTokens(di) {
  if (!_sevTokCache.has(di)) _sevTokCache.set(di, tokenize(SEARCH.texts[di] || ""));
  return _sevTokCache.get(di);
}
function _sevPhraseHit(tokens, phrase) {
  const n = phrase.length;
  if (!n || n > tokens.length) return false;
  outer: for (let i = 0; i <= tokens.length - n; i++) {
    for (let j = 0; j < n; j++) if (tokens[i + j] !== phrase[j]) continue outer;
    return true;
  }
  return false;
}
function _sevTermsPresent(tokens, terms) {
  const have = new Set(tokens);
  return terms.filter(t => have.has(t)).length;
}
function _sevTextMatches(tokens, entry) {
  const cues = entry.cues || {};
  for (const phrase of (cues.phrases || [])) if (_sevPhraseHit(tokens, phrase)) return true;
  const terms = cues.terms || [];
  return terms.length > 0 && _sevTermsPresent(tokens, terms) * 5 >= terms.length * 4;
}
function _sevQueryMatches(queryTerms, entry) {
  const cues = entry.cues || {};
  for (const phrase of (cues.phrases || [])) if (_sevPhraseHit(queryTerms, phrase)) return true;
  const terms = cues.terms || [];
  if (!terms.length) return false;
  const need = Math.max(3, Math.floor((terms.length + 1) / 2));
  return _sevTermsPresent(queryTerms, terms) >= need;
}
function applySeverance(ranked, queryTerms) {
  const sev = SEARCH.severance;
  LAST_SEVERANCE = { applied: !!sev, excluded: [] };
  if (!sev || !Array.isArray(sev.entries)) return ranked;
  const pageEntries = sev.entries.filter(e => e.kind === "page");
  const claimEntries = sev.entries.filter(e => e.kind !== "page");
  const qMatched = claimEntries.filter(e => _sevQueryMatches(queryTerms, e));
  const kept = [];
  for (const r of ranked) {
    let hitIds = pageEntries.filter(e => e.page === r.path).map(e => e.id);
    if (!hitIds.length && qMatched.length) {
      const toks = _sevDocTokens(r.di);
      hitIds = qMatched.filter(e => _sevTextMatches(toks, e)).map(e => e.id);
    }
    if (hitIds.length) LAST_SEVERANCE.excluded.push({ path: r.path, entries: hitIds });
    else kept.push(r);
  }
  return kept;
}
function bm25Raw(queryTerms) {
  const idx = SEARCH.index, K1 = 1.5, B = 0.75;
  const scores = new Map();
  const idf = {};
  for (const t of new Set(queryTerms)) {
    const d = idx.df[t] || 0;
    idf[t] = Math.log(1 + (idx.n - d + 0.5) / (d + 0.5));
  }
  for (const t of queryTerms) {
    for (const [di, f] of (idx.postings[t] || [])) {
      const dl = idx.doc_len[di];
      const denom = f + K1 * (1 - B + B * dl / idx.avgdl);
      scores.set(di, (scores.get(di) || 0) + idf[t] * (f * (K1 + 1)) / denom);
    }
  }
  return [...scores.entries()]
    .filter(([, s]) => s > 0)
    .map(([di, s]) => ({ score: s, di, path: SEARCH.docs[di].path }))
    .sort((a, b) => (b.score - a.score) || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
}
function bm25Rank(queryTerms) { return applySeverance(bm25Raw(queryTerms), queryTerms); }
/* Hybrid ranking: BM25 + personalized PageRank over the wikilink
 * graph — a mirror of scripts/wiki_search.py hybrid_rank() (same
 * constants, same combination). The build parity-checks the Python
 * mirror (lenslib) against the reference, so this lane cannot
 * silently diverge from the canonical ranker. */
const HYBRID_ALPHA = 0.6, PPR_DAMPING = 0.85, PPR_SEEDS = 10, PPR_GRAPH_FLOOR = 0.01;
function personalizedPagerank(adj, seeds) {
  const n = adj.length;
  if (!n || !seeds.size) return new Map();
  let total = 0; for (const v of seeds.values()) total += v;
  total = total || 1;
  const teleport = new Map(), rank = new Map();
  for (let i = 0; i < n; i++) { const t = (seeds.get(i) || 0) / total; teleport.set(i, t); rank.set(i, t); }
  for (let iter = 0; iter < 200; iter++) {
    let dangling = 0;
    for (let i = 0; i < n; i++) if (!(adj[i] || []).length) dangling += rank.get(i);
    const next = new Map();
    let delta = 0;
    for (let i = 0; i < n; i++) {
      let incoming = 0;
      for (const j of (adj[i] || [])) { const deg = (adj[j] || []).length; if (deg) incoming += rank.get(j) / deg; }
      const v = (1 - PPR_DAMPING) * teleport.get(i) + PPR_DAMPING * (incoming + dangling * teleport.get(i));
      next.set(i, v); delta += Math.abs(v - rank.get(i));
    }
    for (const [i, v] of next) rank.set(i, v);
    if (delta < 1e-7) break;
  }
  return rank;
}
/* TITLE-BOOST-BEGIN — exact-title/stem-match boost (Marathon R3
 * TB7), a mirror of scripts/wiki_search.py title_boost_value:
 * a query that exactly matches a page title or file stem gets
 * +10; a stemmed match gets +5. Decisive by construction (the
 * pre-boost hybrid score is bounded well under 5). The block
 * between TITLE-BOOST-BEGIN/END is pure functions only, so the
 * Lens tests can extract and execute it under node. */
const TITLE_EXACT_BOOST = 10.0, TITLE_STEM_BOOST = 5.0;
function stemTokenJs(tok) {
  let t = String(tok).toLowerCase();
  if (t.length > 4 && t.endsWith("ies")) t = t.slice(0, -3) + "y";
  else if (t.length > 5 && t.endsWith("ing")) t = t.slice(0, -3);
  else if (t.length > 4 && t.endsWith("ed")) t = t.slice(0, -2);
  else if (t.length > 3 && t.endsWith("es") && !t.endsWith("ss")) t = t.slice(0, -2);
  else if (t.length > 3 && t.endsWith("s") && !t.endsWith("ss")) t = t.slice(0, -1);
  if (t.length > 3 && t[t.length - 1] === t[t.length - 2] && !"aeiou".includes(t[t.length - 1])) t = t.slice(0, -1);
  return t;
}
function titleBoostJs(queryTerms, title, stem) {
  const q = (queryTerms || []).map(t => String(t).toLowerCase());
  if (!q.length) return { boost: 0, kind: null };
  const titleToks = tokenize(title || "");
  const stemToks = tokenize(String(stem || "").replace(/-/g, " "));
  const seqEq = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
  if (seqEq(q, titleToks) || seqEq(q, stemToks)) return { boost: TITLE_EXACT_BOOST, kind: "exact" };
  const qStems = new Set(q.map(stemTokenJs));
  for (const toks of [titleToks, stemToks]) {
    if (!toks.length) continue;
    const stemSet = new Set(toks.map(stemTokenJs));
    if (stemSet.size === qStems.size && [...stemSet].every(t => qStems.has(t))) return { boost: TITLE_STEM_BOOST, kind: "stem" };
  }
  return { boost: 0, kind: null };
}
/* TITLE-BOOST-END */
function hybridRank(queryTerms) {
  // The base is the UNsevered BM25 list (the Python hybrid ranks
  // first and severs last, at its stage 5 — mirrored below).
  const base = bm25Raw(queryTerms);
  if (!base.length) return [];
  const adj = SEARCH.graph_adj || [];
  const bm = new Map(base.map(r => [r.di, r.score]));
  const seeds = new Map(base.slice(0, PPR_SEEDS).map(r => [r.di, r.score]));
  const ppr = personalizedPagerank(adj, seeds);
  let maxB = 0, maxP = 0;
  for (const v of bm.values()) if (v > maxB) maxB = v;
  for (const v of ppr.values()) if (v > maxP) maxP = v;
  const out = [];
  for (let di = 0; di < SEARCH.docs.length; di++) {
    const b = bm.get(di) || 0;
    let pr = ppr.get(di) || 0;
    // Structural pages (the catalog, the ledger) walk but do not
    // receive the PPR component — mirror of wiki_search.py.
    if (SEARCH.docs[di].path === "wiki/index.md" || SEARCH.docs[di].path === "wiki/log.md") pr = 0;
    if (b <= 0 && !(maxP > 0 && pr >= PPR_GRAPH_FLOOR * maxP)) continue;
    const tb = titleBoostJs(queryTerms, SEARCH.docs[di].title,
      (SEARCH.docs[di].path || "").split("/").pop().replace(/\.md$/, ""));
    out.push({ score: (maxB ? b / maxB : 0) + HYBRID_ALPHA * (maxP ? pr / maxP : 0) + tb.boost,
               di, path: SEARCH.docs[di].path, bm25: b, ppr: pr,
               title_boost: tb.boost, title_match: tb.kind,
               via: b > 0 && pr > 0 ? "both" : (b > 0 ? "bm25" : "graph") });
  }
  const ranked = out.sort((a, b2) => (b2.score - a.score) || (a.path < b2.path ? -1 : a.path > b2.path ? 1 : 0));
  return applySeverance(ranked, queryTerms);
}
function makeSnippet(text, queryTerms, width) {
  width = width || 170;
  const qset = new Set(queryTerms);
  let best = null, bestKey = null;
  const lines = String(text).split("\n");
  lines.forEach((raw, pos) => {
    const line = raw.trim();
    if (!line) return;
    const toks = tokenize(line);
    const distinct = new Set(toks.filter(t => qset.has(t))).size;
    if (!distinct) return;
    const key = [distinct, toks.filter(t => qset.has(t)).length, -pos];
    if (!bestKey || key[0] > bestKey[0] || (key[0] === bestKey[0] && (key[1] > bestKey[1] || (key[1] === bestKey[1] && key[2] > bestKey[2])))) {
      bestKey = key; best = line;
    }
  });
  if (best === null) return "(match in token stream; no single line holds a query term)";
  if (best.length <= width) return best;
  const lower = best.toLowerCase();
  let mpos = -1;
  mpos = firstTermOffset(lower, qset);
  if (mpos < 0) return best.slice(0, width) + "…";
  const start = Math.max(0, mpos - Math.floor(width / 3));
  let out = best.slice(start, start + width);
  if (start > 0) out = "…" + out;
  if (start + width < best.length) out += "…";
  return out;
}
function stripFrontmatter(text) {
  if (text.startsWith("---")) {
    const end = text.indexOf("\n---", 3);
    if (end > 0) return text.slice(end + 4);
  }
  return text;
}

/* ---------------- Surfaces (the surfaces build, items 56/57/59) --------------
 * Facets, passage-level results, corpus-vocabulary suggestions and
 * the relaxation ladder. All data is precomputed at build
 * (lenslib: doc facets, facet schema, sections, vocabulary, tag
 * registry maps, freshness lines); the rules below mirror
 * lenslib's facet_counts / pick_passage / suggest_terms.
 * Facet state is per-query and in-memory only. */
const FACET_TOP = 5;
let facetFilters = {};      // dim -> Set of selected values
let facetOrder = [];        // dims in the order they were narrowed
let facetQuery = "";
let rerenderSearch = null;  // set by renderSearch / runAsk
function facetStateFor(q) {
  if (facetQuery !== q) { facetQuery = q; facetFilters = {}; facetOrder = []; }
}
function docFacetsOf(di) { return (SEARCH.docs[di] && SEARCH.docs[di].facets) || {}; }
function facetPassesJs(facets, filters) {
  for (const dim of Object.keys(filters || {})) {
    const wanted = filters[dim];
    if (!wanted || !wanted.size) continue;
    const have = facets[dim] || [];
    if (!have.some(v => wanted.has(v))) return false;
  }
  return true;
}
/* Query-preview counts with self-exclusion (lenslib facet_counts):
 * a dimension's counts are computed under the OTHER dimensions'
 * filters, so the number beside a value is what selecting it
 * would leave — and a zero is shown greyed, never as a dead end
 * the searcher discovers by clicking. */
function facetCountsJs(poolDis, filters) {
  const out = {};
  for (const dim of (SEARCH.facets || []).map(f => f.key)) {
    const others = {};
    for (const d of Object.keys(filters || {})) if (d !== dim) others[d] = filters[d];
    const counts = new Map();
    for (const di of poolDis) {
      const facets = docFacetsOf(di);
      if (facetPassesJs(facets, others)) for (const v of facets[dim] || []) counts.set(v, (counts.get(v) || 0) + 1);
    }
    for (const di of poolDis) for (const v of docFacetsOf(di)[dim] || []) if (!counts.has(v)) counts.set(v, 0);
    out[dim] = counts;
  }
  return out;
}
function toggleFacet(dim, value) {
  const set = facetFilters[dim] || (facetFilters[dim] = new Set());
  if (set.has(value)) set.delete(value); else set.add(value);
  if (!set.size) delete facetFilters[dim];
  facetOrder = facetOrder.filter(d => d !== dim);
  if (facetFilters[dim]) facetOrder.push(dim);
  if (rerenderSearch) rerenderSearch();
}
function clearFacets() {
  facetFilters = {}; facetOrder = [];
  if (rerenderSearch) rerenderSearch();
}
/* The matched passage for one result (item 57) — lenslib
 * pick_passage mirrored: best paragraph by distinct query terms,
 * then total hits, then earliest; windowed around the first hit.
 * The section's anchor is the id render_markdown emitted for
 * that heading, so the deep link lands on it. */
function pickPassageJs(di, queryTerms) {
  const sections = (SEARCH.sections || [])[di] || [];
  const qset = new Set(queryTerms);
  let best = null, bestKey = null, pos = 0;
  for (const sec of sections) {
    for (const para of String(sec.text || "").split(/\n\s*\n/)) {
      const p = para.trim();
      if (p) {
        const toks = tokenize(p);
        const distinct = new Set(toks.filter(t => qset.has(t))).size;
        if (distinct) {
          const key = [distinct, toks.filter(t => qset.has(t)).length, -pos];
          if (!bestKey || key[0] > bestKey[0] || (key[0] === bestKey[0] && (key[1] > bestKey[1] || (key[1] === bestKey[1] && key[2] > bestKey[2])))) {
            bestKey = key; best = { text: p, heading: sec.heading, anchor: sec.anchor };
          }
        }
      }
      pos++;
    }
  }
  if (!best) return null;
  const width = 420;
  if (best.text.length > width) {
    const orig = best.text;
    const lower = orig.toLowerCase();
    let mpos = -1;
    mpos = firstTermOffset(lower, qset);
    if (mpos >= 0) {
      const start = Math.max(0, mpos - Math.floor(width / 3));
      let out = orig.slice(start, start + width);
      if (start > 0) out = "…" + out;
      if (start + width < orig.length) out += "…";
      best = { ...best, text: out };
    }
  }
  return best;
}
/* Did-you-mean from the corpus's OWN vocabulary (item 59;
 * lenslib suggest_terms mirrored): candidates come only from
 * the index's term dictionary — a term that actually occurs,
 * so a suggestion is guaranteed to return results — ranked by
 * edit distance <= 2, then document frequency. */
function _levCap(a, b, cap) {
  if (Math.abs(a.length - b.length) > cap) return cap + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let rowMin = cur[0];
    for (let j = 1; j <= b.length; j++) {
      const v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      cur.push(v); rowMin = Math.min(rowMin, v);
    }
    if (rowMin > cap) return cap + 1;
    prev = cur;
  }
  return prev[b.length];
}
function suggestTermsJs(token, limit) {
  limit = limit || 3;
  const df = SEARCH.index.df || {};
  const cands = [];
  for (const term of Object.keys(df)) {
    if (term === token || Math.abs(term.length - token.length) > 2) continue;
    const dist = _levCap(token, term, 2);
    if (dist <= 2) cands.push([dist, -df[term], term]);
  }
  cands.sort((x, y) => (x[0] - y[0]) || (x[1] - y[1]) || (x[2] < y[2] ? -1 : 1));
  return cands.slice(0, limit).map(c => c[2]);
}
function suggestionsFor(q, terms) {
  /* Term corrections for tokens absent from the index
   * (suggest_mode "missing": a token the corpus HAS gets no
   * correction), plus phrase suggestions from the shipped
   * vocabulary — titles, headings, tag labels. */
  const out = { corrections: [], phrases: [] };
  const df = SEARCH.index.df || {};
  for (const t of terms) {
    if (!(df[t] > 0)) {
      const s = suggestTermsJs(t, 1)[0];
      if (s) out.corrections.push({ from: t, to: s });
    }
  }
  const ql = q.trim().toLowerCase();
  if (ql.length >= 4) {
    for (const v of SEARCH.vocab || []) {
      const vl = v.text.toLowerCase();
      if (vl === ql || vl.length < 4) continue;
      const vtoks = tokenize(v.text);
      if (vtoks.length > 1 && terms.length > 1 &&
          terms.every(t => vtoks.some(vt => _levCap(t, vt, 1) <= 1)) &&
          terms.some(t => !vtoks.includes(t))) {
        out.phrases.push(v);
      } else if (vtoks.length === 1 && terms.length === 1 && _levCap(ql, vl, 2) <= 2 && vl !== terms[0]) {
        out.phrases.push(v);
      }
      if (out.phrases.length >= 3) break;
    }
  }
  return out;
}
/* Facet-tagged queries (item 59): a query token that IS a facet
 * value in the corpus's own vocabulary — a tag, a class, a work
 * type, a stage, a status — is offered as a one-click filter. */
function queryFacetTags(terms) {
  const out = [];
  const seen = new Set();
  for (const t of terms) {
    for (const dim of SEARCH.facets || []) {
      for (const v of dim.values) {
        if (v.value.toLowerCase() === t && !seen.has(dim.key + "::" + v.value)) {
          seen.add(dim.key + "::" + v.value);
          out.push({ dim: dim.key, dimLabel: dim.label, value: v.value });
        }
      }
    }
  }
  return out;
}
/* The relaxation ladder (item 59): when the exact search finds
 * nothing in the ranked lanes, widenings are tried IN ORDER and
 * the rung that produced the results is NAMED in the UI — a
 * search that silently widened would be a small lie.
 *   exact → variants (altLabel/title variants + corpus-term
 *   corrections) → facet drop (narrowing filters, last first)
 *   → broader tag (the registry's broader concept added)
 *   → loosest (substring full-text). */
function _rankedEmpty(L) { return !L.bm25.length && !L.hybrid.length; }
function searchWithLadder(q) {
  const base = searchLanes(q);
  if (!_rankedEmpty(base)) return { lanes: base, rung: null, note: "" };
  const terms = tokenize(q);
  // Rung 1 — variants.
  const resolve = (SEARCH.tags && SEARCH.tags.resolve) || {};
  const vTerms = [], vNotes = [];
  for (const t of terms) {
    const pref = resolve[t];
    if (pref && pref !== t) { vTerms.push(...tokenize(pref)); vNotes.push(`${t} → ${pref} (tag variant)`); }
    else if (!((SEARCH.index.df || {})[t] > 0)) {
      const s = suggestTermsJs(t, 1)[0];
      if (s) { vTerms.push(s); vNotes.push(`${t} → ${s} (corpus term)`); }
      else vTerms.push(t);
    } else vTerms.push(t);
  }
  if (vNotes.length) {
    const L2 = _searchLanes(vTerms.join(" "), facetFilters);
    if (!_rankedEmpty(L2)) return { lanes: L2, rung: "variants", note: `No exact results — widened at rung 1, “variants”: ${vNotes.join("; ")}.` };
  }
  // Rung 2 — facet drop: the active narrowing filters come off,
  // last applied first, until something matches.
  const activeDims = facetOrder.filter(d => (facetFilters[d] || new Set()).size);
  if (activeDims.length) {
    const trial = {};
    for (const d of Object.keys(facetFilters)) trial[d] = new Set(facetFilters[d]);
    const dropped = [];
    for (const dim of [...activeDims].reverse()) {
      delete trial[dim]; dropped.push(dim);
      const L3 = _searchLanes(q, trial);
      if (!_rankedEmpty(L3)) {
        const labels = dropped.map(d => ((SEARCH.facets || []).find(f => f.key === d) || {}).label || d);
        return { lanes: L3, rung: "facet-drop", note: `No results under the active filters — widened at rung 2, “facet drop”: the ${labels.join(", ")} filter(s) were set aside for this view (your chips above are unchanged).` };
      }
    }
  }
  // Rung 3 — broader tag.
  const broader = (SEARCH.tags && SEARCH.tags.broader) || {};
  const bTerms = [...terms], bNotes = [];
  for (const t of terms) {
    const pref = resolve[t] || t;
    const b = broader[pref];
    if (b) { bTerms.push(...tokenize(b)); bNotes.push(`${pref} widened to its broader tag ${b}`); }
  }
  if (bNotes.length) {
    const L4 = _searchLanes(bTerms.join(" "), facetFilters);
    if (!_rankedEmpty(L4)) return { lanes: L4, rung: "broader", note: `Still nothing exact — widened at rung 3, “broader tag”: ${bNotes.join("; ")}.` };
  }
  // Rung 4 — loosest: any query term as a substring of the
  // page's plain text, ranked by occurrences.
  const needles = terms.filter(t => t.length >= 3);
  if (needles.length) {
    const hits = [];
    SEARCH.docs.forEach((doc, di) => {
      const plain = (SEARCH.plain[di] || "").toLowerCase();
      let n = 0;
      for (const t of needles) { let i = -1; while ((i = plain.indexOf(t, i + 1)) >= 0) n++; }
      if (n > 0) hits.push({ score: n, di, doc, path: doc.path, snippet: makeSnippet(SEARCH.plain[di], terms), passage: pickPassageJs(di, terms) });
    });
    hits.sort((a, b) => (b.score - a.score) || (a.path < b.path ? -1 : 1));
    if (hits.length) {
      const lanes = { ...base, bm25: hits.slice(0, 10), hybrid: [], loosest: true };
      return { lanes, rung: "loosest", note: `Widened at rung 4, “loosest”: no ranked match exists, so pages merely containing the words as text are shown, ranked by occurrences.` };
    }
  }
  return { lanes: base, rung: "exhausted", note: "The relaxation ladder was climbed in order — exact · variants · facet drop · broader tag · loosest — and nothing in the corpus matched at any rung." };
}
function bindSearchSurface(root) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll("[data-facet-toggle]").forEach(b => b.addEventListener("click", () => {
    const [dim, val] = b.getAttribute("data-facet-toggle").split("::");
    toggleFacet(dim, decodeURIComponent(val));
  }));
  root.querySelectorAll("[data-facet-clear]").forEach(b => b.addEventListener("click", clearFacets));
  root.querySelectorAll("[data-facet-apply]").forEach(b => b.addEventListener("click", () => {
    const [dim, val] = b.getAttribute("data-facet-apply").split("::");
    const set = facetFilters[dim] || (facetFilters[dim] = new Set());
    set.add(decodeURIComponent(val));
    facetOrder = facetOrder.filter(d => d !== dim); facetOrder.push(dim);
    if (rerenderSearch) rerenderSearch();
  }));
}

/* ---------------- Nav panel: Knowledge | Files ----------------
   Knowledge: pages grouped by type with real counts (the nashsu-style
   panel). Files: the same pages grouped by folder. Both are computed
   at build (window.LENS_KNOWLEDGE); the type-group counts sum to the
   graph's page count, and the structural pages (index, log) ride in a
   separate "Wiki record" group so the sum stays exact. */
let treeTab = store("lens-tree-tab") || "knowledge";
let treeActiveId = null;
function treePageLink(p, activeId) {
  return `<a href="#/read/${encodeURIComponent(p.id)}" class="${p.id === activeId ? "selected" : ""}">${esc(p.title)}</a>`;
}
function renderTree(activeId) {
  treeActiveId = activeId;
  let h = `<div class="tree-tabs" role="group" aria-label="Page panel">
    <button class="chip" data-tree-tab="knowledge" aria-pressed="${treeTab === "knowledge"}">Knowledge</button>
    <button class="chip" data-tree-tab="files" aria-pressed="${treeTab === "files"}">Files</button>
  </div>`;
  if (treeTab === "files" && KNOWLEDGE.files && KNOWLEDGE.files.length) {
    for (const g of KNOWLEDGE.files) {
      h += `<h3>${esc(g.label)} <span class="tree-count" data-file-count="${g.count}">${g.count}</span></h3>` +
        g.pages.map(p => treePageLink(p, activeId)).join("");
    }
  } else if (KNOWLEDGE.groups && KNOWLEDGE.groups.length) {
    for (const g of KNOWLEDGE.groups) {
      h += `<h3><span class="swatch-dot" style="background:${esc(g.colour)}"></span>${esc(g.label)} <span class="tree-count" data-kg-count="${g.count}">${g.count}</span></h3>` +
        g.pages.map(p => treePageLink(p, activeId)).join("");
    }
    const rec = KNOWLEDGE.record || { pages: [] };
    if (rec.pages.length) {
      h += `<h3>${esc(rec.label || "Wiki record")}</h3>` + rec.pages.map(p => treePageLink(p, activeId)).join("") +
        `<p class="caption">The catalogue and the running log — the wiki's own record, not counted among the knowledge pages above.</p>`;
    }
  } else {
    const sections = [["sources", "Sources"], ["entities", "Entities"], ["concepts", "Concepts"], ["syntheses", "Syntheses"], ["queries", "Queries"]];
    const top = ["overview", "index", "log"].filter(id => PAGES[id]);
    if (top.length) {
      h += `<h3>Start here</h3>` + top.map(id => `<a href="#/read/${id}" class="${id === activeId ? "selected" : ""}">${esc(PAGES[id].title)}</a>`).join("");
    }
    for (const [sec, label] of sections) {
      const items = Object.values(PAGES).filter(p => p.section === sec).sort((a, b) => a.title.localeCompare(b.title));
      if (!items.length) continue;
      h += `<h3>${label}</h3>` + items.map(p => `<a href="#/read/${p.id}" class="${p.id === activeId ? "selected" : ""}">${esc(p.title)}</a>`).join("");
    }
  }
  treeEl.innerHTML = h;
  treeEl.querySelectorAll("[data-tree-tab]").forEach(b => b.addEventListener("click", () => {
    treeTab = b.getAttribute("data-tree-tab");
    store("lens-tree-tab", treeTab);
    renderTree(treeActiveId);
  }));
}

/* ---------------- Black Box rail (always visible) ---------------- */
function renderBlackBoxRail() {
  const el = document.getElementById("blackbox-rail");
  const g = BLACKBOX.gateway_ledger, w = BLACKBOX.watcher_ledger;
  const statusWord = s => s === "verified" ? "Verified" : s === "broken" ? "Broken" : s === "gap" ? "Gap" : "Not started";
  const chipFor = s => s === "verified" ? chip("verified", "Verified") : s === "broken" ? chip("broken", "Broken") : chip("open", statusWord(s));
  el.innerHTML = `
    <h3>Black Box</h3>
    <p class="caption">Gateway ledger: ${chipFor(g.status)} · ${g.entries_checked} entries<br>
    Watcher ledger: ${chipFor(w.status)} · ${w.entries_checked} entries<br>
    Unattributed since build: ${BLACKBOX.unattributed.length} · Denials: ${BLACKBOX.denials.length}</p>
    <p class="caption">${esc(BLACKBOX.note || "")}</p>
    <p><a href="#/blackbox">Open flight recorder</a></p>`;
}

/* ---------------- Inspector ---------------- */
function setInspector(html) { inspectorCtx.innerHTML = html; }
function hashChip(state) {
  if (state === "verified") return chip("verified", "Verified");
  if (state === "changed") return chip("stale", "Changed since manifest");
  if (state === "missing") return chip("broken", "Missing file");
  if (state === "page") return chip("info", "Wiki page");
  return chip("open", "Not in manifest");
}
function pageInspector(p) {
  const prov = p.citations.length
    ? `<ul>${p.citations.map(c => c.is_page
        ? `<li>${pageLink(c.page_id, c.path)}<br>${hashChip("page")}</li>`
        : `<li><span class="mono">${esc(c.path)}</span><br>${c.sha_short ? `<span class="mono">${esc(c.sha_short)}…</span> ` : ""}${hashChip(c.hash_state)}</li>`).join("")}</ul>`
    : `<p class="caption">This page cites no raw source.</p>`;
  const backs = p.backlinks.length
    ? `<ul>${p.backlinks.map(b => `<li>${pageLink(b.from)} <span class="caption">(${esc(b.kind)})</span></li>`).join("")}</ul>`
    : `<p class="caption">No page links here yet.</p>`;
  const rel = (ADJ[p.id] || []).slice(0, 8);
  const relHtml = rel.length
    ? `<ul>${rel.map(r => `<li>${pageLink(r.other)}<br><span class="caption">${esc(signalWords(r))}</span></li>`).join("")}</ul>`
    : `<p class="caption">No related pages in the graph.</p>`;
  /* TB4 wiring point 3: the scored related-pages rail, reading
     the page artefact's related_pages (evaluation/related-pages.json
     at build) — score and the artefact's own `why`, verbatim. */
  const scored = p.related_pages || [];
  const scoredHtml = scored.length
    ? `<ul>${scored.map(r => `<li>${pageLinkByPath(r.page)}<br><span class="caption">score ${esc(r.score)} · ${esc((r.why || []).join("; "))}</span></li>`).join("")}</ul>`
    : `<p class="caption">No scored related pages in the artefact for this page.</p>`;
  const fbRow = (FEEDBACK.pages || []).find(r => r.page === p.path);
  const fbHtml = fbRow
    ? `<p class="caption">Feedback so far: ${fbRow.counts.thumbs_up || 0} up · ${fbRow.counts.thumbs_down || 0} down · ${fbRow.counts.correction || 0} correction(s) · net ${esc(fbRow.net)}${fbRow.needs_attention ? " · needs attention" : ""}.</p>`
    : `<p class="caption">No feedback recorded for this page yet — use the controls at the foot of the page.</p>`;
  const hist = p.history.length
    ? `<ul>${p.history.map(hx => `<li><span class="mono">${esc(hx.sha)}</span> · ${esc(hx.date)}<br>${esc(hx.subject)}</li>`).join("")}</ul>`
    : `<p class="caption">No git history recorded for this file.</p>`;
  const attest = p.attested_until
    ? `<p class="caption">Attestation: verified by owner until ${esc(p.attested_until)}.</p>`
    : "";
  const growth = p.stage
    ? `<p class="caption"><span class="stage-badge stage-${esc(p.stage)}">${esc(p.stage)}</span> Planted ${esc(p.planted || "—")} · last tended ${esc(p.tended || "—")}.</p>`
    : `<p class="caption">No growth stage recorded for this page yet.</p>`;
  setInspector(`
    <h3>Inspector</h3>
    <h4>Growth stage</h4>${growth}
    <h4>Provenance</h4>${prov}${attest}
    <h4>Backlinks</h4>${backs}
    <h4>Related (graph)</h4>${relHtml}
    <h4>Related pages (scored)</h4>${scoredHtml}
    <h4>Feedback</h4>${fbHtml}
    <h4>History</h4>${hist}
    <h4>Activity</h4>
    <p class="caption">No activity recorded for this page yet.</p>
    <p class="caption">Raw source bodies open through the gateway; they are never shipped as static files.</p>`);
}
function defaultInspector(extra) {
  setInspector(`<h3>Inspector</h3>${extra || `<p class="caption">Open a page to see its provenance, backlinks, related pages, and history here.</p>`}`);
}

/* ---------------- Feedback (TB4 wiring point 5) ----------------
   Portal thumbs/correction controls. A record follows
   evaluation/feedback-format.md exactly ({id, ts, source:
   portal, page, kind, text?}; a correction requires text) —
   feedbackRecordJs mirrors lenslib.make_feedback_record. The
   record is POSTed to /api/feedback where a store exists; the
   static Lens has none, so a failed POST appends the record to
   this browser's feedback log instead — stated on the face of
   the control, never silently dropped — and the log downloads
   as JSONL that scripts/wiki_feedback_triage.py triages
   directly (`triage <file>`). */
const FEEDBACK_KINDS_JS = ["thumbs_up", "thumbs_down", "correction"];
function feedbackRecordJs(page, kind, text, ts, recordId) {
  if (!FEEDBACK_KINDS_JS.includes(kind)) throw new Error("bad feedback kind: " + kind);
  if (!page) throw new Error("feedback needs a page");
  if (kind === "correction" && !(text || "").trim()) throw new Error("correction needs text");
  const rec = { id: recordId, ts: ts, source: "portal", page: page, kind: kind };
  if ((text || "").trim()) rec.text = text.trim();
  return rec;
}
function feedbackControlsHtml(p) {
  return `
    <section class="feedback-controls" aria-label="Feedback on this page">
      <h2 style="font-family:var(--font-display)">Feedback</h2>
      <p class="caption">Thumbs and corrections are recorded in the feedback format (evaluation/feedback-format.md) and triaged with scripts/wiki_feedback_triage.py. On this static build a record is sent to /api/feedback where a store exists, and otherwise kept in this browser's feedback log — downloadable as JSONL below — never silently dropped.</p>
      <div class="chip-row">
        <button class="chip" data-fb="thumbs_up" aria-label="Thumbs up for this page">👍 Helpful</button>
        <button class="chip" data-fb="thumbs_down" aria-label="Thumbs down for this page">👎 Not helpful</button>
      </div>
      <form id="fb-correction-form" class="ask-box">
        <input id="fb-correction-text" type="text" placeholder="Suggest a correction to this page…" aria-label="Suggest a correction">
        <button class="btn" type="submit">Send correction</button>
      </form>
      <p class="caption" id="fb-status"></p>
      <button class="chip" id="fb-download" type="button">Download this browser's feedback log (JSONL)</button>
    </section>`;
}
function submitFeedback(p, kind, text) {
  const statusEl = document.getElementById("fb-status");
  const setStatus = msg => { if (statusEl) statusEl.textContent = msg; };
  let rec;
  try {
    rec = feedbackRecordJs(p.path, kind, text, new Date().toISOString(),
      "fb-" + Date.now().toString(36) + "-" + Math.floor(Math.random() * 1e6).toString(36));
  } catch (e) { setStatus(String(e.message || e)); return; }
  const keepLocal = () => {
    const rows = readJsonLog("lens-feedback-log");
    rows.push(rec);
    writeJsonLog("lens-feedback-log", rows);
    setStatus("Saved in this browser's feedback log (no live feedback store behind this static build). Download the log and triage it with scripts/wiki_feedback_triage.py.");
  };
  if (typeof fetch !== "function") { keepLocal(); return; }
  let pending;
  try {
    pending = fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rec) });
  } catch (e) { keepLocal(); return; }
  if (!pending || typeof pending.then !== "function") { keepLocal(); return; }
  pending.then(res => { if (res && res.ok) setStatus("Feedback recorded."); else keepLocal(); }).catch(() => keepLocal());
}
function wireFeedbackControls(p) {
  canvas.querySelectorAll("[data-fb]").forEach(b => b.addEventListener("click", () => submitFeedback(p, b.getAttribute("data-fb"), "")));
  const form = document.getElementById("fb-correction-form");
  if (form) form.addEventListener("submit", ev => {
    ev.preventDefault();
    const input = document.getElementById("fb-correction-text");
    submitFeedback(p, "correction", input ? input.value : "");
    if (input) input.value = "";
  });
  const dl = document.getElementById("fb-download");
  if (dl) dl.addEventListener("click", () => {
    const rows = readJsonLog("lens-feedback-log");
    const blob = new Blob([rows.map(r => JSON.stringify(r)).join("\n") + (rows.length ? "\n" : "")], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "feedback.jsonl";
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

/* ---------------- Items 58 + 60: zero results, standing queries,
   recent/frequent strip, ⌘K palette ----------------
   Item 58: when search finds nothing the surface is DESIGNED
   (wave-7 lane, Baymard's five strategies as the record states
   them), and the failed search can be saved as a standing query.
   Item 60: standing queries re-run at build (the Briefing section
   in renderBriefing reads BRIEFING.standing_queries); the
   recent/frequent strip and the palette live here.
   The Lens is read-only: nothing in this section writes to the
   wiki. The query/view logs below are localStorage in the
   owner's browser only — no tracking leaves the browser. */

/* ----- Client-side query + view log (item 60, find 18) ----- */
function readJsonLog(key) {
  try {
    const v = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(v) ? v : [];
  } catch (e) { return []; }
}
function writeJsonLog(key, rows) {
  try { localStorage.setItem(key, JSON.stringify(rows.slice(0, 60))); } catch (e) {}
}
function logQuery(q) {
  q = (q || "").trim();
  if (!q) return;
  const rows = readJsonLog("lens-query-log").filter(r => r.q !== q);
  rows.unshift({ q, ts: Date.now() });
  writeJsonLog("lens-query-log", rows);
  renderRecentStrip();
}
function logPageView(id) {
  const pg = PAGES[id];
  if (!pg) return;
  const rows = readJsonLog("lens-page-views");
  rows.unshift({ id, title: pg.title, ts: Date.now() });
  writeJsonLog("lens-page-views", rows);
}
function recentQueries(limit) {
  return readJsonLog("lens-query-log").slice(0, limit || 8).map(r => r.q);
}
function recentPages(limit) {
  const seen = new Set(), out = [];
  for (const r of readJsonLog("lens-page-views")) {
    if (seen.has(r.id) || !PAGES[r.id]) continue;
    seen.add(r.id);
    out.push({ id: r.id, title: PAGES[r.id].title });
    if (out.length >= (limit || 5)) break;
  }
  return out;
}
function frequentPages(limit) {
  const counts = new Map();
  for (const r of readJsonLog("lens-page-views")) {
    if (PAGES[r.id]) counts.set(r.id, (counts.get(r.id) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])
    .slice(0, limit || 5).map(([id]) => ({ id, title: PAGES[id].title }));
}
function renderRecentStrip() {
  const el = document.getElementById("recent-strip");
  if (!el) return;
  const qs = recentQueries(6), fp = frequentPages(4);
  if (!qs.length && !fp.length) {
    el.innerHTML = `<p class="strip-note">Your recent searches and most-opened pages will appear here — kept in this browser only.</p>`;
    return;
  }
  el.innerHTML =
    (qs.length ? `<div class="strip-row"><span class="strip-label">Recent</span>${qs.map(q => `<a class="chip-link" href="#/ask?q=${encodeURIComponent(q)}">${esc(q)}</a>`).join(" ")}</div>` : "") +
    (fp.length ? `<div class="strip-row"><span class="strip-label">Frequent</span>${fp.map(p => pageLink(p.id)).join(" · ")}</div>` : "");
}

/* ----- Corpus-vocabulary suggestions (item 59) are NOT
   re-implemented here: the surfaces build renders its own
   corrections + phrase strip (suggestionsFor) directly above
   the lanes in searchLanesHtml, in the zero case too, and its
   relaxation ladder (searchWithLadder) names the rung it
   climbed. What the zero surface below adds is the part of
   Baymard strategy 2 the ladder does not climb: dropping a
   keyword. ----- */

/* ----- Relaxed variants (Baymard strategy 2; the interface half
   of the relaxation ladder): drop-one-term and single-term
   widenings, each run live with a result count and the top hit as
   its preview. Offered as one-tap links — never auto-applied. */
function relaxedVariants(q) {
  const terms = tokenize(q);
  if (terms.length < 2) return [];
  const seen = new Set([terms.join(" ")]), cands = [];
  const push = arr => {
    const v = arr.join(" ");
    if (v && !seen.has(v)) { seen.add(v); cands.push(v); }
  };
  for (let i = 0; i < terms.length; i++) push(terms.filter((_, j) => j !== i));
  for (const t of terms) push([t]);
  const out = [];
  for (const v of cands) {
    const vt = tokenize(v);
    const paths = new Set();
    let top = null;
    for (const r of hybridRank(vt)) {
      paths.add(r.path);
      if (!top && SEARCH.docs[r.di] && SEARCH.docs[r.di].id) top = SEARCH.docs[r.di];
    }
    for (const r of bm25Rank(vt)) paths.add(r.path);
    if (paths.size) out.push({ q: v, count: paths.size, top });
  }
  return out.sort((a, b) => b.count - a.count).slice(0, 4);
}

/* ----- Nearest sections (Baymard strategy 1) ----- */
function nearestSections(terms) {
  const labels = { sources: "Sources", entities: "Entities", concepts: "Concepts", syntheses: "Syntheses", queries: "Queries" };
  const bySec = {};
  for (const pg of Object.values(PAGES)) {
    if (!labels[pg.section]) continue;
    const toks = tokenize(pg.title || "");
    if (!terms.some(t => toks.includes(t))) continue;
    (bySec[pg.section] = bySec[pg.section] || []).push(pg);
  }
  return Object.entries(bySec).sort((a, b) => b[1].length - a[1].length).slice(0, 3)
    .map(([key, pgs]) => ({ id: pgs[0].id, label: `${labels[key]} — ${pgs.length} page${pgs.length === 1 ? "" : "s"} with your words in the title` }));
}

/* ----- The designed zero-results surface (item 58) ----- */
function watchRecordText(q) {
  return JSON.stringify({ name: q, query: q, saved_from: "zero-results" });
}
function zeroResultsHtml(q) {
  const terms = tokenize(q);
  const variants = relaxedVariants(q);
  const sections = nearestSections(terms);
  const recent = recentPages(5);
  const popular = [...GRAPH.nodes].sort((a, b) => (b.wdegree || 0) - (a.wdegree || 0)).slice(0, 5);
  /* Facet reset (Algolia's rule: the reset control lives ON the
     zero page). The facet state is the surfaces build's own
     (facetFilters / clearFacets); the hook is guarded so this
     surface stands even where no facet build is present. */
  const filtersActive = (typeof facetFilters !== "undefined" && facetFilters && Object.keys(facetFilters).length > 0)
    || (typeof window !== "undefined" && typeof window.LENS_CLEAR_FILTERS === "function");
  return `<div class="zero-state">
    <h2>Nothing in the wiki matches &ldquo;${esc(q)}&rdquo; yet</h2>
    <p>That is a gap in the wiki, not a mistake by you. The search ran over page names, the full text, the index, exact identifiers and the link graph, and no lane found anything. Corrections and vocabulary matches from the corpus's own words, when it has any, are listed just above. Here is what to try instead:</p>
    ${variants.length ? `<div class="zero-block"><h3>Broader searches that do match</h3><ul>${variants.map(v => `<li><a href="#/ask?q=${encodeURIComponent(v.q)}">&ldquo;${esc(v.q)}&rdquo;</a> — ${v.count} result${v.count === 1 ? "" : "s"}${v.top ? `, top hit ${pageLink(v.top.id, v.top.title)}` : ""}</li>`).join("")}</ul></div>` : ""}
    ${sections.length ? `<div class="zero-block"><h3>Nearest sections</h3><p>${sections.map(s => `<a class="chip-link" href="#/read/${encodeURIComponent(s.id)}">${esc(s.label)}</a>`).join(" ")}</p><p class="caption">Or browse instead: ${pageLink("index", "the index")} · <a href="#/graph">the graph</a> · <a href="#/cards">Cards</a>.</p></div>` : ""}
    ${filtersActive ? `<div class="zero-block"><h3>Filters can cause this</h3><p>The commonest cause of an empty result in a faceted search is the filter stack itself. <button type="button" class="btn" id="zero-clear-filters">Clear all filters and search again</button></p></div>` : ""}
    <div class="zero-block zero-watch">
      <h3>Watch this search — nothing yet, watching</h3>
      <p>A failed search can become a <strong>standing query</strong>: it is re-run at every Lens build, and the Briefing reports what is new since you last looked. The Lens is read-only, so this page cannot save the watch itself — the button sends the request to the agent through the Ask door, and he files it in the standing-query register (<code>evaluation/standing-queries.jsonl</code>). The watch starts when he files it, and this section will say so.</p>
      <p><button type="button" class="btn btn-primary" id="zero-watch-btn">Ask the Agent to watch &ldquo;${esc(q)}&rdquo;</button></p>
      <p class="caption" id="zero-watch-status"></p>
      <details><summary>The exact record the agent files</summary><pre class="zero-record">${esc(watchRecordText(q))}</pre><p class="caption">Filed with: <code>python3 scripts/wiki_standing_queries.py add --name "${esc(q)}" --query "${esc(q)}" --from zero-results</code>. If the Ask door is unreachable from this copy, give the agent the record in chat instead.</p></details>
    </div>
    ${recent.length ? `<div class="zero-block"><h3>You were recently looking at</h3><p>${recent.map(p => pageLink(p.id)).join(" · ")}</p></div>` : ""}
    <div class="zero-block">
      <h3>Ask a person instead</h3>
      <p>Search finds pages; The agent answers questions. <button type="button" class="btn" id="zero-ask-btn">Ask the Agent: &ldquo;${esc(q)}&rdquo;</button></p>
    </div>
    <div class="zero-block"><h3>Most-linked pages</h3><ul>${popular.map(n => `<li>${pageLink(n.id)} <span class="caption">${esc(n.group)} · link weight ${(n.wdegree || 0).toFixed(1)}</span></li>`).join("")}</ul></div>
  </div>`;
}
function wireZeroState(q) {
  const wbtn = document.getElementById("zero-watch-btn");
  if (wbtn) wbtn.addEventListener("click", () => requestWatch(q));
  const abtn = document.getElementById("zero-ask-btn");
  if (abtn) abtn.addEventListener("click", () => askAgentWith(q));
  const cbtn = document.getElementById("zero-clear-filters");
  if (cbtn) cbtn.addEventListener("click", () => {
    /* clearFacets (the surfaces build's own reset) re-renders
       the surface itself; the other hooks are belt-and-braces. */
    if (typeof clearFacets === "function") clearFacets();
    else if (typeof window !== "undefined" && typeof window.LENS_CLEAR_FILTERS === "function") window.LENS_CLEAR_FILTERS();
    else route();
  });
}
function requestWatch(q) {
  const status = document.getElementById("zero-watch-status");
  const note = t => { if (status) status.textContent = t; };
  note("Sending the request to the agent through the Ask door…");
  if (typeof fetch !== "function") { note("This copy has no live Ask door — use the record below instead; nothing was sent."); return; }
  let pending;
  try {
    pending = fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: `Standing query request: please file a standing query named "${q}" for the search "${q}" (saved from a zero-results search).`,
        mode: "answer",
      }),
    });
  } catch (e) { note("Could not reach the Ask door from this copy — use the record below instead; nothing was sent."); return; }
  if (!pending || typeof pending.then !== "function") { note("Could not reach the Ask door from this copy — use the record below instead; nothing was sent."); return; }
  pending
    .then(res => (res && typeof res.json === "function") ? res.json().then(() => res.status) : (res ? res.status : 0))
    .then(statusCode => {
      if (statusCode === 201) note("Request sent. Once the agent files it, this search appears under “Standing queries” in the Briefing, with a line for anything new since you last looked.");
      else note(`The Ask door did not accept the request (${statusCode || "no response"}). Use the record below instead — nothing was filed.`);
    })
    .catch(() => note("Could not reach the Ask door from this copy — use the record below instead; nothing was sent."));
}
function askAgentWith(q) {
  const ta = document.getElementById("agent-question");
  if (ta) { ta.value = q; ta.focus(); if (ta.scrollIntoView) ta.scrollIntoView(); return; }
  try { sessionStorage.setItem("lens-agent-prefill", q); } catch (e) {}
  location.hash = "#/ask";
}

/* ----- ⌘K command palette (item 60, find 19) -----
   A keyboard-first overlay over the existing merged search:
   results ARE the merged search's (page-name matches + the
   hybrid lane), grouped by kind — views, pages, actions — with
   recents shown before typing. Vanilla, no framework. */
const PALETTE_VIEWS = [
  { label: "Briefing", route: "#/", sub: "view" },
  { label: "Wiki — read the overview", route: "#/read/overview", sub: "view" },
  { label: "Ask", route: "#/ask", sub: "view" },
  { label: "Graph", route: "#/graph", sub: "view" },
  { label: "Memory", route: "#/memory", sub: "view" },
  { label: "Timeline", route: "#/timeline", sub: "view" },
  { label: "Decisions", route: "#/decisions", sub: "view" },
  { label: "Proposals", route: "#/proposals", sub: "view" },
  { label: "Cards", route: "#/cards", sub: "view" },
  { label: "Black Box", route: "#/blackbox", sub: "view" },
];
let paletteIsOpen = false, paletteSel = 0, paletteFlat = [];
function fuzzySubseq(needle, hay) {
  needle = (needle || "").toLowerCase();
  hay = (hay || "").toLowerCase();
  if (!needle) return 0;
  let i = 0, score = 0, last = -2;
  for (let j = 0; j < hay.length && i < needle.length; j++) {
    if (hay[j] === needle[i]) { score += last === j - 1 ? 2 : 1; last = j; i++; }
  }
  return i === needle.length ? score : -1;
}
function paletteItems(q) {
  q = (q || "").trim();
  const groups = [];
  if (!q) {
    const rec = [];
    for (const p of recentPages(4)) rec.push({ kind: "page", label: p.title, sub: "recently viewed", route: `#/read/${encodeURIComponent(p.id)}` });
    for (const rq of recentQueries(4)) rec.push({ kind: "search", label: rq, sub: "recent search", route: `#/ask?q=${encodeURIComponent(rq)}` });
    if (rec.length) groups.push({ name: "Recent", items: rec });
    groups.push({ name: "Go to", items: PALETTE_VIEWS.map(v => ({ kind: "view", label: v.label, sub: v.sub, route: v.route })) });
    return groups;
  }
  const pages = [], seenIds = new Set();
  for (const m of nameMatches(q)) {
    if (!seenIds.has(m.id)) { seenIds.add(m.id); pages.push({ kind: "page", label: m.title, sub: m.type, route: `#/read/${encodeURIComponent(m.id)}` }); }
  }
  for (const r of hybridRank(tokenize(q))) {
    if (pages.length >= 7) break;
    const d = SEARCH.docs[r.di];
    if (d && d.id && !seenIds.has(d.id)) { seenIds.add(d.id); pages.push({ kind: "page", label: d.title, sub: d.type, route: `#/read/${encodeURIComponent(d.id)}` }); }
  }
  if (pages.length) groups.push({ name: "Pages", items: pages });
  const views = PALETTE_VIEWS
    .map(v => ({ v, s: fuzzySubseq(q, v.label) }))
    .filter(x => x.s >= 0)
    .sort((a, b) => b.s - a.s)
    .map(x => ({ kind: "view", label: x.v.label, sub: x.v.sub, route: x.v.route }));
  if (views.length) groups.push({ name: "Go to", items: views });
  groups.push({ name: "Actions", items: [
    { kind: "action", label: `Ask: “${q}”`, sub: "open in the Ask view", run: () => { location.hash = `#/ask?q=${encodeURIComponent(q)}`; } },
    { kind: "action", label: "Copy link to this search", sub: "clipboard", run: () => copyTextSafe(location.origin + location.pathname + `#/ask?q=${encodeURIComponent(q)}`) },
  ] });
  return groups;
}
function copyTextSafe(t) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t);
  } catch (e) {}
}
function renderPalette() {
  const input = document.getElementById("palette-input");
  const box = document.getElementById("palette-results");
  if (!box) return;
  const groups = paletteItems(input ? input.value : "");
  paletteFlat = groups.flatMap(g => g.items);
  if (paletteSel >= paletteFlat.length) paletteSel = 0;
  if (!paletteFlat.length) {
    box.innerHTML = `<div class="empty-note">No page, view or action matches. Press Enter to run it as a search in the Ask view.</div>`;
    return;
  }
  let idx = -1;
  box.innerHTML = groups.map(g => `<div class="palette-group">${esc(g.name)}</div>` +
    g.items.map(it => {
      idx++;
      return `<button type="button" class="palette-item${idx === paletteSel ? " sel" : ""}" data-palette-idx="${idx}"><span class="palette-label">${esc(it.label)}</span><span class="palette-sub">${esc(it.sub || "")}</span></button>`;
    }).join("")).join("");
  box.querySelectorAll("[data-palette-idx]").forEach(b => b.addEventListener("click", () => {
    paletteSel = parseInt(b.getAttribute("data-palette-idx"), 10);
    activatePaletteItem();
  }));
}
function activatePaletteItem() {
  const input = document.getElementById("palette-input");
  const it = paletteFlat[paletteSel];
  closePalette();
  if (!it) {
    const q = input ? input.value.trim() : "";
    if (q) location.hash = `#/ask?q=${encodeURIComponent(q)}`;
    return;
  }
  if (it.run) it.run();
  else if (it.route) location.hash = it.route;
}
function openPalette() {
  const p = document.getElementById("palette");
  if (!p) return;
  paletteIsOpen = true;
  paletteSel = 0;
  p.hidden = false;
  const input = document.getElementById("palette-input");
  if (input) { input.value = ""; input.focus(); }
  renderPalette();
}
function closePalette() {
  const p = document.getElementById("palette");
  if (p) p.hidden = true;
  paletteIsOpen = false;
}
const paletteOpenBtn = document.getElementById("palette-open");
if (paletteOpenBtn) paletteOpenBtn.addEventListener("click", openPalette);
const paletteEl = document.getElementById("palette");
if (paletteEl) paletteEl.addEventListener("click", ev => { if (ev.target === paletteEl) closePalette(); });
const paletteInput = document.getElementById("palette-input");
if (paletteInput) {
  paletteInput.addEventListener("input", () => { paletteSel = 0; renderPalette(); });
  paletteInput.addEventListener("keydown", ev => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); paletteSel = Math.min(paletteSel + 1, paletteFlat.length - 1); renderPalette(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); paletteSel = Math.max(paletteSel - 1, 0); renderPalette(); }
    else if (ev.key === "Enter") { ev.preventDefault(); activatePaletteItem(); }
    else if (ev.key === "Escape") { ev.preventDefault(); closePalette(); }
  });
}
document.addEventListener("keydown", ev => {
  if ((ev.metaKey || ev.ctrlKey) && (ev.key || "").toLowerCase() === "k") {
    ev.preventDefault();
    if (paletteIsOpen) closePalette(); else openPalette();
  }
});

/* ---------------- Mode: Briefing ---------------- */
function renderBriefing() {
  const s = BRIEFING.stats || {};
  const bt = s.pages_by_type || {};
  const typeLine = Object.entries(bt).map(([k, v]) => `${v} ${k}`).join(" · ");
  const verdicts = {};
  for (const v of ((HONESTY && HONESTY.admission_verdicts) || [])) verdicts[v.briefing_key] = v;
  const stat = (label, value, context, href, key) => `
    <a class="stat-block" href="${href}"><span class="stat-label">${esc(label)}</span>
    <span class="stat-value">${esc(value)}</span><span class="stat-context">${esc(context)}</span>${key && verdicts[key] ? `<span class="stat-verdict" title="${esc(verdicts[key].reason)}">${esc(verdicts[key].verdict)}</span>` : ""}</a>`;
  const gaps = [];
  for (const o of (BRIEFING.lint_items.orphans || [])) gaps.push(`<li>${pageLink(o.id)} — no links in or out</li>`);
  for (const m of (BRIEFING.lint_items.missing_pages || [])) gaps.push(`<li><span class="mono">[[${esc(m.target)}]]</span> — linked from ${m.count} page(s), no page exists yet</li>`);
  for (const t of (BRIEFING.lint_items.thin || [])) gaps.push(`<li>${pageLink(t.id)} — source page citing no raw source</li>`);
  const waiting = (BRIEFING.waiting_on_you || []).map((w, i) => {
    if (!w.text) return `<li>${pageLink(w.id)} — ${esc(w.summary || "")}</li>`;
    return `<li>${esc(w.text)}</li>`;
  }).join("");
  const latest = BRIEFING.latest_log;
  canvas.innerHTML = `
    <h1 class="mode-title">Briefing</h1>
    <p class="stamp-line">Generated ${esc(BRIEFING.generated_at || GENERATED_AT)} · from <code>${esc(BRIEFING.git_head_short || HEAD_SHORT)}</code>. A briefing is a generated view, not a source.</p>
    <section class="brief-section"><h2>Where everything stands</h2>
      <p>${esc(BRIEFING.overview_lede || "")}</p>
      <p><a href="#/read/overview">Open the full overview</a></p></section>
    <div class="stat-grid">
      ${stat("Pages", s.pages, typeLine, "#/cards", "pages")}
      ${stat("Raw sources", s.raw_files, `${((s.raw_bytes || 0) / 1048576).toFixed(1)} MB under provenance`, "#/read/founding-note", "raw_files")}
      ${stat("Decisions decided", s.decisions_decided, "Chapter 7 register", "#/decisions", "decisions_decided")}
      ${stat("Log entries", s.log_entries, "in wiki/log.md", "#/timeline", "log_entries")}
      ${stat("Graph edges", s.edges, "wikilinks + citations, one edge table", "#/graph", "edges")}
    </div>
    ${HONESTY ? `<p class="caption">The counts above are labelled under the Briefing's admission rule: ${esc(HONESTY.admission_rule)} The numbers that pass the test are the health section below.</p>${honestyHtml()}` : ""}
    <section class="brief-section"><h2>New since the last build</h2>
      <p class="caption">${esc(BRIEFING.deltas_label || "")}</p>
      ${(BRIEFING.deltas || []).length ? `<ul>${BRIEFING.deltas.map(d => `<li>${esc(d)}</li>`).join("")}</ul>` : `<p>Nothing new since the last briefing.</p>`}</section>
    <section class="brief-section"><h2>Open gaps</h2>
      ${gaps.length ? `<ul>${gaps.join("")}</ul>` : `<p>No gaps recorded by the build lint.</p>`}</section>
    <section class="brief-section"><h2>Standing queries</h2>
      ${STANDING.length ? `<ul>${STANDING.map(sq => {
        if (sq.paused) return `<li><strong>${esc(sq.name)}</strong> — paused <span class="caption">(&ldquo;${esc(sq.query)}&rdquo;)</span></li>`;
        if (sq.baseline) return `<li><strong>${esc(sq.name)}</strong> — watching ${sq.total_hits} page${sq.total_hits === 1 ? "" : "s"}; baseline set at this build, so future builds can report what is new <span class="caption">(&ldquo;${esc(sq.query)}&rdquo;)</span></li>`;
        if (sq.new_count) return `<li><strong>${esc(sq.name)}</strong> — <strong>${sq.new_count} new since ${esc(sq.since || "the last build")}</strong>: ${(sq.new_pages || []).map(p => `${pageLink(p.id)} <span class="caption">(${esc(p.kind)})</span>`).join(", ")} <span class="caption">(&ldquo;${esc(sq.query)}&rdquo; · ${sq.total_hits} match now)</span></li>`;
        return `<li><strong>${esc(sq.name)}</strong> — nothing new since ${esc(sq.since || "the last build")} <span class="caption">(&ldquo;${esc(sq.query)}&rdquo; · ${sq.total_hits} match now)</span></li>`;
      }).join("")}</ul>
      <p class="caption">Standing queries are re-run at every Lens build against the whole wiki. A query's last-looked stamp advances only in a build that reports something new for it, and the advance is written back to the register (evaluation/standing-queries.jsonl) — never silently.</p>`
      : `<p>No standing queries yet. When a search finds nothing, its results page offers &ldquo;Watch this search&rdquo;: The agent files it, and from then on this section reports what is new since you last looked.</p>`}</section>
    <section class="brief-section"><h2>Waiting on you</h2>
      ${waiting ? `<ul>${waiting}</ul><p class="caption">Decisions are made in chat: tell the agent there and the ruling is recorded on the Ideas board — this list is read-only and decides nothing.</p>` : `<p>Nothing is waiting on you.</p>`}</section>
    <section class="brief-section"><h2>System health</h2>
      <ul>
        <li>Canonical anchor — ${esc(BRIEFING.health.canonical_anchor || "")}</li>
        <li>Provenance manifest — ${esc(BRIEFING.health.manifest || "")}</li>
        <li>Black Box chain — ${esc(BRIEFING.health.blackbox_chain || "")}</li>
        <li>Last restore drill: ${esc((BRIEFING.health.restore_drill || "").replace("No restore drill recorded.", "") || "")}${(BRIEFING.health.restore_drill || "").includes("No restore") ? "No restore drill recorded." : ""}</li>
      </ul></section>
    <section class="brief-section"><h2>Latest activity</h2>
      ${latest ? `<p>${esc(latest.date)} — ${esc(latest.title)} · <a href="#/timeline">Open the timeline</a></p>` : `<p>Nothing recorded yet.</p>`}</section>`;
  defaultInspector(`<p class="caption">Every briefing bullet links to its page or record. Numbers are computed at build from the canonical repository.</p>`);
}

/* ---------------- Mode: Reading ---------------- */
function renderRead(id, anchor) {
  const p = PAGES[id];
  if (!p) {
    canvas.innerHTML = `<h1 class="mode-title">Page not found</h1><p>No page with id <span class="mono">${esc(id)}</span> exists in this build.</p>`;
    defaultInspector();
    return;
  }
  renderTree(id);
  logPageView(id);
  let bodyHtml = p.html.replace(/<h1[^>]*>[\s\S]*?<\/h1>/, "");
  /* TB4 wiring point 2: History/Diff tabs reading the page
     artefact's page_history (evaluation/page-history.json at
     build); the git-short history on the artefact is the
     fallback when the artefact has no row for this page. */
  const ph = p.page_history || { history: [], latest_diff: "" };
  const histRows = (ph.history && ph.history.length) ? ph.history
    : (p.history || []).map(h => ({ commit: h.sha, date: h.date, author: "", subject: h.subject }));
  const tabsHtml = `<div class="page-tabs" role="tablist" aria-label="Page views">
        <button class="chip" data-ptab="content" aria-pressed="true">Content</button>
        <button class="chip" data-ptab="history" aria-pressed="false">History</button>
        <button class="chip" data-ptab="diff" aria-pressed="false">Diff</button>
      </div>`;
  const historyPanel = `<div id="page-history-panel" hidden>
      <h2 style="font-family:var(--font-display)">History</h2>
      ${histRows.length ? `<ul>${histRows.map(hx => `<li><span class="mono">${esc(String(hx.commit || "").slice(0, 7))}</span> · ${esc(hx.date || "")}${hx.author ? ` · ${esc(hx.author)}` : ""}<br>${esc(hx.subject || "")}</li>`).join("")}</ul>` : `<p class="caption">No history recorded for this page in evaluation/page-history.json.</p>`}
    </div>`;
  const diffPanel = `<div id="page-diff-panel" hidden>
      <h2 style="font-family:var(--font-display)">Latest diff</h2>
      ${ph.latest_diff ? `<pre class="diff-view">${esc(ph.latest_diff)}</pre>` : `<p class="caption">No diff recorded for this page in evaluation/page-history.json.</p>`}
    </div>`;
  const tocItems = p.headings.filter(h => h.level >= 2 && h.level <= 3);
  const toc = tocItems.length ? `<nav class="toc" aria-label="On this page"><h4>On this page</h4><ul>${tocItems.map(h => `<li style="margin-left:${(h.level - 2) * 14}px"><a href="#${esc(h.anchor)}" data-anchor="${esc(h.anchor)}">${esc(h.text)}</a></li>`).join("")}</ul></nav>` : "";
  canvas.innerHTML = `
    <div class="reading-wrap reading-focus-wrap">
      <p class="page-breadcrumb">${esc(p.section)} › ${esc(p.type)}</p>
      <h1 class="mode-title" style="font-size:28px">${esc(p.title)}${p.stage ? ` <span class="stage-badge stage-${esc(p.stage)}" title="Growth stage — planted ${esc(p.planted || "?")}, last tended ${esc(p.tended || "?")}">${esc(p.stage)}</span>` : ""}</h1>
      ${p.lede ? `<p style="color:var(--ink-2);font-size:17px;line-height:1.6">${esc(p.lede)}</p>` : ""}
      <div class="chip-row">
        ${chip("info", p.type)}
        ${p.updated ? `<span class="chip">Updated ${esc(p.updated)}</span>` : ""}
        ${p.citations.length ? `<span class="chip">${p.citations.length} source${p.citations.length > 1 ? "s" : ""} cited</span>` : `<span class="chip">No sources cited</span>`}
        ${p.stale ? chip("stale", "Stale") : ""}
      </div>
      ${p.stale ? `<div class="stale-banner">A source for this page changed. Treat claims as unverified until re-checked.</div>` : ""}
      ${p.attested_until ? `<p class="verified-line">Verified by owner until ${esc(p.attested_until)}</p>` : ""}
      ${(p.provenance && (p.provenance.last_modified || p.provenance.last_author)) ? `<p class="caption page-provenance">Last modified ${esc(p.provenance.last_modified || "—")}${p.provenance.last_author ? ` by ${esc(p.provenance.last_author)}` : ""} · <a href="${esc(p.edit_link || p.path)}">canonical source</a></p>` : ""}
      ${tabsHtml}
      <div id="page-content-panel">
      ${toc}
      <div class="lf-controls" role="group" aria-label="Line focus">
        <span class="caption">Line focus:</span>
        ${[0, 1, 3, 5].map(n => `<button class="chip" data-lf="${n}" aria-pressed="false">${n === 0 ? "Off" : n + (n === 1 ? " line" : " lines")}</button>`).join("")}
        <span class="caption">dims the rest; arrow keys or the pointer move the band</span>
      </div>
      <div class="lf-mask" style="display:none"></div>
      <div class="lf-mask" style="display:none"></div>
      <article class="reading-body">${bodyHtml}</article>
      ${(p.cite_passages && p.cite_passages.length) ? `
      <h2 style="font-family:var(--font-display)">Claims and their sources</h2>
      <p class="caption">Each claim beside the exact passage its citation locks to — verbatim from the citation lockfile. A claim whose passage is not in the lockfile shows nothing here; nothing is paraphrased into a quote.</p>
      ${p.cite_passages.map(cp => `
      <div class="cite-pair">
        <p class="cite-claim">${esc(cp.claim || "")}</p>
        <blockquote class="cite-passage">${esc(cp.quote || "")}</blockquote>
        <p class="caption"><span class="mono">${esc(cp.source || "")}</span>${cp.range ? ` · lines ${cp.range[0]}–${cp.range[1]}` : ""}${cp.cite_id ? ` · lock ${esc(cp.cite_id)}` : ""}</p>
        ${cp.standing ? `<p class="caption cite-standing">Standing: relied on by ${esc(cp.standing.reliance_count)} page${cp.standing.reliance_count === 1 ? "" : "s"} · treatment ${esc(cp.standing.treatment)}${cp.standing.treatment_date ? ` (${esc(cp.standing.treatment_date)})` : ""} · cited text ${cp.standing.cited_text_changed ? `changed${cp.standing.cited_text_changed_date ? ` (${esc(cp.standing.cited_text_changed_date)})` : ""}` : "unchanged"}</p>` : ""}
      </div>`).join("")}` : ""}
      <h2 style="font-family:var(--font-display)">Linked from</h2>
      ${p.backlinks.length ? `<ul>${p.backlinks.map(b => `<li>${pageLink(b.from)}</li>`).join("")}</ul>` : `<p class="caption">No page links here yet.</p>`}
      </div>
      ${historyPanel}
      ${diffPanel}
      ${feedbackControlsHtml(p)}
    </div>`;
  canvas.querySelectorAll("[data-anchor]").forEach(a => {
    a.addEventListener("click", ev => {
      ev.preventDefault();
      const t = document.getElementById(a.getAttribute("data-anchor"));
      if (t) t.scrollIntoView();
    });
  });
  canvas.querySelectorAll("[data-ptab]").forEach(b => b.addEventListener("click", () => {
    const which = b.getAttribute("data-ptab");
    canvas.querySelectorAll("[data-ptab]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    const cp = document.getElementById("page-content-panel"); if (cp) cp.hidden = which !== "content";
    const hp = document.getElementById("page-history-panel"); if (hp) hp.hidden = which !== "history";
    const dp = document.getElementById("page-diff-panel"); if (dp) dp.hidden = which !== "diff";
  }));
  wireFeedbackControls(p);
  const lfWrap = canvas.querySelector(".reading-focus-wrap");
  const lfArticle = canvas.querySelector(".reading-body");
  if (lfWrap && lfArticle) setupLineFocus(lfWrap, lfArticle);
  if (anchor) {
    const t = document.getElementById(anchor);
    if (t) t.scrollIntoView();
  }
  pageInspector(p);
}

/* ---------------- Mode: Graph ----------------
   The nashsu-shaped view, rebuilt in our stack: header stats, a
   Type/Community colour toggle, a Node Types legend whose rows are
   filter toggles, an Insights panel of computed findings, and node
   size by weighted degree. Colour is always redundant — shape and
   label carry the same information (design system §1.4/§2.5). */
let graphView = "canvas";
let graphSelected = null;
let graphColourMode = "type";   // "type" | "community"
let graphTypeFilter = null;     // display-group key, or null
let graphCommFilter = null;     // community id, or null
let graphInsightsOpen = true;
let graphNodeQuery = "";
let graphEdgeTypeFilter = null;   // relation-map edge type, or null (TB4 wiring point 1)

const FALLBACK_TYPE_COLOURS = { overview: "#F2C94C", source: "#F2994A", entity: "#5B8DEF", concept: "#A06CD5", synthesis: "#5FA88F", query: "#95A5A6", other: "#95A5A6" };
const TYPE_COLOUR = {};
for (const g of (GRAPH.type_groups || [])) TYPE_COLOUR[g.key] = g.colour;
function typeColour(key) { return TYPE_COLOUR[key] || FALLBACK_TYPE_COLOURS[key] || "#C9C2B4"; }
const COMMUNITY_COLOURS = (GRAPH.community_colours && GRAPH.community_colours.length)
  ? GRAPH.community_colours
  : ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#999999"];
function groupOf(node) { return node.group || (node.id === "overview" ? "overview" : (FALLBACK_TYPE_COLOURS[node.type] ? node.type : "other")); }
function nodeFill(node) {
  if (graphColourMode === "community") return COMMUNITY_COLOURS[node.community % COMMUNITY_COLOURS.length];
  const g = groupOf(node);
  if (g === "query") return "none";
  return typeColour(g);
}
const MAXW = Math.max(1, ...GRAPH.nodes.map(n => n.wdegree || 0));
function sizeFor(node) {
  const s = 6 + 16 * Math.sqrt((node.wdegree || 0) / MAXW);
  return Math.round(Math.min(22, Math.max(6, s)) * 10) / 10;
}
function shapeFor(node) {
  const [x, y] = [node.x, node.y];
  const size = sizeFor(node);
  const fill = nodeFill(node);
  const g = groupOf(node);
  const common = `fill="${fill}" stroke="#0E0D0B" stroke-width="1" class="node-shape"`;
  if (g === "source") return `<rect x="${x - size / 2}" y="${y - size / 2}" width="${size}" height="${size}" ${common}></rect>`;
  if (g === "synthesis") return `<path d="M ${x} ${y - size / 1.4} L ${x + size / 1.4} ${y} L ${x} ${y + size / 1.4} L ${x - size / 1.4} ${y} Z" ${common}></path>`;
  if (g === "query" && graphColourMode === "type") return `<circle cx="${x}" cy="${y}" r="${size / 1.6}" fill="none" stroke="${typeColour("query")}" stroke-width="1.6" stroke-dasharray="3 2" class="node-shape"></circle>`;
  return `<circle cx="${x}" cy="${y}" r="${size / 1.7}" ${common}></circle>`;
}
function insightCategories() { return (GRAPH.insights && GRAPH.insights.categories) || []; }
function insightTotal() { return insightCategories().reduce((s, c) => s + (c.count || 0), 0); }
function insightItemHtml(it, n) {
  const links = (it.pages || []).map(pid => {
    const t = PAGES[pid] ? PAGES[pid].title : pid;
    return pageLink(pid, t.length > 26 ? t.slice(0, 25) + "…" : t);
  }).join(" · ");
  return `<div class="insight-item"><span class="insight-n">${n}.</span> ${esc(it.text)}${links ? `<br>${links}` : ""}</div>`;
}
function graphLegendHtml() {
  if (graphColourMode === "community") {
    const rows = GRAPH.communities.map(c => `
      <button class="legend-row" data-comm-filter="${c.id}" aria-pressed="${graphCommFilter === c.id}">
        <span class="swatch" style="background:${COMMUNITY_COLOURS[c.id % COMMUNITY_COLOURS.length]}"></span>
        <span class="legend-label">${esc(c.label)}</span>
        <span class="legend-count">${c.members.length} · ${c.cohesion}% inside</span>
      </button>`).join("");
    return `<div class="legend-panel"><h4>Communities</h4>${rows}
      <p class="caption">Community colours are a lens, never canonical categories — the clusters are computed from link patterns at build. Select a row to fade the other clusters.</p></div>`;
  }
  const rows = (GRAPH.type_groups || []).map(g => `
    <button class="legend-row" data-type-filter="${esc(g.key)}" aria-pressed="${graphTypeFilter === g.key}">
      <span class="swatch" style="background:${esc(g.colour)}"></span>
      <span class="legend-label">${esc(g.singular || g.label)}</span>
      <span class="legend-count">${g.count}</span>
    </button>`).join("");
  return `<div class="legend-panel"><h4>Node Types</h4>${rows}
    <p class="caption">Colour, shape, and label all encode the same type. Select a row to fade the other types.</p></div>`;
}
function graphInsightsPanelHtml() {
  const cats = insightCategories();
  if (!cats.length) return "";
  let n = 0;
  const body = cats.map(c => `
    <h4>${esc(c.label)} · ${c.count}</h4>
    ${c.items.map(it => insightItemHtml(it, ++n)).join("")}`).join("");
  return `<div class="insights-panel"><div class="insights-head"><h3>Insights</h3><button class="chip" id="insights-close">Close</button></div>${body}
    <p class="caption">Every finding is computed from the edge table at build; nothing here is generated prose.</p></div>`;
}
function graphInsightsSectionHtml() {
  const cats = insightCategories();
  if (!cats.length) return `<h2 style="font-family:var(--font-display)">Insights</h2><p class="caption">No insights computed at this build.</p>`;
  let n = 0;
  return `<h2 style="font-family:var(--font-display)">Insights · ${insightTotal()}</h2>` + cats.map(c => `
    <div class="card"><h3>${esc(c.label)} · ${c.count}</h3>${c.items.map(it => insightItemHtml(it, ++n)).join("")}</div>`).join("");
}
function hoistingPanelHtml() {
  const rows = (GRAPH.relation_maps && GRAPH.relation_maps.hoisting) || [];
  if (!rows.length) return `<h2 style="font-family:var(--font-display)">Hoisting candidates</h2><p class="caption">No hoisting candidates in evaluation/relation-maps.json at this build.</p>`;
  return `<h2 style="font-family:var(--font-display)">Hoisting candidates</h2>
    <div class="card"><p class="caption">Pages with enough linked children to hoist into a section view, computed by scripts/wiki_relation_maps.py — a computed suggestion, never an edit.</p>
    <ul>${rows.map(h => `<li>${pageLinkByPath(h.page)} <span class="caption">— ${esc(h.child_count)} linked children${h.suggestion ? ` · ${esc(h.suggestion)}` : ""}</span></li>`).join("")}</ul></div>`;
}
function renderGraph() {
  const mode = graphView;
  const stats = GRAPH.stats || { pages: GRAPH.nodes.length, direct_links: GRAPH.edges.filter(e => e.direct).length, relations: GRAPH.edges.length };
  const nodeById = {};
  for (const n of GRAPH.nodes) nodeById[n.id] = n;
  let main = "";
  if (mode === "canvas") {
    const edgeLines = GRAPH.edges.filter(e => e.direct).map(e => {
      const a = nodeById[e.a], b = nodeById[e.b];
      if (!a || !b) return "";
      const w = 0.8 + Math.min(2.7, e.weight / 3);
      const incident = graphSelected && (e.a === graphSelected || e.b === graphSelected);
      const dim = (graphSelected && !incident)
        || (graphEdgeTypeFilter && !(e.rm_types || []).includes(graphEdgeTypeFilter))
        || (graphTypeFilter && groupOf(a) !== graphTypeFilter && groupOf(b) !== graphTypeFilter)
        || (graphCommFilter !== null && a.community !== graphCommFilter && b.community !== graphCommFilter);
      return `<line class="graph-edge ${incident ? "incident" : ""}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke-width="${w.toFixed(1)}" style="opacity:${dim ? 0.05 : incident ? 0.95 : 0.35}"></line>`;
    }).join("");
    const nodes = GRAPH.nodes.map(n => {
      let op = 1;
      if (graphTypeFilter && groupOf(n) !== graphTypeFilter) op = 0.15;
      if (graphCommFilter !== null && n.community !== graphCommFilter) op = 0.15;
      if (graphSelected && n.id !== graphSelected && !(ADJ[graphSelected] || []).some(r => r.other === n.id)) op = Math.min(op, 0.25);
      return `<g class="graph-node ${n.id === graphSelected ? "selected" : ""}" data-node="${esc(n.id)}" style="opacity:${op}">
        ${shapeFor(n)}<text x="${n.x}" y="${n.y + 24}" text-anchor="middle">${esc(n.title.length > 34 ? n.title.slice(0, 33) + "…" : n.title)}</text></g>`;
    }).join("");
    main = `<div class="graph-stage"><div class="graph-wrap"><svg viewBox="0 0 1000 660" role="img" aria-label="Knowledge graph">${edgeLines}${nodes}</svg></div>
      ${graphLegendHtml()}
      ${graphInsightsOpen ? graphInsightsPanelHtml() : ""}
      </div>
      <p class="caption">Graph image — the same data is available as a list (toggle above). ${graphColourMode === "community" ? "Node colour encodes community; shape and label still encode page type." : "Node colour and shape encode page type."} Node size scales with total link weight (√ scaling, biggest hub full size). Communities are generated clusters, not canonical categories.</p>`;
  } else {
    main = GRAPH.communities.map(c => `
      <div class="card"><h3>${esc(c.label)}</h3><p class="caption">${c.members.length} pages (${esc(c.share)}% of the wiki) · hub: ${pageLink(c.hub_id, c.hub_title)} · ${esc(c.cohesion)}% of link weight stays inside</p>
      <ul>${c.members.map(id => { const n = nodeById[id]; return `<li>${pageLink(id)} <span class="caption">(${esc(n ? n.type : "")} · ${n ? n.degree : 0} links)</span></li>`; }).join("")}</ul></div>`).join("")
      + graphInsightsSectionHtml() + graphReportSectionHtml();
  }
  canvas.innerHTML = `
    <h1 class="mode-title">Knowledge Graph</h1>
    <p class="graph-stats">${stats.pages} pages · ${stats.direct_links} links</p>
    <p class="caption">${stats.relations} weighted relations (direct link · shared sources · common neighbours · type affinity) · ${GRAPH.communities.length} communities · tier ${GRAPH.tier} layout, precomputed at build. Click a node to see why it is related to its neighbours.</p>
    <div class="graph-toolbar" role="group" aria-label="Graph controls">
      <span class="toolbar-group" role="group" aria-label="Colour by">
        <button class="chip" data-colour="type" aria-pressed="${graphColourMode === "type"}">Type</button>
        <button class="chip" data-colour="community" aria-pressed="${graphColourMode === "community"}">Community</button>
      </span>
      <button class="chip" id="insights-toggle" aria-pressed="${graphInsightsOpen}">Insights ${insightTotal()}</button>
      <span class="toolbar-group" role="group" aria-label="View">
        <button class="chip" data-gview="canvas" aria-pressed="${mode === "canvas"}">Graph</button>
        <button class="chip" data-gview="list" aria-pressed="${mode === "list"}">Graph as list</button>
      </span>
      <span class="toolbar-group" role="group" aria-label="Relation edge type">
        ${(GRAPH.relation_maps && GRAPH.relation_maps.edge_types || []).map(et => `<button class="chip" data-edge-type="${esc(et)}" aria-pressed="${graphEdgeTypeFilter === et}">${esc(et)}</button>`).join("")}
      </span>
      <form id="graph-search-form" class="graph-search"><input id="graph-search-input" type="search" placeholder="Find a page in the graph…" value="${esc(graphNodeQuery)}" aria-label="Find a page in the graph"><button class="chip" type="submit">Find</button></form>
    </div>
    ${main}
    ${hoistingPanelHtml()}`;
  canvas.querySelectorAll("[data-edge-type]").forEach(b => b.addEventListener("click", () => {
    const k = b.getAttribute("data-edge-type");
    graphEdgeTypeFilter = graphEdgeTypeFilter === k ? null : k;
    renderGraph();
  }));
  canvas.querySelectorAll("[data-gview]").forEach(b => b.addEventListener("click", () => { graphView = b.getAttribute("data-gview"); renderGraph(); }));
  canvas.querySelectorAll("[data-colour]").forEach(b => b.addEventListener("click", () => { graphColourMode = b.getAttribute("data-colour"); renderGraph(); }));
  const it = document.getElementById("insights-toggle");
  if (it) it.addEventListener("click", () => { graphInsightsOpen = !graphInsightsOpen; renderGraph(); });
  const ic = document.getElementById("insights-close");
  if (ic) ic.addEventListener("click", () => { graphInsightsOpen = false; renderGraph(); });
  canvas.querySelectorAll("[data-type-filter]").forEach(b => b.addEventListener("click", () => {
    const k = b.getAttribute("data-type-filter");
    graphTypeFilter = graphTypeFilter === k ? null : k;
    renderGraph();
  }));
  canvas.querySelectorAll("[data-comm-filter]").forEach(b => b.addEventListener("click", () => {
    const k = parseInt(b.getAttribute("data-comm-filter"), 10);
    graphCommFilter = graphCommFilter === k ? null : k;
    renderGraph();
  }));
  const gsf = document.getElementById("graph-search-form");
  if (gsf) gsf.addEventListener("submit", ev => {
    ev.preventDefault();
    graphNodeQuery = document.getElementById("graph-search-input").value.trim().toLowerCase();
    if (graphNodeQuery) {
      const hit = GRAPH.nodes.filter(n => n.title.toLowerCase().includes(graphNodeQuery))
        .sort((a, b) => (b.wdegree || 0) - (a.wdegree || 0))[0];
      if (hit) { graphSelected = hit.id; graphView = "canvas"; }
    }
    renderGraph();
    if (graphSelected && PAGES[graphSelected]) graphInspector(graphSelected);
  });
  canvas.querySelectorAll(".graph-node").forEach(g => g.addEventListener("click", () => {
    graphSelected = g.getAttribute("data-node");
    renderGraph();
    graphInspector(graphSelected);
  }));
  if (graphSelected && PAGES[graphSelected]) graphInspector(graphSelected);
  else defaultInspector(`<p class="caption">Select a node to see its related pages and the signals behind each relation. A score is never shown alone — the signals are listed in words.</p>`);
}
function graphInspector(id) {
  const n = GRAPH.nodes.find(x => x.id === id);
  const comm = GRAPH.communities.find(c => c.id === (n && n.community));
  const rel = (ADJ[id] || []).slice(0, 8);
  const cocit = (GRAPH.cocitations || {})[id] || [];
  const cocitHtml = cocit.length ? `
    <h4>Co-cited with</h4>
    <p class="caption">Pages other pages link to alongside this one, with the sentences that cite them together — computed at build from the edge table.</p>
    <ul>${cocit.map(c => `<li>${pageLink(c.other)} <span class="caption">— cited together by ${c.shared_citers} page${c.shared_citers > 1 ? "s" : ""}</span>${c.sentences.length ? `<br>${c.sentences.map(s => `<span class="caption">“${esc(s.text)}” — ${pageLink(s.by)}</span>`).join("<br>")}` : ""}</li>`).join("")}</ul>` : "";
  setInspector(`
    <h3>${esc(PAGES[id] ? PAGES[id].title : id)}</h3>
    <p class="caption">${esc(n ? n.type : "")} · ${n ? n.degree : 0} neighbours · total link weight ${n ? n.wdegree : 0} · ${esc(comm ? comm.label : "")}</p>
    <p><a class="btn btn-primary" href="#/read/${encodeURIComponent(id)}">Open page</a></p>
    <h4>Related — and why</h4>
    ${rel.length ? `<ul>${rel.map(r => `<li>${pageLink(r.other)}<br><span class="caption">${esc(signalWords(r))} · weight ${r.weight}</span></li>`).join("")}</ul>` : `<p class="caption">No relations.</p>`}${cocitHtml}`);
}
function graphReportSectionHtml() {
  const r = GRAPH_REPORT;
  if (!r || !(r.god_nodes || []).length) return "";
  const gods = r.god_nodes.map((g, i) => `<div class="insight-item"><span class="insight-n">${i + 1}.</span> ${pageLink(g.id)} <span class="caption">— link weight ${g.wdegree} across ${g.degree} neighbour(s)</span></div>`).join("");
  const miss = (r.missing_links || []).map(m => `<div class="insight-item">${pageLink(m.a)} · ${pageLink(m.b)} <span class="caption">— no direct link; ${m.common_neighbours} shared neighbour(s), Adamic–Adar ${m.adamic_adar}. Computed suggestion only; no page has been changed.</span></div>`).join("");
  const typeEntries = Object.entries((r.typed_edges || {}).counts || {}).sort((a, b) => b[1] - a[1]);
  const types = typeEntries.map(([t, c]) => `${esc(t)} ${c}`).join(" · ");
  const qs = (r.suggested_questions || []).map(q => `<div class="insight-item">${esc(q.question)}<br><span class="caption">${esc(q.basis)}</span></div>`).join("");
  const methods = r.community_methods
    ? `<p class="caption">Community detection, measured at build: the rendered clusters are the ${esc(r.community_methods.rendered)} partition (${r.community_methods.louvain.communities} communities, largest ${r.community_methods.louvain.largest_share}% of the wiki). Label propagation — the Graph Analysis plugin's algorithm — finds ${r.community_methods.label_propagation.communities} communities here, its largest swallowing ${r.community_methods.label_propagation.largest_share}% around the super-hubs, so it is reported, not rendered.</p>` : "";
  return `<h2 style="font-family:var(--font-display)">Graph report</h2>
    <div class="card"><h3>God nodes — pages carrying the most link weight</h3>${gods}${methods}</div>
    ${miss ? `<div class="card"><h3>Missing link? — computed suggestions, never written to pages</h3>${miss}</div>` : ""}
    ${types ? `<div class="card"><h3>Typed link edges</h3><p class="caption">Every edge in the edge table carries a type. A wikilink's type is inferred from the heading it sits under (grounds / contradicts / extends / exemplifies / supersedes / mentions); a frontmatter-declared link keeps its declared relation; a citation is "cites". Census at this build: ${types}.</p></div>` : ""}
    ${qs ? `<div class="card"><h3>Suggested questions</h3>${qs}</div>` : ""}`;
}

/* ---------------- Mode: Timeline ---------------- */
let tlStream = "All", tlText = "";
function renderTimeline() {
  const streams = ["All", ...new Set(TIMELINE.events.map(e => e.stream))];
  const items = TIMELINE.events.filter(e =>
    (tlStream === "All" || e.stream === tlStream) &&
    (!tlText || (e.title + " " + e.summary).toLowerCase().includes(tlText)));
  let lastDate = "";
  const rows = items.map(e => {
    const sep = e.date !== lastDate ? `<h2 style="font-family:var(--font-display);font-size:18px;margin:24px 0 8px">${esc(e.date)}</h2>` : "";
    lastDate = e.date;
    return `${sep}<div class="timeline-item stream-${esc(e.stream.replace(/ /g, ""))}">
      <p class="timeline-date">${esc(e.date)} · ${esc(e.stream)}${e.sha ? ` · <span class="mono">${esc(e.sha)}</span>` : ""}${e.actor ? ` · ${esc(e.actor)}` : ""}</p>
      <p class="timeline-title">${esc(e.title)}</p>
      ${e.summary ? `<p class="timeline-summary">${esc(e.summary)}</p>` : ""}
      ${e.files ? `<p class="caption">${e.files} file(s) changed</p>` : ""}
    </div>`;
  }).join("");
  canvas.innerHTML = `
    <h1 class="mode-title">Timeline</h1>
    <p class="caption">${esc(TIMELINE.caption || "")}</p>
    <div class="filter-chips">${streams.map(s => `<button class="chip" data-stream="${esc(s)}" aria-pressed="${tlStream === s}">${esc(s)}</button>`).join("")}
    <input id="tl-filter" type="search" placeholder="Filter events…" value="${esc(tlText)}" style="padding:8px 12px;background:var(--surface-2);color:var(--ink-1);border:1px solid var(--line-2);border-radius:6px"></div>
    ${rows || `<div class="empty-note">No events match this filter.</div>`}`;
  canvas.querySelectorAll("[data-stream]").forEach(b => b.addEventListener("click", () => { tlStream = b.getAttribute("data-stream"); renderTimeline(); }));
  const f = document.getElementById("tl-filter");
  f.addEventListener("input", () => { tlText = f.value.toLowerCase(); const pos = f.selectionStart; renderTimeline(); const nf = document.getElementById("tl-filter"); nf.focus(); nf.setSelectionRange(pos, pos); });
  defaultInspector(`<p class="caption">${TIMELINE.events.length} events from wiki/log.md and this wiki's git commits. External repositories are not monitored.</p>`);
}

/* ---------------- Mode: Decisions ---------------- */
function renderDecisions() {
  const cards = DECISIONS.decisions.map(d => `
    <div class="card">
      <div class="chip-row">${chip("decided", "Decided")} <span class="chip">${esc(d.decider)} · ${esc(d.date)}</span></div>
      <h3>${esc(d.title)}</h3>
      <p>${esc(d.detail)}</p>
      <p><a href="#/read/decision-register">Open the register entry</a></p>
    </div>`).join("");
  const open = DECISIONS.open_items.map(o => `
    <div class="card">
      <div class="chip-row">${chip("open", "Open")}</div>
      <h3>${esc(o.title)}</h3>
      <p>${esc(o.summary || "")}</p>
      <p><a href="#/read/${encodeURIComponent(o.id)}">Open page</a></p>
    </div>`).join("");
  canvas.innerHTML = `
    <h1 class="mode-title">Decisions</h1>
    <p class="caption">Decided law first, then what is still open. An open item names its page; nothing here auto-reverses a decision.</p>
    <h2 style="font-family:var(--font-display)">Waiting on you</h2>
    ${DECISIONS.open_items.length ? `<p>${DECISIONS.open_items.length} idea / question page(s) stand open — below the decided law.</p>` : `<p>Nothing is waiting on you.</p>`}
    <h2 style="font-family:var(--font-display)">Decided</h2>
    ${cards || `<p>No decisions recorded.</p>`}
    ${DECISIONS.refinements ? `<div class="card"><h3>Refinements directed later the same day</h3><p>${esc(DECISIONS.refinements)}</p></div>` : ""}
    <h2 style="font-family:var(--font-display)">Proposed — not decided</h2>
    ${PROPOSALS.proposals.length ? `<p>Staged gateway proposals awaiting your ruling: <a href="#/proposals">${PROPOSALS.proposals.length} proposal(s) with per-hunk diffs</a> — display only; decisions are made in chat.</p>` : ""}
    ${open || `<p>Nothing proposed.</p>`}`;
  defaultInspector(`<p class="caption">The register page is wiki/syntheses/decision-register.md. Owner decision controls arrive with the gateway; this build is read-only.</p>`);
}

/* ---------------- Mode: Proposals (staged — display only) ----------------
   The gateway's staged change proposals as per-hunk diffs against
   the current pages, computed at build time. There is deliberately
   no control of any kind here: decisions are made in chat and
   executed through the gateway. */
function renderProposals() {
  const noteLine = PROPOSALS.note || "Decisions are made in chat — this view only displays.";
  const diffHtml = p => (p.diff.hunks || []).map(h => `
    <div class="diff-hunk">
      <div class="diff-hunk-head mono">${esc(h.header)}</div>
      ${h.lines.map(l => `<div class="diff-line diff-${l.kind}">${l.kind === "add" ? "+" : l.kind === "del" ? "-" : l.kind === "meta" ? "\\" : " "} ${esc(l.text)}</div>`).join("")}
    </div>`).join("");
  const checksLine = p => {
    const parts = [];
    if (p.sanitiser_verdict) parts.push(`sanitiser ${esc(p.sanitiser_verdict)}`);
    if (p.defense_verdict) parts.push(`defence scan ${esc(p.defense_verdict)}`);
    if (p.profile_check) parts.push(`profile ${esc(p.profile_check.mode || "")} · ${p.profile_check.violations} violation(s)`);
    if (p.eval_gate_verdict) parts.push(`eval gate ${esc(p.eval_gate_verdict)}`);
    return parts.length ? `<p class="caption">Gateway checks at staging: ${parts.join(" · ")}</p>` : "";
  };
  const cards = PROPOSALS.proposals.map(p => `
    <div class="card">
      <div class="chip-row">${chip("open", "Awaiting decision")}${p.is_new ? chip("new", "New page") : ""} <span class="chip mono">${esc(p.proposal_id)}</span></div>
      <h3 class="mono">${esc(p.target_path)}</h3>
      <p class="caption">Staged ${esc(p.submitted_at || "")} by ${esc(p.submitted_by || "unknown")}${p.task_ref ? ` · task <span class="mono">${esc(p.task_ref)}</span>` : ""} · plan hash <span class="mono">${esc(String(p.sha256 || "").slice(0, 12))}…</span> · <span class="diff-add-n">+${p.diff.added}</span> / <span class="diff-del-n">-${p.diff.removed}</span> lines</p>
      ${checksLine(p)}
      ${p.target_id && !p.is_new ? `<p><a href="#/read/${encodeURIComponent(p.target_id)}">Open the current page</a></p>` : ""}
      <div class="diff">${diffHtml(p) || `<p class="caption">No textual difference from the current page.</p>`}</div>
    </div>`).join("");
  const footnote = [
    ...(PROPOSALS.excluded || []).map(x => `<p class="caption">Excluded: <span class="mono">${esc(x.proposal_id)}</span> — ${esc(x.reason)}</p>`),
    ...(PROPOSALS.skipped || []).map(x => `<p class="caption">Skipped: <span class="mono">${esc(x.file)}</span> — ${esc(x.reason)}</p>`),
  ].join("");
  canvas.innerHTML = `
    <h1 class="mode-title">Proposals</h1>
    <p class="caption">${esc(noteLine)}</p>
    <p>Staged through the gateway, diffed against the current pages at build time. Oldest first — the head of the queue is the longest waiting.</p>
    ${PROPOSALS.proposals.length ? cards : `<div class="empty-note">No staged proposals are awaiting a decision in this build.${PROPOSALS.source_note ? ` ${esc(PROPOSALS.source_note)}` : ""}</div>`}
    ${footnote}`;
  defaultInspector(`<p class="caption">Staged proposals live in staging/proposed/ as a proposed page text beside its gateway manifest (proposer, task, plan hash, check verdicts). This view only displays them — decisions are made in chat and executed through the gateway.</p>`);
}

/* ---------------- Mode: Trails (item 62a) ----------------
   Authored reading paths over the typed-edge graph. The walk's
   state is serialised in the URL — #/trails/<id>?stack=<page,
   page,...>&at=<n>, the stacked-notes form — so a trail link
   resumes exactly where it was left; lenslib.trail_url is the
   canonical serialiser this mirrors. The stack in the address
   is authoritative: a link from an older build still walks the
   pages it names (register notes/types fill in where the page
   is still a trail step). */
function trailHash(trail, at) {
  const stack = trail.steps.map(s => encodeURIComponent(s.page)).join(",");
  return `#/trails/${encodeURIComponent(trail.id)}?stack=${stack}&at=${at}`;
}
function trailStepsFor(trail, params) {
  if (!params || !params.stack) return trail.steps;
  const ids = params.stack.split(",").map(s => { try { return decodeURIComponent(s); } catch (e) { return s; } }).filter(Boolean);
  if (!ids.length) return trail.steps;
  return ids.map(id => {
    const reg = trail.steps.find(s => s.page === id);
    if (reg) return reg;
    const p = PAGES[id];
    return { page: id, title: p ? p.title : id, type: p ? p.type : "", section: p ? p.section : "", via: null, note: "" };
  });
}
function renderTrails(selectedId, params) {
  const trail = (TRAILS.trails || []).find(t => t.id === selectedId);
  if (!trail) {
    const cards = (TRAILS.trails || []).map(t => `
    <div class="card">
      <h3>${esc(t.title)}</h3>
      <p>${esc(t.summary || "")}</p>
      <p class="trail-strip">${t.steps.map((s, i) => `${i ? `<span class="trail-hop">— ${esc(s.via || "link")} →</span> ` : ""}${esc(s.title)}`).join(" ")}</p>
      <div class="card-actions"><a class="btn btn-primary" href="${trailHash(t, 0)}">Walk this trail</a></div>
    </div>`).join("");
    const dropped = (TRAILS.dropped || []).map(d => `<p class="caption">Not rendered: <span class="mono">${esc(d.id)}</span> — ${esc((d.reasons || []).join("; "))}</p>`).join("");
    canvas.innerHTML = `
    <h1 class="mode-title">Trails</h1>
    <p class="caption">${esc(TRAILS.note || "")}</p>
    <p>Reading paths authored over the graph's typed edges — each hop names the edge it walks. The path lives in the URL, so a trail can be resumed or shared inside the portal.</p>
    ${(TRAILS.trails || []).length ? cards : `<div class="empty-note">No trails are authored in this build.</div>`}
    ${dropped}`;
    defaultInspector(`<p class="caption">Trails are authored in tools/lens/trails.json and validated at build against the edge table. A trail whose hop disappears is dropped with its reason — never quietly rerouted.</p>`);
    return;
  }
  const steps = trailStepsFor(trail, params || {});
  let at = parseInt((params && params.at) || "0", 10);
  if (isNaN(at) || at < 0) at = 0;
  if (at >= steps.length) at = steps.length - 1;
  const cur = steps[at];
  const prevStep = at > 0 ? steps[at - 1] : null;
  const regTrail = { id: trail.id, steps };
  const strip = steps.map((s, i) => `
    ${i ? `<span class="trail-hop">— ${esc(s.via || "link")} →</span>` : ""}
    <a class="trail-stop${i === at ? " trail-stop-current" : ""}" href="${trailHash(regTrail, i)}"${i === at ? ` aria-current="step"` : ""}>${esc(s.title)}</a>`).join(" ");
  canvas.innerHTML = `
    <p class="page-breadcrumb"><a href="#/trails">Trails</a> › ${esc(trail.title)}</p>
    <h1 class="mode-title">${esc(trail.title)}</h1>
    <p>${esc(trail.summary || "")}</p>
    <p class="trail-strip">${strip}</p>
    <div class="card">
      <p class="caption" style="letter-spacing:.08em;text-transform:uppercase">Step ${at + 1} of ${steps.length}${cur.type ? ` · ${esc(cur.type)}` : ""}</p>
      <h3>${pageLink(cur.page, cur.title)}</h3>
      ${prevStep ? `<p class="trail-arrive">You arrived via a <span class="mono">${esc(cur.via || "link")}</span> edge from ${esc(prevStep.title)}.</p>` : `<p class="trail-arrive">The trail starts here.</p>`}
      ${cur.note ? `<p>${esc(cur.note)}</p>` : ""}
      <div class="card-actions">
        <a class="btn btn-primary" href="#/read/${encodeURIComponent(cur.page)}">Open this page</a>
        ${at > 0 ? `<a class="btn" href="${trailHash(regTrail, at - 1)}">Previous step</a>` : ""}
        ${at < steps.length - 1 ? `<a class="btn" href="${trailHash(regTrail, at + 1)}">Next step</a>` : ""}
      </div>
    </div>
    <p class="caption">This walk is in the URL (stack + step), so the link above resumes it exactly here.</p>`;
  defaultInspector(`<p class="caption">Every hop in a trail is a real edge in the built graph, validated at build time; the edge type at each hop is the graph's own type for that link.</p>`);
}

/* ---------------- Mode: Cards ---------------- */
let cardCategory = store("lens-cards-cat") || "Sources";
function cardPool() {
  if (cardCategory === "Recent") {
    return [...CARDS.cards].sort((a, b) => (b.updated || "").localeCompare(a.updated || "")).slice(0, 12);
  }
  if (cardCategory === "Decisions") {
    return DECISIONS.decisions.map(d => ({ id: "decision-register", title: d.title, type: "decision", category: "Decisions", summary: d.detail, no_summary: false, why: null, updated: d.date, source_path: null, related: [] }));
  }
  return CARDS.cards.filter(c => c.category === cardCategory);
}
function renderCards() {
  const cats = ["Sources", "Entities", "Concepts", "Syntheses", "Queries", "Decisions", "Recent"];
  const pool = cardPool();
  let idx = parseInt(store(`lens-cards-pos-${cardCategory}`) || "0", 10);
  if (isNaN(idx) || idx >= pool.length) idx = 0;
  const c = pool[idx];
  const cardHtml = c ? `
    <div class="card deck-card">
      <p class="caption" style="letter-spacing:.08em;text-transform:uppercase">${esc(c.category)} · ${esc(c.type)}</p>
      <h3>${esc(c.title)}</h3>
      ${c.no_summary ? `<p>No summary yet — open the page to read it in full.</p>` : `<p>${esc(c.summary || "")}</p>`}
      ${c.why ? `<p class="why">${esc(c.why)}</p>` : ""}
      <div class="chip-row">${c.updated ? `<span class="chip">Updated ${esc(c.updated)}</span>` : ""}${c.category === "Decisions" ? chip("decided", "Decided") : ""}</div>
      ${c.source_path ? `<p class="caption">Source: <span class="mono">${esc(c.source_path)}</span> — raw bodies open through the gateway.</p>` : ""}
      <div class="card-actions">
        <a class="btn btn-primary" href="#/read/${encodeURIComponent(c.id)}">Open</a>
        ${(c.related || []).map(r => `<a class="btn" href="#/read/${encodeURIComponent(r.id)}">Related: ${esc(r.title.length > 26 ? r.title.slice(0, 25) + "…" : r.title)}</a>`).join("")}
      </div>
    </div>
    <div class="deck-nav">
      <button class="btn" id="card-prev" ${idx === 0 ? "disabled" : ""}>Previous</button>
      <span class="caption">Card ${idx + 1} of ${pool.length} · ${esc(cardCategory)}</span>
      <button class="btn" id="card-next" ${idx >= pool.length - 1 ? "disabled" : ""}>Next</button>
    </div>` : `<div class="empty-note">No cards in this category yet.</div>`;
  canvas.innerHTML = `
    <h1 class="mode-title">Cards</h1>
    <div class="filter-chips">${cats.map(x => `<button class="chip" data-cat="${esc(x)}" aria-pressed="${cardCategory === x}">${esc(x)}</button>`).join("")}</div>
    ${cardHtml}`;
  canvas.querySelectorAll("[data-cat]").forEach(b => b.addEventListener("click", () => { cardCategory = b.getAttribute("data-cat"); store("lens-cards-cat", cardCategory); renderCards(); }));
  const prev = document.getElementById("card-prev"), next = document.getElementById("card-next");
  if (prev) prev.addEventListener("click", () => { store(`lens-cards-pos-${cardCategory}`, String(idx - 1)); renderCards(); });
  if (next) next.addEventListener("click", () => { store(`lens-cards-pos-${cardCategory}`, String(idx + 1)); renderCards(); });
  defaultInspector(`<p class="caption">Card summaries come from the page lede, then the index line, then nothing — the interface never invents a summary. Deck position is a device preference only.</p>`);
}

/* ---------------- Search + Ask ---------------- */
function searchLanes(q) {
  facetStateFor(q);
  return _searchLanes(q, facetFilters);
}
function _searchLanes(q, filters) {
  const terms = tokenize(q);
  const fullBm25 = bm25Rank(terms);
  const fullHybrid = hybridRank(terms);
  // The facet pool: every doc either ranked lane found (post-
  // severance). Counts and narrowing both work on this pool.
  const poolSet = new Set([...fullBm25, ...fullHybrid].map(r => r.di));
  const pool = [...poolSet].sort((a, b) => a - b);
  const narrow = list => list.filter(r => facetPassesJs(docFacetsOf(r.di), filters));
  const decorate = r => {
    const doc = SEARCH.docs[r.di];
    return { ...r, doc,
             passage: pickPassageJs(r.di, terms),
             snippet: makeSnippet(SEARCH.texts[r.di], terms) };
  };
  const bm25 = narrow(fullBm25).slice(0, 10).map(decorate);
  const hybrid = narrow(fullHybrid).slice(0, 10).map(decorate);
  const qset = new Set(terms);
  const idxLane = [];
  const seenIdx = new Set();
  for (const e of SEARCH.index_entries) {
    const lt = new Set(tokenize(e.line));
    if ([...qset].some(t => lt.has(t))) {
      for (const pid of e.page_ids) {
        if (!seenIdx.has(pid)) { seenIdx.add(pid); idxLane.push({ id: pid, line: e.line }); }
      }
    }
  }
  const needle = q.trim().toLowerCase();
  const exactPages = [], exactRaw = [];
  if (needle.length >= 2) {
    for (const p of SEARCH.exact.pages) {
      if (p.id === needle || p.title.toLowerCase().includes(needle) || p.path.toLowerCase().includes(needle)) exactPages.push(p);
    }
    const isHashy = /^[0-9a-f]{4,}$/.test(needle);
    for (const r of SEARCH.exact.raw) {
      if (r.path.toLowerCase().includes(needle) || (isHashy && r.sha256 && r.sha256.includes(needle))) exactRaw.push(r);
    }
  }
  let expansion = [];
  const topId = bm25.length ? bm25[0].doc.id : (idxLane.length ? idxLane[0].id : null);
  if (topId && ADJ[topId]) {
    const hitIds = new Set(bm25.map(r => r.doc.id));
    expansion = ADJ[topId].filter(r => !hitIds.has(r.other)).slice(0, 5)
      .map(r => ({ id: r.other, why: signalWords(r), from: topId }));
  }
  return { terms, bm25, hybrid, idxLane, exactPages, exactRaw, expansion,
           pool, facetCounts: facetCountsJs(pool, filters), filters };
}
function docResultHtml(r) {
  const d = r.doc;
  const title = d.id ? pageLink(d.id, d.title) : esc(d.title);
  /* Passage-level result (item 57): the matched passage itself,
   * with a deep link to the heading it sits under; the one-line
   * snippet is the fallback when no passage holds a query term.
   * The freshness line (fold-in 2) renders only when lenslib
   * computed one at build — silence is no adverse signal on
   * record, never a claim of freshness. */
  const pas = r.passage;
  const body = pas
    ? `<p class="snippet passage">${esc(pas.text)}</p>${pas.anchor && d.id ? `<p class="passage-under">under <a href="#/read/${encodeURIComponent(d.id)}/${encodeURIComponent(pas.anchor)}">§ ${esc(pas.heading)}</a></p>` : ""}`
    : `<p class="snippet">${esc(r.snippet)}</p>`;
  return `<div class="result"><span class="result-title">${title}</span> <span class="chip chip-info">${esc(d.type)}</span>
    ${body}${d.fresh ? `<p class="fresh-line">${esc(d.fresh)}</p>` : ""}<p class="result-path">${esc(d.path)} · score ${r.score.toFixed(2)}</p></div>`;
}
/* The facet rail + the removable filter stack (item 56). Counts
 * come from the live pool (facetCountsJs); a zero-count value is
 * rendered greyed and inert — narrowing can never dead-end.
 * Morville's rules (wave-7 find 2): counts always visible, top
 * values by population, selected values restated as a removable
 * stacking-chip stack above the results. */
function facetRailHtml(L) {
  if (!(SEARCH.facets || []).length || !L.pool.length) return "";
  /* The stack always states the owner's actual filter state
   * (module facetFilters) — even when a ladder rung widened the
   * view, the chips show what is really selected. */
  const stack = [];
  for (const dim of Object.keys(facetFilters)) {
    const label = ((SEARCH.facets || []).find(f => f.key === dim) || {}).label || dim;
    for (const v of facetFilters[dim]) {
      stack.push(`<button class="chip chip-filter" data-facet-toggle="${dim}::${encodeURIComponent(v)}" title="Remove this filter">${esc(label)}: ${esc(v)} ×</button>`);
    }
  }
  const groups = (SEARCH.facets || []).map(dim => {
    const counts = L.facetCounts[dim.key] || new Map();
    const selected = facetFilters[dim.key] || new Set();
    const rows = [...counts.entries()]
      .sort((a, b) => (b[1] - a[1]) || (a[0] < b[0] ? -1 : 1));
    const shown = rows.filter(([v]) => selected.has(v))
      .concat(rows.filter(([v]) => !selected.has(v)).slice(0, FACET_TOP - rows.filter(([v]) => selected.has(v)).length));
    if (!shown.length) return "";
    const vals = shown.map(([v, c]) => {
      if (c === 0 && !selected.has(v)) return `<span class="facet-val facet-zero" aria-disabled="true">${esc(v)} <span class="facet-count">0</span></span>`;
      return `<button class="facet-val${selected.has(v) ? " facet-on" : ""}" data-facet-toggle="${dim.key}::${encodeURIComponent(v)}" aria-pressed="${selected.has(v)}">${esc(v)} <span class="facet-count">${c}</span></button>`;
    }).join("");
    return `<div class="facet-group"><h4>${esc(dim.label)}</h4>${vals}</div>`;
  }).join("");
  if (!groups && !stack.length) return "";
  return `<div class="facet-block">
    ${stack.length ? `<div class="facet-stack"><span class="caption">Narrowed by:</span> ${stack.join(" ")} <button class="chip" data-facet-clear="1">Clear all</button></div>` : ""}
    <div class="facet-rail">${groups}</div>
  </div>`;
}
/* Page-name matches for the merged search (layout review,
   fix 3): title or id contains the query text. Shown as the first
   lane, ahead of every ranked lane. */
function nameMatches(q) {
  const needle = (q || "").trim().toLowerCase();
  if (needle.length < 2) return [];
  return Object.values(PAGES)
    .filter(p => p.title.toLowerCase().includes(needle) || p.id.toLowerCase().includes(needle))
    .sort((a, b) => a.title.localeCompare(b.title))
    .slice(0, 8);
}
/* The result block shared by the Search renderer and the merged Ask
   view: page-name matches first, then the unblended ranked lanes in
   the router's order, then graph expansion. */
function searchLanesHtml(q) {
  const widened = searchWithLadder(q);
  const L = widened.lanes;
  const names = nameMatches(q);
  const qTerms = tokenize(q);
  /* Did-you-mean + phrase suggestions from the corpus's own
   * vocabulary, and facet-tagged query terms (item 59) — shown
   * alongside the results, never applied silently. */
  const sug = suggestionsFor(q, qTerms);
  const correctedQ = c => q.replace(new RegExp(`\\b${c.from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i"), c.to);
  const sugHtml = (sug.corrections.length || sug.phrases.length) ? `<div class="suggest-strip">
    ${sug.corrections.map(c => `<span>Did you mean <a href="#/ask?q=${encodeURIComponent(correctedQ(c))}">${esc(c.to)}</a> <span class="caption">(for “${esc(c.from)}” — a term this corpus actually uses)</span></span>`).join(" ")}
    ${sug.phrases.map(p => `<span>${p.kind === "tag" ? "Tag" : p.kind === "page" ? "Page" : "Heading"}: ${p.id ? `<a href="#/read/${encodeURIComponent(p.id)}">${esc(p.text)}</a>` : `<a href="#/ask?q=${encodeURIComponent(p.text)}">${esc(p.text)}</a>`}</span>`).join(" ")}
  </div>` : "";
  const tagTerms = queryFacetTags(qTerms).filter(t => !((facetFilters[t.dim] || new Set()).has(t.value)));
  const tagHtml = tagTerms.length ? `<div class="suggest-strip"><span class="caption">In the corpus's vocabulary:</span> ${tagTerms.map(t => `<button class="chip" data-facet-apply="${t.dim}::${encodeURIComponent(t.value)}" title="Narrow to this ${esc(t.dimLabel.toLowerCase())}">“${esc(t.value)}” is a ${esc(t.dimLabel.toLowerCase())} — narrow to it</button>`).join(" ")}</div>` : "";
  const ladderHtml = widened.note ? `<p class="ladder-note">${esc(widened.note)}</p>` : "";
  const multiword = L.terms.length > 1;
  const laneOrder = multiword ? ["bm25", "hybrid", "index", "exact"] : ["index", "exact", "bm25", "hybrid"];
  const laneHtml = {
    bm25: L.bm25.length ? `<div class="lane"><h3>${L.loosest ? "Loosest full-text (substring)" : "Full-text (BM25)"}</h3>${L.bm25.map(docResultHtml).join("")}</div>` : "",
    hybrid: L.hybrid.length ? `<div class="lane"><h3>Hybrid (BM25 + graph)</h3><p class="caption">Text score blended with a personalized-PageRank walk over the wikilink graph, seeded by the strongest text hits — the same hybrid ranking as scripts/wiki_search.py (parity-checked at build). Pages found by the walk alone are marked “via graph”.</p>${L.hybrid.map(docResultHtml).join("")}</div>` : "",
    index: L.idxLane.length ? `<div class="lane"><h3>Index</h3>${L.idxLane.map(x => `<div class="result"><span class="result-title">${pageLink(x.id)}</span><p class="snippet">${esc(x.line.replace(/^-\s*/, ""))}</p></div>`).join("")}</div>` : "",
    exact: (L.exactPages.length || L.exactRaw.length) ? `<div class="lane"><h3>Exact</h3>
      ${L.exactPages.map(p => `<div class="result"><span class="result-title">${pageLink(p.id, p.title)}</span><p class="result-path">${esc(p.path)}</p></div>`).join("")}
      ${L.exactRaw.slice(0, 8).map(r => `<div class="result"><span class="result-title mono">${esc(r.path)}</span><p class="result-path">${r.sha256 ? esc(r.sha256.slice(0, 16)) + "…" : ""} · ${esc(r.hash_state)} · raw bodies open through the gateway</p></div>`).join("")}</div>` : "",
  };
  let results = (names.length ? `<div class="lane"><h3>Pages by name</h3>${names.map(p => `<div class="result"><span class="result-title">${pageLink(p.id)}</span><p class="result-path">${esc(p.id)} · ${esc(p.type)}</p></div>`).join("")}</div>` : "")
    + laneOrder.map(k => laneHtml[k]).join("");
  if (L.expansion.length) {
    results += `<div class="lane"><h3>Graph expansion <span class="chip chip-info">expansion</span></h3>
      <p class="caption">Neighbours of the strongest hit (${esc(PAGES[L.expansion[0].from] ? PAGES[L.expansion[0].from].title : L.expansion[0].from)}), labelled as expansions — never blended into the ranked lanes.</p>
      ${L.expansion.map(x => `<div class="result"><span class="result-title">${pageLink(x.id)}</span><p class="snippet">${esc(x.why)}</p></div>`).join("")}</div>`;
  }
  /* Zero results is a designed surface, not a bare end (item 58):
     Baymard's five recovery strategies + save-the-failed-search. */
  if (!results) results = zeroResultsHtml(q);
  return sugHtml + tagHtml + ladderHtml + facetRailHtml(L)
    + `<p class="caption">Lanes are shown unblended; lane order is the router's decision (${multiword ? "topical question: full-text leads" : "short/exact question: index and exact lead"}).</p>` + results;
}
function renderSearch(q) {
  q = q || "";
  rerenderSearch = () => renderSearch(q);
  const results = q ? searchLanesHtml(q) : "";
  canvas.innerHTML = `
    <h1 class="mode-title">Search</h1>
    <form class="ask-box" id="search-page-form"><input id="search-page-input" type="search" value="${esc(q)}" placeholder="Search the wiki…" aria-label="Search the wiki"><button class="btn btn-primary" type="submit">Search</button></form>
    <p class="caption">This is the Owner's local lookup over the build's postings. It scores with the same BM25 and the same BM25+PageRank hybrid as scripts/wiki_search.py (both parity-checked at build).</p>
    ${results}`;
  bindSearchSurface(canvas);
  const form = document.getElementById("search-page-form");
  form.addEventListener("submit", ev => { ev.preventDefault(); location.hash = "#/search?q=" + encodeURIComponent(document.getElementById("search-page-input").value); });
  if (q) wireZeroState(q);
  defaultInspector(`<p class="caption">Why these results? Each lane is labelled: Index (the catalogue), BM25 (full text), Exact (ids, paths, hashes), Graph expansion (neighbours, never blended in).</p>`);
}
/* The merged Ask/Search action (layout review, fix 3): one box —
   the extractive answer, then the search lanes with page-name matches
   first. The page-list box and legacy #/search links land here too. */
let askQuery = "";
function runAsk(q) {
  askQuery = q || "";
  rerenderSearch = () => runAsk(askQuery);
  const res = document.getElementById("ask-results");
  if (res) {
    res.innerHTML = q && q.trim() ? `<h2 style="font-family:var(--font-display)">Search results</h2>` + searchLanesHtml(q) : "";
    bindSearchSurface(res);
  }
  if (q && q.trim()) { logQuery(q); wireZeroState(q); }
  answerQuestion(q);
}
function renderAsk(prefill) {
  canvas.innerHTML = `
    <h1 class="mode-title">Ask</h1>
    <p class="caption">One box for search and questions: page-name matches first, then the ranked lanes, then an extractive answer quoted from the pages it used. The gateway Ask (Ask the Agent, below) composes full answers and logs the exchange in the Black Box.</p>
    <form class="ask-box" id="ask-form"><input id="ask-input" type="text" placeholder="Search or ask the wiki…" value="${esc(prefill || "")}" aria-label="Ask a question"><button class="btn btn-primary" type="submit">Ask</button></form>
    <div id="ask-answer"></div>
    <div id="ask-results"></div>
    <section class="ask-agent">
      <h2 style="font-family:var(--font-display)">Ask the Agent</h2>
      <p>Questions go to the agent through the gateway, and he picks them up regularly — there is no instant answer here. When he answers, the answer appears in the history below and as a page in this Lens.</p>
      <form class="ask-box" id="agent-ask-form"><textarea id="agent-question" placeholder="Ask the Agent a question…" aria-label="Ask the Agent a question"></textarea><select id="agent-mode" aria-label="Ask mode"><option value="answer" selected>Answer — composed, cited</option><option value="search">Search — passages only</option><option value="deep-research">Deep Research — decomposed</option></select><button class="btn btn-primary" type="submit">Ask the Agent</button></form>
      <p class="caption">Mode: <strong>Answer</strong> composes one cited answer; <strong>Search</strong> returns the supporting passages only, with no composed answer; <strong>Deep Research</strong> decomposes the question and answers each part separately.</p>
      <div id="agent-ask-status"></div>
    </section>
    <div id="qa-history"></div>`;
  const form = document.getElementById("ask-form");
  form.addEventListener("submit", ev => { ev.preventDefault(); runAsk(document.getElementById("ask-input").value); });
  const agentForm = document.getElementById("agent-ask-form");
  if (agentForm) agentForm.addEventListener("submit", ev => { ev.preventDefault(); submitAgentQuestion(); });
  renderQaHistory();
  loadQaHistory();
  if (prefill) runAsk(prefill);
  /* A zero-results "Ask the Agent" click from another view parks the
     question in sessionStorage; land it in the Ask the Agent box. */
  let agentPrefill = "";
  try {
    agentPrefill = sessionStorage.getItem("lens-agent-prefill") || "";
    if (agentPrefill) sessionStorage.removeItem("lens-agent-prefill");
  } catch (e) { agentPrefill = ""; }
  if (agentPrefill) {
    const mq = document.getElementById("agent-question");
    if (mq && !mq.value) mq.value = agentPrefill;
  }
  defaultInspector(`<p class="caption">An answer shows its evidence state, the sources it used, and what it looked at but did not use. Insufficient evidence is stated, never filled from model memory.</p>`);
}
function qaCitationId(c) {
  if (c == null) return "";
  if (typeof c === "string") return c;
  return c.id || c.page_id || c.page || "";
}
function renderQaHistory() {
  const el = document.getElementById("qa-history");
  if (!el) return;
  if (!QA_HISTORY || !QA_HISTORY.length) {
    el.innerHTML = `
      <h2 style="font-family:var(--font-display)">Question history</h2>
      <p class="caption">No questions yet — the first one is yours.</p>`;
    return;
  }
  el.innerHTML = `
    <h2 style="font-family:var(--font-display)">Question history</h2>` +
    QA_HISTORY.map(entry => {
      const answered = entry.status === "answered" || !!entry.answer;
      const citations = Array.isArray(entry.citations) ? entry.citations : [];
      const chips = citations.map(c => {
        const cid = qaCitationId(c);
        if (!cid) return "";
        const label = (typeof c === "object" && c !== null && (c.title || c.label)) || (PAGES[cid] ? PAGES[cid].title : cid);
        return `<a class="cite-chip" href="#/read/${encodeURIComponent(cid)}">${esc(label)}</a>`;
      }).join("");
      const modeLabel = { "search": "Search", "answer": "Answer", "deep-research": "Deep Research" }[entry.mode];
      const verdictChip = entry.trust_verdict === "ok" ? chip("verified", "Trust · ok")
        : entry.trust_verdict === "hold" ? chip("atrisk", "Trust · hold")
        : entry.trust_verdict === "review" ? chip("stale", "Trust · review") : "";
      const groundedChip = (typeof entry.grounded_claims === "number")
        ? chip("info", `grounded in ${entry.grounded_claims} claim${entry.grounded_claims === 1 ? "" : "s"}`) : "";
      const metaChips = (modeLabel || verdictChip || groundedChip) ? `<div class="chip-row">${modeLabel ? chip("info", "Mode · " + modeLabel) : ""}${verdictChip}${groundedChip}</div>` : "";
      const verdictNote = !answered ? "" : entry.trust_verdict === "hold" && !entry.abstained
        ? `<p class="qa-warning">Weak evidence — this answer rests on thin or low-scoring citations. Treat it with care.</p>`
        : entry.trust_verdict === "review"
        ? `<p class="qa-warning">Conflicting evidence — the cited pages disagree, or a cited page carries an open contradiction. Review before relying on this answer.</p>` : "";
      const details = Array.isArray(entry.citation_details) ? entry.citation_details : [];
      const passages = details.filter(d => d && d.passage).map(d => {
        const cid = qaCitationId(d);
        const label = (PAGES[cid] ? PAGES[cid].title : cid) + (typeof d.score === "number" ? ` · relevance ${d.score}` : "");
        return `<div class="excerpt">“${esc(d.passage)}”<a class="cite-chip" href="#/read/${encodeURIComponent(cid)}">${esc(label)}</a></div>`;
      }).join("");
      return `
      <div class="card qa-entry">
        <p class="qa-question">${esc(entry.question || "")}</p>
        <p class="caption">Asked by ${esc(entry.asker || "")}${entry.asked_at ? ` · ${esc(entry.asked_at)}` : ""}</p>
        ${metaChips}
        ${answered ? `
        ${entry.answered_at ? `<p class="caption">Answered ${esc(entry.answered_at)}</p>` : ""}
        <p>${esc(entry.answer || "")}</p>
        ${verdictNote}
        ${passages}
        ${chips ? `<p>${chips}</p>` : ""}` : `
        <div class="chip-row">${chip("open", "Waiting for the agent")}</div>`}
      </div>`;
    }).join("");
}
function loadQaHistory() {
  if (typeof fetch !== "function") return;
  let pending;
  try { pending = fetch("data/qa.json"); } catch (e) { return; }
  if (!pending || typeof pending.then !== "function") return;
  pending
    .then(res => (res && typeof res.json === "function") ? res.json() : null)
    .then(data => {
      if (data && Array.isArray(data.entries)) {
        QA_HISTORY = data.entries;
        renderQaHistory();
      }
    })
    .catch(() => {});
}
function submitAgentQuestion() {
  const statusEl = document.getElementById("agent-ask-status");
  const setStatus = msg => { if (statusEl) statusEl.textContent = msg; };
  const fail = () => setStatus("That didn't reach the question store — nothing was saved. If you are viewing a local preview, there is no live question store behind it; try again from the deployed Lens.");
  const input = document.getElementById("agent-question");
  const value = input ? String(input.value || "").trim() : "";
  if (!value) { setStatus("Write a question first — nothing was sent."); return; }
  const modeEl = document.getElementById("agent-mode");
  const mode = modeEl && ["search", "answer", "deep-research"].includes(modeEl.value) ? modeEl.value : "answer";
  if (typeof fetch !== "function") { fail(); return; }
  let pending;
  try {
    pending = fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: value, mode: mode }),
    });
  } catch (e) { fail(); return; }
  if (!pending || typeof pending.then !== "function") { fail(); return; }
  pending
    .then(res => {
      if (!res || typeof res.json !== "function") throw new Error("no-json-response");
      return res.json().then(() => res.status);
    })
    .then(status => {
      if (status === 201) setStatus("Question received — The agent picks questions up regularly; your answer will appear here.");
      else fail();
    })
    .catch(() => fail());
}
function answerQuestion(q) {
  const box = document.getElementById("ask-answer");
  if (!q || !q.trim()) { box.innerHTML = ""; return; }
  const L = searchLanes(q);
  const hits = L.bm25.filter(r => r.doc.id);
  const lanesSearched = "Index · BM25 full-text · Exact · Graph expansion";
  if (!hits.length) {
    box.innerHTML = `
      <div class="chip-row">${chip("open", "Insufficient evidence")}</div>
      <p>The wiki does not hold enough verified material to answer this. Nothing has been guessed. You can stage a research proposal instead.</p>
      <p class="caption">Lanes searched: ${lanesSearched}. Proposals are staged through the gateway; in this build, note the gap and it will be filed from the wiki log.</p>`;
    return;
  }
  const used = hits.slice(0, 3);
  const notUsed = hits.slice(3, 8);
  const strong = used.length >= 2 && used[0].score >= 4;
  const state = strong ? chip("verified", "Answered") : chip("open", "Partially answered");
  const excerpts = used.map(r => {
    const text = stripFrontmatter(SEARCH.texts[r.di]);
    const snip = makeSnippet(text, L.terms, 420);
    return `<div class="excerpt">${esc(snip)}<a class="cite-chip" href="#/read/${encodeURIComponent(r.doc.id)}">${esc(r.doc.title)} · wiki page</a></div>`;
  }).join("");
  const claimPages = new Set((MEMORY.claims || []).map(c => c.claim_id));
  const groundedN = used.filter(r => claimPages.has(r.doc.path)).length;
  box.innerHTML = `
    <div class="chip-row">${state}${chip("info", `grounded in ${groundedN} claim${groundedN === 1 ? "" : "s"}`)}</div>
    <p class="caption">Extractive answer — the passages below are quoted from the pages cited, not composed. Lanes searched: ${lanesSearched}.</p>
    ${excerpts}
    <h3 style="font-family:var(--font-display)">Sources used</h3>
    <ul>${used.map(r => `<li>${pageLink(r.doc.id)} <span class="caption">(${esc(r.doc.path)})</span></li>`).join("")}</ul>
    ${notUsed.length ? `<h3 style="font-family:var(--font-display)">Looked at, not used</h3><ul>${notUsed.map(r => `<li>${esc(r.doc.title)} <span class="caption">(${esc(r.doc.path)})</span></li>`).join("")}</ul>` : ""}`;
}

/* ---------------- Mode: Memory (memory transparency) ----------------
   The Sakana "My Fish" pattern, idea only and re-implemented: over
   the artefact scripts/wiki_memory_transparency.py builds from the
   wiki's existing records — the claims list, each claim's history,
   its connections (pages that cite it, Ask events grounded in it),
   and the Ask events themselves with the pages each answer used. */
function renderMemory() {
  const claims = MEMORY.claims || [];
  const history = MEMORY.claim_history || {};
  const connections = MEMORY.connections || [];
  const events = MEMORY.ask_events || [];
  canvas.innerHTML = `
    <h1 class="mode-title">Memory</h1>
    <p class="caption">What the wiki remembers, shown from its own records: the claim index, the Ask door's Q&A log, notices, outcomes and re-verifications. Nothing here is generated prose — every row is a record, and a view with no records says so.</p>
    <h2 style="font-family:var(--font-display)">Claims · ${claims.length}</h2>
    ${claims.length ? claims.map(c => `
      <div class="card">
        <p>${esc(c.text || "")}</p>
        <p class="caption">${pageLinkByPath(c.claim_id)} · stated ${esc(c.stated || "—")} · supports ${esc(c.supports)} · contradicts ${esc(c.contradicts)} · verified ${esc(c.verified_n)}${c.superseded ? " · superseded" : ""} · hash <span class="mono">${esc(c.hash || "")}</span></p>
      </div>`).join("") : `<p class="caption">No claims in the claim index yet.</p>`}
    <h2 style="font-family:var(--font-display)">Claim history</h2>
    ${Object.keys(history).length ? Object.keys(history).sort().map(cid => `
      <div class="card"><h3>${pageLinkByPath(cid)}</h3>
      <ul>${(history[cid] || []).map(e => `<li><span class="mono">${esc(e.event || "")}</span> · ${esc(e.date || "—")}${e.notice ? ` · ${esc(e.notice)}` : ""}${e.outcome ? ` · ${esc(e.outcome)}` : ""}${e.result ? ` · ${esc(e.result)}` : ""}${e.reason ? `<br><span class="caption">${esc(e.reason)}</span>` : ""}</li>`).join("")}</ul></div>`).join("") : `<p class="caption">No claim-history events derivable from the records.</p>`}
    <h2 style="font-family:var(--font-display)">Connections</h2>
    ${connections.length ? connections.map(c => `
      <div class="card"><h3>${pageLinkByPath(c.claim_id)}</h3>
      <p class="caption">Cited by: ${(c.cited_by_pages || []).length ? c.cited_by_pages.map(pp => pageLinkByPath(pp)).join(" · ") : "no page cites it yet"}<br>
      Ask events grounded in it: ${(c.ask_event_ids || []).length ? c.ask_event_ids.map(esc).join(", ") : "none"} · supports ${esc(c.supports)} · contradicts ${esc(c.contradicts)}</p></div>`).join("") : `<p class="caption">No claim connections derivable from the records.</p>`}
    <h2 style="font-family:var(--font-display)">Ask events · ${events.length}</h2>
    ${events.length ? events.map(e => `
      <div class="card qa-entry">
        <p class="qa-question">${esc(e.question || "")}</p>
        <p class="caption">Asked by ${esc(e.asker || "")}${e.asked_at ? ` · ${esc(e.asked_at)}` : ""} · ${esc(e.status || "")}</p>
        <div class="chip-row">${chip("info", `grounded in ${e.grounded_claims || 0} claim${(e.grounded_claims || 0) === 1 ? "" : "s"}`)}</div>
        <p class="caption">Pages used: ${(e.cited_pages || []).length ? e.cited_pages.map(pp => pageLinkByPath(pp)).join(" · ") : "none recorded"}</p>
      </div>`).join("") : `<p class="caption">No Ask events recorded yet.</p>`}`;
  defaultInspector(`<p class="caption">The Memory view renders evaluation/memory-transparency.json, built by scripts/wiki_memory_transparency.py from the claim index and the Ask log. Rebuild it with the Lens.</p>`);
}

/* ---------------- Mode: Black Box ---------------- */
function renderBlackBox() {
  const g = BLACKBOX.gateway_ledger;
  const w = BLACKBOX.watcher_ledger || { status: "not-started" };
  const started = g.status !== "not-started";
  const headHash = g.head ? String(g.head).slice(0, 12) : "";
  const banner = g.status === "broken"
    ? `<div class="bb-banner broken">Chain broken at entry ${esc(g.first_bad_seq)}. Entries after ${esc(g.first_bad_seq)} are not trusted until this is resolved.</div>`
    : g.status === "verified"
      ? `<div class="bb-banner">Chain verified · ${g.entries_checked} entries · head ${esc(headHash)}… · git HEAD ${esc(HEAD_SHORT)} — the gateway ledger is live.</div>`
      : `<div class="bb-banner">Chain not started · 0 entries · git HEAD ${esc(HEAD_SHORT)} — the gateway ledger does not exist yet.</div>`;
  const section = (title, inner) => `<h2 style="font-family:var(--font-display)">${title}</h2>${inner}`;
  const listOr = (items, renderItem, emptyCopy) => items && items.length
    ? `<ul class="bb-list">${items.map(renderItem).join("")}</ul>`
    : `<div class="empty-note">${emptyCopy}</div>`;
  canvas.innerHTML = `
    <h1 class="mode-title">Black Box — flight recorder</h1>
    ${banner}
    <p>${esc(BLACKBOX.note || "")}</p>
    <p>The Black Box records through three doors: the gateway ledger (the official record), git (the inherent write trail), and a local filesystem watcher (supplementary, honestly labelled). Agents will touch the wiki only through the gateway or git, so every read and write lands in one of these records.</p>
    ${section("Sessions", listOr(BLACKBOX.sessions,
      s => `<li><strong>${esc(s.actor)}</strong> · <span class="mono">${esc(s.session_id)}</span><br><span class="caption">${esc(s.started)} → ${esc(s.last)} · ${esc(s.summary)}</span></li>`,
      started ? "No sessions recorded yet."
              : "No sessions recorded. Sessions appear when an agent first works through the gateway."))}
    ${section("Denials", listOr(BLACKBOX.denials,
      d => `<li>seq ${esc(d.seq)} · ${esc(d.ts)} · ${esc(d.actor)} · ${esc(d.action)}${d.tool ? ` · <span class="mono">${esc(d.tool)}</span>` : ""}</li>`,
      "No denials recorded. A denial is recorded as plainly as a success when one happens."))}
    ${section("Unattributed activity", listOr(BLACKBOX.unattributed,
      u => `<li>${esc(u.ts)} · ${esc(u.what || "")} <span class="caption">(watcher, unattributed-local)</span></li>`,
      started ? "No unattributed filesystem activity recorded by the watcher."
              : "No gateway session matches this activity — this queue is empty because the ledger has not started, not because activity is being hidden."))}
    ${section("Watcher gaps", listOr(BLACKBOX.watcher_gaps,
      gp => `<li>Watcher restarted ${esc(gp.restart_ts)} · last heartbeat before the gap: ${esc(gp.last_heartbeat || "unknown")}</li>`,
      w.status === "not-started"
        ? "The watcher is not installed in this build. Gap bands will be drawn here for any window the watcher is offline."
        : "No watcher gaps recorded — no offline window since the watcher started."))}`;
  defaultInspector(`<p class="caption">Chain status is a banner with numbers, never a green dot. A broken chain outranks every other Black Box display.</p>`);
}

/* ---------------- Item 65: Briefing honesty stack ----------------
   Bullet graphs (value bar + target tick + declared qualitative
   bands, zero baseline), lint-lane sparklines on ONE shared scale,
   and the re-verification forecast with the due-now claims as a
   visible leading block. All geometry is computed at build
   (stateviews.py); this code only draws it. */
function bulletSvg(b) {
  const W = 260, H = 28, g = b.geometry;
  const tones = { good: "#39463A", watch: "#4C4330", bad: "#5A3A2E" };
  let out = `<svg class="bullet-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(b.label)}: ${esc(b.value)} ${esc(b.unit || "")}, ${esc(b.target_label)}, scale 0 to ${esc(b.scale_max)}">`;
  for (const band of g.bands) {
    out += `<rect x="${(band.from * W).toFixed(1)}" y="2" width="${Math.max(0, (band.to - band.from) * W).toFixed(1)}" height="${H - 4}" fill="${tones[band.tone] || "#333"}"><title>${esc(band.label)} (${esc(band.tone)})</title></rect>`;
  }
  out += `<rect x="0" y="10" width="${(g.value_frac * W).toFixed(1)}" height="8" fill="#C9A24B"></rect>`;
  out += `<line x1="${(g.target_frac * W).toFixed(1)}" y1="4" x2="${(g.target_frac * W).toFixed(1)}" y2="${H - 4}" stroke="#F2EEE6" stroke-width="2.5"></line>`;
  out += "</svg>";
  return out;
}
function sparkSvg(entry, sharedMax) {
  const pts = entry.points || [];
  if (!pts.length) return `<span class="caption">no filings yet</span>`;
  if (pts.length === 1) {
    const y = 26 - (pts[0].value / Math.max(1, sharedMax)) * 24;
    return `<svg class="spark-svg" viewBox="0 0 100 28" role="img" aria-label="${esc(entry.label)}: ${pts[0].value} on ${esc(pts[0].date)} (one filing — a dot, not a trend)"><circle cx="50" cy="${y.toFixed(1)}" r="3" fill="#C9A24B"/></svg>`;
  }
  return `<svg class="spark-svg" viewBox="0 0 100 28" role="img" aria-label="${esc(entry.label)} sparkline, shared scale 0 to ${sharedMax}"><polyline points="${esc(entry.points_svg || "")}" fill="none" stroke="#C9A24B" stroke-width="1.6"/></svg>`;
}
function forecastHtml(f) {
  if (!f) return "";
  if (f.error) return `<section class="brief-section"><h2>Re-verification forecast</h2><p class="caption">${esc(f.error)}</p></section>`;
  const byPath = {};
  for (const id of Object.keys(PAGES)) byPath[PAGES[id].path] = id;
  const dueItems = (f.due_now || []).map(r => {
    const id = byPath[r.page];
    const label = id ? pageLink(id) : `<span class="mono">${esc(r.page)}</span>`;
    const when = r.status === "overdue" ? `overdue by ${esc(r.days_overdue)}d (due ${esc(r.due)})` : `due today (${esc(r.due)})`;
    return `<li>${label} — ${when}<br><span class="caption">${esc(r.claim)}</span></li>`;
  }).join("");
  const maxScale = Math.max(1, f.total_scheduled || 1);
  const bars = (f.weeks || []).map(w => `<div class="fc-bar" style="height:${Math.max(1, (w.due_count / maxScale) * 70).toFixed(0)}px" title="${esc(w.from)} to ${esc(w.to)}: ${w.due_count} due"></div>`).join("");
  const cum = f.cumulative_if_neglected || [];
  const stepPts = cum.map((v, i) => `${(i * 11 + 5)},${(84 - (v / maxScale) * 70).toFixed(1)}`).join(" ");
  return `<section class="brief-section"><h2>Re-verification forecast — next ${esc(f.window_days)} days</h2>
    <div class="fc-wrap">
      <div class="fc-duenow"><span class="caption">Due now — in the window, never excluded</span><span class="fc-big">${esc(f.due_now_count)} claim${f.due_now_count === 1 ? "" : "s"}</span><span class="caption">${esc(f.overdue_count)} overdue · ${esc(f.due_now_count - f.overdue_count)} due today</span></div>
      <div class="fc-bars">${bars}${cum.length ? `<svg class="fc-cum" width="${cum.length * 11}" height="84" aria-hidden="true"><polyline points="${stepPts}" fill="none" stroke="#9A927F" stroke-width="1.4" stroke-dasharray="3 2"/></svg>` : ""}</div>
    </div>
    <p class="caption">Bars: claims falling due per week, on the same count scale as the dashed line — the cumulative pile if nothing is verified (do-nothing scenario). ${esc(f.note)}</p>
    ${dueItems ? `<ul>${dueItems}</ul>` : `<p>Nothing is due. The next scheduled check is inside the window above.</p>`}</section>`;
}
function honestyHtml() {
  const h = HONESTY;
  if (!h) return "";
  const bullets = (h.bullets || []).map(b => `
    <div class="bullet-row"><span class="bullet-label">${esc(b.label)}</span>${bulletSvg(b)}<span class="bullet-value">${esc(b.value)} <span class="caption">${esc(b.target_label)}</span></span>
    <span class="bullet-note">${esc(b.note)} Bands: ${(b.bands || []).map(x => `${esc(x.label)} (${esc(x.tone)})`).join(" · ")}. Scale 0–${esc(b.scale_max)}.</span></div>`).join("");

  const ls = h.lane_series || { series: [], shared_max: 1 };
  const sparks = (ls.series || []).map(e => {
    const pts = e.points || [];
    const nums = pts.length ? `${pts[0].value} → ${pts[pts.length - 1].value} · ${pts.length} filing${pts.length === 1 ? "" : "s"} · latest ${esc(pts[pts.length - 1].date)}` : "no data yet";
    return `<div class="spark-row"><span>${esc(e.label)}</span>${sparkSvg(e, ls.shared_max)}<span class="spark-nums">${esc(nums)}<br><span class="caption">${esc(e.metric)}</span></span></div>`;
  }).join("");
  return `<section class="brief-section"><h2>Health — numbers that can change a decision</h2>
    ${bullets || `<p class="caption">No bullets computed in this build.</p>`}
    ${(h.bullet_notes || []).map(n => `<p class="caption">${esc(n)}</p>`).join("")}
    <h3 style="font-family:var(--font-display);font-size:18px;margin:18px 0 4px">Lint lanes, one scale</h3>
    ${sparks}
    <p class="caption">${esc(ls.scale_note || "")} Source filings: ${(ls.filings_used || []).map(esc).join(", ") || "none"}${(ls.filings_skipped || []).length ? ` · skipped (unreadable): ${ls.filings_skipped.map(esc).join(", ")}` : ""}. ${esc(h.chart_gate || "")}</p></section>
  ${forecastHtml(h.forecast)}`;
}

/* ---------------- Mode: State (item 63) ---------------- */
function renderState() {
  const mx = STATE.matrix, lc = STATE.lifecycle;
  let matrixHtml = `<p class="caption">No matrix in this build.</p>`;
  if (mx) {
    const cap = 48;
    const head = mx.states.map(st => `<th>${esc(st)}<span class="mx-count">${(mx.totals[st] || []).length} pages</span></th>`).join("");
    const rows = mx.topics.map(row => `<tr><th>${esc(row.topic)}<span class="mx-count">${row.total} pages</span></th>${mx.states.map(st => {
      const ids = row.cells[st] || [];
      const squares = ids.slice(0, cap).map(id => `<a class="mx-sq s-${st}" href="#/read/${encodeURIComponent(id)}" title="${esc(PAGES[id] ? PAGES[id].title : id)}"></a>`).join("");
      return `<td class="mx-cell"><span class="mx-squares">${squares}</span><span class="mx-count">${ids.length}${ids.length > cap ? ` (first ${cap} shown)` : ""}</span></td>`;
    }).join("")}</tr>`).join("");
    const totalsRow = `<tr><th>All topics<span class="mx-count">${mx.total_pages} pages</span></th>${mx.states.map(st => `<td class="mx-cell"><span class="mx-count">${(mx.totals[st] || []).length}</span></td>`).join("")}</tr>`;
    const gaps = (mx.gaps || []).map(g => `<li><strong>${esc(g.topic)}</strong> × ${esc(g.state)} — ${esc(g.meaning)}</li>`).join("");
    const unver = (mx.unverified_pages || []).map(id => pageLink(id)).join(", ");
    const due = (mx.due_pages || []).map(id => pageLink(id)).join(", ");
    matrixHtml = `
      <table class="state-table"><thead><tr><th>Topic (tag)</th>${head}</tr></thead><tbody>${rows}${totalsRow}</tbody></table>
      <p class="caption">One square per page (mosaic, not bubbles: count is the encoding). A page counts in every topic it is tagged with. ${mx.state_notes ? Object.entries(mx.state_notes).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" ") : ""} Tags on fewer than 2 pages are folded into the totals only${(mx.folded_topics || []).length ? ` (${mx.folded_topics.map(esc).join(", ")})` : ""}. Untagged pages: ${(mx.untagged_pages || []).length}.</p>
      <h3 style="font-family:var(--font-display);font-size:18px">The work list — empty cells</h3>
      ${gaps ? `<ul>${gaps}</ul>` : `<p>No empty cells in the gap columns.</p>`}
      <p><strong>Unverified pages (${(mx.unverified_pages || []).length}):</strong> ${unver || "none"}</p>
      <p><strong>Due for re-verification (${(mx.due_pages || []).length}):</strong> ${due || "none"}</p>
      <p class="caption">What this view cannot show: whether a page's citations actually support its claims. The lockfile proves a cited source has not changed; it does not prove the source says what the page claims. State is per page, not per claim.</p>`;
  }
  let lifeHtml = `<p class="caption">No lifecycle data in this build.</p>`;
  if (lc) {
    const maxCount = Math.max(1, ...(lc.prefixes || []).map(p => p.count));
    const rows = (lc.prefixes || []).map(p => {
      const depth = p.prefix.length - 1;
      const term = p.terminal_count ? ` · ends here: ${p.terminal_pages.slice(0, 4).map(id => pageLink(id)).join(", ")}${p.terminal_pages.length > 4 ? ` +${p.terminal_pages.length - 4}` : ""}` : "";
      const open = p.terminal_count && !(lc.resting_states || []).includes(p.prefix[p.prefix.length - 1]) ? ` <span class="lc-open">open loop</span>` : "";
      return `<div class="lc-row" style="padding-left:${depth * 22}px"><span class="lc-count">${p.count}</span><span class="lc-bar" style="width:${Math.max(3, (p.count / maxCount) * 130).toFixed(0)}px"></span><span class="lc-path">${p.prefix.map(esc).join(" → ")}</span><span class="lc-term">${term}${open}</span></div>`;
    }).join("");
    lifeHtml = `${rows}
      <p class="caption">${lc.record_count} lifecycle-bearing pages, aggregated by shared prefix (LifeFlow form: width = count). A path ends in a resting state (${(lc.resting_states || []).map(esc).join(", ")}) or it is an open loop — a claim the record has left mid-lifecycle. Paths are computed from the registers (claim frontmatter, the citation lockfile, the treatment and severance registers, attestation frontmatter, the re-verification history, the outcomes log) — every event on every record is in the build artefact (data/state.json) with its source named. State order is the lifecycle's canonical order (stateviews.py), stated here rather than smuggled: ${(lc.order || []).map(esc).join(" → ")}.</p>`;
  }
  const arg = STATE.argdown || { blocks: 0, pages: [] };
  canvas.innerHTML = `
    <h1 class="mode-title">State of the evidence</h1>
    <p class="stamp-line">Generated ${esc(STATE.generated_at || GENERATED_AT)} · from <code>${esc(STATE.git_head_short || HEAD_SHORT)}</code>. Computed at build from the registers; a view of record, not a source.</p>
    <section class="state-section"><h2>Evidence and gap matrix — topics × verification state</h2>${matrixHtml}</section>
    <section class="state-section"><h2>Claim histories — aggregated by lifecycle prefix</h2>${lifeHtml}</section>
    <section class="state-section"><h2>Argument maps</h2>
      ${arg.blocks ? `<p>${arg.blocks} Argdown block(s) compiled in this build, on: ${arg.pages.map(id => pageLink(id)).join(", ")}. Each map renders inside its page, under the block that is its source of truth.</p>` : `<p>No page carries an <span class="mono">\`\`\`argdown</span> block yet, so there are no maps to draw — the compiler ships with the Lens (own parser for the subset our pages would use: [statements], &lt;arguments&gt;, + support / − attack relations), and the first page that adds a block gets its map at the next build. Zero is the true count, stated rather than dressed up.</p>`}
      ${(arg.unparsed || []).length ? `<p class="caption">Lines outside the supported subset, named rather than dropped: ${arg.unparsed.map(u => `${esc(u.page)}: ${esc(u.line)}`).join("; ")}</p>` : ""}</section>`;
  defaultInspector(`<p class="caption">State-shaped views (item 63): the shape of the corpus's evidence, drawn from its registers. Empty cells and open loops are the work list.</p>`);
}

/* ---------------- Item 64: reading profile by calibration --------
   The owner's typography is set by MEASUREMENT, not preference
   (Readability Consortium: readers cannot pick their own best;
   +38 WPM average when the font is set by measured performance).
   What this profile will NEVER contain (synthesis N1): no RSVP
   (one-word-at-a-time) display and no Bionic Reading-style
   bolding — the evidence is that they do not help sustained
   comprehension. Timing + recognition checks, winner stored
   client-side and applied portal-wide. */
const READ_PRESETS = [
  { id: "inter-loose", name: "Inter · 18px · loose", font: "\"Inter\", system-ui, sans-serif", size: 18, lh: 1.7, measure: 66, ls: "", ws: "", bg: "", lig: "" },
  { id: "fraunces-standard", name: "Fraunces · 18px · standard", font: "\"Fraunces\", Georgia, serif", size: 18, lh: 1.6, measure: 64, ls: "", ws: "", bg: "", lig: "" },
  { id: "atkinson-standard", name: "Atkinson Hyperlegible · 18px", font: "\"Atkinson Hyperlegible\", \"Inter\", sans-serif", size: 18, lh: 1.65, measure: 66, ls: "", ws: "", bg: "", lig: "" },
  { id: "inter-airy", name: "Inter · 20px · airy", font: "\"Inter\", system-ui, sans-serif", size: 20, lh: 1.85, measure: 58, ls: "", ws: "", bg: "", lig: "" },
  { id: "fraunces-compact", name: "Fraunces · 17px · compact", font: "\"Fraunces\", Georgia, serif", size: 17, lh: 1.55, measure: 74, ls: "", ws: "", bg: "", lig: "" },
  { id: "comfort-bda", name: "Comfort (BDA) · Atkinson · 19px · cream", font: "\"Atkinson Hyperlegible\", \"Inter\", sans-serif", size: 19, lh: 2.0, measure: 62, ls: "0.35ch", ws: "1.225ch", bg: "#F5EFE0", lig: "none" },
];
const PROFILE_KEY = "lens.profile.v1";
let currentProfile = null;
function presetStyle(p) {
  return `font-family:${p.font};font-size:${p.size}px;line-height:${p.lh};max-width:${p.measure}ch;letter-spacing:${p.ls || "normal"};word-spacing:${p.ws || "normal"};font-variant-ligatures:${p.lig || "normal"};${p.bg ? `background:${p.bg};color:#171410;` : ""}`;
}
function applyReadingProfile(p, save) {
  try {
    const root = document.documentElement;
    if (!root || !root.style) return;
    const vars = { "--read-font": p ? p.font : "", "--read-size": p ? p.size + "px" : "", "--read-lh": p ? String(p.lh) : "", "--read-measure": p ? p.measure + "ch" : "", "--read-ls": p ? (p.ls || "normal") : "", "--read-ws": p ? (p.ws || "normal") : "", "--read-lig": p ? (p.lig || "normal") : "", "--read-bg": p ? (p.bg || "transparent") : "" };
    for (const k of Object.keys(vars)) {
      if (p) root.style.setProperty(k, vars[k]); else root.style.removeProperty(k);
    }
    if (document.body && document.body.classList) document.body.classList.toggle("profile-light", !!(p && p.bg));
    currentProfile = p || null;
    if (save) store(PROFILE_KEY, p ? JSON.stringify(p) : "");
  } catch (e) { /* a profile must never break the portal */ }
}
function applyStoredProfile() {
  try {
    const raw = store(PROFILE_KEY);
    if (raw) { const p = JSON.parse(raw); if (p && p.font) applyReadingProfile(p, false); }
  } catch (e) { /* ignore a corrupt stored profile */ }
}
function scoreCalibration(rows) {
  /* Pure scoring: WPM from words/seconds; a setting qualifies only
     with BOTH recognition answers right (comprehension gates
     speed). Winner = fastest qualifying setting. If none qualify,
     the fallback maximises WPM × comprehension fraction and says
     so — the result is labelled, never laundered. */
  const scored = rows.map((r, i) => ({ ...r, i, wpm: r.seconds > 0 ? Math.round((r.words / r.seconds) * 60) : 0, qualified: r.correct >= 2 }));
  const qualified = scored.filter(r => r.qualified);
  let winner = null, fallback = false;
  if (qualified.length) winner = qualified.reduce((a, b) => (b.wpm > a.wpm ? b : a));
  else if (scored.length) { fallback = true; winner = scored.reduce((a, b) => ((b.wpm * b.correct) > (a.wpm * a.correct) ? b : a)); }
  return { rows: scored, winner, fallback };
}
function plainTextOf(id) {
  const p = PAGES[id];
  if (!p) return "";
  return String(p.html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}
function calibrationPassages() {
  const ids = Object.keys(PAGES).filter(id => plainTextOf(id).length > 2600).sort();
  const picked = [];
  for (let k = 0; k < READ_PRESETS.length && ids.length; k++) {
    picked.push(ids[Math.floor((k * ids.length) / READ_PRESETS.length)]);
  }
  return picked.map(id => {
    const text = plainTextOf(id);
    let cut = text.slice(0, 1050);
    const lastStop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("? "), cut.lastIndexOf("! "));
    if (lastStop > 500) cut = cut.slice(0, lastStop + 1);
    const sentences = cut.split(/(?<=[.!?])\s+/).filter(s => s.split(" ").length >= 6);
    return { page: id, text: cut, words: cut.split(/\s+/).length, sentences };
  });
}
let calState = null;
function renderReading() {
  const prof = currentProfile;
  const presetRows = READ_PRESETS.map(p => `
    <div class="rp-preset"><h3>${esc(p.name)}</h3>
      <p class="caption">${esc(p.size)}px · line-height ${esc(p.lh)} · measure ${esc(p.measure)}ch${p.ls ? ` · letter-spacing ${esc(p.ls)}` : ""}${p.ws ? ` · word-spacing ${esc(p.ws)}` : ""}${p.bg ? " · cream reading surface" : ""}</p>
      <p style="${presetStyle(p)}">The quick brown fox jumps over the lazy dog — and a wiki page reads at the pace its typography allows.</p>
      <button class="btn" data-apply-preset="${esc(p.id)}">Use this setting</button></div>`).join("");
  canvas.innerHTML = `
    <h1 class="mode-title">Reading profile</h1>
    <p>Your typography, set by <strong>measurement</strong> — not by feel. Readers cannot reliably pick the setting they read fastest in (Readability Consortium studies: preference matched the measured best only ~18% of the time, and the measured best averaged +38 WPM). So the Lens times you.</p>
    <p class="caption">This profile will never contain RSVP (one-word-at-a-time) display or Bionic Reading-style bolding: the evidence record (wave-7 reading lane; synthesis N1) is that speed-reading surfaces do not help sustained comprehension. Calibration by measurement is the alternative that does.</p>
    <section class="brief-section"><h2>Current profile</h2>
      ${prof ? `<p><strong>${esc(prof.name || prof.id)}</strong>${prof.calibratedWpm ? ` — calibrated at ${esc(prof.calibratedWpm)} WPM` : " — chosen manually"}. It applies to reading surfaces portal-wide, on this device only.</p><button class="btn" id="profile-reset">Reset to Lens defaults</button>` : `<p>No profile set. The Lens is using its default typography (Inter, 16px, line-height 1.65, measure 72ch).</p>`}</section>
    <section class="brief-section"><h2>Calibrate</h2>
      <p>Six settings, one short passage each (passages are this wiki's own pages). Read once at your normal pace; after each passage, two recognition questions check comprehension — speed only counts when comprehension holds. About four minutes.</p>
      <div id="cal-area"><button class="btn btn-primary" id="cal-start">Start calibration</button></div></section>
    <section class="brief-section"><h2>Or pick directly</h2>${presetRows}</section>`;
  defaultInspector(`<p class="caption">The profile lives in this browser (localStorage) and nowhere else — the Lens stays a static, read-only site. Atkinson Hyperlegible (Braille Institute, SIL OFL 1.1) is self-hosted with its licence, as a first-class candidate.</p>`);
  const startBtn = document.getElementById("cal-start");
  if (startBtn) startBtn.addEventListener("click", () => {
    calState = { step: 0, results: [], passages: calibrationPassages(), phase: "ready", t0: 0 };
    calStep();
  });
  const resetBtn = document.getElementById("profile-reset");
  if (resetBtn) resetBtn.addEventListener("click", () => { applyReadingProfile(null, true); renderReading(); });
  canvas.querySelectorAll("[data-apply-preset]").forEach(b => b.addEventListener("click", () => {
    const p = READ_PRESETS.find(x => x.id === b.getAttribute("data-apply-preset"));
    if (p) { applyReadingProfile({ ...p }, true); renderReading(); }
  }));
}
function calStep() {
  const area = document.getElementById("cal-area");
  if (!area || !calState) return;
  const { step, passages } = calState;
  if (step >= READ_PRESETS.length) { calFinish(); return; }
  const preset = READ_PRESETS[step];
  const passage = passages[step % passages.length];
  if (calState.phase === "ready") {
    area.innerHTML = `<p><strong>Setting ${step + 1} of ${READ_PRESETS.length}: ${esc(preset.name)}</strong></p>
      <p class="caption">The passage appears when you press Start — the clock runs from that moment. Read it once, at your normal pace, then press Done.</p>
      <button class="btn btn-primary" id="cal-go">Start reading</button> <button class="btn" id="cal-skip">Skip this setting</button>`;
    document.getElementById("cal-go").addEventListener("click", () => { calState.phase = "reading"; calState.t0 = Date.now(); calStep(); });
    document.getElementById("cal-skip").addEventListener("click", () => { calState.step++; calState.phase = "ready"; calStep(); });
    return;
  }
  if (calState.phase === "reading") {
    area.innerHTML = `<p><strong>Setting ${step + 1} of ${READ_PRESETS.length}: ${esc(preset.name)}</strong></p>
      <div class="cal-passage" style="${presetStyle(preset)}"><p>${esc(passage.text)}</p></div>
      <button class="btn btn-primary" id="cal-done">Done reading</button>`;
    document.getElementById("cal-done").addEventListener("click", () => {
      calState.seconds = Math.max(1, (Date.now() - calState.t0) / 1000);
      calState.phase = "questions";
      calStep();
    });
    return;
  }
  /* questions phase: which sentences were in the passage? */
  const sents = passage.sentences;
  const other = calState.passages[(step + 1) % calState.passages.length];
  const qs = [0, 1].map(qi => {
    const target = sents[1 + qi] || sents[0] || "";
    const distract = (other.sentences || []).slice(qi, qi + 2);
    const options = [target, ...distract].filter(Boolean);
    const rot = (step + qi) % Math.max(1, options.length);
    const ordered = options.slice(rot).concat(options.slice(0, rot));
    return { target, ordered };
  });
  area.innerHTML = `<p><strong>Setting ${step + 1} of ${READ_PRESETS.length}: ${esc(preset.name)}</strong> — which sentences were in the passage you just read?</p>
    ${qs.map((q, qi) => `<fieldset class="cal-q"><legend class="caption">Question ${qi + 1}</legend>${q.ordered.map((o, oi) => `<label><input type="radio" name="cal-q${qi}" value="${oi}"> ${esc(o)}</label>`).join("")}</fieldset>`).join("")}
    <button class="btn btn-primary" id="cal-record">Record result</button>`;
  document.getElementById("cal-record").addEventListener("click", () => {
    let correct = 0;
    qs.forEach((q, qi) => {
      const picked = area.querySelector(`input[name="cal-q${qi}"]:checked`);
      if (picked && q.ordered[parseInt(picked.value, 10)] === q.target) correct++;
    });
    calState.results.push({ preset: preset.id, name: preset.name, words: passage.words, seconds: Math.round(calState.seconds * 10) / 10, correct });
    calState.step++;
    calState.phase = "ready";
    calStep();
  });
}
function calFinish() {
  const area = document.getElementById("cal-area");
  if (!area || !calState) return;
  const { rows, winner, fallback } = scoreCalibration(calState.results);
  const table = rows.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.wpm)} WPM</td><td>${esc(r.correct)}/2</td><td>${r.qualified ? "qualifies" : "does not qualify"}${winner && r.i === winner.i ? " · <strong>winner</strong>" : ""}</td></tr>`).join("");
  area.innerHTML = `<h3 style="font-family:var(--font-display)">Calibration results</h3>
    <table class="cal-table"><thead><tr><th>Setting</th><th>Speed</th><th>Comprehension</th><th>Verdict</th></tr></thead><tbody>${table}</tbody></table>
    ${winner ? `<p>${fallback ? "No setting qualified (comprehension gate), so the fallback rule — fastest speed weighted by comprehension — picks" : "Fastest qualifying setting:"} <strong>${esc(winner.name)}</strong> at ${esc(winner.wpm)} WPM.</p>
    <button class="btn btn-primary" id="cal-apply">Apply ${esc(winner.name)} as my profile</button>` : `<p>No results recorded.</p>`}
    <button class="btn" id="cal-again">Run it again</button>`;
  const applyBtn = document.getElementById("cal-apply");
  if (applyBtn && winner) applyBtn.addEventListener("click", () => {
    const p = READ_PRESETS.find(x => x.id === winner.preset);
    if (p) applyReadingProfile({ ...p, calibratedWpm: winner.wpm }, true);
    renderReading();
  });
  const againBtn = document.getElementById("cal-again");
  if (againBtn) againBtn.addEventListener("click", () => { calState = { step: 0, results: [], passages: calibrationPassages(), phase: "ready", t0: 0 }; calStep(); });
}

/* ---------------- Line focus (item 64) ----------------
   A mask that dims all but 1/3/5 lines around the current one
   (wave-7 reading find 9). Pointer or arrow keys move the band.
   The text is never rewritten — this is a reading aid laid over
   the page, removed as cleanly as it is added. */
let lfLines = 0, lfBandY = null;
function lfLineHeight(article) {
  try {
    const p = article.querySelector("p");
    if (p && typeof getComputedStyle === "function") {
      const v = parseFloat(getComputedStyle(p).lineHeight);
      if (v > 0) return v;
    }
  } catch (e) { /* fall through to the default */ }
  return 26;
}
function lfPosition(wrap, article) {
  const masks = wrap.querySelectorAll(".lf-mask");
  if (!masks.length || !lfLines) return;
  try {
    const lh = lfLineHeight(article);
    const top = article.offsetTop || 0;
    const bottom = top + (article.offsetHeight || 0);
    if (lfBandY === null) lfBandY = top + lh;
    lfBandY = Math.max(top + lh / 2, Math.min(bottom - lh / 2, lfBandY));
    const bandH = lfLines * lh;
    const mTop = masks[0], mBot = masks[1];
    mTop.style.display = "block"; mBot.style.display = "block";
    mTop.style.top = "0px"; mTop.style.height = Math.max(0, lfBandY - bandH / 2) + "px";
    mBot.style.top = (lfBandY + bandH / 2) + "px"; mBot.style.bottom = "0px";
  } catch (e) { /* layout aids must never break reading */ }
}
function setupLineFocus(wrap, article) {
  const saved = parseInt(store("lens.linefocus") || "0", 10);
  lfLines = [0, 1, 3, 5].includes(saved) ? saved : 0;
  lfBandY = null;
  const btns = wrap.querySelectorAll("[data-lf]");
  const paint = () => {
    btns.forEach(b => b.setAttribute("aria-pressed", String(parseInt(b.getAttribute("data-lf"), 10) === lfLines)));
    wrap.querySelectorAll(".lf-mask").forEach(m => { m.style.display = lfLines ? "block" : "none"; });
    if (lfLines) lfPosition(wrap, article);
  };
  btns.forEach(b => b.addEventListener("click", () => {
    lfLines = parseInt(b.getAttribute("data-lf"), 10);
    store("lens.linefocus", String(lfLines));
    lfBandY = null;
    paint();
  }));
  wrap.addEventListener("pointermove", ev => {
    if (!lfLines) return;
    try { const r = wrap.getBoundingClientRect(); lfBandY = ev.clientY - r.top; lfPosition(wrap, article); } catch (e) { /* ignore */ }
  });
  paint();
}

/* ---------------- Router ---------------- */
const MORE_ROUTES = ["graph", "timeline", "decisions", "proposals", "trails", "cards", "blackbox", "state", "reading"];
function setMore(open) {
  const mm = document.getElementById("more-modes");
  const mt = document.getElementById("more-toggle");
  if (mm) mm.hidden = !open;
  if (mt) mt.setAttribute("aria-expanded", String(open));
}
function setRail(route) {
  document.querySelectorAll(".rail-item, .tab-item").forEach(a => {
    a.classList.toggle("selected", a.getAttribute("data-route") === route);
  });
  /* A secondary mode keeps its "More" group open so the current
     place in the rail stays visible. */
  if (MORE_ROUTES.includes(route)) setMore(true);
}
function route() {
  const full = location.hash.replace(/^#\/?/, "");
  /* The query string is parsed BEFORE the path split: previously
     "#/search?q=x" split into head "search?q=x", matched nothing,
     and silently fell through to the Briefing. */
  const qpos = full.indexOf("?");
  const raw = qpos >= 0 ? full.slice(0, qpos) : full;
  let qParam = "";
  /* All query params, values left ENCODED: routes that carry
     structured values (the trails stack) split before decoding,
     per-component. Only `q` is decoded here, as before. */
  const qParams = {};
  if (qpos >= 0) {
    for (const pair of full.slice(qpos + 1).split("&")) {
      const eq = pair.indexOf("=");
      if (eq > 0) qParams[pair.slice(0, eq)] = pair.slice(eq + 1);
    }
    if (qParams.q !== undefined) {
      try { qParam = decodeURIComponent(qParams.q.replace(/\+/g, " ")); } catch (e) { qParam = ""; }
    }
  }
  const [head, arg, anchor] = raw.split("/");
  renderTree(null);
  renderRecentStrip();
  if (!raw || head === "") { setRail("briefing"); renderBriefing(); }
  else if (head === "read") { setRail("read"); renderRead(decodeURIComponent(arg || "overview"), anchor ? decodeURIComponent(anchor) : null); }
  else if (head === "graph") { setRail("graph"); renderGraph(); }
  else if (head === "timeline") { setRail("timeline"); renderTimeline(); }
  else if (head === "decisions") { setRail("decisions"); renderDecisions(); }
  else if (head === "proposals") { setRail("proposals"); renderProposals(); }
  else if (head === "trails") { setRail("trails"); renderTrails(arg ? decodeURIComponent(arg) : null, qParams); }
  else if (head === "cards") { setRail("cards"); renderCards(); }
  else if (head === "ask") { setRail("ask"); renderAsk(qParam || (arg ? decodeURIComponent(arg) : "")); }
  /* Search is merged into Ask (fix 3); the legacy route and its
     deep links land on the same merged view. renderSearch remains
     available for the standalone renderer checks. */
  else if (head === "search") { setRail("ask"); renderAsk(qParam); }
  else if (head === "blackbox") { setRail("blackbox"); renderBlackBox(); }
  else if (head === "memory") { setRail("memory"); renderMemory(); }
  else if (head === "state") { setRail("state"); renderState(); }
  else if (head === "reading") { setRail("reading"); renderReading(); }
  else { setRail("briefing"); renderBriefing(); }
  canvas.scrollTop = 0;
}
document.getElementById("search-form").addEventListener("submit", ev => {
  ev.preventDefault();
  const v = document.getElementById("global-search").value;
  location.hash = "#/ask?q=" + encodeURIComponent(v);
});
/* Rail "More" disclosure. */
const moreToggle = document.getElementById("more-toggle");
if (moreToggle) moreToggle.addEventListener("click", () => {
  const mm = document.getElementById("more-modes");
  setMore(mm ? mm.hidden : true);
});
/* Phone tab bar "More" panel. */
const tabMore = document.getElementById("tab-more");
const tabMoreToggle = document.getElementById("tab-more-toggle");
function setTabMore(open) {
  if (tabMore) tabMore.hidden = !open;
  if (tabMoreToggle) tabMoreToggle.setAttribute("aria-expanded", String(open));
}
if (tabMoreToggle) tabMoreToggle.addEventListener("click", () => setTabMore(tabMore ? tabMore.hidden : true));
if (tabMore) tabMore.querySelectorAll("a").forEach(a => a.addEventListener("click", () => setTabMore(false)));
/* Inspector drawer: topbar toggle, in-drawer Close, Esc. */
function setInspectorOpen(open) {
  const b = document.body;
  if (b && b.classList) b.classList.toggle("inspector-open", open);
  const t = document.getElementById("inspector-toggle");
  if (t) t.setAttribute("aria-expanded", String(open));
}
const inspectorToggle = document.getElementById("inspector-toggle");
if (inspectorToggle) inspectorToggle.addEventListener("click", () => {
  const isOpen = document.body && document.body.classList ? document.body.classList.contains("inspector-open") : false;
  setInspectorOpen(!isOpen);
});
const inspectorClose = document.getElementById("inspector-close");
if (inspectorClose) inspectorClose.addEventListener("click", () => setInspectorOpen(false));
const pagesToggle = document.getElementById("pages-toggle");
if (pagesToggle) pagesToggle.addEventListener("click", () => {
  const nav = document.getElementById("navcol");
  const open = nav.classList.toggle("open");
  pagesToggle.setAttribute("aria-expanded", String(open));
});
document.addEventListener("keydown", ev => {
  if (ev.key === "Escape") setInspectorOpen(false);
  if (lfLines && (ev.key === "ArrowDown" || ev.key === "ArrowUp") && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
    const wrap = canvas.querySelector(".reading-focus-wrap");
    const article = canvas.querySelector(".reading-body");
    if (wrap && article && wrap.querySelector(".lf-mask")) {
      const step = lfLineHeight(article) * (ev.key === "ArrowDown" ? 1 : -1);
      lfBandY = (lfBandY === null ? (article.offsetTop || 0) : lfBandY) + step;
      lfPosition(wrap, article);
      ev.preventDefault();
    }
  }
  const raw = location.hash.replace(/^#\/?/, "");
  if (raw === "cards" && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
    if (ev.key === "ArrowRight") { const b = document.getElementById("card-next"); if (b && !b.disabled) b.click(); }
    if (ev.key === "ArrowLeft") { const b = document.getElementById("card-prev"); if (b && !b.disabled) b.click(); }
  }
});
window.addEventListener("hashchange", route);
applyStoredProfile();
renderBlackBoxRail();
route();
