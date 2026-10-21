# Log

Append-only. Latest first.

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
