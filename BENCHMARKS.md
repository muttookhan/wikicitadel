# Benchmarks

Every number below comes from the **reference deployment** — the private
installation WikiCitadel was extracted from — measured in October 2026
against its own corpus. They are published as a *method and a baseline*,
not as a promise about your corpus: the harnesses that produced them ship
in this repository (`evaluation/`), so you can reproduce the same
measurements on your own wiki and compare like with like.

## Method, before numbers

- The evaluation harness is a regression gate: it runs a frozen golden
  set of questions against the corpus and **blocks any change that makes
  recall worse**. The recipe (judge, prompt, subset, top-k) is pinned in
  the harness configuration; changing the recipe starts a new baseline,
  never edits the old one.
- Quality, latency and cost are reported as separate numbers, never
  collapsed into one score.
- Abstention is measured on its own battery of unanswerable questions,
  tuned at a frozen threshold. A system that answers everything scores
  zero here by construction.

## Reference-deployment results (October 2026)

| Measurement | Result | Notes |
|---|---|---|
| Golden-set retrieval — pooled coverage @10 | **0.9394** | 15-question golden set, owner's own history |
| Golden-set retrieval — MRR | **0.7324** | temporal questions the weakest slice |
| Abstention battery | **12 / 12** | at the frozen threshold τ = 1.23 |
| Conflict slice (contradiction handling) | Identify 1 · Solve 0 | on the seed conflict question; the "solve" half is the field's weakest category everywhere it is measured |
| Citation lockfile | 73 markers, 14 pages | every marker re-verified verbatim against its source lines |
| Provenance manifest | 231 sources, 855 leaves | Merkle manifest, verified clean |
| Traversal census | 109 pages · 792 edges · 0 orphans | read-only traversal door over the compiled graph |

## Test suites (reference deployment, October 2026)

| Suite | Result |
|---|---|
| Engine (`scripts/tests`) | 907 passed, 1 skipped (an OCR test needing an optional PDF library) — re-measured 2026-10-20 after the marathon build wave |
| Ask door (`tools/ask`) | 252 passed, 7 skipped — same re-measurement |
| Gateway (`tools/gateway`) | 74 passed |
| Local editor (`tools/editor`) | 28 passed — same re-measurement |

The shipped seed corpus runs the portable subsets of these suites; the
reference deployment additionally carries corpus-bound test classes that
assert facts about its own private corpus, which are not shipped (the
shipped test files say so, in their headers).

## Measured scale ceiling (search door)

`scripts/wiki_scale_bench.py` builds synthetic corpora in memory and
times the BM25 ranking path of `scripts/wiki_search.py`. Measured
2026-10-20 on the reference machine (results file:
`evaluation/results/scale-bench.json`): median probe latency 4.7 ms at
100 pages, 51 ms at 1,000, 147 ms at 2,500, 307 ms at 5,000, 652 ms at
10,000 (~120 words per page). **The stated ceiling is 2,500 synthetic
pages under a 250 ms interactive threshold** — dated, machine-specific,
and re-measurable by re-running the bench. No claim is made beyond the
measured sizes; a real corpus's pages are longer than the synthetic
ones, so treat the ceiling as an upper bound, not a promise.

## Reproducible benchmark packs

`scripts/wiki_bench_repro.py` pins a benchmark run as a *pack*: the
engines, top-k, the golden-questions file by SHA-256, the corpus size,
the git HEAD and the Python version are recorded in one manifest
(`evaluation/results/repro-<label>.json`), and `compare` fails if
coverage@10, MRR or hit rate regressed between two packs. The seed
corpus ships a three-question fictional golden set
(`evaluation/golden-questions.jsonl`); its first pack
(`repro-seed-2026-10-20.json`) scores coverage@10 = 1.0 on all three
engines — a smoke-grade baseline for the demo corpus, not a quality
claim. The reference deployment's 15-question pack from the same day
scores bm25 1.0 · hybrid 0.9333 · hindsight 1.0 under its pinned
recipe.

## What we do not claim

- No comparison scores against other systems: the landscape figures in
  this project's research are adoption data (stars, licences, features),
  not benchmark results, and no rival was installed or benchmarked.
- No cost figures, and no latency figures beyond the measured search
  ceiling above: the reference deployment's doors are owner-driven and
  low-volume; publish your own from the harness's per-query records
  rather than trusting anyone's, including ours.
