#!/usr/bin/env python3
"""Pins wiki_reuse (Marathon R6 lane BB; Wilkinson et al.
FAIR pattern): a declared `reuse:` in the vocabulary passes
clean; a missing statement is reported and read under the
CONFIG's default (never a hardcoded one); an out-of-vocabulary
value is reported and falls back to the default, stated; a
config whose own default is outside the vocabulary is a
config finding; `statement` renders the effective terms; and
the check never modifies a page.

Run:  python3 -m unittest discover -s scripts/tests
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "wiki_reuse", SCRIPTS / "wiki_reuse.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CONFIG = {
    "field": "reuse",
    "default_reuse": "internal",
    "default_basis": "fixture default",
    "classes": [
        {"id": "open", "label": "Open",
         "statement": "Reuse with attribution."},
        {"id": "cite-only", "label": "Cite only",
         "statement": "Quote and cite only."},
        {"id": "internal", "label": "Internal",
         "statement": "Inside this wiki only."},
        {"id": "closed", "label": "Closed",
         "statement": "Reading in place only."},
    ],
}


def page(reuse_line=None):
    fm = ["title: Fixture Page", "type: concept",
          "created: 2026-01-15", "updated: 2026-01-15",
          "sources: [raw/sources/x.md]", "tags: [fixture]"]
    if reuse_line is not None:
        fm.append(reuse_line)
    return "---\n" + "\n".join(fm) + "\n---\n\nBody text.\n"


class TestReuse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "wiki" / "concepts").mkdir(parents=True)
        (self.root / "evaluation").mkdir(parents=True)
        (self.root / "evaluation" / "reuse-vocabulary.json") \
            .write_text(json.dumps(CONFIG))
        self.pg = self.root / "wiki" / "concepts" / "p.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _report(self):
        return m.check(self.root)

    def test_declared_in_vocabulary_is_clean(self):
        self.pg.write_text(page("reuse: open"))
        r = self._report()
        self.assertEqual(r["stats"]["missing"], 0)
        self.assertEqual(r["stats"]["invalid"], 0)
        rec = r["pages"][0]
        self.assertEqual(rec["effective"], "open")
        self.assertEqual(rec["source"], "declared")
        self.assertEqual(m.main(["--root", str(self.root),
                                 "check"]), 0)

    def test_missing_reads_under_config_default(self):
        self.pg.write_text(page())
        r = self._report()
        rec = r["pages"][0]
        self.assertEqual(rec["findings"], ["missing-statement"])
        self.assertEqual(rec["effective"], "internal")
        self.assertEqual(rec["source"], "default")
        self.assertEqual(m.main(["--root", str(self.root),
                                 "check"]), 1)

    def test_default_comes_from_config_not_code(self):
        cfg = dict(CONFIG, default_reuse="open")
        (self.root / "evaluation" / "reuse-vocabulary.json") \
            .write_text(json.dumps(cfg))
        self.pg.write_text(page())
        rec = self._report()["pages"][0]
        self.assertEqual(rec["effective"], "open")

    def test_invalid_value_falls_back_and_is_named(self):
        self.pg.write_text(page("reuse: free-for-all"))
        rec = self._report()["pages"][0]
        self.assertEqual(rec["findings"], ["invalid-statement"])
        self.assertEqual(rec["effective"], "internal")
        self.assertEqual(rec["source"], "default-fallback")

    def test_bad_default_is_a_config_finding(self):
        cfg = dict(CONFIG, default_reuse="bogus")
        (self.root / "evaluation" / "reuse-vocabulary.json") \
            .write_text(json.dumps(cfg))
        self.pg.write_text(page("reuse: open"))
        r = self._report()
        self.assertEqual([f["kind"] for f in
                          r["config_findings"]], ["bad-default"])
        self.assertEqual(m.main(["--root", str(self.root),
                                 "check"]), 1)

    def test_statement_renders_effective_terms(self):
        self.pg.write_text(page("reuse: cite-only"))
        st = m.statement_for(self.root, "wiki/concepts/p.md")
        self.assertEqual(st["effective"], "cite-only")
        self.assertEqual(st["statement"], "Quote and cite only.")
        self.pg.write_text(page())
        st = m.statement_for(self.root, "wiki/concepts/p.md")
        self.assertEqual(st["effective"], "internal")
        self.assertEqual(st["findings"], ["missing-statement"])

    def test_check_never_modifies_pages(self):
        self.pg.write_text(page())
        h = hashlib.sha256(self.pg.read_bytes()).hexdigest()
        self._report()
        self.assertEqual(
            hashlib.sha256(self.pg.read_bytes()).hexdigest(), h)

    def test_structural_pages_without_frontmatter_exempt(self):
        (self.root / "wiki" / "index.md").write_text("# Index\n")
        self.pg.write_text(page("reuse: open"))
        r = self._report()
        self.assertEqual([p["page"] for p in r["pages"]],
                         ["wiki/concepts/p.md"])

    def test_missing_config_is_usage_error(self):
        (self.root / "evaluation" / "reuse-vocabulary.json") \
            .unlink()
        self.assertEqual(m.main(["--root", str(self.root),
                                 "check"]), 2)


if __name__ == "__main__":
    unittest.main()
