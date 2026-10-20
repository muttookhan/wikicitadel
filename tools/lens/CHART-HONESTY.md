# Chart honesty gate — the Lens build checklist (item 65)

Every chart that ships in the Lens answers to this list before it
ships. The rules are Alberto Cairo's, restated as checkable items
(wave-7 surfaces lane, find 18), plus this wiki's own vanity rule.
Items marked **[mechanical]** are checked over the built artefact
by the Phase-8 lane of `tools/lens/smoke_test.js` (reported
separately from the main smoke counts) or by
`tools/lens/stateviews.py`'s geometry; the rest are checked by the
builder's eye at the moment a chart is added — a chart that cannot
pass an item does not ship until it can.

## The gate

1. **Bars and bullets start at zero.** No truncated axis on any
   length-encoded quantity, ever. If a truncated scale were ever
   unavoidable, the axis would carry a visible break mark and the
   caption would say why — no chart in the current build does
   this. **[mechanical]** bullet geometry is computed in
   `stateviews.bullet_geometry` from a zero baseline.
2. **Length before area before angle.** Quantities are encoded by
   position or length (bars, bullet bars, mosaic square COUNTS,
   prefix-bar widths). No bubble sizes, no pie slices, no
   area-scaled icons.
3. **One scale per comparison.** Sparklines that invite comparison
   share a scale; the shared maximum is computed once
   (`stateviews.lint_lane_series`) and printed in the caption.
   Different scales per lane would lie by shape. **[mechanical]**
   the Phase-8 smoke lane asserts every lane's sparkline was
   plotted against the artefact's single `shared_max`.
4. **Numbers beside the marks.** Every chart carries its exact
   values as text next to it (bullet values and target labels,
   sparkline first → last values, forecast counts). A shape you
   cannot read a number off is decoration, not evidence.
5. **The caption states what the view cannot show.** Each new view
   names its own bound in its caption: the matrix cannot show
   whether citations support claims; the forecast does not project
   re-scheduling after a verification; the lifecycle view's state
   order is stated, not smuggled.
6. **Overdue is never excluded from a window.** A forecast that
   starts at today and drops what is already due lies by omission
   (the Anki Future Due flaw). The due-now block leads the
   forecast artefact and the rendering. **[mechanical]** the
   Phase-8 smoke lane asserts the forecast's `due_now` block
   exists and the renderer's output contains it.
7. **Colour is never the only channel.** State squares pair colour
   with column position and a printed count; support/attack edges
   pair colour with a + / − glyph; bullet bands pair shade with a
   printed label and tone word.
8. **No chartjunk.** No gradients encoding nothing, no 3-D, no
   decorative axes. Gridlines only where they carry a value (the
   forecast's cumulative line is dashed and labelled as the
   do-nothing scenario, in words).

## The vanity-metrics admission rule

A metric joins the Briefing as a health signal only if it can
change a decision — the test: **"if this number moved 20%, what
would I do?"** A count that can only grow answers "nothing": it is
demoted to *context*, labelled as context where it stands, and the
health section is carried by numbers that can demand action (due
counts, open cases, lint counts, gate distances).

Applied to the Briefing's current metrics (also recorded in the
built artefact, `briefing.honesty.admission_verdicts`):

| Metric | Verdict | Why |
|---|---|---|
| Pages | context | Cumulative corpus size; cannot go down; a 20% jump decides nothing. |
| Raw sources | context | Provenance inventory size; growth is the ingest rule working, not a signal. |
| Decisions decided | context | Register size; the actionable form — decisions awaiting a ruling — already stands under "Waiting on you". |
| Log entries | context | Activity volume; more is not better or worse. |
| Graph edges | context | Grows with the corpus; the actionable forms (orphans, broken targets) are lint bullets. |

Admitted as health (the bullets): claims past re-verification due,
open contradiction Cases, broken link targets, source pages citing
no raw source, retrieval MRR and citation coverage @10 against
their recorded baselines. Locked-citation coverage is *not*
admitted yet: it has no declared target on record, and a bullet
without a target is a bar wearing a costume — it joins when the
owner sets the target.
