---
id: evidence-ttl
title: Evidence TTL — the rules page
type: synthesis
status: current
created: 2026-01-15
updated: 2026-01-15
sources: []
tags:
  - governance
work_type: advice
methods: "Convention adopted from the object-TTL pattern in the project's research notes; enforcement is scripts/wiki_evidence_ttl.py."
stage: tended
---

# Evidence TTL

Evidence expires unless reaffirmed (EU-N5; pattern: a
per-collection object TTL — a declarative "evidence
expires unless reaffirmed" mechanism). A claim is only as
fresh as the evidence under it, and a page that knows its
evidence ages must say how fast.

## The convention

A page — a claim page included, since claim pages are
pages — may carry two frontmatter fields:

- `evidence_as_of: YYYY-MM-DD` — when the evidence the
  page rests on was last gathered or checked.
- `evidence_ttl_days: <positive integer>` — how many days
  that evidence may be relied on from the as-of date.
  The form `evidence_ttl: "90d"` is accepted as the same
  statement.

The due date is `evidence_as_of + evidence_ttl_days`. On
or after it, the evidence is **due for refresh**: a
re-check against the sources is owed before the page's
claims are relied on as current. Refreshing means doing
the re-check and moving `evidence_as_of` to the date it
was actually done — never moving the date without the
check.

## What the fields are not

- Not an owner attestation. `verified_until` /
  `verified_by: owner` is the owner's positive freshness
  signal and stays owner-only; evidence fields are
  agent-writable because they record when evidence was
  gathered, not that anyone verified the page.
- Not a deletion or retirement clock. A due page is not
  wrong, severed, or tombstoned; it is owed a re-check.
  Nothing is removed when a TTL lapses.
- Not mandatory. A page with no evidence fields is
  outside the convention and is counted, not flagged.
  A page may carry `evidence_as_of` alone as a dated
  record with no horizon; that is the honest no-TTL
  state.

## The checker

`python3 scripts/wiki_evidence_ttl.py [--as-of DATE]
[--json] [--all]` reports, over the compiled layer
(filings and talk pages excluded, as in the lint lanes):

- **due** — pages past their due date, most overdue
  first, with the as-of, the TTL and the due date;
- **invalid** — a TTL with no as-of, an unparseable
  as-of, or an unparseable TTL. A half-stated TTL is
  worse than none, because a reader may trust a horizon
  that does not exist;
- **current** — pages inside their TTL (listed only
  with `--all`).

The checker reports only. It never edits a page, extends
a date, or retires a claim; exit 1 means due or invalid
findings exist, so a nightly sweep can surface them
beside Lane 2 of the lint lanes.
