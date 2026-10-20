"""Tests for scripts/wiki_stamp.py (wave-10 fold-in): the
compile stamp is written as flat frontmatter scalars, read
back by the wiki's own parser, and round-trips the OKF
export."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_stamp as ws  # noqa: E402
import wiki_validate as wv  # noqa: E402

PAGE = """---
title: "Fixture"
type: synthesis
created: 2030-10-20
updated: 2030-10-20
sources:
  - raw/x.md
tags: [test]
---

# Fixture

Body.
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="stamp-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        page = self.root / "wiki" / "syntheses" / "fix.md"
        page.parent.mkdir(parents=True)
        page.write_text(PAGE, encoding="utf-8")
        self.rel = "wiki/syntheses/fix.md"


class StampTests(Fixture):
    def test_stamp_round_trip_through_wiki_parser(self):
        ws.stamp_page(self.rel, prompt=ws.UNVERSIONED,
                      converter="none", on="2030-10-20",
                      root=self.root)
        text = (self.root / self.rel).read_text()
        fields, body = wv.parse_frontmatter(text)
        self.assertEqual(fields["compiled_prompt"],
                         "unversioned-agent-pass")
        self.assertEqual(fields["compiled_converter"], "none")
        self.assertEqual(fields["compiled_date"], "2030-10-20")
        self.assertIn("# Fixture", body)

    def test_stamp_round_trip_through_okf_export(self):
        import yaml
        import wiki_okf_export as okf
        ws.stamp_page(self.rel, prompt="tmpl/compile@2",
                      converter="wiki_convert.py@1",
                      on="2030-10-20", root=self.root)
        text = (self.root / self.rel).read_text()
        fields, body = wv.parse_frontmatter(text)
        rendered = okf.render_concept(fields, body)
        fm = rendered.split("---\n")[1]
        parsed = yaml.safe_load(fm)
        ns = parsed["llm_wiki"]
        self.assertEqual(ns["compiled_prompt"], "tmpl/compile@2")
        self.assertEqual(ns["compiled_converter"],
                         "wiki_convert.py@1")
        self.assertEqual(ns["compiled_date"], "2030-10-20")

    def test_restamp_updates_in_place(self):
        ws.stamp_page(self.rel, prompt="a", converter="none",
                      on="2030-10-20", root=self.root)
        ws.stamp_page(self.rel, prompt="b", converter="none",
                      on="2030-10-21", root=self.root)
        text = (self.root / self.rel).read_text()
        self.assertEqual(text.count("compiled_prompt:"), 1)
        self.assertEqual(text.count("compiled_date:"), 1)
        shown = ws.show_stamp(self.rel, root=self.root)
        self.assertEqual(shown["compiled_prompt"], "b")
        self.assertEqual(shown["compiled_date"], "2030-10-21")

    def test_show_unstamped_is_none(self):
        self.assertIsNone(ws.show_stamp(self.rel, root=self.root))

    def test_empty_prompt_refused(self):
        with self.assertRaises(ws.StampError):
            ws.stamp_page(self.rel, prompt="  ", converter="none",
                          root=self.root)


if __name__ == "__main__":
    unittest.main()
