# Log

Append-only. Latest first.

## 2026-10-27 — landscape weekly: the forgetting cluster; forgetting battery built

- Research (primary sources read 2026-10-27): the GitHub API for
  the tracked landscape projects; four October 2026 arXiv papers
  opened in full — Bemula (arXiv:2610.18052), Keep Your Receipts
  (arXiv:2610.17719), Beyond Downstream QA / FEB-30
  (arXiv:2610.22209), MemoryTax (arXiv:2610.29823) — plus
  Memora/FAMA (arXiv:2604.20006) and Zep v4. Raw record:
  `raw/sources/2026-10-27-landscape-weekly.md`; compiled:
  [[landscape-research-2026-10-27]].
- Build: the forgetting battery — `scripts/wiki_forgetting_check.py`
  + `evaluation/forgetting-battery.jsonl` + unit tests, and the
  "Forgetting battery" convention in AGENTS.md. First run in this
  tree: 2 severance entries, 11 checks, 0 failures; tests 6/6.
- A secondary "Graph-MIND" launch claim is recorded in the raw
  record as unverified (no matching primary repository); nothing
  was adopted from it.

## 2026-10-22 — research report ingest: capability register, source indexes, vault map

- Ingest (owner-approved in chat, 2026-10-22): the comprehensive
  research report (Completed Edition) entered the raw layer as an
  extract — preface, programme-in-numbers, how-to-read, and the
  complete fifteen-capability gap analysis, verbatim — at
  `raw/sources/2026-10-21-comprehensive-research-gap-analysis.md`,
  sensitivity class **public** (stamped in its `.ingest.json`
  sidecar; the extraction is stated on the file's own face).
  Compiled as [[comprehensive-research-report-2026-10-21]].
- The report's rows stand as data, no per-project pages:
  `evaluation/source-index.jsonl` (1,259 deep-studied rows with
  GOOD / BAD / TOOK / DIDN'T and licence) and
  `evaluation/catalogue-index.jsonl` (3,425 rows, marked
  *catalogued, not studied*; contact emails in listing text
  redacted).
- The gap analysis stands as a register:
  `evaluation/capability-register.jsonl` (15 rows; verdicts —
  idea 10, owner-gated 4, rejected 1, code 0), maintained by
  `scripts/wiki_capability_register.py`.
- Priority builds from the analysis: three verified already
  standing (severance exclusions in search; the corrections-
  ledger precheck; the lexical support check) and one built —
  the standing JSONL vault map, `scripts/wiki_vault_map.py` →
  `evaluation/vault-map.jsonl`. Owner-gated capabilities stay
  parked as register rows.

## 2026-01-16 — i18n demo pages

- Added two fictional demo pages, [[demo-guide-ja]] (Japanese) and
  [[demo-guide-ko]] (Korean), proving the seed corpus carries
  non-English pages natively; indexed under Concepts.

## 2026-01-15 — founding

- Installation created from the WikiCitadel seed. Schema: `AGENTS.md`.
- Ingest: the owner's founding note preserved at
  `raw/sources/founding-note.md`; compiled into [[overview]],
  [[decision-register]] and [[founding-note]]; the blanket form of the
  founding direction registered under a negative treatment and severed
  the same day it was asserted (see [[decision-register]]).
- The retired concept page [[standing-approval]] was tombstoned with its
  reason stated, replaced by [[decision-register]].
- One idea waits on the owner's ruling in [[ideas]].

## [2026-10-21] build | Memory and retrieval designs (Marathon Round 3, lane TB2)
Six Tier B designs landed as tested machinery in both trees: wiki_loadout, wiki_claim_chain, wiki_tiered_read, wiki_advisory_memory, wiki_claim_index scripts (+12 tests each tree) and tools/ask/groundedness_gate.py (+4 tests, default off, contract unwired). No existing files edited. Scripts 1025 / ask 289 (private), 955 / 254 (public); validator PASS both.

## [2026-10-21] build | Marathon Round 3 lane TA1 — progressive retrieval

CN5b dual-level retrieval routing (scripts/wiki_dualroute.py, deterministic R1–R8 rules over wiki_search), claude-mem 3-layer progressive-disclosure retrieval (scripts/wiki_progressive.py, stop-between-layers with visible per-layer cost), and exocortex proposed lenses from un-filed sources (scripts/wiki_lens_propose.py, proposals only, never auto-files) — built and fixture-tested for both trees; compiled page [[progressive-retrieval]].

## [2026-10-21] ingest | Capture pipeline extensions (Marathon Round 3, lane TA4)

Seven Tier A rows built in both trees: KR-R2 parse-quality gating in wiki_convert.py (score in every ingest sidecar; --quality-threshold quarantines below-threshold parses, exit 3); Memobase-pattern ingest buffer/flush (scripts/wiki_ingest_buffer.py, crash-safe claim-by-rename); clip templates auto-selected by URL pattern (scripts/wiki_clip_templates.py, generic fallback stated and recorded); MarkDownload preview-and-edit checkpoint (wiki_clip --preview + scripts/wiki_preview.py confirm, the only filing step); wallabag per-site extraction rules (scripts/wiki_site_rules.py + templates/site-rules.json); the Memos jot capture kind (templates/capture/jot.md); DEVONthink-Classify suggested filing (scripts/wiki_suggest_filing.py — suggestion only, no write path; the clip sidecar records suggested_filing). Suites: private scripts 1055 OK, validator PASS (12 warnings); public scripts 985 OK, validator PASS (34 warnings).

## [2026-10-21] build | Marathon R3 lane TA6 (Tier A conventions/templates/tools)
EU-N2 collections census, Excalidraw diagrams convention, generation
templates as files, manual-bound invocation tokens, ARK ?info lookup,
did:webvh lead page, terms-of-deposit template, Cablate naming-lock
half, JP-R2 disclosure checker, cohesion term mining, KR5
answerability-verified golden-set builder. Golden sets byte-untouched.

## [2026-10-21] build | Tier B governance + verification machinery (Marathon R3, TB3)
Eight scoped builds, both trees, new files only: checkpoint
completion predicates + evidence-strength ladder
(wiki_checkpoint_predicates.py, oota pattern); deterministic
agent-loop hooks register + runner (wiki_hooks.py, Haystack
pattern); per-source-type compilation templates under
templates/compilation/ + conformance checker
(wiki_compile_check.py, RAGFlow pattern); Crossref-gated
correction acceptance (wiki_correction_gate.py — offline
register is the authority, live Crossref an injectable seam,
default off; CiteIndex pattern); WARC writer for web ingests
(wiki_warc.py, Gnosis pattern); standalone offline verifier
for the checkpoint register (wiki_checkpoint_verify_offline.py,
verified against the live register: chain intact); HMAC-signed
pipeline receipts (wiki_receipts.py, in-toto pattern, test-only
local key); GRADE moved_by lint over grade-bearing registers
(wiki_grade_moves.py — clean against the live registers).
36 new tests per tree.

## [2026-10-21] build | Marathon R3 lane TB4 — graph/portal bundle
Relation maps + hoisting, entity-alias register, importance-with-decay
artefact, gateway conflict classifier (classify-only), section-ownership
checker, typed-IR cache, per-entity current-understanding generator,
block IDs + section embeds, per-page history/diff data, related-pages
rail data, feedback record format + triage. Scripts suites: private
1056 / public 986; gateway 81 both; validator PASS both.

## [2026-10-21] setup | Capture and triage machinery (Marathon R3, lane TB5)

Ten scoped tools landed with fixture tests (38 new tests per tree):
filing router (proposals only), rule-amendment detector (drafts,
manual-only adoption), triage verdicts (report only), companion
grouper + register, conversation-log query with cited excerpts,
snapshot bundles with hash verifier, pre-ingest OCR seam,
offline transcription seam, staging inbox with file-sidecar
register, and citekey register + checker. Concept page:
[[capture-triage-machinery]].

## [2026-10-21] build | Eval & judging machinery (Marathon R3 TB6)
Nine scoped Tier-B builds in scripts/ (CRAG gate, MiniCheck lexical fallback, LongMemEval five-ability template, quality gates, judge-output recovery, kenfold both-orders merge gate, KULLM judge-language A/B, JGLUE/KLUE native-eval agreement gate, held-out hash-manifest runner), each with fixture tests (35 new tests per tree). No model calls; no judge certified (0 owner-labelled); golden sets byte-untouched.

## [2026-10-21] build | Marathon Round 3 lane TA7 — doors and watch machinery

MCP read door gains the traverse --pin frozen read (session --pin + per-call pin argument, traverse semantics imported; tools/mcp-read/tests +9). Per-page link-health (scripts/wiki_link_health.py + Lens-inspector data file tools/lens/data/link-health.json; Lens-build wiring proposed, not landed). Automation-readiness gate (scripts/wiki_automation_gate.py + templates/automation-manifest.example.json). Gap-9 standing auto-watch (scripts/wiki_auto_watch.py + templates/watch-manifest.example.json) in front of the ingest queue — machinery only, NOT wired into any live cron; proposed cron line in the lane manifest. Build record: [[marathon-round-3-ta7-2026-10-21]].

## [2026-10-21] build | Marathon Round 3, lane TA3 — governance/lint rows
CN6a index re-derivation/fixity (scripts/wiki_index_fixity.py), EU-N5 evidence TTL (rules page + scripts/wiki_evidence_ttl.py), six cherry-picked Linter-catalogue rules (scripts/wiki_lint_rules.py, standalone — lint lanes untouched), pack-time secret-pattern scan (scripts/wiki_pack_scan.py wired into wiki_bag pack: refuses on hits, --allow-pack-findings overrides, no live hits baselined — 41 hits in 8 files on the private compiled set await the owner's ruling), retraction watch (evaluation/retraction-watch.jsonl header-seeded, scripts/wiki_retraction_watch.py, fetch seam off by default). Built in both trees; suite counts in the lane manifest.

## [2026-10-21] build | Marathon Round 3 Lane TA5 — six proposal-machinery rows

Graphify edge provenance in wiki_graph_export.py (EXTRACTED in the main census; INFERRED co-citation edges separate, dashed teal) plus five new proposal-only tools — wiki_entity_merge.py (sage-wiki), wiki_compact_proposal.py (ReMe), wiki_consolidate.py (LightMem), wiki_compile_watch.py (KR-R1), wiki_pending_review.py (Vanillaflava) — each with fixture tests (25 new tests). Scripts suites and validators re-run; see wiki/syntheses/marathon-r3-ta5-proposal-machinery-2026-10-21.md.

## [2026-10-21] build | Marathon R3 lane TB1: source-hash staleness lint, two-phase answering (flag, default OFF), blast-radius dry run, expiring intentions, version-stack detector, EU6a answer traces — abstention battery 12/12 in the lane tree, validator PASS both trees; final integrated suite counts are carried in the round-3 record page.

## [2026-10-21] build | Marathon Round 3 lane TB8 — five gated patterns

Built in scoped, tested form for both trees: Scrapbox-pattern
env-flagged destructive gateway tools (default-refused, ledgered;
fixture tool only), Langflow-pattern workflow-as-MCP-tool in the
read door (wiki_workflow; read verbs only), E2B-pattern sandboxed
verification-script runner, SearXNG-pattern low-confidence web
expansion hook (fetcher seam default OFF; UNFILED candidates
only), and the gap-15 remainder narration-plan format (data only,
no media generated). Gap-12 preset marketplace parked by standing
gate. Detail: [[marathon-r3-tb8-patterns-2026-10-21]] and the lane
manifest at ~/workspace/marathon-r3/TB8/MANIFEST.md.

## [2026-10-21] build | Marathon R3 lane TB7 — retrieval and ranking machinery
Ten Tier B rows built in both trees: exact-title/stem boost in the hybrid rankers (scripts/wiki_search.py + Lens mirror lenslib.py; Lens pool data regenerates at build), ranking-expression evaluator with shadow mode (wiki_rank_expr.py), bounded graph expansion + GraphRAG community summaries (wiki_graphrag.py), citation-scope checker (wiki_citation_scope.py), KR-R4 structured ingest register (wiki_structured_ingest.py), KAG relation index (wiki_kag.py), MemoRAG global memory (wiki_memorag.py), script normalization + Japanese dual-track profile (wiki_script_norm.py, evaluation/retrieval-profiles/), RAPTOR tree index (wiki_raptor.py), agent-object loader (wiki_agent_object.py). Abstention battery 12/12 and golden set unchanged in the lane tree; lane manifest was lost to the night's /tmp fault and is reconstructed in the round-3 record.

## [2026-10-21] build | Marathon R3 lane TA2 — evaluation benches (as persisted)
Persisted and integrated: HaluMem operations-sample fixtures + runner (scripts/wiki_eval_ops.py), Lit-RAGBench fixture + format runner (scripts/wiki_lit_ragbench.py), stale-context bench (scripts/wiki_stale_bench.py), repeat-consistency checker (scripts/wiki_repeat_check.py) and the no-context abstention bench mode in scripts/wiki_eval_extended.py. Five further rows the lane reported (bench reproducibility pack, KR-hybrid config artefact, NQ-open adapter, JE-R3 evidence pool, pickup benchmark seam) did not persist in the lane's scratch under the night's /tmp fault; they stand as remainders in the round-3 record page.

## [2026-10-21] correction | The TA2 entry above, corrected on the lane's final manifest

The earlier TA2 log entry ("evaluation benches (as persisted)") was written from an interim lane report that did not survive audit: the five rows it named as remainders (bench reproducibility pack, KR-hybrid config, NQ-open adapter, JE-R3 evidence pool, pickup benchmark seam) appear in no queue record and were not this lane's rows. Lane TA2's actual five rows, per its final manifest (~/workspace/marathon-r3/TA2/MANIFEST.md), were all built and are integrated: the JP4 LIT-RAGBench harness, HaluMem operation-level scoring, the stale-context trap bench, the --no_context control arm in scripts/wiki_eval_extended.py, and the report-only repeat/loop detector. The stale-context bench springs its traps on the live corpora (private 1/5, public 2/5, exit 1 by design) — the private trap (SCB-03) is recorded as a finding in the round-3 record page.

## [2026-10-21] ingest | Marathon Round 4 — fix round + builds

The fix round: citation lockfile regenerated (12 OK / 0 UNLOCKED, pre-existing hashes verified unchanged), Dockerfile lens-requirements fix, CI workflow added, lifecycle states declared (19 warnings → 0), ambiguous wikilinks path-qualified (9 → 0; the 2 duplicate-stem warnings remain by design — translations at parallel paths), checkpoint-test portability skip, README corrections, and the investigations (orphans/index, marathon-page citation sample, lenslib/build_lens sizes) reported in [[marathon-round-4-2026-10-21]]. Builds: memory-transparency views, TB4 Lens wiring points 1/2/3/5, CJK segmentation, publish CLI, source catalogue, memo capture + the wiki_memos read tool, schema-guided extraction, memory distil, packing check, MILU rule, reading notes.

## [2026-10-21] ingest | Marathon Round 5 — six queued builds

The web-fetch contract, the BEIR task register + harness, the RO-Crate sidecar generator, corpus-generated eval-question drafts (staging only, boundary enforced in code), the report-only FActScore atomic-claim check, and reflexion post-failure notes — with the three conventions recorded in AGENTS.md. Record: [[marathon-round-5-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 6 — seven queued builds

The CommonMark dialect pin + conformance test (15/29 pass; 14 divergences recorded as findings, renderer unchanged), the RFC 7763 variant label, MTEB task definitions, the PosQ positional slice (no collapse; an end-position penalty pinned as a tripwire), the FAIR reuse statement, the ORKG quality track, and the domain-analysis preamble. Record: [[marathon-round-6-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 7 — eight queued builds

The DocETL decomposition + gleaning pass for ingest compile, CiteSee-pattern Lens citation augmentation (the cited-text-changed date is a stated remainder — rendered dateless, never invented), Memoize-pattern git provenance with one configured edit-link prefix, tracking-parameter stripping at capture with the original preserved, the textlint starter check (config as data, our own runner, report-only), the Jotter pattern re-implemented (source records, cited-by, unconnected — report-only), the feed-clip identity + tri-state register (deliberately unwired seam), and the file-handed browser-bookmarks importer (staging only, manual-first). Record: [[marathon-round-7-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 8 — twelve queued builds

Model-identity provenance on verification lines (same-model lines stamped report-only), coverage-at-accuracy reporting for the abstention battery, the Rosenthal threat-and-disclosure register (economic and organisational failure left blank as genuine findings), a weighted damage field on snapshot records, WARC 1.1 source capture whose payload digest is the locked hash, an in-toto attestation pilot beside the checkpoint path (HMAC signature stand-in, labelled as such), Difftastic adopted as the external review diff driver with a stated fallback, a standalone persistent-identifier checker, PPI-style judge reporting (no estimate emitted at labelled-n 0), CRUD lifecycle task definitions, the RAGBench sentence-support row schema, and annotation guidelines as data (coverage honestly 0 today). Record: [[marathon-round-8-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 9 — ten queued builds

Vocabulary basis lines, the LongMemEval knowledge-update + temporal slice (a separate slice; the pinned battery untouched), the pass^k job-reliability line over a new run register, the MAST failure-mode sidecar beside the corrections ledger, the report-only failure-history precheck, the citeproc bibliography trial plus CITATION.cff (public facts only — the authors field awaits the owner's credit ruling and was not invented), the placeholders report (none found) with a link-reference export option, the Kopia snapshot pilot (a copy of this tree restored with 1,307/1,307 files hash-identical; side-copy only), heed-rate reporting (first report honestly unmeasured), and benchmark reproducibility grading (all records ungraded, stated plainly). Record: [[marathon-round-9-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 10 — twelve queued items closed

The retraction-propagation audit register and citation-function
register; trials of GROBID (door failure — no Java runtime in
the environment; evidence records the exact commands and
errors), CETEIcean (ran on a labelled fixture), kraken (door
failure at install — the dependency stack did not finish
downloading; no OCR output exists), Annotorious (ran headless,
W3C shape checker), OpenRefine and Bolognese (both ran with
evidence); the CiteIndex evidence gate (report-only), the
CSL-JSON bibliography export (empty by fact — the citekeys
register holds no citekeys), the Crossmark updates manifest, and
the CiteProof checker-accuracy ledger (3/3 seeded-bad fixtures
caught, controls clean, the real lockfile untouched). Record:
[[marathon-round-10-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 11 — nine queued items closed

The appraisal register, the RiC-style typed relation register,
the occasional-actions register, and the use / knowledge-
enhancement log; the Indic NLP, PyThaiNLP and PySastrawi trials
(all ran with evidence; the Sastrawi dictionary was not
redistributed — outputs only); the mdBook print artefact for
the declared page set; and the per-run export loss inventory.
This tree's Round 10 record page gained its missing `sources`
field (a validator error at the Round 10 base). Record:
[[marathon-round-11-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 12 — eight queued items closed

The Zaveri coverage register, the link-type tally, the
cited-source availability probe, the Automerge / Loro / TinyBase
pattern halves, integration-path merge hygiene, and the
advisory reservation register. Rounds 11 and 12 are published
together as sync entry 26 after the publish-service outage
during Round 11. Record: [[marathon-round-12-2026-10-21]].

## [2026-10-21] ingest | Marathon Round 13 — programme close

Round 11's ten queued items closed (curation register,
keeping-motivation field, share/publish vocabulary, PIOP
checklist, Janome + Kiwi trials ran, CJK rule set, ontology page
type, annotation contract with no labels created, link-graph
evaluation harness). The Rounds 4–13 programme closes here;
Rounds 11–13 stand complete locally, unpublished while the
publish service is down. Record:
[[marathon-round-13-2026-10-21]].

## [2026-10-28] lint | Fix-all pass (owner directive, 2026-10-28) — registry seeded, close 7/8, orphaned pages indexed, generator repairs ported
Under the owner's directive (fix all; WikiCitadel not to be left orphaned, keep improving it toward world-class): (1) The landscape-weekly commit of 2026-10-27 (forgetting battery) was still local-only; it is published with this pass. (2) **Tag registry seeded**: this tree carried the tags tooling but no registry, so all 47 tags in use read as unregistered — `evaluation/tag-registry.jsonl` created from the live census (46 pages, 96 uses), 47 concepts registered with first-draft glosses; check now reads unregistered 0, integrity 0. One test pin updated on the record: `test_wiki_graph_shapes` pinned TagRegistrationShape violations > 0 (true only while no registry existed); it now pins exactly 0, the shape's detection still exercised by its fixture tests. (3) **Periodic close repaired from 5/8 to 7/8**: #1 provenance manifest regenerated over the 2026-10-27 landscape files (verify CLEAN); #5 seed decision seed-d1's superseded blanket form now names its successor (its own current form, the same-day reversal). #3 stands FAIL, honestly: this seed tree carries no Black Box ledger (no `wiki/access/` layer) — building one is a feature build for the board, not a repair, and no ledger was fabricated. (4) **Index completed**: [[citation-chain]], [[corrections-ledger]] and [[periodic-close-2026-10-28]] added (new Rules and Filings sections); lint now reads 0 orphans, 0 missing from index. (5) **Generator repairs ported from the private tree**: `wiki_lint_lanes.py` neutralises wikilink brackets in every quoted excerpt (the self-poisoning loop that grew the private tree's broken links 1 → 21 over six nightly runs) and Lane 3 quotes validator lines in code blocks; `wiki_close.py` skips `#` register headers. Validator PASS, errors 0, before and after.

## [2026-10-28] setup | Severmark standard + public benchmarks page (owner-ruled product decision, 2026-10-28)
The owner's product ruling (Shape A distributed as Shape D; product name Severmark; this tree remains the open-source wiki edition) sets two build items in motion, both landed here: (1) `docs/severmark-standard.md` — the verifiable-memory pattern stated as a small implementable standard in five parts (memory receipts, severance, approval-gated writes with a trust ledger, measured abstention, conformance batteries), each part naming its WikiCitadel machinery; (2) `docs/benchmarks.md` — the standard's public claims page, every number produced by running the check in this tree on 2026-10-28: forgetting battery 2 severance entries / 11 checks / 0 failures; citation lock check PASS (12 locked, OK 12 · MOVED 0 · CHANGED 0 · MISSING 0); instrument tests 55 OK; gateway suite 91 OK. Stated plainly on the page: the abstention battery and the conflict slice CANNOT run on this seed corpus — their runners ship but the battery/slice data files do not (`evaluation/abstention-battery.jsonl`, `evaluation/conflict-questions.jsonl` absent), so no score is claimed for either. Both docs linked from README.md ("The standard" section). No commit or publish in this step — custody stays with the parent session.

## [2026-10-28] setup | Memory-operations slice built (FEB-30 pattern; port of the private wiki's slice, same day)
The landscape-weekly board item (a) from 2026-10-27, built in the private wiki and ported here the same day under the owner's delegation: `evaluation/memory-ops-battery.jsonl` (6 synthetic trajectories, 22 scored steps + 2 probes — identical to the private tree's — plus 3 live probes written against THIS tree's seed register: the seed-d1-blanket superseded form, a restatement of D2, a token-novel claim), `scripts/wiki_memory_ops_check.py` (classifies with this tree's real cores — wiki_claim_match for free-text claims, the wiki_severance register derivation observed across a ruling's recorded write; the expected label is read only by the scorer), `scripts/tests/test_wiki_memory_ops_check.py` (8/8, incl. a deliberately mislabelled fixture and a misrecorded supersession, both caught). First run: accuracy 0.9091 — create 6/6 · reinforce 8/8 · update 3/4 · supersede 3/4; probes 2/2; live probes 3/3. The two disagreements are the findings: a value change in free text classifies as REINFORCE (update exists only as a maintainer register/page revision), and a ruling never written to the register classifies as no operation at all. Registered in AGENTS.md beside the abstention and forgetting batteries; filed at [[memory-ops-slice-2026-10-28]]; the result is also on the public claims page (docs/benchmarks.md). No commit or publish in this step — custody stays with the parent session.

## [2026-10-28] decision | Owner name ruling: WikiCitadel is the name; Severmark is a branch inside it
Owner, in chat 2026-10-28 22:43 EDT: keep using the WikiCitadel name; Severmark "like a branch or something." The forward-facing docs are reframed accordingly: README and docs/benchmarks.md present Severmark as a branch of WikiCitadel, and docs/severmark-standard.md no longer calls Severmark the product name — WikiCitadel is the product; Severmark names the branch that carries the standard and its conformance work. Historical filings keep their original wording; they are records, not branding.

## [2026-10-28] decision | Owner directive: personal identifiers scrubbed from the public tree
Owner directed (chat, 2026-10-28 23:00 EDT): remove his name, his email, the family name, and any reference to him or his projects from this public repo. Scrub applied across the tree: LICENSE holder becomes "WikiCitadel contributors"; personal-name references in code, tests and the research indexes become "the owner"; account-name author/agent strings become "owner"; repo URLs and the MCP server name take the neutral wikicitadel name; the home-school fixture becomes "Example Home School"; the Google-account scope mentions become "Google scope"; the ISBN capture default timezone becomes UTC. Standards-bundle artefacts rebuilt so all six are byte-identical to a fresh build. On record: this cleans the current tree — git history and the account name in the repo's URL are outside what file edits can change, and remain the owner's call.

## [2026-11-03] ingest | Landscape research — weekly run (2026-11-03)

Weekly landscape run. Primary sources read 2026-11-03: the GitHub API (repos + releases) for the tracked landscape, GitHub release pages and READMEs opened in full, seven arXiv papers opened (one in full text). Headline: delivery is not use, and a change is not local — MemUse (arXiv:2611.01718), StateGraph (arXiv:2611.02912), rate-limited filtering (arXiv:2611.02361), Retrieved but Not Read (arXiv:2610.21731, submitted 2026-10-15 — missed by the previous run, recorded now with its real date), MemHarmBench (arXiv:2611.01700), the memory-files security study (arXiv:2610.38521) and curation+consolidation (arXiv:2610.39790). Tracked releases since 2026-10-27: PowerContext v1.5.0 (2026-11-03), Basic Memory v1.0.0, Cognee v1.6.6 stable, Graphify v0.9.97–v0.9.101; akitaonrails/ai-memory added to the tracked landscape. The first GitHub API pass hit the unauthenticated rate limit on four calls; all recovered on a second pass — recorded as a door failure in the raw source. Full record: raw/sources/2026-11-03-landscape-weekly.md; compiled: [[landscape-research-2026-11-03]]. BUILD: the dependency-revision battery — scripts/wiki_dependency_check.py + evaluation/dependency-battery.jsonl + tests (1 fallen / 0 weakened / 12 checks / 0 failures, tests 4/4) + the AGENTS.md "Dependency-revision battery" convention. No commit or publish in this step — custody stays with the parent session.

## [2026-11-03] build | Per-sentence receipt-granularity audit — built, first run filed

The receipt-granularity audit (pattern: Choudhary, arXiv:2610.17719: flat whole-page receipts wrong about two-thirds of the time vs per-sentence receipts 100%/88% faithful) is built: scripts/wiki_receipt_audit.py + scripts/tests/test_wiki_receipt_audit.py (11/11). Deterministic (stdlib only, no network, no model calls) and report-only — it never edits a citation or a claim. It scans the compiled layer (wiki/syntheses/, wiki/entities/, wiki/concepts/), counts strict-grammar claim-level markers (the validator's own grammar, code spans and fences blanked first), and classifies each page flat-only / partial / receipted / uncited against its frontmatter sources coverage (.ingest.json sidecars covered by a marker into the parent source; non-raw sources entries recorded, never counted against coverage). First run: 29 pages scanned, 12 flat-only, 0 partial, 2 receipted ([[owner]] and [[decision-register]] — the layer's 3 markers, all into the founding note), 15 uncited. Records: evaluation/receipt-audit-2026-11-03.jsonl; run filed at [[receipt-audit-2026-11-03]]. No citation was changed by the build or the run. No commit or publish in this step — custody stays with the parent session.

## [2026-11-03] build | FAMA slice for the Ask battery — built, first run filed

The FAMA-style forgetting-aware slice (pattern: Memora — Uddin et al., Findings of ACL 2026, arXiv:2604.20006; boarded 2026-10-27, owner-approved 2026-11-03, built in the private wiki and ported here the same day) is built: `scripts/wiki_fama_check.py` + `evaluation/fama-battery.jsonl` + `scripts/tests/test_wiki_fama_check.py` (10/10). Joint credit per case: an answer earns credit only when it recalls what still stands AND uses nothing the severance register has cut; a record citing severed evidence scores 0 (the catch probes, claim-level and page-level), and an all-severed case earns credit by abstaining. First run: **FAMA 1.0000 over 2 pipeline cases** (recall 1.0, non-use 1.0), 10/10 cases + fixture probes pass, 0 failures; the forgetting and dependency batteries re-ran green. Filed at [[fama-slice-2026-11-03]] — including the honest limit: this tree's compiled prose carries no text-cuttable restatement of the severed blanket form (0 lines cut), so the live cases pin recall and clean records while the non-use kinds ride the probe suite. No commit or publish in this step — custody stays with the parent session.

## [2026-11-03] build | Quote-verification gate — built, first run filed

The quote-verification gate (pattern: obsidian-second-brain v0.19.0 `verify_quotes.py`, MIT — pattern only, clean implementation) is built: scripts/wiki_quote_gate.py + scripts/tests/test_wiki_quote_gate.py (15/15). Before any reconcile or rewrite acts on a contradiction, both sides' quotes must verify verbatim — exact path, exact line range, exact text — against the cited source, judged under the citation lockfile's quote-lane normalisation (scripts/wiki_cite_lock.py, reused in-process: smart quotes straightened, whitespace runs collapsed; nothing else forgiven). A contradiction whose quotes do not both verify is dropped and counted, with the failing side and reason named. The gate consumes the stored contradiction records the reconcile path consumes — the Contradiction Cases register (evaluation/contradiction-cases.jsonl, scripts/wiki_cases.py). First run (live/probe split): LIVE — 0 records checked: this tree's Cases machinery is present but its register file was never created (no contradiction case has ever been filed here; a missing register is an empty record set, not an error), so nothing is actionable and nothing is blocked, and the first case ever filed is gated from the moment it lands. PROBES — the test suite's fixture pairs carry the run: a both-sides-exact pair verifies and passes through with its sources byte-untouched, and every drop reason fires (text-mismatch, right quote at wrong lines, missing-file, one-side-bad, lines-not-recorded, line-range-out-of-bounds). Report-only throughout: no page, claim, citation or register line was edited, and no Case was opened, ruled or closed by the gate. Regression: receipt-audit and FAMA tests pass. Results: evaluation/quote-gate-2026-11-03.jsonl (empty — no records on file); run filed at [[quote-gate-2026-11-03]].

## [2026-11-03] build | Point-of-use slice for memory delivery — built, first run filed

The point-of-use slice (board item approved by the owner 2026-11-03; pattern: MemUse — Xu, Li & Xu, arXiv:2611.01718, opened in the 2026-11-03 landscape research) is built in this tree. MemUse scores memory at its point of use — relevance / novelty / influence / observed effect per delivered entry — and its boarded form named the prerequisite: a delivery log in MemUse's form, which the Ask door did not keep. The slice builds both: tools/ask/delivery_log.py, an additive module the door's composition path can emit through (one record per question: deliveries with status delivered / severed / dropped — severed candidates logged as cut with their severing entry, never as delivered — the answer's citations, abstention, and the outcome where one is recorded; no answering behaviour changed, nothing wired into a live path by the module itself), and scripts/wiki_point_of_use_check.py + evaluation/point-of-use-battery.jsonl + scripts/tests/test_wiki_point_of_use_check.py (16/16), driving the Ask door's real deterministic core (evidence_packing with the live severance list and standings, the pickup composition rule, the answer contract) — the same core the FAMA slice pins. First run: 7 delivered items over 5 live cases — relevance 0.8571, novelty 0.8571, influence 0.5714; delivered-irrelevant 0.1429, relevant-but-unused 0.3333 (the register's lifecycle account delivered under the composition bar in PC-002, and a supplied answer citing nothing in PC-005); observed effect 1 of 7 (recorded beneficial), the rest UNOBSERVED and never inferred; 13/13 cases + fixture probes pass. The live/probe split is stated on the run page: this tree's compiled prose carries no text-cuttable restatement of its severed blanket form (the FAMA slice's finding, 0 lines), so the severed and abstention kinds ride the fixture probe suite here, as the sibling batteries' non-use kinds do. The run's delivery log: evaluation/point-of-use-delivery-log.jsonl. Regressions: FAMA tests + quote-gate tests OK (25), FAMA run still 10/10, Ask-door package tests 377 OK. Results filed at [[point-of-use-2026-11-03]].

## [2026-11-03] build | Cross-session injection slice — built, first run filed

The cross-session injection slice (board item 5, approved by the owner 2026-11-03; pattern: MemHarmBench — Wang et al., arXiv:2611.01700, opened in the 2026-11-03 landscape research) is built in this tree: scripts/wiki_injection_check.py (byte-identical port) + evaluation/injection-battery.jsonl + scripts/tests/test_wiki_injection_check.py (17/17). The slice runs PLANT → REMOVE → PROBE-in-a-fresh-composition over the Ask door's real deterministic core and judges the target NEUTRALISED / DELIVERED-INERT / STEERED / WORKING. First run: 9/9 cases + chain probes match their pinned verdicts (neutralised 2, steered 4, delivered-inert 1, working 2) — including a LIVE FINDING on this tree's seed corpus: INJ-001, the severed blanket direction D1, STEERS from its retained compiled prose. The severance entries record the claim in the founding note's wording; the decision register retains D1 reworded, and the register's TEXT match misses it (sev-0001: 6/11 cue terms, bar ≥ 9, no phrase contiguous; sev-0002: 1/6, bar ≥ 5); no page-level entry names the register page; standings mark the page tier 3 (negative, claim-scoped) but label rather than exclude, and the composition rule cites by relative score, so a fresh composition cites D1 beside D2. The case pins STEERED so the measurement cannot rot silently. INJ-002 (D2) is the benign control: WORKING. The fixture chains (two-stage, plant potent in stage A first) pin the same findings as in the private tree: the paraphrased retained instruction STEERS (2/12 cue terms), the deleted source STEERS (deletion is not severance), the weakened fixture steers (not vacuous), the verbatim severed plant is NEUTRALISED (fx-sev-1), the benign severed fact is cut (fx-sev-2), the benign standing fact works, and the delivered-inert band is recorded as ranking luck. The live/probe split is stated on the run page: this tree's corpus carries the retained-instruction kind live, in its sharpest form; the severed-by-register kinds ride the probes. Regressions: FAMA + point-of-use + quote-gate tests OK, FAMA run still 10/10, point-of-use run still 13/13. Results filed at [[injection-slice-2026-11-03]].

## [2026-11-03] build | Reading-depth gate — built, first run filed

The reading-depth gate (board item 6, approved by the owner 2026-11-03; pattern: Walters, Chen & Toni, "Retrieved but Not Read", arXiv:2610.21731, opened in the 2026-11-03 landscape research: snippet-only episodes stale 6.4% vs 1.3% for integrated reading, unfaithful citations 6.4% vs 2.3%) is built in this tree: tools/ask/reading_log.py + scripts/wiki_reading_depth_check.py (byte-identical ports) + evaluation/reading-depth-battery.jsonl + scripts/tests/test_wiki_reading_depth_check.py (12/12). The research protocol already states the rule in prose (search is discovery, never evidence; a find rests on the opened page; verification level marked at the point of reliance, never upgraded silently) — the gate makes it a checked property. The reading log is a SEPARATE record from the delivery log, by design: delivery proves what the pack showed, reading must independently prove what the answering process opened and what status it claimed, so a stripped reading record can fail closed without changing delivery semantics. Per question it records pages opened in full (page + whole line span), pages seen only as delivered passages (severed and dropped candidates never count as passage reading), the answer's citations, abstention, and the claimed reading status. The gate computes the true depth (FULL / PASSAGE-ONLY / NONE) from the log and enforces: UNOPENED-CITATION, flagged once per cited page never opened in full; SNIPPET-AS-VERIFIED, when a not-FULL episode claims verified reading (verified requires every citation to rest on a full opening); and MISSING-READING-LOG, failing closed — no log, no verified status. First run: 12/12 cases + probes meet their pinned expectations; 5 live episodes — FULL 2, PASSAGE-ONLY 3, NONE 0; citations backed by full opening 2/5 (0.4); 3 unopened-citation flags; passage-only share 0.6; 1 verified episode, 1 snippet-as-verified, 0 live abstentions. The live/probe split is stated on the run page: this tree's compiled prose carries no text-cuttable restatement of its severed blanket form (0 lines), so the all-severed abstention kind and the NONE depth class ride the fixture probe suite — whose weakened fixture (a full-opening episode with its reading log stripped) fails closed, proving the gate is not vacuous. The run's reading log: evaluation/reading-depth-log.jsonl. Regressions: FAMA + point-of-use + injection + quote-gate tests 58/58 OK; FAMA run still 10/10, point-of-use still 13/13, injection still 9/9. Results filed at [[reading-depth-2026-11-03]]. No commit or publish in this step — custody stays with the parent session.

## [2026-11-03] build | Context-reuse revalidation (reuse guard) — built, first run filed

The context-reuse revalidation constraint (board item 7, approved by the owner 2026-11-03; pattern: PowerContext v1.5.0, OceanBase, Apache-2.0 — pattern only, opened in the 2026-11-03 landscape research: context reuse whose proofs are revalidated, so forgotten memories, revoked access or expired proofs stop reuse) is built in this tree: tools/ask/reuse_guard.py + scripts/wiki_reuse_guard_check.py + scripts/tests/test_wiki_reuse_guard_check.py (14/14) as byte-identical ports, with evaluation/reuse-guard-battery.jsonl written against this tree's seed corpus. The constraint is adopted ahead of the feature it governs — if prepared context (an evidence pack) is ever reused across calls, the reuse must revalidate against the current severance, permission/standing and revision state before it is served — in two halves. THE DOOR AUDIT (AST over the door's sources, nothing executed) inspected all 22 door modules in this tree and found the same single surface as the private tree: router.py's ResponseCache, a content-addressed on-disk cache of model responses keyed by sha256 of [normalised prompt, provider, model], one-day TTL, no register revalidation — dormant (nothing in the answering path imports router; only its own tests construct it). Verdict NO-LIVE-REUSE, pinned by battery case RC-005. Packing computes fresh per call; the delivery and reading logs are write-only; the pickup's record reads are the Q&A ledger; page-text caches are function-local. THE REVALIDATION: a pack record pins each delivered item with its preparation-time folded standing and page-bytes sha256 under a register fingerprint; revalidate_record returns VALID or STALE with per-item reasons — SEVERED-SINCE (entry named), STANDING-CHANGED, REVISED-SINCE — the fingerprint necessary but never sufficient. First run: 13/13 cases + probes meet their pins; live packs VALID 1, STALE 3 (RC-002 severed-since on the overview's founding claim, entry RC-sev-1 named; RC-003 revised-since on the decision register; RC-004 standing-changed on the overview, tier 1 → 3); the probe suite mutates real files in a fixture tree, and its deliberately UNGUARDED fixture door is judged UNGUARDED by the audit, its guarded twin GUARDED, a clean door NO-LIVE-REUSE. Regressions: FAMA + point-of-use + injection + reading-depth + quote-gate tests 70/70 OK; FAMA run still 10/10, point-of-use still 13/13, injection still 9/9, reading-depth still 12/12. Results filed at [[reuse-guard-2026-11-03]]. No commit or publish in this step — custody stays with the parent session.

## [2026-11-03] build | Outcome-validated learning (SenseLab addition) — built, first run filed

The outcome-validated learning addition the owner directed in from the SenseLab idea (outcome register + confidence weighted by real outcomes; the hosted product not adopted) is built in this tree: evaluation/outcome-register.jsonl (append-only: id, recorded date, claim identity in the delivery log's hash shape + page, relied_in, outcome worked/failed/partial, an evidence pointer that must resolve, note; corrections are NEW records superseding the old — the register is never edited in place) + scripts/wiki_outcome_check.py (byte-identical port) + evaluation/outcome-battery.jsonl written against this tree's seed corpus + scripts/tests/test_wiki_outcome_check.py (16/16; LiveTests pin this tree's battery). THE FOLD: per claim start 0, worked +1, failed −1, partial 0 — all three counted; a superseded record contributes nothing, its correction (chain-resolving) in its place; per-page weight is the fold over the page's claims. THE FEEDER: the point-of-use delivery log's recorded outcomes fold into the same weights through the answers' citations (beneficial → worked, harmful → failed, neutral → partial); a register record restating a qid's own outcome for the same claim is counted ONCE (deduped), a different outcome for the same qid + claim counts on its own — proven by computing the fold two ways and requiring agreement. INTEGRITY: every claim exists in the compiled layer (block-segmented sentence split in both raw and annotation-stripped shapes, the door's own) or the delivery log, on the page named; every evidence pointer resolves (repo path, commit:<hex>, msg:<id> in raw/); supersessions name real earlier records and never fork; a delivery-referenced outcome names a claim that qid delivered. First run: 13/13 cases + probes pass, 0 failures, integrity clean; the register is seeded with exactly the outcome already on record — the point-of-use first run's 1 observed effect, beneficial → worked (OC-001 the decision-register claim via PC-001), also verifying against the compiled layer itself; 1 deduped; weights: 1 claim at +1 (page syntheses/decision-register +1), most-corrected honestly empty; coverage 1 of 3 delivered claims (0.3333), the rest UNOBSERVED — nothing backfilled, nothing inferred. The fold kinds beyond reinforcement ride the 9 fixture probes in this tree, as the sibling batteries' non-use kinds do. THE WEIGHTS ARE A VIEW: nothing in the answering path consumes them yet; wiring them into ranking is a separate future ruling. Results filed at [[outcome-learning-2026-11-03]]. No commit or publish in this step — custody stays with the parent session.

## [2026-11-03] build | History rewrite executed + host-neutral wording fixes

Two fixes landed on this local tree. (1) WORDING: the private-host leftovers are now host-neutral — pickup docs push to the `origin` remote, the decision watch's ref candidates drop the azure remote, the gateway ledger reads "the canonical git history". (2) HISTORY: a pre-rewrite audit found the Gmail-authored commits the filing targeted existed only on the GitHub stub repo, which has since been deleted and recreated empty — this local history never contained them (0 hits across all revisions, checked before and after). All 63 commits' author and committer identities were nevertheless normalised to the single GitHub noreply identity (the GitHub noreply identity), replacing the three placeholder identities in use, so the history that is eventually uploaded is uniform. Integrity proof: the HEAD tree hash is byte-identical before and after (af031b65) — no file content changed; the old objects were purged (reflog expired, gc pruned, fsck shows nothing unreachable); a full-history content scan finds neither personal Gmail address in any revision; the validator passes. Pre-rewrite backup: a git bundle held outside the repo (wikicitadel-prehistoryrewrite-2026-11-03.bundle). Still outstanding, unchanged: the upload itself waits on the owner adding the recreated repo to the Muse GitHub App's repository access, and GitHub secret scanning/push protection can only be toggled after that.

## [2026-11-03] build | Severance keyed to citation lineage (board item 10, WikiCitadel)

Board item 10 built in this tree (owner approval 2026-11-03). The severance generator (scripts/wiki_severance.py) gained a citation-lineage derivation appended after the base entries: origin receipts read from each severed claim's record page; a fixpoint closure severing any cited passage whose ^[cite:] target overlaps severed ground (wording-independent, transitive through intermediate pages); superseded-block severance on claim-record pages; dangling-citation severance (a citation whose target no longer resolves severs the citing passage); and automatic derived page-level entries for pages left with no live basis. Derived entries are marked derived, name their basis in source.record_id, and never renumber base ids. The Ask door needed no change — a derived entry carries the passage's own words, so the door's TEXT rule cuts it. On this corpus exactly one entry derives: sev-0003 for the retained D1 passage on the decision-register page, basis sev-0001, via the superseded-block relation (the origin-receipt relation does not fire here — neither founding-note span matches either claim at the TEXT bar, so the standing D2 passage is untouched). The injection slice's fixture probes now build their severance lists with the real generator, and the pins flipped: INJ-001 STEERED → NEUTRALISED (cut by sev-0003), paraphrase and deleted-source probes STEERED → NEUTRALISED; slice 9/9, verdicts neutralised 5 / steered 1 (weakened fixture only) / delivered-inert 1 / working 2, INJ-002 and all benign controls unmoved, no case or threshold weakened. The same regeneration resolved a pre-existing staleness (the decisions register's hash had drifted; entries were unchanged) — the severance check now reports up to date. Regressions: forgetting battery 3 entries, 14 checks, 0 failures (the derived entry's own checks added; preservation holds), FAMA 1.0000 (10/10), memory-ops 0.9091, point-of-use 13/13, reading-depth 12/12, reuse guard 13/13, dependency 12 checks 0 failures — all identical to baseline; the abstention battery and conflict slice ship no battery file in this tree and error on the missing file, before and after, unchanged; validator PASS (errors 0, warnings 39). New tests: scripts/tests/test_wiki_severance_lineage.py (10, all passing, including the real-corpus D1/D2 pins); test_wiki_injection_check.py updated to record the fixed behaviour. Record: [[severance-lineage-fix-2026-11-03]]. Nothing committed.

## [2026-11-03] build | Claim-once typed handoffs + access-weighted retention (board item 8, both halves)

Built in this tree. Half A: `scripts/wiki_handoffs.py` over the new append-only register `evaluation/handoff-protocol.jsonl` (state folded from offered/claimed/completed/refused events, never stored; claim-once pinned — wrong-owner, double, post-completion and post-expiry claims and pre-claim or synthesis-less completions are refused by name and the refusal is recorded; completion is the receiver's act carrying a synthesis, governing rule 5), with `scripts/wiki_handoff_check.py` + `evaluation/handoff-battery.jsonl` (10/10 probes; live register clean at 0 handoffs) and tests 12/12. No wiring is claimed in this tree: there is no filings pickup here and the Ask pickup is a question loop, not a work-handoff loop, so nothing was wired and nothing backfilled — stated plainly on the run page. Half B: `scripts/wiki_retention_weighted.py`, a sibling of `scripts/wiki_retention.py` reusing its policy/classification/filed dates, pricing observed use (delivery log deliveries + citations; standing outcome records) beside each clocked item — each use extends the review clock 7 days, capped at one extra period; keep-forever gains no clock. The build also ported `evaluation/retention-policy.json` — the file this tree's schema names as the policy of record, which the tree lacked (base check before: exit 2, policy unreadable; after the port: 257 files, 16 expired, 0 unclassed, exit 3; the tool's tests still 11/11; classes unchanged, the port dated inside the file). Weighted live run: 16 clocked, 0 with observed use, 16 past weighted date (exactly the base check's 16), 12 uses over 2 keep-forever pages (syntheses/decision-register 11, overview 1); tests 6/6 over fixtures in the real formats. Regressions: point-of-use 13/13 and outcome 13/13 unchanged; validator PASS. Filed at [[claim-once-retention-2026-11-03]].

## [2026-11-08] build | Model-routing layer Phase 1 — the routing record (board item 9, owner-approved items 21–28)

Event date 2026-11-08; written 2026-11-08. Phase 1 of the model-routing layer ([[model-routing-layer-design-2026-11-03]], [[model-routing-phase-1-2026-11-08]]), records only, no behaviour change — the design page ported into this tree with its Port notes (the input post is not in this tree's corpus, so its two cite markers were omitted rather than carried at a missing source; seat identities unnamed; J2 noted as not instantiated here). All eight owner rulings implemented: scope (B) — `decided_by: script` is a first-class record; Phase 1 records-only; floor as drawn and enforced in the record path (a floor item routed away from the Coordinator is refused, exit 3, nothing written); Ask composition untouched (Phase 3 may propose re-routing it, battery-gated); batched records for mechanical/scheduled runs, per-job for judgement jobs; suspension after exactly 3 consecutive failures of one (job kind × route) pair; outcome view as advice (Phase 2, not built); both trees. Built: `scripts/wiki_routing.py` (record / validate / suspended / check-brief; episode ids in the delivery-log claim-hash + qid scheme), `evaluation/routing-register.jsonl` seeded with the build's own two records (J4 build `a2975191c4fa9da0`, J4 delivery-log extension `b008663b79dd8397`, both outcome null pending audit), `scripts/tests/test_wiki_routing.py` (28 tests, all passing), and the delivery-log routing-fields extension landed directly in `tools/ask/delivery_log.py` (optional job_kind/route/budget_class/brief/fallback_events; old lines read unchanged, one episode not two; VERSION stays 1). Citation lockfile checked PASS (12/12 OK) with no rebuild — the port carries no markers. Batteries all identical to baseline: point-of-use 13/13, outcome 13/13 (integrity 0), FAMA 1.0000 (10/10); the abstention + conflict batteries do not exist in this tree (pre-existing FileNotFoundError, unchanged by this build — no battery file added or touched); adjacent suites 40 OK, tools/ask/tests 377 OK (2 skipped); validator PASS (errors 0, warnings 42); leak lint PASS; tag check PASS (0 unregistered). Nothing committed (the coordinator commits).

## [2026-11-08] build | Correction: leak-lint wording in the Phase 1 entry above

Correction: the Phase 1 log entry just above says "leak lint PASS". That is wrong — `scripts/wiki_leak_lint.py` reports an overall verdict of findings (32 new, 0 baselined), all in the pre-existing takehome zip `wikicitadel-prerecreate-2026-10-29.zip`. None of the 32 findings is in a file this build added or ported. The Phase 1 record page [[model-routing-phase-1-2026-11-08]] and the index line carry the corrected wording.

## [2026-11-08] build | Correction: validator warning count in the Phase 1 entry above

Correction: the Phase 1 log entry above says "warnings 42". The final validator run after the Phase 1 page was written reports warnings 43 — 42 pre-page + 1, the new warning being the Phase 1 page's own empty `sources` list. Errors 0, result PASS, unchanged. The Phase 1 record page [[model-routing-phase-1-2026-11-08]] carries the corrected count.

## [2026-11-08] build | Lifecycle flip — validator warn-legacy to enforce (Owner ruling, item 29: YES, ENFORCE)

Event date 2026-11-08; written 2026-11-08. `tools/gateway/profiles/wiki-default.json` mode flipped warn-legacy → enforce in both trees, ruling recorded in the profile comment (reversible by flipping back). WikiCitadel validator: baseline errors 0, warnings 43; flip-only errors 0, warnings 43 — the flip surfaced 0 here (this tree's transitions already declare 'current', 'active', 'superseded' and 'tombstoned'); final after this record page errors 0, warnings 44 (+1 is the record page's own empty sources list). Private tree: baseline errors 0, warnings 68 (lifecycle 14); flip-only errors 14, warnings 54; all 14 pages fixed frontmatter-only to `status: published`; final errors 0, warnings 55. New suite `scripts/tests/test_wiki_lifecycle_flip.py` (5 tests, both trees) runs the real validator against a fixture tree carrying the shipped profile: undeclared initial status errors under enforce and passes once fixed; warn-legacy copy only warns; grandfathered stays a warning. Regressions: schema 6, flip 5, routing 28, gateway lifecycle-profile 4 — all green (no test_wiki_profile.py file in this tree, pre-existing); private tree schema 6, profile 19, flip 5, routing 25, gateway 4 — all green. Leak lint run on this build's files: no new findings in them (32 pre-existing findings in the 2026-10-29 takehome zip, untouched). Record: [[lifecycle-flip-2026-11-08]]. Plan-wrong finding on the record page: the enforced initial states are the status_transitions map, not the axes vocabulary — needs-verification and deprecated still error as initial status in this tree. Stale prose flagged, not changed: profile.py / store.py / validator docstrings still describe warn-legacy as the shipped default. Nothing committed (the coordinator commits); Stage 2 in-flight work untouched; raw/ untouched.

## [2026-11-08] build | Hosted gateway door — the HTTP shim (board item 30, both trees)

Event date 2026-11-08; written 2026-11-08. Owner ruling 2026-11-08, item 30: YES, BUILD IT — build only, not activation. Built: `tools/gateway/gateway/http_server.py` (stdlib-only thin shim over `Gateway._call_tool` — no new auth/scope/write logic; binds localhost only, any non-loopback bind refused at startup; Bearer token auth reusing the salted-token registry; `/v1/` read routes first, staging-only writes, promotion exposed through the exact same `store.promote()` path) + `tools/gateway/tests/test_http_server.py` (12 tests, fixtures only). The shim and its tests are byte-identical across trees. Promote choice: EXPOSED via the shared code path (refused without manifest, refused without authorisation, succeeds only with both; tamper quarantined). Tests: gateway suite 103 green (91 pre-existing + 12 new; private tree 109 — 97 + 12); validator PASS (errors 0, warnings 44 at baseline, 45 after the record page, +1 the page's own empty sources list; private tree 60 → 61); Item 9 routing tests green (62 here, 65 private). Leak lint on this build's files: no new findings (32 pre-existing findings in the 2026-10-29 takehome zip, untouched). NOT built/deployed/activated: no real tokens, no service, no hosting, no Mem0-shaped memory routes, no OpenAI-compatible endpoint, no events feed, no webhooks, no dashboard. Gaps recorded on the record page: no versioned-path scheme for gateway tools exists in the design (Mem0 `/v3` covers the memory API, not gateway tools — `/v1/` adopted); no port specified (manual CLI default 8765 is a local convention). Stage 6 overlap note on the record page: this build realises the unified-memory Round 6 sketch's shim, so Stage 6 must reuse it, not duplicate it. Record: [[hosted-gateway-door-2026-11-08]]. Nothing committed (the coordinator commits); in-flight work untouched; raw/ untouched; `server.py` unmodified (stdio canonical).

## [2026-11-10] ingest | Landscape research — weekly run (2026-11-10)

Weekly landscape run. Primary sources read 2026-11-10: Anthropic's "The components of agent memory" (2026-11-06, opened in full); five arXiv papers opened in full (arXiv:2611.11840, 2611.12068, 2611.09721, 2611.08644, 2611.05753); the Kompl README opened in full (tuirk/Kompl, Apache-2.0 — new to the tracked landscape). Headline: a correct answer is not evidence — agreement-scored readers guess on certified-insufficient histories, and the frontier lab's production memory post measures this system's founding defences (hoarding, concurrent writers, wiki bloat) from the other side. Tracked releases since 2026-11-03: Graphify v0.9.102–v0.9.105, PowerContext v1.5.1, Cognee v1.6.7, ai-memory v3.4.x–v3.4.5; no new releases at nashsu, Mem0, LightRAG, GraphRAG, obsidian-second-brain; six projects unverified (GitHub API rate limit — door failure recorded in the raw source). Full record: raw/sources/2026-11-10-landscape-weekly.md; compiled: [[landscape-research-2026-11-10]]. BUILD: the evidence-sufficiency slice — scripts/wiki_insufficiency_check.py + evaluation/insufficiency-battery.jsonl + tests 6/6 + the AGENTS.md "Evidence-sufficiency slice" convention (8 cases, 27 checks, 0 failures; naive reader agreement 3/3, appropriate 0/3). Leak/denylist scan over this run's changed public files: clean. Local commit only in this step — publication stays with the parent session's route.
