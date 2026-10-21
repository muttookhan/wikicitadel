---
title: "Marathon Round 4 — record (2026-10-21)"
type: synthesis
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: [marathon, record]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: record
methods: "Written from the artefacts: suite counts re-run in this tree after integration; the fix round's per-task verification is stated with its evidence. This page is a build record; its claims are checkable against the code, the tests and the registers in this tree."
---

# Marathon Round 4 — record (2026-10-21)

## The fix round (a code review's findings, executed)

1. **Citation lockfile regenerated** with
   `scripts/wiki_cite_lock.py build`: 4 → 12 citations,
   covering the 8 i18n markers that were UNLOCKED. The
   check reads **12 OK / 0 UNLOCKED**. Every pre-existing
   hash was verified unchanged before the result was
   accepted (the source's own sha256 is unchanged in the
   manifest); nothing in `evaluation/` was hand-edited.
2. **Dockerfile** installs `tools/lens/requirements.txt`
   before the Lens build step. Every step is verified
   locally; **the image build itself is unverified where
   Docker is unavailable** — stated in the README's
   limitations.
3. **CI workflow** `.github/workflows/ci.yml` added
   (push + pull request, Python 3.12, openssh-client,
   PyYAML, the README test command, `sh install.sh`, a
   Lens rebuild). YAML validated locally; a full
   actionlint was not possible. Note: publishing workflow
   files requires the publishing integration to hold the
   workflows permission; where it does not, the file
   ships in the tree but the hosted workflow cannot be
   registered by the integration alone.
4. **Lifecycle states declared** in the gateway profile:
   `current` and `tombstoned` join the axes vocabulary;
   `active`, `current`, `tombstoned` are declared states
   with their transitions (tombstoned terminal). The 19
   "not a declared state" warnings are **zero**.
5. **Ambiguous wikilinks path-qualified**: ambiguous-
   wikilink warnings 9 → 0, and the Lens build prints no
   "id collision" note — the six shared i18n frontmatter
   ids are language-qualified (overview-de/-ja/-ko/-zh,
   decision-register-ja/-ko). **Remainder, with its
   reason:** the 2 duplicate-stem warnings remain — the
   i18n pages are translations at parallel paths, and the
   stems clear only by renaming files, which the
   resolver does not require.
6. **Checkpoint tests** skip with a stated reason when
   `ssh-keygen` is absent (proven both ways); no
   assertion weakened.
7. **README corrected**: precise tagline (the lockfile
   detects when cited text changes; it does not verify
   that a claim is true), citation coverage stated with
   the real numbers, the operator-run audit command in
   place of a "nightly audit", the 46.7% figure
   attributed to Inspeximus, and a Status and known
   limitations section.

Investigations (no restructuring): the 13 graph-orphan
pages and the 7 pages outside the index catalogue are
named in the maintainer's record — the pattern is Round
3's build-record pages standing graph-isolated, plus one
genuine index omission (citation-chain); a sample of
three marathon record pages (ta5, tb7, ta7) found zero
inline citation markers — their provenance is page-level,
and their claims trace to code and tests rather than
cited passages; `tools/lens/lenslib.py` (2,722 lines)
and `tools/lens/build_lens.py` (2,064 lines) have a
proposed split by cluster / by data product, not
executed.

## Builds

- **Memory-transparency views** (Sakana pattern, idea
  only, our code): `scripts/wiki_memory_transparency.py`
  builds `evaluation/memory-transparency.json` from the
  claim index and the Q&A records; the Lens gains a
  Memory view and a "grounded in N claims" chip on Q&A
  entries.
- **TB4 Lens wiring, points 1, 2, 3, 5**: relation-map
  edge-type filter + Hoisting candidates panel;
  per-page History/Diff tabs; the related-pages rail
  with score and reason; feedback controls per
  `evaluation/feedback-format.md` (with the static-site
  fallback stated on the control). Point 4 — importance
  as a ranker signal — remains unbuilt by design.
- **CJK search segmentation** (Kagome pattern, MIT):
  CJK runs are indexed whole and as character bigrams in
  `scripts/wiki_search.py`, `tools/lens/lenslib.py` and
  the Lens client mirror, parity-tested; a 検索 query
  now retrieves the Japanese demo guide.
- **Publish CLI** (zenn-cli shape, MIT):
  `scripts/wiki_publish.py` — check (the real validator,
  imported), preview, and a push command that prints its
  plan and executes no git.
- **Source catalogue** (Korpora pattern, CC-BY-4.0):
  `scripts/wiki_source_registry.py` builds
  `evaluation/source-catalog.json` over `raw/sources/`
  (licences recorded only where a collection's own
  records state one) and renders [[source-registry]].
- **Memo capture** (Memos pattern, MIT): a `memo`
  capture kind (tags the only structure),
  `scripts/wiki_memo.py`, a traverse `memos` command,
  and a tenth MCP read tool, `wiki_memos`.
- **Schema-guided extraction** (DeepKE pattern, MIT):
  `scripts/wiki_schema_extract.py` — deterministic, no
  model calls; proposals only, never auto-applied.
- **Memory distil** (MemU pattern, Apache-2.0):
  `scripts/wiki_memory_distil.py` — mine, bridge and
  distil memory-shaped logs into an attributed digest;
  exercised on fixtures.
- **Packing check, MILU rule, reading notes**: a
  Lost-in-the-Middle position check for assembled packs;
  the MILU source-terms rule enforced in the golden-set
  builder (the set itself byte-untouched); a
  Chain-of-Note reading-notes step behind a flag,
  default off.

## Verification (this tree, after integration)

scripts **1456 OK** (skipped=2); ask **274 OK**; gateway
**91 OK**; mcp-read **52 OK**; editor **56 OK**; Lens
**31 OK**; validator **PASS** (17 warnings — the classes
are named in §1 and the corpus's standing classes);
citation lock **12 OK / 0 UNLOCKED**; `sh install.sh`
exit 0; golden set byte-identical. The model router
remains an unwired seam.
