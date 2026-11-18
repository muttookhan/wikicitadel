#!/usr/bin/env python3
"""W2: graph time-travel + freshness colouring — the temporal
section of tools/lens/lenslib.py (per-node grounded dates on the
Lens graph artefact; the client scrubs by creation date and
colours by freshness).

Pinned here: the date precedence is the one stated in lenslib's
temporal header (creation: frontmatter created > planted > git
first commit; update: frontmatter tended > updated > git last
commit); a page with no date from any source gets None, never an
invented date; freshness bands measure age at the build date
with their stated boundaries; the time-travel predicate hides an
ungrounded node from every past view; and the artefact block
assembles deterministically (same inputs, byte-identical JSON).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def hist(*dates_newest_first):
    """A page-history entry: history list is newest-first."""
    return {"history": [{"commit": "x" * 40, "date": d,
                         "author": "A", "subject": "s"}
                        for d in dates_newest_first],
            "commits": len(dates_newest_first)}


class PrecedenceTests(unittest.TestCase):
    def test_created_frontmatter_wins_over_planted_and_git(self):
        out = L.page_temporal_dates(
            {"created": "2026-10-13", "planted": "2026-10-14"},
            hist("2026-10-20T00:00:00-04:00", "2026-10-15T00:00:00-04:00"))
        self.assertEqual(out["created"], "2026-10-13")
        self.assertEqual(out["created_from"], "frontmatter created")

    def test_created_planted_beats_git(self):
        out = L.page_temporal_dates(
            {"planted": "2026-10-14"},
            hist("2026-10-20T00:00:00-04:00", "2026-10-15T00:00:00-04:00"))
        self.assertEqual(out["created"], "2026-10-14")
        self.assertEqual(out["created_from"], "frontmatter planted")

    def test_created_git_first_commit_is_the_earliest(self):
        out = L.page_temporal_dates(
            {}, hist("2026-10-20T05:07:45-04:00",
                     "2026-10-13T10:52:53+00:00"))
        self.assertEqual(out["created"], "2026-10-13")
        self.assertEqual(out["created_from"], "git first commit")

    def test_updated_tended_wins_over_updated_and_git(self):
        out = L.page_temporal_dates(
            {"tended": "2026-10-18", "updated": "2026-10-21"},
            hist("2026-10-20T00:00:00-04:00"))
        self.assertEqual(out["updated"], "2026-10-18")
        self.assertEqual(out["updated_from"], "frontmatter tended")

    def test_updated_frontmatter_beats_git(self):
        out = L.page_temporal_dates(
            {"updated": "2026-10-19"}, hist("2026-10-20T00:00:00-04:00"))
        self.assertEqual(out["updated"], "2026-10-19")
        self.assertEqual(out["updated_from"], "frontmatter updated")

    def test_updated_git_last_commit_is_the_latest(self):
        out = L.page_temporal_dates(
            {}, hist("2026-10-20T05:07:45-04:00",
                     "2026-10-13T10:52:53+00:00"))
        self.assertEqual(out["updated"], "2026-10-20")
        self.assertEqual(out["updated_from"], "git last commit")

    def test_no_source_no_date(self):
        out = L.page_temporal_dates({}, None)
        self.assertEqual(out, {"created": None, "created_from": None,
                               "updated": None, "updated_from": None})
        out = L.page_temporal_dates({"created": "not a date"},
                                    {"history": []})
        self.assertIsNone(out["created"])
        self.assertIsNone(out["created_from"])

    def test_yaml_value_shapes_normalise(self):
        out = L.page_temporal_dates(
            {"created": datetime.date(2026, 10, 12),
             "updated": datetime.datetime(2026, 10, 21, 9, 30)}, None)
        self.assertEqual(out["created"], "2026-10-12")
        self.assertEqual(out["updated"], "2026-10-21")

    def test_page_text_read_by_line_rule(self):
        # The build passes the page text: scalars come from
        # _fresh_fields, so a page whose YAML block fails to
        # parse wholesale (an unquoted colon in its title, say)
        # still yields the dates written on its face.
        text = ("---\n"
                "title: Report completion — Stage 2: the catalogue\n"
                "type: synthesis\n"
                "created: 2026-10-22\n"
                "updated: 2026-10-22\n"
                "---\n\n# Body\n")
        out = L.page_temporal_dates(text, None)
        self.assertEqual(out["created"], "2026-10-22")
        self.assertEqual(out["created_from"], "frontmatter created")
        self.assertEqual(out["updated"], "2026-10-22")
        self.assertEqual(out["updated_from"], "frontmatter updated")


class FreshnessBandTests(unittest.TestCase):
    BUILT = "2026-10-22"

    def test_boundaries(self):
        cases = [("2026-10-22", "fresh"), ("2026-10-15", "fresh"),
                 ("2026-10-14", "recent"), ("2026-09-22", "recent"),
                 ("2026-09-21", "ageing"), ("2026-07-24", "ageing"),
                 ("2026-07-23", "stale"), ("2020-01-01", "stale")]
        for updated, want in cases:
            self.assertEqual(L.freshness_band(updated, self.BUILT),
                             want, updated)

    def test_future_update_clamps_to_fresh(self):
        self.assertEqual(L.freshness_band("2026-12-01", self.BUILT),
                         "fresh")

    def test_unknown(self):
        self.assertEqual(L.freshness_band(None, self.BUILT), "unknown")
        self.assertEqual(L.freshness_band("junk", self.BUILT),
                         "unknown")
        self.assertEqual(L.freshness_band("2026-10-20", None),
                         "unknown")


class ExistsAtTests(unittest.TestCase):
    def test_no_scrub_shows_everything(self):
        self.assertTrue(L.node_exists_at("2026-10-20", ""))
        self.assertTrue(L.node_exists_at(None, None))

    def test_scrub_compares_creation(self):
        self.assertTrue(L.node_exists_at("2026-10-20", "2026-10-20"))
        self.assertTrue(L.node_exists_at("2026-10-19", "2026-10-20"))
        self.assertFalse(L.node_exists_at("2026-10-21", "2026-10-20"))

    def test_ungrounded_hidden_from_past_views(self):
        self.assertFalse(L.node_exists_at(None, "2026-10-20"))
        self.assertFalse(L.node_exists_at("junk", "2026-10-20"))


class TemporalBlockTests(unittest.TestCase):
    NODES = [
        {"created": "2026-10-12", "created_from": "frontmatter created",
         "updated": "2026-10-21", "updated_from": "frontmatter tended"},
        {"created": "2026-10-20", "created_from": "git first commit",
         "updated": "2026-07-01", "updated_from": "git last commit"},
        {"created": None, "created_from": None,
         "updated": None, "updated_from": None},
    ]

    def test_counts_and_bands(self):
        block = L.graph_temporal(self.NODES, "2026-10-22")
        self.assertEqual(block["built_on"], "2026-10-22")
        self.assertEqual(block["counts"],
                         {"nodes": 3, "with_created": 2,
                          "without_created": 1, "with_updated": 2,
                          "without_updated": 1})
        self.assertEqual(block["earliest_created"], "2026-10-12")
        by_key = {b["key"]: b["count"] for b in block["bands"]}
        self.assertEqual(by_key, {"fresh": 1, "recent": 0,
                                  "ageing": 0, "stale": 1,
                                  "unknown": 1})
        self.assertIn("no grounded creation date", block["rules"])

    def test_deterministic_assembly(self):
        a = json.dumps(L.graph_temporal(self.NODES, "2026-10-22"),
                       sort_keys=True)
        b = json.dumps(L.graph_temporal(list(self.NODES),
                                        "2026-10-22"),
                       sort_keys=True)
        self.assertEqual(a, b)


class CorpusCensusTests(unittest.TestCase):
    """The real corpus tonight: every graph (content) page carries
    frontmatter created/updated — the schema requires them — so
    every node is grounded. Structural pages (index/log) are not
    graph nodes and are excluded the way the build excludes
    them."""

    def test_real_corpus_nodes_all_grounded(self):
        wiki = ROOT / "wiki"
        history = L.load_page_history(ROOT)
        total = grounded_created = grounded_updated = 0
        for p in sorted(wiki.rglob("*.md")):
            if "access" in p.relative_to(wiki).parts[:-1]:
                continue
            fm, _body, text = L.parse_markdown_file(p)
            pid = fm.get("id") or p.stem
            if pid in {"index", "log"}:
                continue
            total += 1
            out = L.page_temporal_dates(
                text, history.get(str(p.relative_to(ROOT))))
            if out["created"]:
                grounded_created += 1
            if out["updated"]:
                grounded_updated += 1
        self.assertGreater(total, 30)
        self.assertEqual(grounded_created, total)
        self.assertEqual(grounded_updated, total)


if __name__ == "__main__":
    unittest.main()
