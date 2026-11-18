"""Tests for scripts/wiki_lint_rules.py — the cherry-picked
Linter-catalogue rules. One fixture page per rule pins its
finding class; a clean page pins the zero; the tag rule pins
registered / altLabel / deprecated / unregistered and the
no-registry skip; --only/--skip select rules; unknown rule
names are a usage error. Fixture trees in temp dirs only.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_lint_rules", HERE.parents[1] / "wiki_lint_rules.py")
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

FM = ("---\ntitle: T\ntype: concept\ncreated: 2026-01-01\n"
      "updated: 2026-01-01\nsources: []\ntags: [demo]\n---\n\n")


def write(root, rel, text):
    p = root / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def by_rule(report, rule):
    return [f for f in report["findings"] if f["rule"] == rule]


class LintRulesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        (self.root / "wiki" / "concepts").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_page_zero(self):
        write(self.root, "concepts/clean.md",
              FM + "# Clean\n\nSee [[other-page|the other page]] and "
              "[the guide](guide.md).\n\n## Part\n\n"
              "![a diagram](diagram.png)\n")
        (self.root / "wiki" / "diagram.png").write_bytes(b"x")
        r = rules.run_rules(self.root,
                            skip={"tag-vocabulary"})
        self.assertEqual(r["total"], 0, r["findings"])

    def test_orphan_media(self):
        write(self.root, "concepts/a.md", FM + "# A\n\nNo images.\n")
        (self.root / "raw").mkdir()
        (self.root / "raw" / "unused.jpg").write_bytes(b"x")
        (self.root / "wiki" / "used.png").write_bytes(b"x")
        write(self.root, "concepts/b.md",
              FM + "# B\n\n![used](used.png)\n")
        r = rules.run_rules(self.root, only={"orphan-media"})
        found = by_rule(r, "orphan-media")
        self.assertEqual([f["page"] for f in found], ["raw/unused.jpg"])

    def test_frontmatter_completeness(self):
        write(self.root, "concepts/thin.md",
              "---\ntitle: Thin\ntype: concept\n---\n\n# Thin\n")
        write(self.root, "concepts/bare.md", "# Bare\n\nNo frontmatter.\n")
        write(self.root, "index.md", "# Index\n")
        write(self.root, "log.md", "# Log\n")
        r = rules.run_rules(self.root,
                            only={"frontmatter-completeness"})
        pages = {f["page"] for f in by_rule(
            r, "frontmatter-completeness")}
        self.assertEqual(pages, {"wiki/concepts/thin.md",
                                 "wiki/concepts/bare.md"})
        thin = [f for f in r["findings"]
                if f["page"].endswith("thin.md")][0]
        self.assertIn("created", thin["detail"])

    def test_link_text_quality(self):
        write(self.root, "concepts/a.md",
              FM + "# A\n\nSee [here](x.md), [[target|click here]] "
              "and [[target|the target page]].\n")
        r = rules.run_rules(self.root, only={"link-text-quality"})
        self.assertEqual(len(by_rule(r, "link-text-quality")), 2)

    def test_heading_structure(self):
        write(self.root, "concepts/a.md",
              FM + "# A\n\n### Skipped\n\n# Second top\n")
        write(self.root, "concepts/b.md", FM + "## Not first H1\n")
        r = rules.run_rules(self.root, only={"heading-structure"})
        kinds = [f["detail"] for f in by_rule(r, "heading-structure")]
        self.assertEqual(len(kinds), 3, kinds)

    def test_image_alt(self):
        write(self.root, "concepts/a.md",
              FM + "# A\n\n![](x.png)\n\n![[y.png]]\n\n"
              "![[z.png|a described image]]\n")
        r = rules.run_rules(self.root, only={"image-alt"})
        self.assertEqual(len(by_rule(r, "image-alt")), 2)

    def _registry(self, concepts):
        ev = self.root / "evaluation"
        ev.mkdir(exist_ok=True)
        lines = ['{"kind": "header"}']
        for pref, status, alts in concepts:
            lines.append(json.dumps(
                {"kind": "concept", "prefLabel": pref,
                 "altLabels": alts, "status": status}))
        (ev / "tag-registry.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    def test_tag_vocabulary(self):
        self._registry([("demo", "preferred", ["demos"]),
                        ("old-tag", "deprecated", [])])
        write(self.root, "concepts/a.md",
              FM.replace("[demo]", "[demo, demos, mystery]") + "# A\n")
        write(self.root, "concepts/b.md",
              FM.replace("[demo]", "[old-tag]") + "# B\n")
        r = rules.run_rules(self.root, only={"tag-vocabulary"})
        found = by_rule(r, "tag-vocabulary")
        self.assertEqual(len(found), 2, found)
        details = " ".join(f["detail"] for f in found)
        self.assertIn("mystery", details)
        self.assertIn("deprecated", details)

    def test_tag_vocabulary_no_registry_skips(self):
        write(self.root, "concepts/a.md", FM + "# A\n")
        r = rules.run_rules(self.root, only={"tag-vocabulary"})
        self.assertEqual(r["total"], 0)
        self.assertTrue(r["stats"]["tag-vocabulary"]["skipped"])

    def test_unknown_rule_is_usage_error(self):
        rc = rules.main(["x", "--root", str(self.root),
                         "--only", "no-such-rule"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
