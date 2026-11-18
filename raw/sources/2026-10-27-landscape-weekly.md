# Landscape research — weekly run, 2026-10-27

Method: primary sources only — the GitHub API (repos + releases
endpoints, read 2026-10-27), arXiv abstract pages opened in full,
vendors' own blogs/release notes opened in full. Star counts are
point-in-time (2026-10-27) and drift. Search results were used for
discovery only, never as evidence.

## Tracked projects — releases since 2026-10-20 (GitHub API)

| Project | Latest release | New since 2026-10-20? | Stars 2026-10-27 | Licence |
|---|---|---|---|---|
| nashsu/llm_wiki | v0.6.13, 2026-10-22 | YES (body carries no notes) | 21,019 | NOASSERTION |
| Graphify-Labs/graphify | v0.9.96, 2026-10-26 | YES — v0.9.94/.95/.96 | 136,583 | Apache-2.0 |
| mem0ai/mem0 | v2.2.1, 2026-09-25 | No | 67,904 | Apache-2.0 |
| HKUDS/LightRAG | v1.5.7, 2026-09-02 | No | 40,364 | MIT |
| khoj-ai/khoj | 2.0.0-beta.28, 2026-03-26 | No | 37,846 | AGPL-3.0 |
| microsoft/graphrag | v3.3.0, 2026-10-08 | No | 36,460 | MIT |
| topoteretes/cognee | v1.6.6rc1, 2026-10-23 | YES — RC, history controls | 32,804 | Apache-2.0 |
| getzep/graphiti | v0.31.2, 2026-10-20 | No (recorded 2026-10-20) | 32,265 | Apache-2.0 |
| tobi/qmd | v2.8.3, 2026-08-16 | No | 30,668 | MIT |
| atomicstrata/llm-wiki-compiler | v1.5.0, 2026-10-19 | No (recorded 2026-10-20) | 2,218 | MIT |
| AgriciDaniel/claude-obsidian | v3.0.1, 2026-10-21 | YES — v3.0.0 hardening + v3.0.1 | 15,874 | MIT |
| eugeniughelbur/obsidian-second-brain | v0.20.0, 2026-10-25 | YES — v0.19.0, v0.20.0 | 4,965 | MIT |
| letta-ai/letta | 0.16.8, 2026-05-14 | No | 25,265 | Apache-2.0 |
| basicmachines-co/basic-memory | v0.24.1, 2026-10-23 | YES — v0.24.0/.1, fix-dominated | 4,367 | AGPL-3.0 |
| Mintplex-Labs/anything-llm | v1.19.0, 2026-10-26 | YES (not memory-relevant) | 67,629 | MIT |

Release-note substance: claude-obsidian v3.0.0 — recoverable
transactions, Obsidian-matching lint, offline labelled retrieval
evaluation. obsidian-second-brain v0.19.0 — an owner check-in for
stale notes, and contradiction handling gated on verbatim quote
verification (`verify_quotes.py`); v0.20.0 — resumable bounded
directory ingestion. Cognee v1.6.6rc1 — `forget(clean_history=True)`;
dataset delete purges associated history and fails if the purge
cannot complete. Graphify v0.9.94–96 — security floors and
extraction-correctness fixes.

## Papers (arXiv, opened in full)

- Xie et al., "Can Agents Forget When Asked?" (arXiv:2610.18052,
  13 Oct 2026) — Bemula, the first memory-unlearning benchmark:
  50 dialogues, 135 forget requests of six types, 1,742 questions;
  no evaluated system passes more than 1.5% of forget requests
  end to end; failures leave data extractable or delete too much.
- Choudhary, "Keep Your Receipts" (arXiv:2610.17719, 13 Oct 2026) —
  retraction cleanup deleting only direct facts cuts contaminated
  queries 32.2% → 28.0%; per-artifact evidence receipts fix it;
  one receipt per sentence is 100%/88% faithful vs ~1/3 for flat
  whole-text summary receipts.
- Toma et al., "Beyond Downstream QA" (arXiv:2610.22209, 15 Oct
  2026) — FEB-30: intrinsic vs QA evaluation diverge 16 points;
  memory-operation classification correct only 20% of the time.
- Peng, "MemoryTax" (arXiv:2610.29823, 21 Oct 2026) — a memory's
  ceiling is set by the model that wrote it; one LoCoMo
  conversation, limits stated in the paper.
- Uddin et al., "From Recall to Forgetting" (Findings of ACL 2026;
  arXiv:2604.20006) — Memora and the FAMA metric penalising
  reliance on invalidated memory.

## New tracked project

OceanBase PowerContext (Apache-2.0, 1,378 stars, 2026-10-27):
v1.3.0 (2026-10-12), v1.4.0 (2026-10-19), v1.4.1 (2026-10-26).
Atomic memories with immutable revisions and exact evidence
references; forget = deactivate while retaining content and
history; retired = cannot be restored directly; a four-mode
evidence gate (disabled / shadow / advisory / enforcing).

Also verified: Zep v4 (vendor blog, 2026-10-14) — Ingestion
Traces, `reference_time`, bounded expansion returning
`truncated` + `truncation_reason`. An independent production
field report of the Karpathy pattern (SeraphimGate, 2026-10-17)
corroborates script-enforced hot-cache budgets and deterministic
lint over prose rules.

## Unverified

A secondary aggregator's 2026-10-26 "Graph-MIND" launch claim had
no matching primary repository on GitHub search (2026-10-27).
Recorded as unverified; nothing adopted.

## Built from this run

The forgetting battery: `scripts/wiki_forgetting_check.py` +
`evaluation/forgetting-battery.jsonl` — Bemula adapted to
deactivation-by-severance (STORED / SEVERED / PARAPHRASE /
PRESERVATION checks, deterministic, no model calls).
