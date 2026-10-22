#!/usr/bin/env python3
"""Tests for scripts/wiki_review_layer.py (Wave 5 — the
periodic review layer).

Fixture corpus exercising every queue reason, run with a
fixed --today (2026-10-22) so every expected number below
is arithmetic, not a clock read:

  entities/fresh-entity.md   entity, tended 2026-10-20,
                             indexed -> not queued
  entities/stale-entity.md   entity, tended 2026-01-02,
                             no review event, not indexed
                             -> cadence-stale (due 2026-04-02,
                             203d overdue) + orphaned-from-index
  sources/attested.md        verified_until 2026-10-01
                             -> attestation-expired (21d)
  syntheses/claim-page.md    claim as_of 2026-10-01, no
                             history -> reverify-overdue
                             (due 2026-10-08, 14d)
  concepts/ttl-page.md       evidence_as_of 2026-09-01,
                             TTL 30d -> evidence-due
                             (due 2026-10-01, 21d)
  queries/pending-page.md    ## Pending Review, 1 open
                             entry -> pending-review-open
  entities/verified-claim.md claim verified 2026-10-20
                             (history event), indexed
                             -> not queued
  entities/retired.md        status: tombstoned -> out of
                             the population

Run:  python3 -m unittest scripts.tests.test_wiki_review_layer
(or via discover from the repo root)
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "wiki_review_layer", SCRIPTS / "wiki_review_layer.py")
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)

TODAY = date(2026, 10, 22)

PAGES = {
    "wiki/index.md": """# Index

- [[fresh-entity]] — a fresh entity
- [[verified-claim]] — a verified claim
""",
    "wiki/log.md": """# Log

## [2026-10-01] setup | Old setup entry

Body.

## [2026-10-20] ingest | Older thing landed

Body.

## [2026-10-21] lint | A lint pass

Body.

## [2026-10-22] ingest | Something landed today

Body.

## [2026-10-22] ingest | Something landed today

Duplicate title, on purpose (recurring-title pattern).
""",
    "wiki/entities/fresh-entity.md": """---
title: Fresh Entity
type: entity
created: 2026-10-01
updated: 2026-10-20
tended: 2026-10-20
sources: []
tags: []
---

# Fresh Entity
""",
    "wiki/entities/stale-entity.md": """---
title: Stale Entity
type: entity
created: 2026-01-01
updated: 2026-01-02
tended: 2026-01-02
sources:
  - raw/sources/ghost.md
tags: []
---

# Stale Entity
""",
    "wiki/sources/attested.md": """---
title: Attested Source
type: source
created: 2026-09-01
updated: 2026-09-01
verified_until: 2026-10-01
verified_by: owner
sources: []
tags: []
---

# Attested Source
""",
    "wiki/syntheses/claim-page.md": """---
title: A Claim
type: synthesis
created: 2026-10-01
updated: 2026-10-01
claim: "The fixture holds."
as_of: 2026-10-01
sources: []
tags: []
---

# A Claim
""",
    "wiki/concepts/ttl-page.md": """---
title: TTL Page
type: concept
created: 2026-09-01
updated: 2026-09-01
evidence_as_of: 2026-09-01
evidence_ttl_days: 30
sources: []
tags: []
---

# TTL Page
""",
    "wiki/queries/pending-page.md": """---
title: Pending Page
type: query
created: 2026-10-15
updated: 2026-10-15
sources: []
tags: []
---

# Pending Page

## Pending Review

- The fixture claim still to corroborate.
""",
    "wiki/entities/verified-claim.md": """---
title: Verified Claim
type: entity
created: 2026-10-10
updated: 2026-10-10
claim: "The verified fixture holds."
as_of: 2026-10-10
sources: []
tags: []
---

# Verified Claim
""",
    "wiki/entities/retired.md": """---
title: Retired Page
type: entity
created: 2025-01-01
updated: 2025-01-01
status: tombstoned
sources: []
tags: []
---

# Retired Page
""",
    "evaluation/reverify-history.jsonl": (
        '{"claim": "wiki/entities/verified-claim.md", '
        '"date": "2026-10-20", "outcome": "pass", '
        '"note": "fixture", "source": "manual"}\n'),
}


def build_fixture(base: Path) -> Path:
    root = base / "corpus"
    for rel, text in PAGES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def digest_tree(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


class ReviewLayerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = build_fixture(Path(self._tmp.name))
        self.doc, self.records = rl.build_queue(
            self.root, TODAY, dict(rl.PROPOSED_CADENCE))
        self.by_page = {e["page"]: e for e in self.doc["queue"]}

    def reasons(self, page):
        return {r["reason"]: r
                for r in self.by_page[page]["reasons"]}

    def test_population(self):
        pop = self.doc["population"]
        # 8 scanned (index/log excluded): fresh, stale,
        # attested, claim, ttl, pending, verified, retired.
        self.assertEqual(pop["scanned"], 8)
        self.assertEqual(pop["retired_excluded"], 1)
        self.assertEqual(pop["attested_expired"], 1)

    def test_cadence_stale_and_orphan(self):
        entry = self.by_page["wiki/entities/stale-entity.md"]
        reasons = self.reasons("wiki/entities/stale-entity.md")
        self.assertIn("cadence-stale", reasons)
        self.assertIn("orphaned-from-index", reasons)
        r = reasons["cadence-stale"]
        self.assertEqual(r["due"], "2026-04-02")
        self.assertEqual(r["days_overdue"], 203)
        self.assertIn("no review event on record", r["detail"])
        self.assertIn("`tended`", r["detail"])
        self.assertEqual(entry["max_days_overdue"], 203)
        self.assertTrue(entry["never_reviewed"])

    def test_attestation_expired(self):
        reasons = self.reasons("wiki/sources/attested.md")
        self.assertIn("attestation-expired", reasons)
        self.assertEqual(reasons["attestation-expired"]["days_overdue"], 21)
        # An attested page is not "never reviewed": no
        # cadence reason may ride along.
        self.assertNotIn("cadence-stale", reasons)
        entry = self.by_page["wiki/sources/attested.md"]
        self.assertFalse(entry["never_reviewed"])

    def test_reverify_overdue_uses_house_schedule(self):
        reasons = self.reasons("wiki/syntheses/claim-page.md")
        self.assertIn("reverify-overdue", reasons)
        r = reasons["reverify-overdue"]
        # FSRS seed: S0=7d anchored at as_of 2026-10-01.
        self.assertEqual(r["due"], "2026-10-08")
        self.assertEqual(r["days_overdue"], 14)

    def test_evidence_due(self):
        reasons = self.reasons("wiki/concepts/ttl-page.md")
        self.assertIn("evidence-due", reasons)
        r = reasons["evidence-due"]
        self.assertEqual(r["due"], "2026-10-01")
        self.assertEqual(r["days_overdue"], 21)

    def test_pending_review_open(self):
        entry = self.by_page["wiki/queries/pending-page.md"]
        reasons = self.reasons("wiki/queries/pending-page.md")
        self.assertIn("pending-review-open", reasons)
        self.assertIsNone(entry["max_days_overdue"])

    def test_not_queued(self):
        self.assertNotIn("wiki/entities/fresh-entity.md", self.by_page)
        self.assertNotIn("wiki/entities/verified-claim.md", self.by_page)
        self.assertNotIn("wiki/entities/retired.md", self.by_page)

    def test_queue_ordering(self):
        # Most overdue first (203), then the 21d pair by
        # page path (concepts < sources), then 14d, then
        # the undated-only entry last.
        order = [e["page"] for e in self.doc["queue"]]
        self.assertEqual(order, [
            "wiki/entities/stale-entity.md",
            "wiki/concepts/ttl-page.md",
            "wiki/sources/attested.md",
            "wiki/syntheses/claim-page.md",
            "wiki/queries/pending-page.md",
        ])

    def test_determinism(self):
        doc2, records2 = rl.build_queue(
            self.root, TODAY, dict(rl.PROPOSED_CADENCE))
        self.assertEqual(
            json.dumps(self.doc, indent=2, sort_keys=True),
            json.dumps(doc2, indent=2, sort_keys=True))
        self.assertEqual(rl.render_queue_md(self.doc),
                         rl.render_queue_md(doc2))
        r1 = rl.build_report(self.root, TODAY,
                             dict(rl.PROPOSED_CADENCE),
                             self.doc, self.records)
        r2 = rl.build_report(self.root, TODAY,
                             dict(rl.PROPOSED_CADENCE),
                             doc2, records2)
        self.assertEqual(r1, r2)

    def test_report_contents(self):
        report = rl.build_report(self.root, TODAY,
                                 dict(rl.PROPOSED_CADENCE),
                                 self.doc, self.records)
        self.assertIn("PROPOSALS", report)
        self.assertIn("## Weekly review — Plus / Minus / Next", report)
        # Plus: today's ingest; the 2026-10-01 setup entry
        # is outside the 7-day window and must not appear
        # in the Plus column.
        plus = report.split("### Plus")[1].split("### Minus")[0]
        self.assertIn("Something landed today", plus)
        self.assertNotIn("Old setup entry", plus)
        # Minus: the lint entry + the attestation warning.
        minus = report.split("### Minus")[1].split("### Next")[0]
        self.assertIn("A lint pass", minus)
        self.assertIn("attestation", minus)
        # Next: the head of the queue.
        nxt = report.split("### Next")[1].split("## Patterns")[0]
        self.assertIn("wiki/entities/stale-entity.md", nxt)
        # Patterns: kinds + the recurring title.
        self.assertIn("ingest 3", report)
        self.assertIn("something landed today", report)
        # Daily review carries today's entries.
        self.assertIn("## Daily review — 2026-10-22", report)

    def test_cli_writes_only_its_artefacts(self):
        before = digest_tree(self.root)
        out_dir = self.root / "evaluation"
        rc = rl.main(["all", "--root", str(self.root),
                      "--today", "2026-10-22"])
        self.assertEqual(rc, 0)
        after = digest_tree(self.root)
        changed = {k for k in after
                   if before.get(k) != after[k]}
        self.assertEqual(changed, {
            "evaluation/review-queue.json",
            "evaluation/review-queue.md",
            "evaluation/review-cadence-report.md",
        })
        doc = json.loads((out_dir / "review-queue.json").read_text(
            encoding="utf-8"))
        self.assertEqual(doc["kind"], "review-queue")
        self.assertEqual(doc["as_of"], "2026-10-22")

    def test_interval_override(self):
        intervals = rl._parse_intervals(["entity=400"])
        doc, _records = rl.build_queue(self.root, TODAY, intervals)
        pages = {e["page"] for e in doc["queue"]}
        # 293d since tended is inside a 400d interval: the
        # cadence reason goes, the orphan reason stays.
        entry = {e["page"]: e for e in doc["queue"]}[
            "wiki/entities/stale-entity.md"]
        self.assertEqual({r["reason"] for r in entry["reasons"]},
                         {"orphaned-from-index"})
        self.assertIn("wiki/entities/stale-entity.md", pages)


if __name__ == "__main__":
    unittest.main()
