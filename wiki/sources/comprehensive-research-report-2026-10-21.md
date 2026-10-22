---
id: comprehensive-research-report-2026-10-21
title: "Comprehensive research report, Completed Edition — gap analysis (source)"
type: source
status: current
created: 2026-10-22
updated: 2026-10-22
sources:
  - raw/sources/2026-10-21-comprehensive-research-gap-analysis.md
  - raw/sources/2026-10-21-comprehensive-research-gap-analysis.ingest.json
tags:
  - research
work_type: record
stage: seedling
planted: 2026-10-22
tended: 2026-10-22
---

# Comprehensive research report — source summary

The research programme's Completed Edition report (2026-10-22),
*The Whole Field, Studied*: every project and paper the programme
studied — the good, the bad, what was taken and built, and what
was not taken and why — with the capability gap analysis as its
centrepiece. The programme studied 1,259 rows at source (Tier 1)
and catalogued 3,425 more (Tier 2).

**What stands in this tree.** The raw layer holds an extract —
the report's preface, its programme-in-numbers, its how-to-read
section, and the complete gap analysis (the fifteen
capabilities), verbatim — at
`raw/sources/2026-10-21-comprehensive-research-gap-analysis.md`,
with the extraction stated on the file's own face and in its
`.ingest.json` sidecar. The row-level parts stand as data, not
prose: `evaluation/source-index.jsonl` (the 1,259 deep-studied
rows, with each row's GOOD / BAD / TOOK / DIDN'T fields and its
licence) and `evaluation/catalogue-index.jsonl` (the 3,425
catalogue rows, marked on their face *catalogued, not studied*;
the two sets are disjoint by name). The full report text is
preserved in the programme's private archive. No per-project
pages were created: every project is queryable in the indexes,
and a page of its own is not owed.

**Sensitivity class: public** — a research record built
entirely from public sources, ingested as this public edition's
own research; the class is stamped in the ingest sidecar.

**What was built from it.** The gap analysis stands as a
register: `evaluation/capability-register.jsonl` (maintained by
`scripts/wiki_capability_register.py`) — one row per capability
with its best source, that source's licence as recorded at study
time, a verdict (idea / code with attribution / owner-gated /
rejected with reason), and this tree's current status stated
from its artefacts. Of the four priority builds the analysis
named, three were verified already standing in this tree — the
severance exclusions in search (`scripts/wiki_search.py`), the
corrections-ledger precheck (`scripts/wiki_precheck.py`), the
lexical support check (`scripts/wiki_factscore_check.py`) — and
the fourth, the standing JSONL vault map, was built with this
ingest (`scripts/wiki_vault_map.py` →
`evaluation/vault-map.jsonl`). The owner-gated capabilities
stay parked: they stand in the register as rows, not builds.

## Conditions and limits

- A row's licence is as recorded by the study at study time,
  from the source's own licence; two of the fifteen best sources
  (cap-04, cap-06) had no licence shown on the opened page, and
  their register rows say so rather than borrowing one.
- The catalogue is a catalogue: its rows were collected and
  field-completed, not opened and studied. Only the source
  index's 1,259 rows carry studied judgements.
- The study's evaluative prose speaks of the programme's own
  wiki in the programme's own voice; the indexes carry those
  fields as the study wrote them. Contact emails appearing in
  catalogue listing text are redacted in the catalogue index.
