---
id: capture-triage-machinery
title: Capture and triage machinery
type: concept
created: 2026-10-21
updated: 2026-10-21
sources: ["raw/sources/founding-note.md"]
tags:
  - capture
  - triage
  - machinery
work_type: record
stage: planted
---

# Capture and triage machinery

The capture/triage half of the Tier B bundle "Graph, portal and
capture forms", built for the demo corpus from patterns surveyed
in other wiki systems. Foreign systems are ideas only unless a
verified MIT/Apache licence is recorded; everything below is an
original re-implementation, machinery plus fixture tests, and
nothing auto-applies changes to compiled pages.

## The ten pieces

1. **Filing router** — `scripts/wiki_filing_router.py` (crow-hq
   pattern, AGPL → ideas only). Routes an incoming filing/capture
   to a proposed destination with a confidence and reasons;
   proposals only, plus an `audit` pass listing misfilings.
2. **Rule-amendment detector** — `scripts/wiki_rule_amendments.py`
   (Newsroom meta loop). Recurring failure patterns in the
   lint/sweep filings are drafted into rule-amendment proposals;
   a draft is never adopted automatically.
3. **Triage verdicts** — `scripts/wiki_triage.py` (Omnia pattern,
   ideas only). A report-only pass over open items emitting
   act / park / escalate verdicts with reasons; a recorded verdict
   is not re-litigated.
4. **Companion groups** — `scripts/wiki_companions.py`
   (pin-llm-wiki pattern, Apache-2.0). Sources that are companions
   of one work (repo + paper + talk) are unified under a companion
   group record at `wiki/companion-groups.json`; the grouper
   proposes groups from shared identifiers.
5. **Conversation-log query** — `scripts/wiki_convo_query.py`
   (DiaryKG pattern, ideas only). Queries a conversation log by
   date, speaker, keyword and decision markers, returning cited
   excerpts (file + line ranges). The public tree ships the tool
   with a fixture log only — it has no real conversation log.
6. **Snapshot bundles** — `scripts/wiki_snapshot.py` (ArchiveBox
   pattern, MIT). Each web source can carry a bundle of fetched
   bytes + headers + a hash manifest, with a verifier; the fetcher
   is injectable and tests never touch the network.
7. **Pre-ingest OCR seam** — `scripts/wiki_preocr.py` (OCRmyPDF
   pattern, MPL → ideas only). Scanned/binary sources route
   through an OCR stage interface before conversion; an absent
   engine is a clean refusal, and extraction confidence is
   recorded to the OCR queue.
8. **Transcription seam** — `scripts/wiki_transcribe.py`
   (Handy/Buzz patterns, MIT). Offline transcription of
   owner-selected recordings through a local engine interface;
   unconfigured means a clean refusal with instructions. No model
   downloads, no network, no watch folder.
9. **Staging inbox** — `scripts/wiki_staging_inbox.py`
   (Karakeep/Linkwarden/Readeck/Paperless shapes, AGPL/GPL →
   ideas only). Captures land in staging with a state
   (new / triaged / filed / parked) held in a sidecar register in
   the files, never a database; moves follow a fixed transition
   table.
10. **Citekeys** — `scripts/wiki_citekeys.py` (Citations plugin
    pattern, MIT). Literature notes gain author-year-key citekeys
    with a register at `wiki/citekeys.json`; the checker proves
    every citekey resolves, is unique, and every `[@key]`
    reference in the wiki resolves.

## Shared discipline

Every tool is proposal-, report- or seam-shaped: routing is a
proposal, triage is a report, amendments are drafts, companion
groups are proposals until a recorded `apply`, OCR and
transcription refuse cleanly rather than degrade silently, and
the staging inbox is the only piece that writes state — its own
register, on an explicit reviewed move.
