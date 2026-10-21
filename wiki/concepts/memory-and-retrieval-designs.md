---
title: Memory and retrieval designs
type: concept
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: [retrieval, memory, marathon-r3]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: record
---

# Memory and retrieval designs

Six Tier B designs, built as working machinery (Marathon Round 3, lane TB2) over the fictional demo corpus, each re-implemented from its design description — no foreign code copied:

- **Per-agent loadout + visibility** (TencentDB pattern): `scripts/wiki_loadout.py` + seed register `evaluation/loadouts.json`.
- **Per-claim version-evolution diff-chains** (Hy Memory pattern): `scripts/wiki_claim_chain.py`.
- **L0/L1/L2 tiered reading** (OpenViking, idea only): `scripts/wiki_tiered_read.py`; `scripts/wiki_traverse.py` is unmodified.
- **Citation-gated advisory retrieval memory** (AutoRAG pattern): `scripts/wiki_advisory_memory.py` — entries without a citation to an existing page are refused.
- **Groundedness gate** (Upstage pattern, delivery side): `tools/ask/groundedness_gate.py` — optional, default OFF, not wired into the standing answer contract; blocks below threshold with a correction request.
- **Claim-level append-only index with temporal multi-signal fusion** (Mem0 pattern): `scripts/wiki_claim_index.py`.

Licences: the named items are designs re-implemented from the idea; Mem0's OSS is Apache-2.0 per the harvest notes, but no code was copied regardless.
