---
id: curation-workarounds
title: Curation activities and workarounds register — the rules page
type: synthesis
status: current
created: 2026-01-15
updated: 2026-01-15
sources: []
tags:
  - governance
work_type: record
methods: "Register page for Marathon Round 13 lane BA; the column structure restates, in this edition's own words, the activity structure of Lee & Stvilia 2017 (Round 11 RA find 1)."
stage: tended
---

# Curation activities and workarounds register

Repository staff do not only follow the stated curation
procedure; they work around its contradictions, and the
workarounds are where the real practice lives (Lee &
Stvilia 2017, *PLOS ONE* 12(3), e0173987 — Texas A&M /
Florida State, CC BY; Round 11 RA find 1). This one-page
register logs an installation's own workarounds against
the study's activity structure, so a workaround is recorded
with the conditions that produced it, not as an unexplained
habit.

## The register

The register itself is `evaluation/curation-workarounds.jsonl`,
maintained with `scripts/wiki_curation.py` (`record` /
`report` / `check`). Its columns are the study's seven
dimensions, restated in our words:

| Column | What it records |
| --- | --- |
| activity | the curation or use activity the workaround belongs to |
| structure | how that activity is organised here (when, per what unit) |
| role | who performs it (owner, agent, a named tool) |
| skills_needed | the skill the activity actually calls for |
| contradiction_or_problem | the contradiction or problem that forced a workaround |
| solution_sought | the proper solution being sought, if any |
| workaround_applied | the workaround in use — the entry's reason to exist |

Each record also carries a `status` (`in-use` / `proposed` /
`retired`), a `record_id`, and the date it was recorded.

## Standing

Seeded empty-but-valid: the header line is the whole
register until a workaround actually in use is recorded.
No workaround is invented to fill the page, and recording
one here changes no procedure — a workaround that should
become the procedure is a separate decision, taken on the
record elsewhere.
