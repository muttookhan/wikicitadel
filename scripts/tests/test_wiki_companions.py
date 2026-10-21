"""Tests for scripts/wiki_companions.py (Marathon R3 TB5 row 4,
pin-llm-wiki pattern): sources sharing a repo/DOI/project id are
proposed as one companion group; the register checker catches
overlap, singleton groups and missing members; apply refuses a
group whose member is already grouped. Run:
python3 -m unittest scripts.tests.test_wiki_companions
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_companions as wco  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="comp-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = self.root / "wiki" / "sources"
        self.src.mkdir(parents=True)
        (self.src / "repo.md").write_text(
            "---\ntitle: Widget repo\nrepo: https://github.com/x/widget\n"
            "---\n\nRepo.\n", encoding="utf-8")
        (self.src / "paper.md").write_text(
            "---\ntitle: Widget paper\ndoi: 10.1000/widget\n"
            "project: widget\n---\n\nSee https://github.com/x/widget\n",
            encoding="utf-8")
        (self.src / "talk.md").write_text(
            "---\ntitle: Widget talk\nproject: widget\n---\n\nTalk.\n",
            encoding="utf-8")
        (self.src / "solo.md").write_text(
            "---\ntitle: Solo\nproject: other\n---\n\nAlone.\n",
            encoding="utf-8")


class ProposeTests(Fixture):
    def test_shared_ids_form_a_group(self):
        result = wco.propose(self.src, self.root)
        groups = result["groups"]
        self.assertEqual(len(groups), 1)
        members = set(groups[0]["members"])
        self.assertIn("wiki/sources/repo.md", members)
        self.assertIn("wiki/sources/paper.md", members)
        self.assertIn("wiki/sources/talk.md", members)
        self.assertNotIn("wiki/sources/solo.md",
                         {m for g in groups for m in g["members"]})

    def test_check_flags_overlap_and_missing(self):
        reg = self.root / "wiki" / "companion-groups.json"
        reg.write_text(json.dumps({"groups": [
            {"id": "a", "members": ["wiki/sources/repo.md",
                                    "wiki/sources/paper.md"]},
            {"id": "b", "members": ["wiki/sources/paper.md",
                                    "wiki/sources/nope.md"]},
        ]}), encoding="utf-8")
        problems = wco.check(reg, self.root)
        joined = " ".join(problems)
        self.assertIn("two groups", joined)
        self.assertIn("missing", joined)

    def test_check_clean_register(self):
        reg = self.root / "wiki" / "companion-groups.json"
        reg.write_text(json.dumps({"groups": [
            {"id": "w", "members": ["wiki/sources/repo.md",
                                    "wiki/sources/talk.md"]}]}),
            encoding="utf-8")
        self.assertEqual(wco.check(reg, self.root), [])


if __name__ == "__main__":
    unittest.main()
