---
title: "Retrieval and ranking machinery — Marathon Round 3 (TB7)"
type: synthesis
created: 2026-10-21
updated: 2026-10-21
sources: [wiki/ideas.md]
tags: [retrieval, ranking, marathon]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: record
methods: "Compiled from the lane's own build record; every tool named here is in scripts/ with fixture tests in scripts/tests/. The demo corpus is fictional throughout."
---

# Retrieval and ranking machinery — Marathon Round 3 (TB7)

Ten Tier B rows from the round-2 research board, built as working,
tested machinery over the fictional demo corpus:

- **Exact-title/stem-match boost** — a query that exactly matches a
  page's title or file stem gets a decisive boost (+10; stemmed
  match +5) in `scripts/wiki_search.py`'s hybrid and hindsight
  rankers, mirrored in `tools/lens/lenslib.py` and the Lens
  client's hybrid lane, so a page titled by the query term cannot
  fall out of the top-10 as the corpus grows.
- **Rank expressions (Vespa pattern)** — the hybrid's final score
  is one evaluation of the named expression `hybrid-current` over
  per-candidate features (bm25, ppr, temporal, recency, rerank,
  importance, title boost); `scripts/wiki_rank_expr.py` lists,
  shows, evaluates and checks the expressions.
- **RAPTOR** — `scripts/wiki_raptor.py` builds a recursive
  summary tree (passages → cluster summaries → root) with an
  extractive summariser behind a model-slot interface, and
  answers queries from any tree level.
- **GraphRAG** — `scripts/wiki_graphrag.py` map-reduces the
  graph export's communities into per-community summary records
  the search layer can consult.
- **Docling pattern** — `scripts/wiki_structured_ingest.py`
  post-processes converter output into a typed block stream
  (headings, paragraphs, tables, lists, code) as JSON beside the
  markdown; the converter itself is untouched.
- **bisheng pattern** — `scripts/wiki_citation_scope.py`:
  citations carry their source file's permission scope; a reader
  outside the scope receives a scope note, never the citation.
- **MemoRAG pattern** — `scripts/wiki_memorag.py`: a deterministic
  clue pass (likely titles, entities, corpus synonyms) runs
  retrieval per clue and merges by rank fusion, with the clues
  printed.
- **IndicTrans2 pattern** — `scripts/wiki_script_norm.py` unifies
  scripts (NFKC width folding, a stated Devanagari romanisation
  table, diacritic folding) so cross-script queries match.
- **KAG pattern** — `scripts/wiki_kag.py` builds the mutual
  page↔concept index and answers logical-form
  (subject/predicate/object) queries against it.
- **Regional-scene candidates** — the Japanese dual-track
  retrieval recipe as a DORMANT profile
  (`evaluation/retrieval-profiles/japanese-dual-track.json`,
  activation condition stated, no embeddings wired); Khoj's
  configured-agent object as validated configuration
  (`scripts/wiki_agent_object.py` +
  `evaluation/agent-objects/`); and the graph export's CSR
  sparse-matrix form (`wiki_graph_export.py --csr-out`,
  FalkorDB pattern).
