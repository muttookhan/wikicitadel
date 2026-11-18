---
title: "Memory-operations slice — first run (2026-10-28)"
type: query
created: 2026-10-28
updated: 2026-10-28
sources: []
tags: [evaluation, memory, filings]
status: draft
confidence: observed
stage: seedling
planted: 2026-10-28
tended: 2026-10-28
work_type: record
---

# Memory-operations slice — first run (2026-10-28)

The FEB-30 pattern (Toma et al., arXiv:2610.22209, via the 2026-10-27 landscape research) built as a standing battery in this tree, mirroring the private wiki's slice of the same day: an intrinsic memory-operation evaluation — fact-evolution trajectories scored against the memory STORE's operation classification (create / update / reinforce / supersede), not downstream QA. FEB-30 found the tested system's operation classification correct only 20% of the time, invisible to QA eval. The convention stands in AGENTS.md ("Memory-operations slice"); the battery is `evaluation/memory-ops-battery.jsonl`, the checker `scripts/wiki_memory_ops_check.py`, the tests `scripts/tests/test_wiki_memory_ops_check.py` (8/8). The trajectories are synthetic by construction (two fictional clubs/gardens) — no seed-corpus facts are used except in the live probes, which run read-only against this tree's real settled corpus (the seed register's blanket-approval reversal).

## What is classified, and by what

Each trajectory is replayed against a fresh temporary store in the real formats (claim pages + a decisions register). The classifier reads only store state and the incoming item; the expected class is read only by the scorer.

- **Free-text claims** are classified by the store's one real text core, `scripts/wiki_claim_match.py`: below the 0.35 noise floor → create; a match on a standing claim → reinforce (the material inherits the settled record; no second record is opened); a match on a superseded form or retired claim → the probe outcome "superseded-repeat".
- **Rulings** are classified by observing the recorded register write through the real severance derivation (`scripts/wiki_severance.py`, register paths): the standing form appears in the derived severance list → supersede; the register line changed and nothing was severed → update (the refinement path); nothing changed → no operation.

Stated limits: claim-match proposes and a human picks — the slice scores the deterministic core, not the pick; the severance derivation's page-level frontmatter signals are out of scope (register paths only).

## First run

`python3 scripts/wiki_memory_ops_check.py` (exit 1 — disagreements are findings):

- **22 scored steps, 20 agreements, accuracy 0.9091** — create 6/6 · reinforce 8/8 · update 3/4 · supersede 3/4
- Probes 2/2 (a re-presented superseded form is flagged as a superseded repeat in both trajectories that try it)
- Live probes 3/3 against this tree's settled corpus: the seed-d1-blanket form surfaces as a superseded repeat at 1.0; a restatement of seed-d1's standing form (D2) matches a standing record; a token-novel claim falls below the floor.

## The two disagreements (the findings)

1. **traj-02 step 2 — a value change in free text classifies as REINFORCE.** The garden workday moved from Saturday to Sunday in a restated sentence; claim-match scored it 0.89 against the standing claim and the store treated it as a restatement. The text core has no value-comparison step, so UPDATE effectively exists in this store only as a register/page revision performed by the maintainer — never as a classification the machinery reaches from text alone.
2. **traj-05 step 1 — a ruling never written to the register classifies as NO OPERATION.** A coaching reversal announced in prose but not recorded in the decisions register changed nothing any surface can see (the same ruling, once recorded in step 2, classified supersede correctly). The register-or-it-does-not-exist discipline is load-bearing, and the slice now measures it.

The FEB-30 headline number (20%) and this slice's 0.9091 are not like-for-like — different store, different trajectory scale, and this battery's steps are constructed to be classifiable except where a blind spot is deliberately probed — but the two blind spots above are the same species as FEB-30's: operation errors that no QA battery would ever surface.
