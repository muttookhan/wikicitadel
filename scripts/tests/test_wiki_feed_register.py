"""Tests for scripts/wiki_feed_register.py (Marathon R7 lane
BB; RSS Importer design, MIT — register re-implemented).

Pins: identity is stable across feed-URL spelling variants and
item-key precedence is guid > link > title+date; a new item
should-stage, a staged item is never re-staged, a dismissed
item stays dismissed, an ingested item is not re-offered; the
register is append-only (dismiss/ingest append, never rewrite);
cleanup reports a missing draft and is idempotent.

Run: python3 -m unittest scripts.tests.test_wiki_feed_register
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FEED = "https://example.org/feed.xml"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_feed_register", SCRIPTS / "wiki_feed_register.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


class IdentityTests(unittest.TestCase):
    def test_feed_normalisation(self):
        self.assertEqual(
            MOD.item_id("HTTPS://Example.ORG:443/feed.xml/", guid="g1"),
            MOD.item_id("https://example.org/feed.xml", guid="g1"))

    def test_key_precedence(self):
        self.assertTrue(MOD.item_key(guid="g", link="l").startswith("guid:"))
        self.assertTrue(MOD.item_key(link="l", title="t").startswith("link:"))
        self.assertTrue(MOD.item_key(title="t").startswith("tp:"))

    def test_same_link_different_feed_differs(self):
        self.assertNotEqual(
            MOD.item_id(FEED, link="https://example.org/a"),
            MOD.item_id("https://other.example/feed", link="https://example.org/a"))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_feed_register.py",
                    self.root / "scripts")
        (self.root / "evaluation").mkdir()
        (self.root / "staging" / "captures").mkdir(parents=True)
        self.tool = self.root / "scripts" / "wiki_feed_register.py"
        self.register = self.root / "evaluation" / "feed-clips.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(self.tool), *argv],
                              capture_output=True, text=True)

    def stage_one(self):
        proc = self.run_cli("stage", "--feed", FEED, "--guid", "g1",
                            "--title", "Item One",
                            "--draft", "staging/captures/one.md")
        self.assertEqual(proc.returncode, 0, proc.stderr)


class FlowTests(Fixture):
    def test_tri_state_flow(self):
        iid = MOD.item_id(FEED, guid="g1")
        self.assertTrue(MOD.should_stage(self.root, iid))
        self.assertEqual(self.run_cli(
            "should-stage", "--feed", FEED, "--guid", "g1").returncode, 0)
        self.stage_one()
        self.assertFalse(MOD.should_stage(self.root, iid))
        # Re-staging is refused; dismissal then sticks.
        self.assertEqual(self.run_cli(
            "stage", "--feed", FEED, "--guid", "g1").returncode, 2)
        self.assertEqual(self.run_cli(
            "dismiss", "--feed", FEED, "--guid", "g1",
            "--reason", "not relevant").returncode, 0)
        self.assertEqual(MOD.current_state(self.root, iid), "dismissed")
        self.assertEqual(self.run_cli(
            "should-stage", "--feed", FEED, "--guid", "g1").returncode, 1)

    def test_ingested_not_reoffered(self):
        self.stage_one()
        self.assertEqual(self.run_cli(
            "ingest", "--feed", FEED, "--guid", "g1",
            "--page", "wiki/sources/one.md").returncode, 0)
        iid = MOD.item_id(FEED, guid="g1")
        self.assertEqual(MOD.current_state(self.root, iid), "ingested")
        self.assertFalse(MOD.should_stage(self.root, iid))

    def test_register_append_only(self):
        self.stage_one()
        lines_after_stage = len(
            self.register.read_text(encoding="utf-8").splitlines())
        self.run_cli("dismiss", "--feed", FEED, "--guid", "g1")
        lines = self.register.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), lines_after_stage + 1)
        kinds = [json.loads(l)["kind"] for l in lines]
        self.assertEqual(kinds[0], "header")

    def test_cleanup_reports_missing_draft_idempotently(self):
        self.stage_one()
        first = MOD.cleanup(self.root, FEED)
        second = MOD.cleanup(self.root, FEED)
        self.assertEqual(first, second)
        self.assertEqual(first["stats"]["missing_drafts"], 1)
        draft = self.root / "staging" / "captures" / "one.md"
        draft.write_text("feed: https://example.org/feed.xml\n",
                         encoding="utf-8")
        self.assertEqual(MOD.cleanup(self.root, FEED)
                         ["stats"]["missing_drafts"], 0)


if __name__ == "__main__":
    unittest.main()
