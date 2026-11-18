---
id: corrections-ledger
title: Corrections ledger
type: synthesis
status: current
created: 2026-10-22
updated: 2026-10-22
sources: []
tags:
  - rules
  - corrections
  - governance
work_type: record
methods: "House ledger format: append-only entries, each classified in the table appended to this page; the corrections-lifecycle report derives from these entries."
stage: seedling
---

# Corrections ledger

The wiki's append-only ledger of corrections. Every time a
claim, a delivery or a rule turns out wrong and is corrected on
the record, the correction is entered here together with the
standing rule it leaves — so the lesson survives as a rule
agents must honour, not as a memory of an embarrassment.
(Pattern: the `rules/` directory of
fuuuuuuma/ai-second-brain-kit, MIT, adapted to this wiki's
layout; the governing text is the "Corrections ledger" section
of the root `AGENTS.md`.)

- **Append-only.** New corrections are appended the same day
  they land. Entries are never deleted or rewritten.
- **Superseded, not erased.** If a later correction overturns
  an entry's rule, the old entry is marked *superseded* and
  linked to the entry that replaces it.
- **Read before acting.** Agents working on ground an entry
  covers read the entry first.
- This page records corrections; it does not rewrite them.
  The pages and logs where each error originally lived keep
  their own corrections in place — each entry below points at
  them.

## Entries

No entries yet. The first correction this wiki records is
appended here the day it lands, with its classification row
added to the table at the foot of this page the same day.

## Classification — entry classes, error kinds, and the repetition counter (schema addition, 2026-10-20)

This section states the ledger's classification schema; each
entry is classified here, in this appended note, never by
rewriting the entry. Patterns: the newsroom corrections
taxonomy and the Washington Post's "Bottomless Pinocchio"
repeater tracking, restated in this wiki's words.

### Entry classes — what kind of ledger act an entry is

Every entry carries one **class**:

- **correction** — we got it wrong. A statement in the
  record was false or out of bounds, is fixed, and the
  error is admitted here.
- **update** — new information superseded a statement that
  was right when it was made. No error is admitted, but
  the change is on the record, not silent.
- **verdict-change** — a standing judgement or rule itself
  changed. The old form stays archived in place — marked
  superseded and linked to its replacement, per the rule
  at the head of this page — never deleted.

**Silent fixes are not entries.** A fix may be made
silently, with no ledger entry, only when it is spelling,
punctuation, or formatting — nothing else. Anything that
changes meaning is never a silent fix: not a word that
changes the fact (a "recall" election that was a "runoff"
is a factual error, not a typo — the documented PolitiFact
loophole this class is written narrowly to exclude), not a
number, not a date, not a name, not an attribution. If it
could change what a reader concludes, it gets an entry.

### Error kinds — what kind of error was made

Every entry also carries one **error kind**, from this
fixed list (new kinds are added only by amending this
list, on the record):

- **wrong-fact** — a statement of fact that was false when
  made: the thing asserted does not exist, did not happen,
  or is not so.
- **wrong-date** — a date, deadline, duration, or temporal
  ordering stated wrongly.
- **overstated-claim** — a claim that outran what had been
  checked: a count, a scope, a coverage figure, or a
  capability asserted beyond the evidence in hand.
- **stale-after-change** — true when written; the
  underlying thing changed and the record was not changed
  with it.
- **misattributed-source** — a claim, quote, number, or
  finding credited to the wrong source, agent, or
  document.
- **broken-mechanics** — tooling or process silently
  failed, truncated, or masked a result, and a conclusion
  was drawn from the masked output.
- **conduct** — the work itself was out of bounds —
  unrequested, unauthorised, or against a standing
  instruction — whatever its factual accuracy.

### The repetition counter

A correction is not the end of an error's file — it starts
a count. `scripts/wiki_corrections.py` reads this page and
reports: entry counts by class, by error kind, and by
standing rule; and a **repeated-since-ruled** list — every
entry whose error kind had already appeared in an earlier
entry, i.e. the failure recurred after its first entry set
a rule against it. A repeated error is a different fact
from a first error: it escalates in the report instead of
quietly gaining a twin entry and being re-corrected in
silence. (The Post's threshold is a political claim
repeated twenty times; ours is one — agent errors recur
across sessions, and the second occurrence is already the
signal.) Recurrences are counted in ledger order, which is
the order the entries — and their rules — landed.

### The seeded entries, classified

| Entry | Class | Error kind | Standing rule |
|---|---|---|---|
