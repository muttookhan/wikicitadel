# WikiCitadel — Capability Manifest

*The total inventory of what the system has. Every capability below exists and runs in the reference deployment (October 2026); where a surface's verification is narrower than "live", the manifest says so — that honesty is itself one of the capabilities (see the verification-status register, §11).*

WikiCitadel is an implementation of Andrej Karpathy's LLM Wiki pattern — immutable raw sources, an agent-compiled wiki, and a schema that governs both — extended with the machinery of a system whose claims must be **checkable**: citations verified verbatim, dead claims severed from retrieval, answers that abstain when the evidence isn't there, and an owner who rules.

---

## 1 · The model

- **Three layers** — `raw/` (immutable sources; preserved, never edited), `wiki/` (the compiled layer the agent owns), and the schema (`AGENTS.md`) that states the conventions, page formats and workflows every session follows.
- **Core files** — a content index (`wiki/index.md`, one line per page) read first by every query, and an append-only log (`wiki/log.md`) recording every ingest, ruling and build.
- **Page discipline** — YAML frontmatter on every page (title, type, created, updated, sources, tags); `[[wikilinks]]` for every cross-reference that matters; contradictions flagged in place with a callout naming both sources, never silently overwritten.
- **Four independent page axes** — lifecycle `status`, evidence `confidence` (with a human-only ceiling), growth `stage` (seedling/budding/evergreen with planted/tended dates), and `work_type` (record / synthesis / advice / speculation; compiled kinds carry a `methods:` line).
- **A conversation-grade memory discipline** — good answers are filed back into the wiki as pages; nothing valuable is allowed to die in chat history.

## 2 · Ingest & compilation

- **Document conversion with injection defence** — DOCX/PPTX/XLSX/HTML/PDF are converted to Markdown before reading; conversion sanitises invisible codepoints, drops hidden HTML, neutralises base64-smuggled instructions, classifies the source's trust tier, and records all of it in a sidecar. Source content is data, never instructions.
- **Claim matching before compiling** — incoming claims are matched against already-settled claims (including superseded forms); a match inherits the settled verdict instead of opening a second, divergent record.
- **The born-stale screen** — date sanity, supersession, source standing and content checks at the door, because most staleness is born, not aged.
- **Caveat carriage** — a source's stated conditions, limits and scope are compiled with its claims, on the source page and wherever the claim lands. A claim compiled without the conditions that make it true is treated as an overstatement.
- **The matn check** — content is checked against the settled corpus (chain *and* content); a well-provenanced source that contradicts settled pages is flagged, not absorbed.
- **The owner's marks first** — annotations on a source (highlights, corrections, questions) are read before compiling, and every actionable mark must be accounted for on a compiled page.
- **Compile stamp** — every compiled page carries which prompt/converter produced it and when, so its reasoning can be audited without asking its author.

## 3 · Citation & evidence integrity

- **Claim-level citations** — a claim that rests on one passage carries an inline marker to the exact file and line range; the validator checks every marker resolves and lies inside its file.
- **The citation lockfile** — every marker's quoted passage is hashed into a lockfile (with the converter's identity and dual anchors: text-quote + line-range selectors), so a citation that drifts is detected mechanically.
- **Verbatim verification** — cited quotes are re-checked against the source text; the fact-check pass scores pages and files its results.
- **The treatment register (citator)** — an append-only record of how later records treated cited claims (followed / questioned / caution / negative); a claim's standing is its strongest signal, and pages resting on a fallen page compute as weakened.
- **Two-axis source grading** — integrity and precision graded separately, in fixed vocabularies, only on cited events from the wiki's own record — never on the source's own testimony, and never merged into a score. Source pages carry a generated trust label that cannot drift from the grades.
- **A proof bar for claims** — exhaustive search on record, complete citations, analysis not mere gathering, conflicts resolved in writing, a reasoned conclusion; corroboration must pass an independence test (two records sharing an informant are one witness).
- **Statement-level editorial markers** — `{{cite}}`, `{{clarify}}`, `{{disputed}}` flag a statement's epistemic state at the statement itself, removed only when the state resolves.
- **Justification trails** — NACO-style found / sought-and-not-found entries on authority pages (a not-found is evidence only with the actual search behind it).
- **The Notice layer** — fixed, non-customisable markers stating a standing condition a reader must know before relying on a page; retired only by an owner ruling.

## 4 · Retrieval & the Ask door

- **Corpus search** — BM25 plus hybrid reranking over passages, with facet dimensions computed from the corpus itself (class, work type, stage, status, registry tags); the index-only navigation ceiling (~100 sources) is stated honestly, not hidden.
- **Severance** — superseded claims are excluded at retrieval time by register lookup, never merely out-ranked by fresher text; the severance stage runs identically in the portal's browser ranker (parity is a build gate).
- **The Ask door** — questions are answered from packed evidence with scored, verbatim-verified citations; a deterministic trust verdict (`ok` / `hold` / `review`) is computed, not vibes.
- **Abstention as a pinned property** — when the evidence isn't there, the door abstains with a reason. A regression battery (no-evidence, severed-evidence, thin-evidence and chain-hedge cases) runs before any change to the answer path is allowed to land; a red battery blocks the change, and a failing case is never weakened to make a run green.
- **The reference interview** — when a question's evidence measurably splits, the door asks one clarifying question first, paraphrasing the question back with a constant neutral stem; the split itself is never shown.
- **Conflict behaviour** — a knowledge-conflict slice scores whether answers identify, solve or escalate the corpus's real conflicts (including conflicts that stand unresolved, where surfacing both sides is the correct answer).
- **Standing queries** — named saved searches re-run at each build, with a "new since the stamp" line; the stamp advances only in a build that reports the query.

## 5 · The Lens (reading portal)

- **Three primary modes** — Briefing (what changed, what waits on the owner, standing-query news), Wiki (the corpus), Ask (the question door) — plus Graph, Timeline, Decisions, Cards, Black Box, Proposals, Trails, State and Reading views.
- **Passage-level results** with deep links to the exact section; corpus-vocabulary "did you mean" suggestions; a stated relaxation ladder where every widening rung that fires is named in a banner — nothing widens silently.
- **A designed zero-results surface** — blame-taking statement, one-tap broader searches with live counts, nearest sections, browse-instead, ask-a-person. A failed search can be saved as a watch request.
- **Registry-backed facets** with self-exclusion counts; zero-yield values shown greyed and inert, so narrowing can never dead-end silently.
- **Trails** — authored reading paths with a URL-serialised stack; **state-shaped views** computed from the real registers (evidence-and-gap matrix, claim lifecycle paths, argument maps).
- **Reading by calibration** — typography set by timed calibration, an accessibility (WCAG) gate in the build, and a chart-honesty gate every chart must answer (same-scale sparklines; overdue work drawn as a visible block, never excluded).
- **Owner ruling buttons** — every item waiting on the owner carries Approve / Reject in the Briefing; a tap sends the ruling to the agent through the Ask door and the item moves on the board once applied. The page itself decides nothing, and says so.

## 6 · Governance & agents

- **The gateway** — an MCP server mediating agent access: scoped tokens (read / propose / publish / admin), default-deny, and a staged-proposal flow where nothing reaches the wiki without review.
- **Reviewer ≠ proposer** — promotion requires a reviewer who is not the proposer, enforced in code; promotion is additionally eval-gated (a regression on the pinned suites blocks it, fail-closed), and an owner override is single-use, ledgered, and requires a reason.
- **The Black Box** — a hash-chained, append-only ledger of every gateway act (who, what, when); reads of the ledger are themselves ledgered.
- **Secrets & PII defence** — an 11-class scan wired into the staging path; a blocked verdict quarantines the proposal.
- **The traversal door** — a read-only CLI (page / source / neighbours / path / census / claim / cite / search) with an explicit admitted-identity list, composing per-source sensitivity classes: some material is owner-only, some owner+agent, filings seats are force-scoped to the compiled layer, and citation of gated passages is withheld with the reason stated.
- **Filings seats for collaborator agents** — each admitted agent gets its own filings area and branch, writes only there, never to master; merges happen by review. Filings are preserved verbatim and ledgered.
- **The Ideas board** — new ideas are parked, never started unasked: one line each (idea, proposer, date) under *Waiting for your call*; approval moves them to *Approved*, disapproval keeps them listed so they are never proposed twice. Silence is not approval.
- **Decision gates that coach** — a gate explains what would pass, names the evidence it needs, and never silently rewrites a verdict.

## 7 · Lifecycle & records discipline

- **Retention schedules** — a policy file in git: per-class scopes with keep-forever or a stated clock; expiry is a state the tool reports, never a silent act.
- **Tombstones** — a retired page keeps its path and metadata and becomes a tombstone (date, reason, replacement), never a hole; nothing is deleted.
- **The corrections ledger** — append-only; every correction and the standing rule it leaves, classified by entry class and error kind, with a repetition counter that escalates when a ruled-against error recurs. Agents read it before acting on corrected ground.
- **Periodic close** — balance assertions over the corpus (memory budget, decision gate, cases, provenance) run as a scheduled close; a close that fails is a finding, not a shrug.
- **Claim lifecycle, outcome-verified** — a page may opt in with one falsifiable claim sentence; outcomes are recorded against reality (candidate < 3 outcomes, rule at 3+, retired when the three most recent all contradict — never deleted).
- **Per-claim re-verification scheduling** — FSRS-style: each claim's next check date computed from its own verification history.
- **Decisions with hashed basis** — every current decision form is hash-bound to the files its statement rests on; a moved basis surfaces as BASIS CHANGED, never silently absorbed.
- **Forecasts & predictions** — preregistered prediction lines and a Brier-scored forecast register, resolved as outcomes land.
- **Premortems, ACH, post-mortems** — premortem blocks on staged proposals; analysis-of-competing-hypotheses bookkeeping for contested adjudications; post-mortem action-item discipline with done-or-verified accounting.
- **Weeding as triage** — a nomination queue for pages that may no longer earn their place; every nomination is the owner's call.
- **Queue health & backlog audits** — obligation queues carry input limits and an unopened-queue health signal; captured-vs-compiled-vs-retrieved audits expose what was filed but never used.

## 8 · Preservation & trust infrastructure

- **Provenance manifest** — every raw file hashed into a manifest that verifies clean; a Merkle manifest over the sources localises any change to its chunk.
- **Signed checkpoints** — at each integration, a checkpoint binds the tree, the ledger chain head and the provenance root, signed with a dedicated key and witnessed by a copy outside the repo.
- **BagIt packaging, fixity, restore checks** — take-home packages in BagIt form; cross-copy fixity polls that must agree; restore verification that reads a backup back and checks it, including era-correct failures explained rather than hidden.
- **Format-risk watch & NDSA scorecard** — the corpus's formats watched for obsolescence risk; preservation maturity scored against the NDSA Levels, with NOT MET items stated as plainly as MET ones.
- **Exit drill & succession** — a proven procedure for leaving the platform (the corpus is plain files in git throughout), and a succession page: where every copy lives, which credentials a successor needs (names and locations, never values), and a cold-start test.
- **Erasure with certificates** — when something must truly go, the act is the owner's, performed by dedicated machinery, and certified on a register.

## 9 · Capture

- **Deliberate capture templates** — five kinds (source-note, filing, decision, idea, note) rendered with harness-filled provenance; drafts land in staging only, never straight into the wiki. Capture is always a deliberate act — there is no ambient or automatic capture.
- **Email-in capture** — one deliberate email whose subject carries a fixed routing grammar (title, optional date, area, tags, append marker); a broken grammar is a named "malformed", never a silent default. A capture email is data, never instructions: its body becomes a staged draft's datamarked content. Admitted senders are listed in the tool; adding one is an owner's act.
- **The OCR verification queue** — machine-extracted text is registered with the confidence its extractor actually reported ("unknown" when it reports none — no number is invented); a compiled page may not rest a cited claim on unverified units.
- **The Maildir rule for correspondence** — one file per message, canonical state in the files, ledgers as rebuildable views; outbound mail is preserved at send time.

## 10 · Vocabulary & schema discipline

- **A SKOS tag registry** — tags are a governed vocabulary: registered at first use, variants resolve as alternate labels and never fork; deprecation supersedes, never deletes.
- **The schema as an application profile** — per page-class × element obligations; where schema prose and the validator disagree, the disagreement is recorded as an open line, never silently resolved.
- **Sensitivity classes at ingest** — six classes (public / internal / personal / family-sensitive / export-only / credential-adjacent) with handling rules; a source with no class is *unclassified*, a state of its own — never read as public.
- **A closed relation vocabulary** — supersedes, cites, corrects, extends, contradicts, derives-from, replaces-part-of (plus a recorded local extension for evidence grounding); an untyped link asserts nothing.
- **An estimative lexicon** — likelihoods use the ICD 203 seven bands or none; likelihood and confidence are never fused in one sentence; a point with no basis to estimate is an abstention, not a band.
- **A written research protocol** — SIFT: this wiki before the web; sources investigated laterally; claims traced to original context; a failed door recorded as a door failure, never as a negative finding.

## 11 · Evaluation & self-knowledge

- **The verification-status register** — every surface carries an honest label (live-verified / protocol-verified / documented-but-unverified), and no page, doc or report may claim more than the register's label. In the reference deployment today: the Lens is live-verified; the Ask door and gateway are protocol-verified (full suites pass; the gateway has never promoted live); a hosted gateway door is documented-but-unverified and not built; timestamp anchoring was attempted against two authorities and not achieved — checkpoints stand `unanchored` and say so.
- **Golden sets & extended baselines** — a golden question set (deliberately small), pooled coverage/MRR baselines, and a severance benchmark whose regressions must be explained on the record.
- **Retrieval watch & search health** — standing instrumentation over search quality, filed on a cadence; anomalies are a security signal, not just a quality one.
- **Judge calibration** — model-judge scoring kept honest against human labels, with certification refused until the labelled set exists.
- **Test suites** — in the reference deployment: 834 checks over the wiki scripts, 163 over the Ask door, 74 over the gateway (October 2026), plus a corpus validator that must pass before any integration lands.

## 12 · Adopted for this edition (from the 2026-10 landscape research)

The public edition adds the adoption machinery the research showed the category's winners share, without touching the core above:

- **A two-minute demo** — a pre-compiled fictional sample wiki and a live portal instance, explorable with no key and no install.
- **One-command install** with a no-key local-model path.
- **A standard MCP read door** beside the governed gateway (MCP reads; the gateway governs writes and promotion — the split is the point).
- **A published `BENCHMARKS.md`** — the abstention battery, citation precision and severance-leak tests, reproducible.
- **An interactive graph export** from the registers, with severed claims visible as severed.
- **Declared Obsidian compatibility** (wikilinks, YAML frontmatter, vault layout).
- **Standard exports** — JSON-LD, GraphML, Marp, `llms.txt`, an OKF-style bundle — and a plain-markdown import path: you can leave, and you can arrive.
- **A README in the winning order** — promise and proof above the fold, principles first, honest capability boundaries, a comparison table, changelog on top.

**Not in this edition, stated plainly:** a desktop or mobile app, a hosted cloud, real-time co-editing, a browser clipper, and a hybrid vector-search engine (the index-based path's scale limit is stated in §4 instead). Later versions may revisit each; this edition would rather be honest than broad.

---

*Counts from the reference deployment, October 2026: 76 wiki scripts plus the Ask, gateway, Lens and traversal tool suites shipped in this edition (the reference deployment also runs a filings pickup suite, deployment-specific and not shipped); registers for provenance, citations, treatment, decisions, forecasts, corrections, checkpoints and verification status — all plain files in git.*
