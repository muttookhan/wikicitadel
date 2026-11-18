#!/usr/bin/env python3
"""Tests for scripts/wiki_weed.py — weeding-as-triage
(item 43). The CLI is driven against a fixture wiki in a
temp dir (the real scripts copied in, so every tool's ROOT
resolves to the fixture; no retrieval baseline exists in
the fixture, so never-retrieved is unmeasured there and
never asserted).

Fixture pages (compiled layer = wiki/** minus index/log):
  queries/lonely.md    no wikilinks in or out -> orphan
  queries/stale.md     anchors in 2030-01, queries class
                       window 60d -> stale-beyond-class;
                       linked both ways with the hub
  syntheses/hub.md     links to stale + target
  concepts/target.md   linked, fresh -> no defect
  syntheses/design-record.md
                       an island, but a NAMED EXCEPTION

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
NEEDS = ("wiki_weed.py", "wiki_rot.py", "wiki_stale.py",
         "wiki_reverify.py", "wiki_validate.py")

TODAY = "2030-10-20"


def page(title, created, body, work_type="record"):
    return (f"---\ntitle: {title}\ntype: query\n"
            f"created: {created}\nupdated: {created}\n"
            f"sources: []\ntags: [fixture]\n"
            f"work_type: {work_type}\n---\n\n{body}\n")


def build_fixture(root: Path):
    (root / "scripts").mkdir(parents=True)
    for name in NEEDS:
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    wiki = root / "wiki"
    (wiki / "queries").mkdir(parents=True)
    (wiki / "syntheses").mkdir()
    (wiki / "concepts").mkdir()
    (wiki / "index.md").write_text("# Index\n",
                                   encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    (wiki / "queries" / "lonely.md").write_text(
        page("Lonely", "2030-10-14", "No links at all."),
        encoding="utf-8")
    (wiki / "queries" / "stale.md").write_text(
        page("Stale", "2030-01-01", "See [[hub]]."),
        encoding="utf-8")
    (wiki / "syntheses" / "hub.md").write_text(
        page("Hub", "2030-10-19", "See [[stale]] and"
             " [[target]].", "synthesis"),
        encoding="utf-8")
    (wiki / "concepts" / "target.md").write_text(
        page("Target", "2030-10-19", "Back to [[hub]]."),
        encoding="utf-8")
    (wiki / "syntheses" / "design-record.md") \
        .write_text(page("Design record", "2030-10-13",
                         "Stands as written, unlinked."),
                    encoding="utf-8")
    (root / "evaluation").mkdir()


class WeedFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_fixture(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv):
        cmd = [sys.executable,
               str(self.root / "scripts" / "wiki_weed.py"),
               *argv, "--root", str(self.root),
               "--today", TODAY]
        return subprocess.run(cmd, capture_output=True,
                              text=True)

    def register(self):
        path = self.root / "evaluation" / \
            "weeding-nominations.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines()
                if line.strip()]


class ScanTests(WeedFixture):
    def test_scan_finds_verified_defects_only(self):
        r = self.run_cli("scan")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wiki/queries/lonely.md", r.stdout)
        self.assertIn("orphan", r.stdout)
        self.assertIn("wiki/queries/stale.md", r.stdout)
        self.assertIn("stale-beyond-class", r.stdout)
        self.assertNotIn("concepts/target.md", r.stdout)
        # The named exception is never nominated, though it
        # is as much an island as lonely.md.
        self.assertNotIn("design-record",
                         r.stdout)

    def test_nominate_files_and_dedupes(self):
        r = self.run_cli("nominate")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.register()
        self.assertEqual(len(rows), 2)
        by_page = {n["page"]: n for n in rows}
        self.assertEqual(
            by_page["wiki/queries/lonely.md"]
            ["proposed_route"], "owner-call")
        self.assertEqual(
            by_page["wiki/queries/stale.md"]
            ["proposed_route"], "refresh")
        for n in rows:
            self.assertEqual(n["status"], "open")
            self.assertTrue(n["defects"])
            for d in n["defects"]:
                self.assertTrue(d["signal"])
                self.assertTrue(d["value"])
        r2 = self.run_cli("nominate")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(len(self.register()), 2)  # no dupes


class RefusalTests(WeedFixture):
    def test_nomination_without_defect_is_refused(self):
        r = self.run_cli("nominate", "--page",
                         "wiki/concepts/target.md",
                         "--route", "owner-call")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUSED", r.stdout)
        self.assertEqual(self.register(), [])

    def test_route_outside_vocabulary_is_refused(self):
        r = self.run_cli("nominate", "--page",
                         "wiki/concepts/target.md",
                         "--signal", "never-retrieved",
                         "--value", "0 appearances",
                         "--route", "delete")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUSED", r.stdout)
        self.assertEqual(self.register(), [])

    def test_merge_into_requires_target(self):
        r = self.run_cli("nominate", "--page",
                         "wiki/concepts/target.md",
                         "--signal", "fork",
                         "--value", "shares a title with a twin",
                         "--route", "merge-into")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUSED", r.stdout)
        self.assertEqual(self.register(), [])

    def test_signal_outside_vocabulary_is_refused(self):
        r = self.run_cli("nominate", "--page",
                         "wiki/concepts/target.md",
                         "--signal", "seems-old",
                         "--value", "a vibe",
                         "--route", "refresh")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.register(), [])

    def test_exempt_page_is_refused(self):
        r = self.run_cli(
            "nominate", "--page",
            "wiki/syntheses/design-record.md",
            "--signal", "orphan", "--value", "an island",
            "--route", "owner-call")
        self.assertEqual(r.returncode, 2)
        self.assertIn("named exception", r.stdout)
        self.assertEqual(self.register(), [])


class AppendOnlyTests(WeedFixture):
    def test_register_only_grows_and_prefix_is_stable(self):
        path = self.root / "evaluation" / \
            "weeding-nominations.jsonl"
        r = self.run_cli("nominate", "--page",
                         "wiki/concepts/target.md",
                         "--signal", "never-retrieved",
                         "--value", "0 appearances in fixture",
                         "--route", "owner-call")
        self.assertEqual(r.returncode, 0, r.stderr)
        before = path.read_bytes()
        r = self.run_cli("nominate")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = path.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))
        # And the tool's vocabulary is exactly six routes.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "wiki_weed", SCRIPTS / "wiki_weed.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(
            mod.ROUTES, ("keep", "refresh", "merge-into",
                         "split", "demote-to-raw",
                         "owner-call"))


if __name__ == "__main__":
    unittest.main()
