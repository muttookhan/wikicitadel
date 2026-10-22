#!/usr/bin/env python3
"""W2: Lens timeline view over dated entries — the timeline
extraction in tools/lens/lenslib.py (filings ledgers + decision
records joining the wiki log on the Lens timeline).

Pinned here: dates come only from the entry's own text (bold or
plain leading date in a ledger bullet; the DECIDED date in a
decision item's head); a candidate with no grounded date is
excluded WITH its reason, never placed; the kind set is the
closed TIMELINE_KINDS; and the merged sort is deterministic —
same-date ties keep extraction order (log, ledgers, decisions,
commits) and two assemblies of the same inputs are byte-identical.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


LEDGER_BODY = """# Test — filings

Intro prose with a date 2025-01-01 that is not an entry.

## Ledger

- **2026-10-18** — Seat opened by the owner. Branch
  `test/filings` created on Azure.
- **2026-10-18 02:53 EDT** — The owner answered: keep the two
  homes separate. More detail follows here.
- **2026-10-20 ~13:36 EDT** — Outbound note filed at the
  owner's direction.
- 2026-10-20: raw/filings/test/audit.md: forensic audit filed.
- A bullet with no date in it at all.

## Later section

- **2026-10-21** — Not a ledger bullet; outside the section.
"""

DECISION_BODY = """# Decisions

1. **Alpha — DECIDED by Usman 2026-10-13: keep it
   RESERVED.** The body of the first decision.
2. **Beta — ruled without the dated form.** Body two.
3. **Gamma — DECIDED by Usman 2026-10-14: YES.** Body three.
"""


class LedgerEntriesTests(unittest.TestCase):
    def test_grounded_forms_all_parse(self):
        entries, excluded = L.ledger_timeline_entries(
            LEDGER_BODY, "wiki/filings/test-filings.md",
            "test-filings", "Test")
        self.assertEqual([e["date"] for e in entries],
                         ["2026-10-18", "2026-10-18",
                          "2026-10-20", "2026-10-20"])
        self.assertTrue(all(e["kind"] == "filing" for e in entries))
        self.assertTrue(all(e["tkind"] == "filing" for e in entries))
        self.assertTrue(all(e["stream"] == "Filings" for e in entries))
        self.assertTrue(all(e["actor"] == "Test" for e in entries))
        self.assertTrue(all(e["link"] == "test-filings" for e in entries))

    def test_continuation_lines_join_and_title_is_first_sentence(self):
        entries, _ = L.ledger_timeline_entries(
            LEDGER_BODY, "s", "test-filings", "Test")
        self.assertEqual(entries[0]["title"], "Seat opened by the owner.")
        self.assertIn("test/filings", entries[0]["summary"])
        self.assertEqual(entries[1]["title"],
                         "The owner answered: keep the two homes separate.")

    def test_undated_bullet_excluded_with_reason(self):
        _, excluded = L.ledger_timeline_entries(
            LEDGER_BODY, "wiki/filings/test-filings.md",
            "test-filings", "Test")
        self.assertEqual(len(excluded), 1)
        self.assertIn("no leading date", excluded[0]["reason"])
        self.assertEqual(excluded[0]["source"],
                         "wiki/filings/test-filings.md")

    def test_bullets_outside_ledger_section_ignored(self):
        entries, _ = L.ledger_timeline_entries(
            LEDGER_BODY, "s", "test-filings", "Test")
        self.assertNotIn("2026-10-21", [e["date"] for e in entries])
        self.assertNotIn("2025-01-01", [e["date"] for e in entries])

    def test_no_ledger_section_is_empty_not_an_error(self):
        self.assertEqual(
            L.ledger_timeline_entries("# Stub\n\nNo filings yet.\n",
                                      "s", "x-filings", "X"),
            ([], []))


class DecisionEntriesTests(unittest.TestCase):
    def test_dated_items_parse_with_cleaned_titles(self):
        entries, _ = L.decision_timeline_entries(
            DECISION_BODY, "wiki/syntheses/chapter7-decisions.md",
            "chapter7-decisions")
        self.assertEqual([e["date"] for e in entries],
                         ["2026-10-13", "2026-10-14"])
        self.assertEqual(entries[0]["title"], "Alpha — keep it RESERVED.")
        self.assertEqual(entries[1]["title"], "Gamma — YES.")
        self.assertTrue(all(e["tkind"] == "decision" for e in entries))
        self.assertTrue(all(e["actor"] == "Usman" for e in entries))
        self.assertEqual(entries[0]["summary"],
                         "The body of the first decision.")

    def test_undated_item_excluded_with_reason(self):
        _, excluded = L.decision_timeline_entries(
            DECISION_BODY, "wiki/syntheses/chapter7-decisions.md",
            "chapter7-decisions")
        self.assertEqual(len(excluded), 1)
        self.assertIn("no DECIDED date", excluded[0]["reason"])


class CollectorTests(unittest.TestCase):
    PAGES = [
        {"path": "wiki/filings/zzz-filings.md", "id": "zzz-filings",
         "body": "# Zzz — filings\n\nReserved seat.\n"},
        {"path": "wiki/filings/test-filings.md", "id": "test-filings",
         "body": LEDGER_BODY},
        {"path": "wiki/sources/other.md", "id": "other",
         "body": "## Ledger\n\n- **2026-01-01** — Not a filings page.\n"},
        {"path": "wiki/syntheses/chapter7-decisions.md",
         "id": "chapter7-decisions", "body": DECISION_BODY},
    ]

    def test_collector_selects_ledgers_and_decision_record(self):
        entries, coverage, excluded = L.timeline_extra_entries(self.PAGES)
        self.assertEqual(len(entries), 4 + 2)
        self.assertEqual(len(excluded), 1 + 1)
        by_source = {r["source"]: r for r in coverage}
        self.assertEqual(
            by_source["wiki/filings/test-filings.md"]["entries"], 4)
        stub = by_source["wiki/filings/zzz-filings.md"]
        self.assertEqual((stub["entries"], stub["excluded"]), (0, 0))
        self.assertIn("note", stub)
        self.assertEqual(
            by_source["wiki/syntheses/chapter7-decisions.md"]["entries"], 2)
        self.assertNotIn("wiki/sources/other.md", by_source)

    def test_unknown_agent_name_falls_back_to_title_case(self):
        pages = [{"path": "wiki/filings/new-agent-filings.md",
                  "id": "new-agent-filings", "body": LEDGER_BODY}]
        entries, _, _ = L.timeline_extra_entries(pages)
        self.assertEqual(entries[0]["actor"], "New Agent")


class KindAndSortTests(unittest.TestCase):
    def test_kind_mapping_stays_inside_the_closed_set(self):
        for raw in ("ingest", "decision", "query", "lint", "setup",
                    "build", "commit", "filing", "anything-else"):
            self.assertIn(L.timeline_kind(raw), L.TIMELINE_KINDS)
        self.assertEqual(L.timeline_kind("ingest"), "ingest")
        self.assertEqual(L.timeline_kind("decision"), "decision")
        self.assertEqual(L.timeline_kind("filing"), "filing")
        self.assertEqual(L.timeline_kind("commit"), "other")
        self.assertEqual(L.timeline_kind("lint"), "log")

    def _assemble(self):
        log = [{"date": "2026-10-20", "kind": "ingest",
                "title": "Log same-date", "source": "wiki/log.md"},
               {"date": "2026-10-21", "kind": "setup",
                "title": "Log newer", "source": "wiki/log.md"}]
        pages = [{"path": "wiki/filings/test-filings.md",
                  "id": "test-filings", "body": LEDGER_BODY},
                 {"path": "wiki/syntheses/chapter7-decisions.md",
                  "id": "chapter7-decisions", "body": DECISION_BODY}]
        extra, _, _ = L.timeline_extra_entries(pages)
        same_day = [dict(e) for e in extra if e["date"] == "2026-10-20"]
        commits = [{"date": "2026-10-20", "kind": "commit",
                    "title": "Commit same-date", "source": "git log"}]
        return L.sort_timeline(log + same_day + commits)

    def test_same_date_ties_keep_extraction_order(self):
        events = self._assemble()
        self.assertEqual(events[0]["title"], "Log newer")
        same = [e["title"] for e in events if e["date"] == "2026-10-20"]
        self.assertEqual(same[0], "Log same-date")
        self.assertEqual(same[-1], "Commit same-date")
        self.assertTrue(all(t.startswith("Outbound")
                            or t.startswith("raw/filings")
                            or t in ("Log same-date", "Commit same-date")
                            for t in same))

    def test_two_assemblies_are_byte_identical(self):
        a = json.dumps(self._assemble(), ensure_ascii=False,
                       sort_keys=True).encode()
        b = json.dumps(self._assemble(), ensure_ascii=False,
                       sort_keys=True).encode()
        self.assertEqual(a, b)
        again = L.sort_timeline(copy.deepcopy(self._assemble()))
        self.assertEqual(a, json.dumps(again, ensure_ascii=False,
                                       sort_keys=True).encode())


if __name__ == "__main__":
    unittest.main()
