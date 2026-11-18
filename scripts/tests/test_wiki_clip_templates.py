"""Tests for scripts/wiki_clip_templates.py (clip templates
auto-selected by URL pattern) and scripts/wiki_site_rules.py
(per-site extraction rules, wallabag pattern) — Marathon
Round 3, lane TA4. Pins: template selection by URL pattern
with the STATED generic fallback; registry-file overrides; a
site rule matching by domain/subdomain; template+rule profile
merging; profile application (keep/strip/title, rotted-rule
visibility); the shipped templates/site-rules.json being
valid; and the wiki_clip integration (a docs-shaped page is
stripped of chrome in the converted text while the preserved
source stays verbatim, and the sidecar records the template).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_clip as clip  # noqa: E402
import wiki_clip_templates as wct  # noqa: E402
import wiki_site_rules as wsr  # noqa: E402

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
REAL_TREE = SCRIPTS.parent

DOCS_PAGE = (
    "<html><head><title>Ignored Title Tag</title></head><body>"
    "<nav>SIDENAV links everywhere</nav>"
    "<main><h1>Real Doc Title</h1>"
    "<p>The substantive documentation paragraph explains the "
    "configuration in enough detail to be worth clipping and "
    "keeping for later reference by readers of the wiki.</p>"
    "</main><footer>FOOTER chrome</footer></body></html>")


class TemplateSelectionTests(unittest.TestCase):
    def test_docs_url_selects_docs_template(self):
        t = wct.select_template("https://docs.example.net/guide/",
                                root=REAL_TREE)
        self.assertEqual(t["name"], "docs")
        self.assertFalse(t["fallback"])
        self.assertTrue(t["matched_pattern"])

    def test_wiki_url_selects_reference_template(self):
        t = wct.select_template(
            "https://en.wikipedia.org/wiki/Photosynthesis",
            root=REAL_TREE)
        self.assertEqual(t["name"], "reference-wiki")

    def test_unmatched_url_gets_the_stated_fallback(self):
        t = wct.select_template("https://random.example.xyz/page",
                                root=REAL_TREE)
        self.assertEqual(t["name"], "generic")
        self.assertTrue(t["fallback"])
        self.assertIsNone(t["matched_pattern"])
        self.assertIn("FALLBACK", t["note"])

    def test_registry_file_overrides_builtin(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "templates").mkdir(parents=True)
        (root / "templates" / "clip-templates.json").write_text(
            json.dumps([{"name": "docs", "patterns": ["special"],
                         "keep": ".special", "strip": [],
                         "title_selector": None, "note": "x"}]),
            encoding="utf-8")
        t = wct.select_template("https://special.example/", root=root)
        self.assertEqual(t["keep"], ".special")

    def test_malformed_registry_is_loud(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "templates").mkdir(parents=True)
        (root / "templates" / "clip-templates.json").write_text(
            "{not json", encoding="utf-8")
        with self.assertRaises(wct.TemplateError):
            wct.load_registry(root)


class SiteRuleTests(unittest.TestCase):
    def test_shipped_rules_file_is_valid(self):
        rules = wsr.load_rules(REAL_TREE)
        self.assertGreaterEqual(len(rules), 3)
        for rule in rules:
            self.assertTrue(rule["domain"])
            self.assertTrue(rule["note"])

    def test_rule_matches_domain_and_subdomain_only(self):
        rules = [{"domain": "example.com", "strip": [".ad"],
                  "keep": None, "title_selector": None,
                  "note": "x"}]
        self.assertIsNotNone(wsr.match_rule(
            "https://example.com/a", rules))
        self.assertIsNotNone(wsr.match_rule(
            "https://blog.example.com/a", rules))
        self.assertIsNone(wsr.match_rule(
            "https://notexample.com/a", rules))
        self.assertIsNone(wsr.match_rule(
            "https://example.com.evil.net/a", rules))

    def test_bad_selector_refused(self):
        with self.assertRaises(wsr.RuleError):
            wsr.validate_rules([{"domain": "x.com",
                                 "strip": ["div > p"]}])

    def test_merge_rule_wins_and_strips_union(self):
        profile = wsr.merge_profiles(
            {"keep": "main", "strip": ["nav"],
             "title_selector": "h1"},
            {"domain": "x.com", "keep": ".body",
             "strip": ["nav", ".ad"], "title_selector": None})
        self.assertEqual(profile["keep"], ".body")
        self.assertEqual(profile["strip"], ["nav", ".ad"])
        self.assertEqual(profile["title_selector"], "h1")


class ApplyProfileTests(unittest.TestCase):
    def test_keep_strip_and_title(self):
        html = ("<body><nav>NAV</nav><article><h1>Heading One</h1>"
                "<p>Body text.</p></article>"
                "<div class='ad-slot'>AD</div></body>")
        out, applied = wsr.apply_profile(
            html, {"keep": "article",
                   "strip": ["nav", ".ad-slot"],
                   "title_selector": "h1"})
        self.assertIn("Body text.", out)
        self.assertNotIn("NAV", out)
        self.assertNotIn("AD", out)
        self.assertEqual(applied["title"], "Heading One")
        self.assertEqual(sorted(applied["stripped"]),
                         [".ad-slot", "nav"])

    def test_rotted_keep_falls_back_visibly(self):
        html = "<body><article><p>Still here.</p></article></body>"
        out, applied = wsr.apply_profile(
            html, {"keep": ".does-not-exist", "strip": [],
                   "title_selector": None})
        self.assertFalse(applied["keep_matched"])
        self.assertIn("Still here.", out)  # never an empty capture


class ClipIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="clip-tpl-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_docs_clip_uses_template_and_records_it(self):
        def fake_fetcher(url):
            return clip.FetchResult(
                DOCS_PAGE.encode("utf-8"),
                content_type="text/html",
                final_url=url)
        res = clip.clip_url(
            "https://docs.example.net/guide/",
            root=self.root, fetcher=fake_fetcher, now=NOW)
        self.assertEqual(res["title"], "Real Doc Title")
        draft = (self.root / res["draft"]).read_text(
            encoding="utf-8")
        self.assertIn("substantive documentation paragraph", draft)
        self.assertNotIn("SIDENAV", draft)
        self.assertNotIn("FOOTER chrome", draft)
        # preserved source stays the fetched bytes, verbatim
        preserved = (self.root / res["preserved"]).read_bytes()
        self.assertEqual(preserved, DOCS_PAGE.encode("utf-8"))
        sidecar = json.loads((self.root / res["sidecar"]).read_text(
            encoding="utf-8"))
        self.assertEqual(sidecar["clip"]["clip_template"]["name"],
                         "docs")
        self.assertFalse(
            sidecar["clip"]["clip_template"]["fallback"])


if __name__ == "__main__":
    unittest.main()
