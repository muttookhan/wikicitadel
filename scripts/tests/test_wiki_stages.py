#!/usr/bin/env python3
"""Tests for scripts/wiki_stages.py — growth-stage proposals and
the frontmatter-only backfill (wave-3 item: page growth-stage
labels).

The classifier is deterministic over observable signals; the
apply step may add ONLY stage/planted/tended frontmatter lines,
must never touch a body, and must never overwrite a field a
page already carries.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TODAY = date(2030, 10, 20)


def load_stages(script_path):
    spec = importlib.util.spec_from_file_location(
        "wiki_stages_fixture", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stages = load_stages(SCRIPTS / "wiki_stages.py")


def sig(**over):
    base = {
        "path": "wiki/x.md", "type": "source", "status": "",
        "sources_n": 1, "cites_n": 0, "body_chars": 3000,
        "outcome_status": "", "planted": "2030-10-12",
        "tended": "2030-10-12", "age_days": 8, "tended_days": 8,
        "existing": {},
    }
    base.update(over)
    return base


class ClassifyTests(unittest.TestCase):
    def test_outcome_rule_is_evergreen(self):
        stage, _ = stages.classify(sig(outcome_status="rule", sources_n=1))
        self.assertEqual(stage, "evergreen")

    def test_rich_and_tended_is_evergreen(self):
        stage, _ = stages.classify(sig(sources_n=3, cites_n=1, tended_days=14))
        self.assertEqual(stage, "evergreen")

    def test_rich_but_untended_is_not_evergreen(self):
        stage, _ = stages.classify(sig(sources_n=3, cites_n=1, tended_days=15))
        self.assertEqual(stage, "budding")

    def test_rich_without_citations_is_budding(self):
        stage, _ = stages.classify(sig(sources_n=5, cites_n=0, tended_days=0))
        self.assertEqual(stage, "budding")

    def test_no_sources_is_seedling(self):
        stage, _ = stages.classify(sig(sources_n=0, cites_n=0, body_chars=9000))
        self.assertEqual(stage, "seedling")

    def test_new_page_without_citations_is_seedling(self):
        stage, _ = stages.classify(sig(sources_n=2, cites_n=0, age_days=1))
        self.assertEqual(stage, "seedling")

    def test_new_page_with_citations_and_sources_is_evergreen(self):
        # Settled beats new when the evidence is strong (rule order).
        stage, _ = stages.classify(
            sig(sources_n=4, cites_n=2, age_days=0, tended_days=0))
        self.assertEqual(stage, "evergreen")

    def test_thin_stub_is_seedling(self):
        stage, _ = stages.classify(
            sig(sources_n=1, cites_n=0, body_chars=1499, age_days=8))
        self.assertEqual(stage, "seedling")

    def test_sourced_page_is_budding(self):
        stage, _ = stages.classify(sig(sources_n=1, cites_n=0, body_chars=4000))
        self.assertEqual(stage, "budding")

    def test_cited_page_is_budding_when_sources_thin(self):
        stage, _ = stages.classify(sig(sources_n=2, cites_n=1, tended_days=3))
        self.assertEqual(stage, "budding")


class FrontmatterTests(unittest.TestCase):
    PAGE = ("---\ntitle: X\ntype: source\ncreated: 2030-10-12\n"
            "updated: 2030-10-18\nsources:\n  - raw/sources/a.md\n"
            "tags: [x]\n---\n\n# X\n\nBody text.\n")

    def test_parse_fields_counts_block_sources(self):
        fm_text, body = stages.split_frontmatter(self.PAGE)
        fields, sources = stages.parse_fields(fm_text)
        self.assertEqual(sources, ["raw/sources/a.md"])
        self.assertEqual(fields["type"], "source")
        self.assertIn("Body text.", body)

    def test_parse_fields_counts_flow_sources(self):
        fm_text, _ = stages.split_frontmatter(
            "---\ntitle: Y\nsources: [\"raw/a.md\", \"raw/b.md\"]\n---\n\nbody\n")
        _, sources = stages.parse_fields(fm_text)
        self.assertEqual(len(sources), 2)

    def test_add_fields_appends_three_lines_body_untouched(self):
        new_text, added = stages.add_stage_fields(
            self.PAGE, {"stage": "budding", "planted": "2030-10-12",
                        "tended": "2030-10-18"})
        self.assertEqual(added, ["stage", "planted", "tended"])
        _, old_body = stages.split_frontmatter(self.PAGE)
        _, new_body = stages.split_frontmatter(new_text)
        self.assertEqual(old_body, new_body)
        fm_text, _ = stages.split_frontmatter(new_text)
        fields, _ = stages.parse_fields(fm_text)
        self.assertEqual(fields["stage"], "budding")
        self.assertEqual(fields["planted"], "2030-10-12")

    def test_add_fields_never_overwrites_existing(self):
        text = self.PAGE.replace("tags: [x]",
                                 "tags: [x]\nstage: evergreen")
        new_text, added = stages.add_stage_fields(
            text, {"stage": "seedling", "planted": "2030-10-12",
                   "tended": "2030-10-18"})
        self.assertEqual(added, ["planted", "tended"])
        fm_text, _ = stages.split_frontmatter(new_text)
        fields, _ = stages.parse_fields(fm_text)
        self.assertEqual(fields["stage"], "evergreen")

    def test_add_fields_no_frontmatter_is_noop(self):
        text = "# Plain\n\nno frontmatter\n"
        new_text, added = stages.add_stage_fields(
            text, {"stage": "seedling", "planted": "2030-10-20",
                   "tended": "2030-10-20"})
        self.assertEqual(added, [])
        self.assertEqual(new_text, text)


class FixtureWikiTests(unittest.TestCase):
    """End-to-end over a temp wiki: propose files a filing and
    changes nothing; apply adds frontmatter lines only."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wiki-stages-"))
        (self.tmp / "scripts").mkdir(parents=True)
        (self.tmp / "wiki" / "filings").mkdir(parents=True)
        (self.tmp / "wiki" / "sources").mkdir(parents=True)
        script_copy = self.tmp / "scripts" / "wiki_stages.py"
        script_copy.write_text(
            (SCRIPTS / "wiki_stages.py").read_text(encoding="utf-8"),
            encoding="utf-8")
        self.script = script_copy
        self.rich = self.tmp / "wiki" / "sources" / "rich.md"
        self.rich.write_text(
            "---\ntitle: Rich\ntype: source\ncreated: 2030-10-12\n"
            "updated: 2030-10-19\nsources:\n  - raw/a.md\n  - raw/b.md\n"
            "  - raw/c.md\ntags: [t]\n---\n\n# Rich\n\n"
            "Claim. ^[cite: raw/a.md#L1-L2]\n\n" + "More text. " * 100,
            encoding="utf-8")
        self.thin = self.tmp / "wiki" / "sources" / "thin.md"
        self.thin.write_text(
            "---\ntitle: Thin\ntype: query\ncreated: 2030-10-12\n"
            "updated: 2030-10-12\nsources: []\ntags: [t]\n---\n\n"
            "# Thin\n\nShort.\n",
            encoding="utf-8")
        self.plain = self.tmp / "wiki" / "index.md"
        self.plain.write_text("# Index\n\nNo frontmatter.\n",
                              encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True, text=True, timeout=60)

    def test_propose_then_apply(self):
        before_rich = self.rich.read_text(encoding="utf-8")
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No page has been changed", r.stdout)
        self.assertEqual(self.rich.read_text(encoding="utf-8"), before_rich)

        filings = list((self.tmp / "wiki" / "filings").glob("stage-backfill-*"))
        self.assertEqual(len(filings), 2)  # .md + .json
        manifest = json.loads(
            (self.tmp / "wiki" / "filings" /
             f"stage-backfill-{date.today().isoformat()}.json")
            .read_text(encoding="utf-8"))
        stages_by_path = {p["path"]: p["stage"]
                          for p in manifest["proposals"]}
        self.assertEqual(stages_by_path["wiki/sources/rich.md"], "evergreen")
        self.assertEqual(stages_by_path["wiki/sources/thin.md"], "seedling")
        self.assertEqual(manifest["structural_no_stage"], ["wiki/index.md"])

        r = self.run_cli("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        mod = load_stages(self.script)
        for page, want in ((self.rich, "evergreen"), (self.thin, "seedling")):
            fm_text, _ = mod.split_frontmatter(
                page.read_text(encoding="utf-8"))
            fields, _ = mod.parse_fields(fm_text)
            self.assertEqual(fields["stage"], want)
            self.assertIn("planted", fields)
            self.assertIn("tended", fields)
        # body of the rich page is untouched
        _, body_after = mod.split_frontmatter(
            self.rich.read_text(encoding="utf-8"))
        _, body_before = mod.split_frontmatter(before_rich)
        self.assertEqual(body_after, body_before)
        # the structural page got nothing
        self.assertEqual(self.plain.read_text(encoding="utf-8"),
                         "# Index\n\nNo frontmatter.\n")
        # second apply is a no-op for pages (all skipped)
        r = self.run_cli("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 page(s) changed", r.stdout)

    def test_late_arrival_is_classified_on_apply(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        late_page = self.tmp / "wiki" / "sources" / "late.md"
        late_page.write_text(
            "---\ntitle: Late\ntype: source\n"
            f"created: {date.today().isoformat()}\n"
            f"updated: {date.today().isoformat()}\n"
            "sources:\n  - raw/a.md\ntags: [t]\n---\n\n# Late\n\n"
            "New page body.\n", encoding="utf-8")
        r = self.run_cli("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        mod = load_stages(self.script)
        fm_text, _ = mod.split_frontmatter(
            late_page.read_text(encoding="utf-8"))
        fields, _ = mod.parse_fields(fm_text)
        self.assertEqual(fields["stage"], "seedling")
        manifest = json.loads(
            (self.tmp / "wiki" / "filings" /
             f"stage-backfill-{date.today().isoformat()}.json")
            .read_text(encoding="utf-8"))
        late_paths = [i["path"] for i in
                      manifest["application"]["late_arrivals"]]
        self.assertIn("wiki/sources/late.md", late_paths)


if __name__ == "__main__":
    unittest.main()
