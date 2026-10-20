# The quarantined extractor — CaMeLS-style, built as a boundary

`tools/ask/quarantine.py` · tests: `tools/ask/tests/test_quarantine.py`
(stdlib only, `unittest`). Additive: nothing in the existing
Ask-door flow (`pickup.py`, `answer_contract.py`, the evidence
packing, the clarification gate) imports it or changed behaviour
because it exists. Wiring it into the pickup is a separate,
future integration step — see *Honest remainder*.

## Where the design was documented (before this build)

The extractor was the survey programme's one named *unbuilt*
remainder — documented in four places, all read before building:

1. **The primary find** — `raw/sources/2026-10-19-feature-survey/wave3-agent-systems.md`,
   §b2 "CaMeLS — Defeating Prompt Injections by Design (Google
   DeepMind, arXiv:2503.18813) — FOR US": instead of filtering
   text, change the architecture — a *privileged* LLM translates
   the user's request into code in a locked-down Python subset;
   a custom interpreter executes it, tracking **provenance and
   capability tags on every value** (data derived from untrusted
   sources stays tagged forever); a *quarantined* LLM extracts
   structured values (typed schema) from untrusted content but
   can **never call tools**; policies are enforced on the
   resulting data-flow graph. Reported there: 77% of AgentDojo
   tasks solved *with* security guarantees vs 84% undefended.
   Explicit non-goal (from the paper, noted in the find):
   text-to-text attacks that never touch control or data flow.
2. **The compiled survey** — `wiki/queries/wiki-feature-survey-2026-10-19.md`,
   wave-3 §4: "capability/provenance-tagged data flow plus a
   quarantined extractor LLM that can never call tools — the
   only injection defence found with a design-level guarantee;
   the Ask-door upgrade pattern."
3. **The recorded next step** — `tools/ask/pickup.md`,
   "Injection defence: datamarking now, CaMeLS next (wave-3,
   2026-10-20)": the full design restated for this door — a
   **privileged planner** that never sees raw untrusted text,
   and a **quarantined extractor** that reads the retrieved
   content but holds **no capabilities** (cannot call tools,
   write records, or act) and returns only structured data
   (facts with provenance) to the planner; data flows carry
   capability/provenance tags; the planner's policy engine
   refuses any plan whose actions depend on data tagged as
   untrusted-origin beyond stated limits. It closes honestly:
   "It is **not** implemented here: today's pickup is a single
   agent that retrieves and composes in one context, and no
   extractor/planner split exists." `answer_contract.py` §9
   says the same from the contract side.
4. **The remainder notices** — `wiki/ideas.md` (the Ask-door
   injection-defence line: "built 2026-10-20 (datamarking layer
   built; the CaMeLS quarantined extractor is documented as the
   next step, not built)"), `raw/sources/2026-10-19-feature-survey/wave10-synthesis.md`
   (the extractor named as a remainder of a built item, *not* a
   queue item — "a build decision for the owner/parent to
   re-queue explicitly"), and `wiki/log.md` (the Phase-8
   completion entry: "Named remainders that were never queue
   items stand as they were: the CaMeLS quarantined extractor
   (documented, not built)").

This build is that explicit re-queue.

## Documented design vs as built

| Documented (CaMeLS / pickup.md) | As built here |
|---|---|
| Quarantined extractor reads untrusted content, holds no capabilities, cannot call tools / write / act | The extractor is an **injectable callable** invoked by the boundary module. The module gives it no tools, no file access, no context — it receives data, returns data. That a production extractor wraps a capability-less model instance remains the deployer's wiring; the boundary enforces everything enforceable in code at the seam. |
| Extractor returns only structured data, typed schema | Enforced: a declared schema (list of `{name, type, required?, max_length?, max_items?}`; types `string` / `integer` / `number` / `boolean` / `string_list`); every returned field type- and size-checked; unknown fields dropped and recorded. |
| Privileged planner never sees raw untrusted text | Preserved as a boundary property, not a planner: the only thing that can cross to any privileged consumer is the envelope's validated `data`, obtained via `trusted_data()`. Raw text never appears in the envelope (only its hash and length). |
| Provenance / capability tags on every value | Partial — see remainder. The **envelope** carries provenance (source id, SHA-256 of the source text, source length, extractor id, timestamp, the schema). There are no per-value capability tags and no interpreter tracking tags through a computation. |
| Planner's policy engine refuses plans depending on untrusted-tagged data beyond limits | **Not built.** No planner, no plan representation, no policy engine exists in this module. The downstream-facing mechanism built instead is the envelope's trust flag (`trusted` / `quarantined`, checked by `is_trusted()` / `trusted_data()`). |
| Privileged LLM translates the request into code in a locked-down subset; a custom interpreter executes it | **Not built, deliberately.** No code generation or execution of any kind was added — executing generated code is a new attack surface this remainder never asked for. |
| (Ask-door layer already built) datamarking + instruction-leak check | Unchanged and complementary: datamarking guards the compose-in-one-context path that exists today; the extractor is the split the pickup.md note records as the end-state. This module's tripwires reuse that layer's narrow-pattern posture. |

## The boundary rules (as enforced in `quarantine.py`)

1. **Only two things cross in.** The extractor is called as
   `extractor(untrusted_text, schema_view)` — exactly two
   positional arguments, no keywords. The source id, the
   question, wiki context, and every other piece of caller state
   stay on the trusted side. The schema view is a fresh copy: an
   extractor that mutates it cannot reach the schema validation
   runs against. (Proven by `BoundaryTests`, whose fake asserts
   its exact inputs.)
2. **The extractor's return is untrusted too.** It is validated
   field by field against the trusted side's own schema copy.
   Unknown fields are dropped and recorded in
   `validation.dropped_fields` — dropped, never passed.
3. **Only validated data crosses out, inside a provenance
   envelope.** `kind: quarantined-extraction`, `status`,
   `trusted` / `quarantined` flags, `data` (or `None`),
   `provenance` (source id / SHA-256 / length, extractor id,
   timestamp, schema), `validation` (dropped / rejected /
   tripwire hits / missing fields / errors), and `quarantine`
   (reason + detail, or `None`). Envelopes are plain
   JSON-serialisable dicts.
4. **Tripwires flag, never obey.** Extracted strings (and
   string-list items) are scanned for instruction-shaped
   patterns — instruction overrides, agent-directed imperatives
   and secrecy directives, tool-call shapes, credential-carrying
   URLs, credential assignments, role impersonation, datamark
   escapes. A hit names the field and pattern in
   `validation.tripwire_hits`, withholds the value, and
   quarantines the envelope. Hits are recorded data; nothing in
   this module executes, follows, or acts on extracted content
   of any shape. Known cost, stated: the patterns are a narrow
   heuristic and still false-positive on some ordinary prose
   (e.g. any extracted string mentioning a "system prompt") —
   the consequence is a hold for human review, never a silent
   pass and never a silent drop.
5. **Fail closed.** Extractor exception, non-mapping return,
   mistyped / oversized value, missing required field, tripwire
   hit, or an input over the size limit (the extractor is not
   called at all) → a quarantined envelope with `data is None`
   and an explicit `quarantine.reason`
   (`extractor_error` / `extractor_bad_return` /
   `schema_mismatch` / `tripwire` / `input_oversized`).
   Partial trust is never emitted: one bad field holds the
   whole extraction, because the clean fields came from the
   same untrusted pass. The only non-quarantining anomaly is
   the unknown field (rule 2), which never crosses.
6. **Caller bugs are not data.** A malformed schema or a
   non-string input raises (`ValueError` / `TypeError`) before
   the extractor is called — those are trusted-side defects,
   surfaced loudly, not quarantine records.

Strictness details that matter: `bool` is rejected as an
integer/number (Python subclassing notwithstanding), numbers
must be finite, integer fields reject floats even when
integral, string lists must be actual lists of strings, and
crossed lists are copies, not aliases of the extractor's
structures.

## Honest remainder

- **No real model is wired.** There is deliberately no model
  call, no network, and no API client in the module. The
  injectable extractor callable is the deliverable seam: a
  future integration supplies a capability-less model wrapper
  behind it, and the boundary, validation, tripwires, and
  envelope are already in place and tested with fakes.
- **Not integrated into the pickup.** `pickup.py` still
  retrieves and composes in one context behind the datamarking
  layer, exactly as `pickup.md` describes. Routing retrieved
  content through this extractor — and splitting planner from
  extractor in the pickup procedure — is a separate integration
  that touches the Ask path and therefore falls under the
  abstention/conflict regression gate in `AGENTS.md` (battery +
  conflict slice re-run before integration). This build changed
  no Ask-path behaviour, so that gate was not triggered by it.
- **No per-value capability tags, no policy engine, no
  planner** (see the table). What a consumer gets is a binary,
  checkable trust decision per extraction, with provenance —
  not CaMeLS's full data-flow tracking. Calling this "CaMeLS
  implemented" would overstate it; it is the CaMeLS *extraction
  boundary*, in the survey's own terms the quarantined half of
  the design.
- **Tripwires are a heuristic**, like the datamarking layer's
  leak check: they hold suspicious values for review; they are
  not a proof that clean-crossing values are safe. The design's
  actual guarantee is structural — an extractor with nothing to
  call and a crossing that only admits typed, bounded values —
  not the pattern list.

## Licence note

CaMeLS is an idea from a paper (Google DeepMind,
arXiv:2503.18813), catalogued in the survey as a design rule
carrying no licence risk. This is an independent
re-implementation in this tree's own code, stdlib only; no code
was copied from any CaMeLS artefact.
