#!/usr/bin/env python3
"""Dense retrieval TRIAL lane — projection, fusion, measurement.

Wave 1 item W1.2 (owner directive 2026-10-22: implement the research
ideas in both wikis). This module is a TRIAL, not a production
change: it builds a rebuildable SQLite projection of the wiki-scope
corpus holding frontmatter + an FTS5 lexical index + a dense vector
store in ONE database, fuses the lexical and dense runs with
Reciprocal Rank Fusion, and MEASURES the fusion against the golden
set and the directional (supersession) slice using the house
harnesses' own scoring functions. The serving path is never touched:
scripts/wiki_search.py is imported read-only (its public
bm25_rank / hybrid_rank are the production legs), no default
changes anywhere, and the production engine decision stays the
owner's — this lane's deliverable is the trial and its numbers.

SUBSTITUTIONS, recorded plainly (the spec names sqlite-vec):
  * sqlite-vec (the vec0 loadable extension) is NOT installed on
    this machine and cannot be loaded (`vec0.so` absent). The
    projection therefore stores embeddings as float32 BLOBs in a
    plain table and cosine similarity runs in Python over the
    ~169-page corpus — the same build / rank interface vec0 would
    sit behind, at corpus sizes where the difference is
    milliseconds. If sqlite-vec is ever installed, the vectors
    table is the only thing that changes.
  * No neural embedding model exists on this machine (no torch /
    FlagEmbedding / model endpoint — established across tonight's
    wave). The dense leg's default embedder is therefore LSA:
    truncated SVD over the corpus's own TF-IDF matrix. That is a
    LEXICAL embedding — it knows terms, not meaning — and it is
    labelled as such everywhere it appears. A signed feature-
    hashing embedder ships behind the same interface as the
    sensitivity control: the gap between the two embedders'
    numbers is itself trial evidence about how much of the dense
    leg's behaviour is embedder choice rather than machinery.

Attributions (licence route: adapt-with-credit, MIT/Apache):
  * sqlite-vec — Alex Garcia, MIT: the one-SQLite-store design
    (docs + FTS5 + vectors together) follows vec0's model.
  * qmd — Tobias Lutke (tobi/qmd), MIT: FTS5 + vectors in a single
    SQLite file, hybrid at query time.
  * LEANN — MIT: recompute-on-demand embeddings; recorded as the
    reserve design for the take-home copy, not used here.
  * Reciprocal Rank Fusion — Cormack, Clarke & Buttcher,
    "Reciprocal Rank Fusion outperforms Condorcet and individual
    Rank Learning Methods", SIGIR 2009. k = 60, the paper's value.
  * Latent Semantic Analysis — Deerwester et al., "Indexing by
    Latent Semantic Analysis", JASIS 1990.
  * ranx — AmenRa (Elias Bassani), MIT: the run-comparison report
    shape (one row per run, metric columns, per-question detail
    kept beside the aggregates) is adapted from ranx's compare
    reports.

Usage:
  python3 scripts/wiki_dense_trial.py build [--db PATH]
        [--embedder svd|hashing] [--dims N]
  python3 scripts/wiki_dense_trial.py query "some question" [--db PATH]
  python3 scripts/wiki_dense_trial.py measure [--db PATH]
        [--out-json PATH] [--out-md PATH]

Stdlib only, plus numpy when importable (the SVD embedder needs
it; without numpy the build refuses honestly and the hashing
embedder remains available). Deterministic: same corpus -> same
projection bytes for the vectors table (verified by tests).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import struct
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIAL_DIR = ROOT / "evaluation" / "dense-trial"
DEFAULT_DB = TRIAL_DIR / "projection.sqlite"
REPORT_JSON = ROOT / "evaluation" / "dense-trial-report.json"
REPORT_MD = ROOT / "evaluation" / "dense-trial-report.md"

RRF_K = 60
SVD_DIMS = 128
HASH_DIMS = 256
TOP = 10


# ---------------------------------------------------------------------------
# House modules, loaded the way wiki_benchmark.py loads wiki_search
# ---------------------------------------------------------------------------

def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_search():
    return _load("wiki_search", "scripts/wiki_search.py")


def load_benchmark():
    return _load("wiki_benchmark", "scripts/wiki_benchmark.py")


def load_eval_extended():
    return _load("wiki_eval_extended", "scripts/wiki_eval_extended.py")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def relpath(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return p.as_posix()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def corpus_hash(docs) -> str:
    h = hashlib.sha256()
    for p, text in sorted(docs, key=lambda d: relpath(d[0])):
        h.update(relpath(p).encode("utf-8"))
        h.update(b"\0")
        h.update(text_hash(text).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


_FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def parse_frontmatter(text: str):
    """(title, type) from YAML frontmatter; ('', '') when absent."""
    m = _FM_RE.match(text)
    if not m:
        return "", ""
    fm = m.group(1)
    title = ""
    typ = ""
    for line in fm.splitlines():
        if line.startswith("title:") and not title:
            title = line.split(":", 1)[1].strip().strip("'\"")
        elif line.startswith("type:") and not typ:
            typ = line.split(":", 1)[1].strip().strip("'\"")
    return title, typ


def vec_to_blob(vec) -> bytes:
    return struct.pack("<%df" % len(vec), *[float(v) for v in vec])


def blob_to_vec(blob: bytes):
    n = len(blob) // 4
    return list(struct.unpack("<%df" % n, blob))


def normalise(vec):
    n = math.sqrt(sum(v * v for v in vec))
    if n == 0.0:
        return list(vec)
    return [v / n for v in vec]


# ---------------------------------------------------------------------------
# Embedders — one interface, two implementations
#
# fit(token_lists) -> None; doc_vectors() -> [[float]] aligned with the
# fitted docs; embed_tokens(tokens) -> [float] for a query. Every
# returned vector is L2-normalised, so cosine is a dot product.
# ---------------------------------------------------------------------------

class HashingEmbedder:
    """Signed feature hashing (Weinberger et al. 2009 pattern):
    each term hashes to one dimension with a deterministic sign;
    tf is log-scaled. Stateless, no training, no vocabulary —
    the control embedder."""

    name = "hashing"
    kind = "lexical (signed feature hashing) — NOT a neural embedding"

    def __init__(self, dims=HASH_DIMS):
        self.dims = dims
        self._docs = None

    def _vector(self, tokens):
        vec = [0.0] * self.dims
        for term, count in Counter(tokens).items():
            h = hashlib.sha256(term.encode("utf-8")).digest()
            idx = int.from_bytes(h[:8], "little") % self.dims
            sign = 1.0 if h[8] % 2 == 0 else -1.0
            vec[idx] += sign * (1.0 + math.log(count))
        return normalise(vec)

    def fit(self, token_lists):
        self._docs = [self._vector(toks) for toks in token_lists]
        return self

    def doc_vectors(self):
        return self._docs

    def embed_tokens(self, tokens):
        return self._vector(tokens)

    def state_tables(self):
        """(terms_rows, component_rows) persisted for query fold-in."""
        return [], []


class SvdEmbedder:
    """LSA: truncated SVD of the log-tf x Robertson-IDF matrix,
    computed through the doc-Gram eigendecomposition (the corpus
    is small; the Gram matrix is docs x docs). Component signs are
    fixed deterministically (largest-|loading| term positive) so
    rebuilds are byte-stable. A LEXICAL embedding: it represents
    term co-occurrence, not learned semantics."""

    name = "svd"
    kind = "lexical (LSA / truncated SVD over TF-IDF) — NOT a neural embedding"

    def __init__(self, dims=SVD_DIMS):
        self.dims = dims
        self.vocab = []          # sorted term list
        self.idf = {}            # term -> idf
        self.components = {}     # term -> [float] * eff_dims (V rows)
        self.eff_dims = 0
        self._docs = None

    # -- training ------------------------------------------------------
    def fit(self, token_lists):
        try:
            import numpy as np
        except ImportError as exc:  # honest refusal, never a fake
            raise RuntimeError(
                "the SVD embedder needs numpy, which is not importable "
                "in this interpreter; use --embedder hashing") from exc
        n = len(token_lists)
        df = Counter()
        for toks in token_lists:
            for term in set(toks):
                df[term] += 1
        self.vocab = sorted(t for t, d in df.items() if d >= 2) or sorted(df)
        self.idf = {t: math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    for t in self.vocab}
        vindex = {t: i for i, t in enumerate(self.vocab)}
        X = np.zeros((n, len(self.vocab)), dtype=np.float64)
        for r, toks in enumerate(token_lists):
            for term, count in Counter(toks).items():
                j = vindex.get(term)
                if j is not None:
                    X[r, j] = (1.0 + math.log(count)) * self.idf[term]
        gram = X @ X.T
        evals, evecs = np.linalg.eigh(gram)          # ascending order
        order = np.argsort(evals)[::-1]
        evals = np.clip(evals[order], 0.0, None)
        evecs = evecs[:, order]
        sing = np.sqrt(evals)
        k = int(min(self.dims, n - 1 if n > 1 else 1,
                    int((sing > 1e-10).sum())))
        k = max(k, 1)
        U = evecs[:, :k]                              # docs x k
        S = sing[:k]
        V = (X.T @ U) / S                             # vocab x k
        # deterministic sign fix per component
        for j in range(k):
            col = V[:, j]
            pivot = int(np.argmax(np.abs(col)))
            if col[pivot] < 0:
                V[:, j] = -col
                U[:, j] = -U[:, j]
        doc_mat = U * S                               # docs x k
        self.eff_dims = k
        self._docs = [normalise([float(v) for v in row]) for row in doc_mat]
        self.components = {t: [float(v) for v in V[vindex[t]]]
                           for t in self.vocab}
        return self

    # -- queries ---------------------------------------------------------
    def embed_tokens(self, tokens):
        vec = [0.0] * self.eff_dims
        for term, count in Counter(tokens).items():
            comp = self.components.get(term)
            if comp is None:
                continue
            w = (1.0 + math.log(count)) * self.idf[term]
            for j, c in enumerate(comp):
                vec[j] += w * c
        return normalise(vec)

    def doc_vectors(self):
        return self._docs

    def state_tables(self):
        terms = [(t, self.idf[t]) for t in self.vocab]
        comps = [(t, vec_to_blob(self.components[t])) for t in self.vocab]
        return terms, comps

    # -- restore from a built projection ---------------------------------
    @classmethod
    def from_state(cls, dims, terms_rows, component_rows):
        emb = cls(dims=dims)
        emb.idf = {t: float(v) for t, v in terms_rows}
        emb.vocab = sorted(emb.idf)
        emb.components = {t: blob_to_vec(b) for t, b in component_rows}
        emb.eff_dims = len(next(iter(emb.components.values()))) \
            if emb.components else 0
        return emb


EMBEDDERS = {"svd": SvdEmbedder, "hashing": HashingEmbedder}


def make_embedder(name, dims=None):
    cls = EMBEDDERS[name]
    if dims is None:
        return cls()
    return cls(dims=dims)


# ---------------------------------------------------------------------------
# The projection — one rebuildable SQLite store:
# docs (frontmatter) + docs_fts (FTS5 lexical) + vectors (dense BLOBs)
# + the embedder state a query fold-in needs. Rebuilding from the
# same corpus reproduces the vectors table byte-for-byte.
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE docs (
  path TEXT PRIMARY KEY, title TEXT, type TEXT,
  n_tokens INTEGER, text_sha256 TEXT);
CREATE VIRTUAL TABLE docs_fts USING fts5(path UNINDEXED, text);
CREATE TABLE vectors (path TEXT PRIMARY KEY, dim INTEGER, vec BLOB);
CREATE TABLE terms (term TEXT PRIMARY KEY, idf REAL);
CREATE TABLE components (term TEXT PRIMARY KEY, vec BLOB);
"""


def build_projection_conn(conn, embedder, docs, ws):
    """Build the whole projection into an open sqlite3 connection
    (file-backed or :memory:). Returns the meta dict."""
    token_lists = [ws.tokenize(text) for _p, text in docs]
    embedder.fit(token_lists)
    vectors = embedder.doc_vectors()
    terms_rows, component_rows = embedder.state_tables()
    conn.executescript(SCHEMA)
    meta = {
        "embedder": embedder.name,
        "embedder_kind": embedder.kind,
        "dims": str(len(vectors[0]) if vectors else 0),
        "corpus_docs": str(len(docs)),
        "corpus_hash": corpus_hash(docs),
        "vocab_size": str(len(terms_rows)),
        "vector_store": "float32 BLOB + python cosine "
                        "(sqlite-vec extension not installed; "
                        "see module docstring)",
        "built_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
    }
    conn.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    for (p, text), toks, vec in zip(docs, token_lists, vectors):
        rel = relpath(p)
        title, typ = parse_frontmatter(text)
        conn.execute(
            "INSERT INTO docs VALUES (?, ?, ?, ?, ?)",
            (rel, title, typ, len(toks), text_hash(text)))
        conn.execute("INSERT INTO docs_fts VALUES (?, ?)", (rel, text))
        conn.execute("INSERT INTO vectors VALUES (?, ?, ?)",
                     (rel, len(vec), vec_to_blob(vec)))
    conn.executemany("INSERT INTO terms VALUES (?, ?)", terms_rows)
    conn.executemany("INSERT INTO components VALUES (?, ?)",
                     component_rows)
    conn.commit()
    return meta


def build_projection(db_path, embedder, docs=None, ws=None):
    """Build (or rebuild) the projection file at db_path. `docs`
    is a [(Path, text)] corpus; the default is the house corpus,
    wiki_search.collect_docs('wiki'). The image is assembled in
    memory and serialised to disk, so the artefact is a plain
    SQLite file any environment can open. Returns a summary."""
    if docs is None:
        ws = ws or load_search()
        docs = ws.collect_docs("wiki")
    if ws is None:
        ws = load_search()
    conn = sqlite3.connect(":memory:")
    try:
        meta = build_projection_conn(conn, embedder, docs, ws)
        image = conn.serialize()
    finally:
        conn.close()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(image)
    return {"db": str(db_path), **meta}


def _connect_projection(source):
    """Open a projection: a path (direct connect; if the
    environment refuses SQLite file access, the file image is
    deserialised into memory instead — the queries are identical)
    or an already-open sqlite3.Connection (used as-is)."""
    if isinstance(source, sqlite3.Connection):
        return source, ":memory: (connection)"
    path = Path(source)
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("SELECT count(*) FROM meta").fetchone()
        return conn, str(path)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(":memory:")
        conn.deserialize(path.read_bytes())
        return conn, "%s (deserialised in-memory)" % path


class ProjectionStore:
    """Read side of a built projection: dense + FTS5 rank legs."""

    def __init__(self, source):
        self.conn, self.source_label = _connect_projection(source)
        self.db_path = self.source_label
        self.meta = dict(self.conn.execute("SELECT key, value FROM meta"))
        name = self.meta["embedder"]
        if name == SvdEmbedder.name:
            terms = self.conn.execute("SELECT term, idf FROM terms").fetchall()
            comps = self.conn.execute(
                "SELECT term, vec FROM components").fetchall()
            self.embedder = SvdEmbedder.from_state(
                int(self.meta["dims"]), terms, comps)
        else:
            self.embedder = HashingEmbedder(dims=int(self.meta["dims"]))
        self.paths = []
        self._matrix = None
        rows = self.conn.execute(
            "SELECT path, vec FROM vectors ORDER BY path").fetchall()
        try:
            import numpy as np
            self._np = np
            self.paths = [r[0] for r in rows]
            self._matrix = np.array(
                [blob_to_vec(r[1]) for r in rows], dtype=np.float64)
        except ImportError:
            self._np = None
            self._rows = rows

    def close(self):
        self.conn.close()

    def dense_rank(self, query_terms, limit=None):
        """[(cosine, relpath)] desc, path tiebreak; score > 0 only
        (the BM25 leg's convention: no signal, no row)."""
        q = self.embedder.embed_tokens(query_terms)
        scored = []
        if self._np is not None:
            sims = self._matrix @ self._np.array(q, dtype=self._np.float64)
            scored = [(float(s), p) for s, p in zip(sims, self.paths)
                      if s > 0.0]
        else:
            for path, blob in self._rows:
                vec = blob_to_vec(blob)
                s = sum(a * b for a, b in zip(q, vec))
                if s > 0.0:
                    scored.append((s, path))
        scored.sort(key=lambda r: (-r[0], r[1]))
        return scored[:limit] if limit else scored

    def fts_rank(self, query_terms, limit=None):
        """[(score, relpath)] from the projection's own FTS5 BM25 —
        the lexical leg that lives in the same store as the
        vectors (the spec's configuration)."""
        if not query_terms:
            return []
        match = " OR ".join('"%s"' % t.replace('"', '""')
                            for t in set(query_terms))
        rows = self.conn.execute(
            "SELECT path, bm25(docs_fts) FROM docs_fts "
            "WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts), path",
            (match,)).fetchall()
        scored = [(-float(score), path) for path, score in rows]
        return scored[:limit] if limit else scored


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (Cormack, Clarke & Buttcher 2009)
# ---------------------------------------------------------------------------

def rrf_fuse(rankings, k=RRF_K):
    """Fuse ranked path lists: score(path) = sum over legs of
    1 / (k + rank in that leg), ranks 1-based; a path absent from
    a leg gets nothing from it. Returns [(score, path)] sorted by
    (-score, path) — fully deterministic."""
    fused = {}
    for ranking in rankings:
        for i, path in enumerate(ranking):
            fused[path] = fused.get(path, 0.0) + 1.0 / (k + i + 1)
    return sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))


def rrf_scores(rankings, k=RRF_K):
    return {path: score for path, score in rrf_fuse(rankings, k=k)}


# ---------------------------------------------------------------------------
# In-memory dense leg (embedder sensitivity runs — no second store)
# ---------------------------------------------------------------------------

def dense_rank_inmemory(embedder, docs, token_lists, query_terms):
    vecs = embedder.doc_vectors()
    q = embedder.embed_tokens(query_terms)
    scored = []
    for (p, _text), vec in zip(docs, vecs):
        s = sum(a * b for a, b in zip(q, vec))
        if s > 0.0:
            scored.append((s, relpath(p)))
    scored.sort(key=lambda r: (-r[0], r[1]))
    return scored


# ---------------------------------------------------------------------------
# Measurement — the house harnesses' own scoring, applied to every run
# ---------------------------------------------------------------------------

def _benchmark_aggregates(per_q):
    """wiki_benchmark.py's aggregate formula, verbatim in effect."""
    n = len(per_q) or 1
    cov = {k: sum(1 for r in per_q
                  if r["must_cite_rank"] is not None
                  and r["must_cite_rank"] <= k) / n
           for k in (1, 3, 5, 10)}
    return {
        "questions": len(per_q),
        "citation_coverage": {f"@{k}": round(v, 4)
                              for k, v in cov.items()},
        "hit_rate_topk": round(
            sum(1 for r in per_q if r["hit_in_topk"]) / n, 4),
        "mean_precision_at_k": round(
            sum(r["precision_at_k"] for r in per_q) / n, 4),
        "mrr_must_cite": round(sum(
            1.0 / r["must_cite_rank"] for r in per_q
            if r["must_cite_rank"] is not None) / n, 4),
    }


def build_runs(store, docs, adj, token_lists, ws):
    """{run_name: (terms) -> [(score, relpath)]}. The production
    legs call wiki_search's public rankers read-only; nothing here
    writes to the serving path."""
    hashing = HashingEmbedder().fit(token_lists)

    def bm25(terms):
        return [(s, relpath(p)) for s, p, _t in ws.bm25_rank(terms, docs)]

    def hybrid(terms):
        return [(s, relpath(p))
                for s, p, _t, _d in ws.hybrid_rank(terms, docs, adj)]

    def fts(terms):
        return store.fts_rank(terms)

    def dense_svd(terms):
        return store.dense_rank(terms)

    def dense_hash(terms):
        return dense_rank_inmemory(hashing, docs, token_lists, terms)

    def fuse(*legs):
        def run(terms):
            rankings = [[p for _s, p in leg(terms)] for leg in legs]
            return [(score, path)
                    for path, score in rrf_fuse(rankings)]
        return run

    return {
        "production_bm25": bm25,
        "production_hybrid": hybrid,
        "projection_fts5": fts,
        "dense_svd": dense_svd,
        "dense_hashing": dense_hash,
        "rrf_bm25+dense_svd": fuse(bm25, dense_svd),
        "rrf_hybrid+dense_svd": fuse(hybrid, dense_svd),
        "rrf_fts5+dense_svd": fuse(fts, dense_svd),
        "rrf_bm25+dense_hashing": fuse(bm25, dense_hash),
    }


# Which fused run answers to which lexical base (for the delta table)
FUSION_BASE = {
    "rrf_bm25+dense_svd": "production_bm25",
    "rrf_hybrid+dense_svd": "production_hybrid",
    "rrf_fts5+dense_svd": "projection_fts5",
    "rrf_bm25+dense_hashing": "production_bm25",
}


def measure(db_path=DEFAULT_DB, out_json=REPORT_JSON, out_md=REPORT_MD,
            store=None, write=True):
    ws = load_search()
    wb = load_benchmark()
    ee = load_eval_extended()
    docs = ws.collect_docs("wiki")
    adj = ws.build_link_graph(docs)
    token_lists = [ws.tokenize(text) for _p, text in docs]
    own_store = store is None
    if own_store:
        store = ProjectionStore(db_path)
    try:
        runs = build_runs(store, docs, adj, token_lists, ws)
        golden = wb.load_questions(str(ROOT / "evaluation"
                                       / "golden-questions.jsonl"))
        extended = ee.load_questions(
            str(ROOT / "evaluation" / "extended-questions.jsonl"))
        directional = [q for q in extended
                       if q.get("slice") == "directional"]

        instruments = {}
        for label, questions, scorer in (
                ("golden", golden, "benchmark"),
                ("directional_slice", directional, "extended")):
            per_run = {}
            for name, run in runs.items():
                rows = []
                for q in questions:
                    ranked = run(ws.tokenize(q["question"]))
                    if scorer == "benchmark":
                        rows.append(wb.score_question(
                            q, [p for _s, p in ranked], TOP))
                    else:
                        rows.append(ee.score_answerable(q, ranked, TOP))
                agg = (_benchmark_aggregates(rows)
                       if scorer == "benchmark" else ee.aggregates(rows))
                per_run[name] = {"aggregates": agg, "per_question": rows}
            instruments[label] = per_run

        # Wins / losses of each fusion against its lexical base,
        # computed from the per-question rows — never hand-picked.
        swings = {}
        for label, per_run in instruments.items():
            swings[label] = {}
            for fused, base in FUSION_BASE.items():
                f_rows = {r["id"]: r for r in per_run[fused]["per_question"]}
                b_rows = {r["id"]: r for r in per_run[base]["per_question"]}
                gained, lost = [], []
                for qid in sorted(f_rows):
                    f_in = f_rows[qid]["must_cite_rank"] is not None \
                        and f_rows[qid]["must_cite_rank"] <= TOP
                    b_in = b_rows[qid]["must_cite_rank"] is not None \
                        and b_rows[qid]["must_cite_rank"] <= TOP
                    if f_in and not b_in:
                        gained.append(qid)
                    elif b_in and not f_in:
                        lost.append(qid)
                swings[label][fused] = {
                    "base": base, "gained_top10": gained,
                    "lost_top10": lost}

        try:
            import subprocess
            head = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                capture_output=True, text=True).stdout.strip() or None
        except Exception:
            head = None
        import hashlib as _hl
        report = {
            "trial": "W1.2 dense retrieval trial lane (2026-10-22)",
            "generated_at": datetime.now().astimezone().isoformat(
                timespec="seconds"),
            "git_head": head,
            "corpus": "wiki/ (scope=wiki)",
            "corpus_docs": len(docs),
            "projection_db": store.source_label,
            "projection_meta": store.meta,
            "serving_path": {
                "wiki_search_sha256": _hl.sha256(
                    (ROOT / "scripts" / "wiki_search.py")
                    .read_bytes()).hexdigest(),
                "note": "wiki_search.py is imported read-only; the "
                        "trial changes no default and no serving "
                        "code. Golden + extended question files are "
                        "measured against, never edited.",
            },
            "embedders": {
                "svd": SvdEmbedder.kind,
                "hashing": HashingEmbedder.kind,
                "note": "No neural embedding model exists on this "
                        "machine; both embedders are lexical. The "
                        "production engine choice remains the "
                        "owner's.",
            },
            "fusion": "Reciprocal Rank Fusion, k=%d" % RRF_K,
            "reproduce": [
                "python3 scripts/wiki_dense_trial.py build",
                "python3 scripts/wiki_dense_trial.py measure",
                "python3 -m unittest scripts.tests.test_wiki_dense_trial",
            ],
            "instruments": instruments,
            "fusion_swings_top10": swings,
        }
    finally:
        if own_store:
            store.close()
    if write:
        write_report(report, out_json, out_md)
    return report


def write_report(report, out_json=REPORT_JSON, out_md=REPORT_MD):
    Path(out_json).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    Path(out_md).write_text(render_markdown(report), encoding="utf-8")


def _agg_row(name, agg):
    cov = agg["citation_coverage"]
    return "| %s | %s | %s | %s | %s | %s | %s |" % (
        name, cov["@1"], cov["@3"], cov["@5"], cov["@10"],
        agg["hit_rate_topk"], agg["mrr_must_cite"])


def render_markdown(report):
    meta = report["projection_meta"]
    lines = [
        "# Dense retrieval trial — measurement report (W1.2, 2026-10-22)",
        "",
        "Trial only. Nothing here changes a production default; the",
        "engine decision stays the owner's. Corpus: %s (%d docs)." % (
            report["corpus"], report["corpus_docs"]),
        "",
        "## The store",
        "",
        "- One SQLite projection: docs frontmatter + FTS5 lexical "
        "index + dense vectors as float32 BLOBs.",
        "- sqlite-vec substitution: %s." % meta["vector_store"],
        "- Embedder in the projection: **%s** — %s." % (
            meta["embedder"], meta["embedder_kind"]),
        "- Dims %s, vocab %s terms, corpus hash `%s…`." % (
            meta["dims"], meta["vocab_size"], meta["corpus_hash"][:16]),
        "- Sensitivity control: **hashing** — %s." % HashingEmbedder.kind,
        "- Fusion: %s." % report["fusion"],
        "",
        "Reproduce:",
        "",
    ]
    lines += ["    %s" % c for c in report["reproduce"]]
    for label, title in (("golden", "Golden set (15 questions)"),
                         ("directional_slice",
                          "Directional / supersession slice "
                          "(extended set)")):
        per_run = report["instruments"][label]
        lines += [
            "",
            "## %s" % title,
            "",
            "| run | cov@1 | cov@3 | cov@5 | cov@10 | hit@10 | MRR |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, data in per_run.items():
            lines.append(_agg_row(name, data["aggregates"]))
        lines += ["", "Fusion swings at top-10 (must-cite gained / "
                      "lost vs the lexical base):", ""]
        for fused, swing in report["fusion_swings_top10"][label].items():
            lines.append("- `%s` vs `%s`: gained %s; lost %s." % (
                fused, swing["base"],
                ", ".join(swing["gained_top10"]) or "none",
                ", ".join(swing["lost_top10"]) or "none"))
    lines += [
        "",
        "## Reading the numbers honestly",
        "",
        "- The dense embedders here are LEXICAL (LSA over TF-IDF;",
        "  signed hashing). They measure the fusion machinery and",
        "  give a floor for what any real embedding model would",
        "  need to beat — they are not evidence about neural dense",
        "  retrieval, which this machine cannot run.",
        "- The directional slice has %d questions; one question is" % (
            report["instruments"]["directional_slice"]
            ["production_bm25"]["aggregates"]["questions"]),
        "  a quarter of the slice. Treat its deltas as smoke, not",
        "  statistics.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Dense retrieval trial lane (W1.2) — trial only, "
                    "changes no production default.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build/rebuild the projection")
    b.add_argument("--db", default=str(DEFAULT_DB))
    b.add_argument("--embedder", choices=sorted(EMBEDDERS),
                   default="svd")
    b.add_argument("--dims", type=int, default=None)

    q = sub.add_parser("query", help="show every leg for one query")
    q.add_argument("question")
    q.add_argument("--db", default=str(DEFAULT_DB))
    q.add_argument("--top", type=int, default=10)

    m = sub.add_parser("measure", help="run the full measurement")
    m.add_argument("--db", default=str(DEFAULT_DB))
    m.add_argument("--out-json", default=str(REPORT_JSON))
    m.add_argument("--out-md", default=str(REPORT_MD))

    args = ap.parse_args(argv)
    if args.cmd == "build":
        emb = make_embedder(args.embedder, dims=args.dims)
        summary = build_projection(Path(args.db), emb)
        print(json.dumps(summary, indent=2))
        return 0
    if args.cmd == "query":
        ws = load_search()
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        token_lists = [ws.tokenize(t) for _p, t in docs]
        store = ProjectionStore(Path(args.db))
        try:
            runs = build_runs(store, docs, adj, token_lists, ws)
            terms = ws.tokenize(args.question)
            for name, run in runs.items():
                ranked = run(terms)[:args.top]
                print("\n== %s" % name)
                for s, p in ranked:
                    print("  %.4f  %s" % (s, p))
        finally:
            store.close()
        return 0
    if args.cmd == "measure":
        if not Path(args.db).exists():
            emb = make_embedder("svd")
            build_projection(Path(args.db), emb)
            print("projection was missing; built with the svd embedder")
        report = measure(Path(args.db), Path(args.out_json),
                         Path(args.out_md))
        for label in ("golden", "directional_slice"):
            print("\n== %s" % label)
            for name, data in report["instruments"][label].items():
                agg = data["aggregates"]
                print("  %-26s cov@10=%.4f  MRR=%.4f" % (
                    name, agg["citation_coverage"]["@10"],
                    agg["mrr_must_cite"]))
        print("\nwrote %s and %s" % (args.out_json, args.out_md))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
