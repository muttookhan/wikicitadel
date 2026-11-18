---
title: Periodic close — 2026-10-28
type: query
created: 2026-10-28
updated: 2026-10-28
sources: []
tags: [close, balance-assertions, accounting, filings]
status: draft
confidence: observed
stage: seedling
planted: 2026-10-28
tended: 2026-10-28
work_type: record
---

# Periodic close — 2026-10-28

The wiki's periodic close (WikiCitadel v1;
`scripts/wiki_close.py`; pattern: Beancount's balance
assertions + periodic close, wave-4 survey, mechanic
only). Each assertion declares the state the books
should be in and recomputes what they are in; both
sides' numbers are printed. **The close surfaces, it
never fixes** — a FAIL below is a finding for the
owner/maintainer, with the items behind it named.

Generated from this tree's own registers by
`scripts/wiki_close.py`; it cites no raw source — its
evidence is the registers it recomputes. (Until
2026-10-28 the template cited a placeholder path,
docs/research-notes.md, that does not exist in this
tree; the citation was a template artefact, removed
at the fix-all pass.)

Result: **7 of 8 assertions PASS**; FAIL: #3. Previous close: 2026-10-28.

| # | Assertion | Declared | Computed | Verdict |
|---|---|---|---|---|
| 1 | Provenance — recorded raw/ == raw/ on disk | 6 files recorded | 6 files on disk | **PASS** |
| 2 | Citation lockfile — locked == markers; manifest sources == sources cited | 12 locked · 1 manifest sources | 12 markers · 1 sources cited | **PASS** |
| 3 | Black Box — hash chain verifies; entries == last seq + 1 | a Black Box ledger exists | no black-box-*.jsonl under wiki/access | **FAIL** |
| 4 | Registers — every evaluation/*.jsonl parses; append-only registers never shrink | 0 unparseable lines · 0 shrunk append-only registers | 0 unparseable · 0 shrunk | **PASS** |
| 5 | Decisions — superseded forms name a successor; current forms stated on a page | 1 decision(s), 1 superseded form(s), each with a successor; every current form stated | 1/1 current forms stated | **PASS** |
| 6 | Evidence — register evidence paths resolve on disk | every cited evidence path resolves | 1 path(s) checked, 0 unresolved | **PASS** |
| 7 | Ideas board — every Approved item accounted for | 1 Approved item(s), each with a BUILT marker or a build-queue reference | 1 accounted for, 0 exception(s) | **PASS** |
| 8 | Memory budget — ~/MEMORY.md stays lean | <= 9000 bytes | 8998 bytes | **PASS** |

## 1. Provenance — recorded raw/ == raw/ on disk — PASS

added 0 · changed 0 · missing 0


## 2. Citation lockfile — locked == markers; manifest sources == sources cited — PASS

unlocked 0 · orphaned 0 · manifest-only sources [] · cited-only sources []


## 3. Black Box — hash chain verifies; entries == last seq + 1 — FAIL


## 4. Registers — every evaluation/*.jsonl parses; append-only registers never shrink — PASS

42 register(s), 5010 non-empty line(s); append-only shrink check vs the 2026-10-28 close


## 5. Decisions — superseded forms name a successor; current forms stated on a page — PASS

stated on: seed-d1 -> wiki/syntheses/decision-register.md


## 6. Evidence — register evidence paths resolve on disk — PASS

treatment subjects + treating sources; source-grade sources + evidence refs; research-log pages


## 7. Ideas board — every Approved item accounted for — PASS

built marker: 1

No exceptions: every Approved item is accounted for above.


## 8. Memory budget — ~/MEMORY.md stays lean — PASS

within budget

## What happens to a FAIL

Nothing automatic. A failed assertion is a balance that
does not balance: it stays on this record until a later
close shows it resolved. Fixes belong to the surfaces
that own them (the provenance tool, the citation lock,
the registers' own tools, the MEMORY.md slimming rule)
— never to the close itself.
