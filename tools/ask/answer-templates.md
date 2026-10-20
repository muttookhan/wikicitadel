# Lens Ask — answer templates per question type

the build (owner-approved). The pickup agent classifies
every question into one of the four types below, decomposes compound
questions into sub-questions of one type each, and composes each
(sub-)answer in that type's shape. Every shape ends the same way:
**cite, or abstain** — the abstention contract in `pickup.md`,
enforced deterministically by `answer_contract.py`.

Citations are wiki page ids (path under `wiki/` without `.md`,
e.g. `overview`, `syntheses/decision-register`) for pages actually
read through the gateway in this run. Never cite a page not read.

---

## Modes (batch 2.1) — the asker's choice shapes the answer

The question record carries a `mode` chosen by the asker:

- **`answer`** (default; also every question filed before modes
  existed): compose one answer in the shape of its type, below.
- **`search`**: passages only — no composed answer. Return the
  supporting passages themselves: the answer text is a one-line
  framing, and each citation is scored (`citation_details` with
  page, score and the exact verbatim passage). Do not summarise,
  do not conclude — the passages are the answer.
- **`deep-research`**: decompose first (see Decomposition below —
  at least two sub-questions), answer each in its own type's shape,
  then compose. A deep-research question answered as a single
  one-shot answer has not been answered in its mode.

Scored citations: wherever a citation supports a specific claim,
record it in `citation_details` as `{page, score, passage}` —
score 1.0 when the passage directly states the claim, ~0.5 for
solid support, and never cite a passage scoring under 0.25 (find a
better one, or abstain). The passage must be verbatim from the
page; the contract verifies it.

---

## 1. Factual lookup — "what is X / when did Y happen / what is the state of Z"

Shape:

- One direct answer, first sentence first: the fact itself, plainly.
- Each fact in the answer traces to a cited page. If two pages
  disagree, say so and cite both — never silently pick one.
- Dates and numbers are stated with their as-of context when the
  page carries one.

Abstain when: no read page states the fact. Name the fact that is
missing ("the wiki does not record X") and, where useful, the
source that would settle it ("a page on Y would settle this").

## 2. Comparison — "X vs Y / which is better / how do A and B differ"

Shape:

- One short section (or paragraph) per option, in the question's
  order. Each option's claims cite that option's own pages — an
  option is never described from another option's page.
- A closing line that answers the actual comparison (the difference
  that matters, or the verdict the evidence supports), citing the
  pages compared.
- An option the wiki barely covers is flagged as thin evidence in
  its section, not silently padded from general knowledge.

Abstain when: either side has no citable coverage — a comparison
with one uncited side is not a comparison. Name the uncovered side
and what would settle it.

## 3. Synthesis — "what do we know about X / summarise the position on Y"

Shape:

- Claims grouped by theme, not by page. Each theme's claims cite
  the pages they rest on; a theme resting on a single page says so.
- Contradictions and open disputes between pages are surfaced as
  their own theme, cited to both sides.
- A closing **coverage note**: what the wiki does *not* cover about
  the question, stated plainly (the gbrain coverage-gap pattern,
  wave-1 survey). A synthesis without its gaps reads as more
  complete than it is.

Abstain when: the pages found do not actually address the question
(topical neighbours are not evidence). Name the gap as the missing
coverage it is.

## 4. Decision history — "what was decided about X / why did we do Y"

Shape:

- A chronological chain: each decision in date order, one line or
  short paragraph each, cited to the page that records it (a
  decisions page, the log, or the page carrying the ruling).
- The **current state** is stated last and cited separately from
  the history — history explains it, it does not substitute for it.
- Superseded or reversed decisions are marked as such, with the
  superseding decision cited. Never present a reversed decision as
  current.

Abstain when: no page records a decision on the matter — "not
recorded" is the answer, and it must not be reconstructed from
adjacent decisions. Name the decision that is missing.

---

## Decomposition (compound questions)

A question asking two or more things ("what did we decide about X,
and how does it compare to Y?") is split before searching:

1. Write the sub-questions down — they go in the answer file's
   `sub_answers`, each with its own `question`, `answer`,
   `citations` (or its own `abstention_reason`).
2. Classify, search, read and compose each sub-question separately,
   in its own type's shape.
3. The composed answer joins the sub-answers in the question's
   order, with a one-line lead if the parts connect. The composed
   answer's `citations` are the union of the sub-answers' citations
   (enforced by `answer_contract.py`).
4. A sub-question that abstains does not sink the others: the
   composed answer gives the answered parts, cited, and states the
   abstained part as an abstention in place.
