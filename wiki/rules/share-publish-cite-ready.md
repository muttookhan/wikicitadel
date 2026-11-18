---
id: share-publish-cite-ready
title: Share, publish, cite-ready — a controlled vocabulary
type: synthesis
status: current
created: 2026-01-15
updated: 2026-01-15
sources: []
tags:
  - governance
work_type: advice
methods: "Vocabulary note for Marathon Round 13 lane BA; the distinction and its three publish tests restate, in this edition's own words, Kuusniemi & Nykyri 2025 (Round 11 RA find 6)."
stage: tended
---

# Share, publish, cite-ready — a controlled vocabulary

These three words are not synonyms, and this wiki does not
use them interchangeably. The distinction is Kuusniemi &
Nykyri's (2025, *LIBER Quarterly* 35 — Helsinki / Tampere,
CC BY 4.0; Round 11 RA find 6): their survey found data
policies using sharing, publishing and openness as if they
meant the same thing, and separated data *publishing* from
general data *sharing* by citability, quality control and
ethical reuse. The vocabulary is held as data in
`evaluation/share-publish-vocabulary.json` and checked by
`scripts/wiki_publication_state.py`.

## The three states

- **share** — a page or dataset is made available to a
  named audience, as it stands. Sharing asserts availability
  only: the item may still change, and no test below is
  claimed for it. A shared item is not published, however
  wide the audience.
- **publish** — the item is made available AND passes all
  three tests:
  - *citability* — it carries a stable identifier or
    locator and a stated version or date, so a citation made
    today names the same object tomorrow;
  - *quality control* — it has passed the checks this wiki
    applies to it (sources cited and verified, contradictions
    flagged in place), with the check state on the record;
  - *ethical reuse* — its reuse terms are stated and
    respected: sensitivity class, consent and rights in its
    sources, and attribution are all honoured by publishing
    it.
  An item failing any one leg is shared, not published,
  whatever it is called.
- **cite-ready** — the item is published AND carries a
  complete citation form on its face — identifier, version
  or date, and locator — that resolves as written, so
  another record can cite it exactly, without
  reconstruction. Cite-ready is a state of the citation
  form, not a stronger quality claim than publish.

## Declaring a state

A page may declare its state with the frontmatter field
`publication_state: share | publish | cite-ready`.
Declaration is a claim made on the record, not a promotion
performed by a tool: `wiki_publication_state.py` reports
declared and invalid values and never writes a state. A
page with no declaration has no state — undeclared is
never read as published. This vocabulary governs the words;
it does not itself publish anything.
