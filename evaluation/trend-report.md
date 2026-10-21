# Eval trend — coverage@10 / MRR vs corpus size

Oldest -> newest. Runs whose files lack a date, a corpus page count, coverage@10 or MRR are listed under Gaps, never dropped silently and never plotted with an invented value.

| date | run | corpus pages | coverage@10 | MRR | source |
|---|---|---|---|---|---|
| 2026-10-20 | seed-2026-10-20/bm25 | 11 | 1.0000 | 0.6111 | repro-seed-2026-10-20.json |
| 2026-10-21 | scale-2026-10-20/bm25 | 48 | 1.0000 | 1.0000 | repro-scale-2026-10-20.json |
| 2026-10-21 | seed-r2-2026-10-20/bm25 | 11 | 1.0000 | 0.6111 | repro-seed-r2-2026-10-20.json |

## Gaps

- repro-scale-2026-10-20.corpus-manifest.json — no coverage@10
- scale-bench.json — no corpus page count (corpus_docs)
