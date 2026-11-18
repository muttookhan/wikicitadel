# Synthetic evaluation slices — report

> SYNTHETIC SLICE — read before citing any figure. These questions were generated deterministically from the corpus's own structure, so the answer is structurally near the question by construction: this slice is EASIER than the hand-written golden/extended sets and its scores must never be pooled with theirs. Its value is regression breadth — breadth the 15-question golden set cannot give — not difficulty. Per-class figures only; the overall synthetic figure is a summary of this slice, not a corpus quality score.

Slice: `evaluation/synthetic-questions.jsonl` (sha256 7a2911a60e18…, 79 questions) · config: house · corpus: 43 docs @ e9ee878401eb6198bee9c6418ec22e0699c62beb

## Per-class results (house configuration)

| class | questions | cov@1 | cov@3 | cov@10 | hit@10 | MRR |
|---|---|---|---|---|---|---|
| title | 22 | 0.8636 | 0.9091 | 0.9545 | 0.9545 | 0.8853 |
| heading | 5 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| claim | 9 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| multihop | 12 | 0.5 | 1.0 | 1.0 | 1.0 | 0.75 |
| table | 7 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| **all synthetic (citation classes)** | 55 | 0.8364 | 0.9636 | 0.9818 | 0.9818 | 0.8996 |

## Zero-match probes (24 questions, tau = 1.2225)

Would abstain (top-1 score < tau): 4 / 24 = 0.1667

## Notes

- No criteria judge this row family: the meta-benchmark's frozen v1 covers the hand-written instruments only. Whether synthetic slices deserve criteria (e.g. a regression floor per class) is a v2 question for the owner/meta-benchmark, recorded here, not decided.
- Excluded-at-generation counts (ambiguous / unanswerable derivations) are in the slice file's header — the slice reports what it refused to ask, not only what it asked.
