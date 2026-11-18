---
title: "Eval & judging machinery (Marathon Round 3, TB6)"
type: concept
created: 2026-10-21
updated: 2026-10-21
sources: [wiki/ideas.md]
tags: [evaluation, judging]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: record
---

# Eval & judging machinery (Marathon Round 3, TB6)

Nine scoped builds over the fictional demo corpus, all
deterministic, no model calls anywhere, and no judge certification:
certification requires owner-labelled data (standing state: 0
labelled), so every judge here is an interface, a fixture, or a fake.

- `scripts/wiki_crag_gate.py` — CRAG confidence scorer + fallback ladder.
- `scripts/wiki_minicheck.py` — claim checker interface; lexical fallback labelled; small-model slot unwired.
- `scripts/wiki_longmem_eval.py` — LongMemEval five-ability template + runner; fixtures at `evaluation/longmem-fixtures.jsonl`.
- `scripts/wiki_quality_gate.py` — standing quality gate over deterministic proxy metrics, labelled as proxies.
- `scripts/wiki_judge_recovery.py` — judge-output recovery pass with a recovered-vs-refused audit trail.
- `scripts/wiki_merge_judge_gate.py` — both-orders double judging merge gate; disagreement refuses.
- `scripts/wiki_judge_lang_ab.py` — judge-prompt-language A/B harness over self-authored fixtures.
- `scripts/wiki_native_eval_gate.py` — native-language eval-set format + annotator-agreement (kappa) gate; tiny Japanese/Korean fixtures in `evaluation/native-eval-fixtures/`.
- `scripts/wiki_heldout.py` — held-out slice outside the tree; only a hash manifest inside, aggregate scores only in reports.

Golden sets are byte-untouched by this lane.
