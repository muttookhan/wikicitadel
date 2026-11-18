#!/usr/bin/env python3
"""the build: live queries over markdown (```wiki-query blocks).

The evaluator lives in tools/lens/lenslib.py: parse_wiki_query
(the tiny grammar), run_wiki_query (evaluation over a page index),
render_wiki_query (list/table markdown), expand_wiki_queries
(block substitution at page render — malformed blocks become a
visible warning callout, never an exception, never silence).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def pg(pid, link, title, type="page", section="wiki", status="",
       tags=(), created="", updated="", as_of="", links=()):
    return {"id": pid, "link": link, "title": title, "type": type,
            "section": section, "status": status, "tags": list(tags),
            "created": created, "updated": updated, "as_of": as_of,
            "links": set(links)}


PAGES = [
    pg("galen-filings", "wiki/filings/galen-filings",
       "Galen — filings ledger", type="query", section="filings",
       tags=["agents", "filings", "galen"],
       created="2030-10-16", updated="2030-10-16"),
    pg("codex-filings", "wiki/filings/codex-filings",
       "Codex — filings ledger", type="query", section="filings",
       tags=["agents", "filings", "codex"],
       created="2030-10-14", updated="2030-10-14"),
    pg("filing-area", "wiki/filings/filing-area",
       "The Agents' Filing Area", type="query", section="filings",
       tags=["agents", "filings", "governance"],
       created="2030-10-14", updated="2030-10-20",
       links=["wiki/filings/galen-filings", "galen-filings"]),
    pg("hugo-lint", "wiki/filings/hugo-lint-2030-10-18",
       "Hugo lint", type="query", section="filings",
       tags=["lint", "hugo", "filings"],
       created="2030-10-18", updated="2030-10-18"),
    pg("current-state", "wiki/syntheses/current-state",
       "Current state", type="synthesis", section="syntheses",
       status="active", tags=["standing-questions"],
       created="2030-10-19", updated="2030-10-20",
       links=["wiki/ideas", "ideas"]),
    pg("claim-a", "wiki/concepts/claim-a", "Claim A",
       type="concept", section="concepts", status="draft",
       created="2030-10-01", updated="2030-10-05",
       as_of="2030-10-05", links=["current-state"]),
    pg("claim-b", "wiki/concepts/claim-b", "Claim B",
       type="concept", section="concepts",
       created="2030-10-02", updated=""),
]


def run(text, pages=PAGES, self_id=None):
    spec = L.parse_wiki_query(text)
    return L.run_wiki_query(spec, pages, self_id=self_id)


class TestGrammar(unittest.TestCase):
    def test_defaults(self):
        spec = L.parse_wiki_query("")
        self.assertEqual(spec["format"], "list")
        self.assertEqual(spec["fields"], ["title"])
        self.assertEqual(spec["sort"], ("title", "asc"))
        self.assertIsNone(spec["limit"])

    def test_comments_and_blanks_ignored(self):
        spec = L.parse_wiki_query("# a note\n\ntype: query\n")
        self.assertEqual(spec["filters"]["type"], "query")

    def test_full_spec(self):
        spec = L.parse_wiki_query(
            "format: table\nfields: title, updated\n"
            "sort: updated desc\nlimit: 3\n")
        self.assertEqual(spec["format"], "table")
        self.assertEqual(spec["fields"], ["title", "updated"])
        self.assertEqual(spec["sort"], ("updated", "desc"))
        self.assertEqual(spec["limit"], 3)

    def test_unknown_directive(self):
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("frobnicate: yes")

    def test_line_without_colon(self):
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("type query")

    def test_duplicate_directive(self):
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("type: query\ntype: concept")

    def test_empty_value(self):
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("type:")

    def test_bad_format(self):
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("format: grid")

    def test_bad_field_and_sort_field(self):
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("fields: title, weight")
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("sort: weight")

    def test_bad_sort_direction(self):
        with self.assertRaises(L.WikiQueryError):
            L.parse_wiki_query("sort: title sideways")

    def test_bad_limit(self):
        for bad in ("limit: 0", "limit: -2", "limit: many"):
            with self.assertRaises(L.WikiQueryError, msg=bad):
                L.parse_wiki_query(bad)

    def test_bad_dates(self):
        for bad in ("updated_after: 20-10-2030",
                    "updated_after: 2030-13-01",
                    "created_before: yesterday"):
            with self.assertRaises(L.WikiQueryError, msg=bad):
                L.parse_wiki_query(bad)


class TestEvaluation(unittest.TestCase):
    def ids(self, rows):
        return [r["id"] for r in rows]

    def test_type_and_section(self):
        rows = run("type: query\nsection: filings")
        # default sort is by title: Codex…, Galen…, Hugo…, The…
        self.assertEqual(self.ids(rows),
                         ["codex-filings", "galen-filings",
                          "hugo-lint", "filing-area"])

    def test_tags_all_required(self):
        rows = run("tags: agents, filings")
        self.assertEqual(self.ids(rows),
                         ["codex-filings", "galen-filings", "filing-area"])

    def test_self_excluded(self):
        rows = run("tags: agents, filings", self_id="filing-area")
        self.assertEqual(self.ids(rows), ["codex-filings", "galen-filings"])

    def test_status(self):
        self.assertEqual(self.ids(run("status: draft")), ["claim-a"])
        self.assertEqual(self.ids(run("status: active")), ["current-state"])

    def test_links_to_by_stem_and_path(self):
        self.assertEqual(self.ids(run("links_to: galen-filings")),
                         ["filing-area"])
        self.assertEqual(
            self.ids(run("links_to: wiki/syntheses/current-state")),
            ["claim-a"])

    def test_date_bounds_inclusive(self):
        rows = run("created_after: 2030-10-14\ncreated_before: 2030-10-16")
        self.assertEqual(self.ids(rows),
                         ["codex-filings", "galen-filings", "filing-area"])

    def test_date_bound_excludes_missing_field(self):
        rows = run("updated_after: 2030-01-01")
        self.assertNotIn("claim-b", self.ids(rows))

    def test_as_of_bound(self):
        self.assertEqual(self.ids(run("as_of_before: 2030-10-31")),
                         ["claim-a"])

    def test_sort_desc_missing_last_and_limit(self):
        rows = run("sort: updated desc")
        # two pages share the newest date; the title tiebreak
        # follows the sort direction, so "The Agents'…" leads.
        self.assertEqual(rows[0]["id"], "filing-area")
        self.assertEqual(rows[1]["id"], "current-state")
        self.assertEqual(rows[-1]["id"], "claim-b")  # no updated date
        rows = run("sort: updated desc\nlimit: 2")
        self.assertEqual(self.ids(rows), ["filing-area", "current-state"])

    def test_no_matches(self):
        self.assertEqual(run("type: entity\nsection: filings"), [])


class TestRender(unittest.TestCase):
    def test_list_render_links_and_extras(self):
        spec = L.parse_wiki_query("fields: title, updated\n"
                                  "section: filings\ntype: query\n"
                                  "tags: agents, filings")
        md = L.render_wiki_query(spec, L.run_wiki_query(
            spec, PAGES, self_id="filing-area"))
        self.assertIn("- [[wiki/filings/codex-filings|Codex — filings ledger]]"
                      " — updated 2030-10-14", md)
        self.assertIn("- [[wiki/filings/galen-filings|Galen — filings ledger]]"
                      " — updated 2030-10-16", md)
        self.assertEqual(md.count("\n- [["), 1)  # exactly two rows

    def test_table_render(self):
        spec = L.parse_wiki_query("format: table\n"
                                  "fields: title, updated\n"
                                  "sort: updated desc\nlimit: 1")
        md = L.render_wiki_query(spec, L.run_wiki_query(spec, PAGES))
        lines = md.splitlines()
        self.assertEqual(lines[0], "| Title | Updated |")
        self.assertEqual(lines[1], "| --- | --- |")
        self.assertIn("[[wiki/filings/filing-area|The Agents' Filing Area]]"
                      " | 2030-10-20", lines[2])

    def test_empty_render_is_a_note_not_silence(self):
        spec = L.parse_wiki_query("type: entity")
        md = L.render_wiki_query(spec, [])
        self.assertIn("no pages match", md)


class TestTableRendererWikilinkCells(unittest.TestCase):
    """A generated table's title cell is a labelled wikilink, whose
    '|' must not split the cell (lenslib split_row is wikilink-
    aware; rows without wikilinks render exactly as before)."""

    def test_labelled_wikilink_cell_stays_one_cell(self):
        md = ("| Title | Updated |\n| --- | --- |\n"
              "| [[wiki/ideas|Ideas — awaiting the owner's call]]"
              " | 2030-10-20 |")
        html_out, wl = L.render_markdown(md)
        self.assertEqual(len(wl), 1)
        self.assertEqual(wl[0][0], "wiki/ideas")
        self.assertEqual(html_out.count("<td>"), 2)

    def test_plain_table_unchanged(self):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        html_out, wl = L.render_markdown(md)
        self.assertEqual(wl, [])
        self.assertEqual(html_out.count("<td>"), 2)
        self.assertIn("<td>1</td>", html_out)


class TestExpand(unittest.TestCase):
    def test_block_replaced_and_prose_untouched(self):
        body = ("Before.\n\n```wiki-query\ntype: concept\n```\n\n"
                "After.\n\n```python\nprint('wiki-query')\n```\n")
        out = L.expand_wiki_queries(body, PAGES)
        self.assertIn("Before.", out)
        self.assertIn("- [[wiki/concepts/claim-a|Claim A]]", out)
        self.assertIn("```python", out)  # other fences untouched
        self.assertNotIn("```wiki-query", out)

    def test_malformed_block_renders_visible_error(self):
        body = "Text.\n\n```wiki-query\nbogus: 1\n```\n"
        out = L.expand_wiki_queries(body, PAGES)
        self.assertIn("[!warning] Live query error", out)
        self.assertIn("unknown directive", out)
        self.assertIn("Text.", out)  # the page still renders

    def test_unclosed_fence_renders_visible_error(self):
        body = "Text.\n\n```wiki-query\ntype: query\n"
        out = L.expand_wiki_queries(body, PAGES)
        self.assertIn("[!warning] Live query error", out)
        self.assertIn("never closed", out)

    def test_expansion_never_raises(self):
        for bad in ("```wiki-query\nlimit: x\n```",
                    "```wiki-query\n:::\n```",
                    "```wiki-query\n```"):
            L.expand_wiki_queries(bad, PAGES)  # must not raise


if __name__ == "__main__":
    unittest.main()
