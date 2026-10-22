# Dense retrieval trial — measurement report (W1.2, 2026-10-22)

Trial only. Nothing here changes a production default; the
engine decision stays the owner's. Corpus: wiki/ (scope=wiki) (42 docs).

## The store

- One SQLite projection: docs frontmatter + FTS5 lexical index + dense vectors as float32 BLOBs.
- sqlite-vec substitution: float32 BLOB + python cosine (sqlite-vec extension not installed; see module docstring).
- Embedder in the projection: **svd** — lexical (LSA / truncated SVD over TF-IDF) — NOT a neural embedding.
- Dims 41, vocab 1538 terms, corpus hash `cdba45c92e694ff2…`.
- Sensitivity control: **hashing** — lexical (signed feature hashing) — NOT a neural embedding.
- Fusion: Reciprocal Rank Fusion, k=60.

Reproduce:

    python3 scripts/wiki_dense_trial.py build
    python3 scripts/wiki_dense_trial.py measure
    python3 -m unittest scripts.tests.test_wiki_dense_trial

## Golden set (15 questions)

| run | cov@1 | cov@3 | cov@5 | cov@10 | hit@10 | MRR |
|---|---|---|---|---|---|---|
| production_bm25 | 0.6667 | 0.6667 | 0.6667 | 1.0 | 1.0 | 0.7143 |
| production_hybrid | 0.6667 | 0.6667 | 1.0 | 1.0 | 1.0 | 0.75 |
| projection_fts5 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 1.0 | 0.6923 |
| dense_svd | 0.6667 | 0.6667 | 1.0 | 1.0 | 1.0 | 0.75 |
| dense_hashing | 0.6667 | 1.0 | 1.0 | 1.0 | 1.0 | 0.8333 |
| rrf_bm25+dense_svd | 0.6667 | 0.6667 | 1.0 | 1.0 | 1.0 | 0.7333 |
| rrf_hybrid+dense_svd | 0.6667 | 0.6667 | 1.0 | 1.0 | 1.0 | 0.75 |
| rrf_fts5+dense_svd | 0.6667 | 0.6667 | 0.6667 | 1.0 | 1.0 | 0.7083 |
| rrf_bm25+dense_hashing | 0.6667 | 1.0 | 1.0 | 1.0 | 1.0 | 0.7778 |

Fusion swings at top-10 (must-cite gained / lost vs the lexical base):

- `rrf_bm25+dense_svd` vs `production_bm25`: gained none; lost none.
- `rrf_hybrid+dense_svd` vs `production_hybrid`: gained none; lost none.
- `rrf_fts5+dense_svd` vs `projection_fts5`: gained SQ-003; lost none.
- `rrf_bm25+dense_hashing` vs `production_bm25`: gained none; lost none.

## Directional / supersession slice (extended set)

| run | cov@1 | cov@3 | cov@5 | cov@10 | hit@10 | MRR |
|---|---|---|---|---|---|---|
| production_bm25 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| production_hybrid | 0.75 | 0.75 | 0.75 | 0.75 | 1.0 | 0.75 |
| projection_fts5 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| dense_svd | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| dense_hashing | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| rrf_bm25+dense_svd | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| rrf_hybrid+dense_svd | 0.75 | 0.75 | 0.75 | 0.75 | 1.0 | 0.7561 |
| rrf_fts5+dense_svd | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| rrf_bm25+dense_hashing | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

Fusion swings at top-10 (must-cite gained / lost vs the lexical base):

- `rrf_bm25+dense_svd` vs `production_bm25`: gained none; lost none.
- `rrf_hybrid+dense_svd` vs `production_hybrid`: gained none; lost none.
- `rrf_fts5+dense_svd` vs `projection_fts5`: gained none; lost none.
- `rrf_bm25+dense_hashing` vs `production_bm25`: gained none; lost none.

## Reading the numbers honestly

- The dense embedders here are LEXICAL (LSA over TF-IDF;
  signed hashing). They measure the fusion machinery and
  give a floor for what any real embedding model would
  need to beat — they are not evidence about neural dense
  retrieval, which this machine cannot run.
- The directional slice has 4 questions; one question is
  a quarter of the slice. Treat its deltas as smoke, not
  statistics.
