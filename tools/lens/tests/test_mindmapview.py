"""Wave-2 item W2 (Markmap outline-to-mindmap Lens view) unit
tests — run from anywhere:

    python3 -m unittest tools.lens.tests.test_mindmapview
    python3 tools/lens/tests/test_mindmapview.py

Covers: the outline nesting (stack discipline, level jumps with
no phantom nodes), the root rule (first H1 consumed as root,
page title otherwise), wikilink attribution to the deepest open
heading with repeat collapsing, resolution honesty (a target
with no page is a marked boundary leaf, never a link), parsing
parity with lenslib (fences and inline code hide headings and
links exactly as page_headings / extract_wikilinks hide them;
the tree's heading sequence IS page_headings' sequence), the
explicit empty state for a heading-less page, and determinism
(same corpus in -> identical artefact bytes out).
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
sys.path.insert(0, str(LENS_DIR))

import lenslib as L  # noqa: E402
import mindmapview as MM  # noqa: E402

ROUTES = {"alpha": "alpha", "beta": "beta", "page": "deep-page"}
RESOLVE = MM.route_resolver(ROUTES)


def headings_of(node, out=None):
    out = [] if out is None else out
    for c in node["children"]:
        if c["kind"] == "heading":
            out.append(c)
        headings_of(c, out)
    return out


def links_of(node, out=None):
    out = [] if out is None else out
    for c in node["children"]:
        if c["kind"] == "link":
            out.append(c)
        links_of(c, out)
    return out


class RootRuleTests(unittest.TestCase):
    def test_first_h1_becomes_root(self):
        rec = MM.page_mindmap("Fallback Title",
                              "# Real Title\n\n## A\n\n## B\n", RESOLVE)
        self.assertEqual(rec["root"]["text"], "Real Title")
        self.assertEqual(rec["root"]["root_kind"], "h1")
        self.assertEqual([h["text"] for h in headings_of(rec["root"])],
                         ["A", "B"])
        self.assertFalse(rec["empty"])

    def test_title_root_without_h1(self):
        rec = MM.page_mindmap("Page Title", "## A\n\n### A1\n", RESOLVE)
        self.assertEqual(rec["root"]["text"], "Page Title")
        self.assertEqual(rec["root"]["root_kind"], "title")
        a = headings_of(rec["root"])[0]
        self.assertEqual(a["text"], "A")
        self.assertEqual([h["text"] for h in headings_of(a)], ["A1"])

    def test_later_h1_is_top_level_child(self):
        body = "# Root\n\n## A\n\n# Second Part\n\n## B\n"
        rec = MM.page_mindmap("T", body, RESOLVE)
        tops = [c["text"] for c in rec["root"]["children"]
                if c["kind"] == "heading"]
        self.assertEqual(tops, ["A", "Second Part"])
        second = [c for c in rec["root"]["children"]
                  if c["text"] == "Second Part"][0]
        self.assertEqual([h["text"] for h in headings_of(second)], ["B"])


class NestingTests(unittest.TestCase):
    def test_level_jump_nests_without_phantom(self):
        body = "## A\n\n#### Deep\n\n## B\n"
        rec = MM.page_mindmap("T", body, RESOLVE)
        a, b = rec["root"]["children"]
        self.assertEqual(a["text"], "A")
        self.assertEqual([c["text"] for c in a["children"]], ["Deep"])
        self.assertEqual(a["children"][0]["level"], 4)
        self.assertEqual(b["text"], "B")
        self.assertEqual(b["children"], [])

    def test_heading_sequence_matches_page_headings(self):
        body = ("# T\n\n## One\n\n## One\n\n### Sub `code` **bold**\n"
                "\n## Two\n")
        rec = MM.page_mindmap("T", body, RESOLVE)
        canonical = L.page_headings(body)
        tree_texts = [rec["root"]["text"]] + \
            [h["text"] for h in headings_of(rec["root"])]
        self.assertEqual(tree_texts, [h["text"] for h in canonical])
        tree_anchors = [h["anchor"] for h in headings_of(rec["root"])]
        self.assertEqual(tree_anchors,
                         [h["anchor"] for h in canonical[1:]])
        # duplicate heading keeps page_headings' de-dup suffix
        self.assertEqual(tree_anchors[1], "one-2")


class LinkAttributionTests(unittest.TestCase):
    BODY = ("Intro links [[alpha]] here.\n\n"
            "## Section\n\nSee [[beta|the beta page]] and [[alpha]].\n\n"
            "### Deeper\n\nMore [[alpha]] and [[ghost-page]].\n")

    def test_attribution_and_collapse(self):
        rec = MM.page_mindmap("T", self.BODY, RESOLVE)
        root_links = [c for c in rec["root"]["children"]
                      if c["kind"] == "link"]
        self.assertEqual(len(root_links), 1)
        self.assertEqual(root_links[0]["target"], "alpha")
        section = headings_of(rec["root"])[0]
        sec_links = [c for c in section["children"] if c["kind"] == "link"]
        self.assertEqual([lf["target"] for lf in sec_links],
                         ["beta", "alpha"])
        self.assertEqual(sec_links[0]["text"], "the beta page")
        deeper = headings_of(section)[0]
        deep_links = [c for c in deeper["children"] if c["kind"] == "link"]
        self.assertEqual([lf["target"] for lf in deep_links],
                         ["alpha", "ghost-page"])

    def test_counts(self):
        rec = MM.page_mindmap("T", self.BODY, RESOLVE)
        # refs: alpha x3 total, beta x1, ghost x1 = 5 occurrences,
        # collapsed per heading -> root 1 + section 2 + deeper 2
        self.assertEqual(rec["counts"]["link_refs"], 5)
        self.assertEqual(rec["counts"]["links"], 5)
        self.assertEqual(rec["counts"]["resolved"], 4)
        self.assertEqual(rec["counts"]["missing"], 1)

    def test_repeat_under_one_heading_counts(self):
        body = "## S\n\n[[alpha]] and again [[alpha|Alpha!]].\n"
        rec = MM.page_mindmap("T", body, RESOLVE)
        leaves = links_of(rec["root"])
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]["count"], 2)
        self.assertEqual(leaves[0]["text"], "alpha")  # first label kept

    def test_resolution_honesty(self):
        rec = MM.page_mindmap("T", self.BODY, RESOLVE)
        ghost = [lf for lf in links_of(rec["root"])
                 if lf["target"] == "ghost-page"][0]
        self.assertIsNone(ghost["page"])
        self.assertTrue(ghost["missing"])
        alpha = links_of(rec["root"])[0]
        self.assertEqual(alpha["page"], "alpha")
        self.assertFalse(alpha["missing"])

    def test_anchor_carried_slugified(self):
        body = "## S\n\n[[alpha#Some Part]]\n"
        rec = MM.page_mindmap("T", body, RESOLVE)
        leaf = links_of(rec["root"])[0]
        self.assertEqual(leaf["anchor"], "some-part")

    def test_bare_name_fallback_resolution(self):
        body = "## S\n\n[[elsewhere/deep/page]]\n"
        rec = MM.page_mindmap("T", body, RESOLVE)
        leaf = links_of(rec["root"])[0]
        self.assertEqual(leaf["page"], "deep-page")
        self.assertFalse(leaf["missing"])


class ParityTests(unittest.TestCase):
    def test_fences_and_inline_code_hide(self):
        body = ("## Real\n\n```\n## Not A Heading\n[[alpha]]\n```\n\n"
                "Inline `[[beta]]` is an example, not a link.\n")
        rec = MM.page_mindmap("T", body, RESOLVE)
        self.assertEqual([h["text"] for h in headings_of(rec["root"])],
                         ["Real"])
        self.assertEqual(links_of(rec["root"]), [])
        self.assertEqual(rec["counts"]["link_refs"], 0)

    def test_parity_with_extract_wikilinks(self):
        body = ("Lede [[a-one]]\n\n## S\n\n[[b-two|B]] [[c-three#Part]]\n")
        rec = MM.page_mindmap("T", body, RESOLVE)
        mine = sorted(lf["target"] for lf in links_of(rec["root"]))
        theirs = sorted(t for t, _a, _l in L.extract_wikilinks(body))
        self.assertEqual(mine, theirs)

    def test_link_inside_heading_line(self):
        body = "## About [[alpha]]\n\nBody text.\n"
        rec = MM.page_mindmap("T", body, RESOLVE)
        section = headings_of(rec["root"])[0]
        self.assertEqual([lf["target"] for lf in links_of(section)],
                         ["alpha"])
        self.assertEqual(rec["counts"]["link_refs"],
                         len(L.extract_wikilinks(body)))


class EmptyStateTests(unittest.TestCase):
    def test_no_headings_is_explicit_empty(self):
        rec = MM.page_mindmap("Bare Page", "Just prose, no headings.\n",
                              RESOLVE)
        self.assertTrue(rec["empty"])
        self.assertEqual(rec["root"]["text"], "Bare Page")
        self.assertEqual(rec["root"]["root_kind"], "title")
        self.assertEqual(rec["counts"]["headings"], 0)

    def test_links_without_headings_hang_off_root(self):
        rec = MM.page_mindmap("T", "Prose with [[alpha]].\n", RESOLVE)
        self.assertTrue(rec["empty"])
        self.assertEqual([lf["target"] for lf in links_of(rec["root"])],
                         ["alpha"])


class DeterminismTests(unittest.TestCase):
    def test_artefact_bytes_stable(self):
        pages = [{"id": "p1", "title": "One",
                  "body": "# One\n\n## A\n\n[[alpha]]\n"},
                 {"id": "p2", "title": "Two", "body": "## B\n"}]
        a = json.dumps(MM.build_mindmaps(pages, RESOLVE),
                       ensure_ascii=False, sort_keys=True)
        b = json.dumps(MM.build_mindmaps(pages, RESOLVE),
                       ensure_ascii=False, sort_keys=True)
        self.assertEqual(a, b)
        art = MM.build_mindmaps(pages, RESOLVE)
        self.assertIn("markmap", art["credit"].lower())
        self.assertEqual(sorted(art["pages"]), ["p1", "p2"])


if __name__ == "__main__":
    unittest.main()
