#!/usr/bin/env python3
"""Wave-3 item C2: proposal diff view — staged-proposal parsing.

The logic lives in tools/lens/lenslib.py: unified_diff_hunks (the
per-hunk diff) and build_proposals_artefact (reading
staging/proposed/ <id>.md + <id>.json pairs into the Lens artefact).
The artefact is display-only data — decisions are made in chat — so
these tests pin the parsing contract: drafts in (oldest first),
legacy/pre-gateway files skipped with a reason, decided proposals
excluded with a reason, malformed manifests never fatal, a missing
staging dir degrading to an empty list.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def stage(repo: Path, pid: str, body: str, manifest: dict | None,
          raw_manifest: str | None = None):
    d = repo / "staging" / "proposed"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.md").write_text(body, encoding="utf-8")
    if raw_manifest is not None:
        (d / f"{pid}.json").write_text(raw_manifest, encoding="utf-8")
    elif manifest is not None:
        (d / f"{pid}.json").write_text(json.dumps(manifest),
                                       encoding="utf-8")


def draft_manifest(pid: str, target: str, **over):
    m = {"proposal_id": pid, "state": "draft",
         "submitted_by": "wiki-evolve",
         "submitted_at": "2030-10-13T14:17:06Z",
         "session_id": "s-1", "task_ref": "t-1",
         "target_path": target, "sha256": "a" * 64, "bytes": 10,
         "cites": [], "sanitiser": {"verdict": "clean", "findings": []}}
    m.update(over)
    return m


class DiffHunks(unittest.TestCase):
    def test_change_hunk_counts_and_kinds(self):
        hunks, n_add, n_del = L.unified_diff_hunks(
            ["a", "b", "c"], ["a", "B", "c"])
        self.assertEqual((n_add, n_del), (1, 1))
        self.assertEqual(len(hunks), 1)
        self.assertTrue(hunks[0]["header"].startswith("@@ -1,3 +1,3 @@"))
        kinds = [l["kind"] for l in hunks[0]["lines"]]
        self.assertEqual(kinds, ["context", "del", "add", "context"])

    def test_new_file_is_one_all_add_hunk(self):
        hunks, n_add, n_del = L.unified_diff_hunks([], ["x", "y"])
        self.assertEqual((n_add, n_del), (2, 0))
        self.assertTrue(all(l["kind"] == "add"
                            for l in hunks[0]["lines"]))

    def test_identical_texts_have_no_hunks(self):
        hunks, n_add, n_del = L.unified_diff_hunks(["a"], ["a"])
        self.assertEqual((hunks, n_add, n_del), ([], 0, 0))


class Artefact(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        (self.repo / "wiki").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_staging_dir_degrades(self):
        art = L.build_proposals_artefact(self.repo, {})
        self.assertFalse(art["source_present"])
        self.assertEqual(art["proposals"], [])
        self.assertIn("Decisions are made in chat", art["note"])

    def test_draft_pair_diffed_against_current_page(self):
        page = self.repo / "wiki" / "target.md"
        page.write_text("one\ntwo\nthree\n", encoding="utf-8")
        stage(self.repo, "prop-00000001", "one\nTWO\nthree\n",
              draft_manifest("prop-00000001", "wiki/target.md"))
        art = L.build_proposals_artefact(
            self.repo, {"wiki/target.md": "target"})
        self.assertEqual(len(art["proposals"]), 1)
        p = art["proposals"][0]
        self.assertEqual(p["target_id"], "target")
        self.assertFalse(p["is_new"])
        self.assertEqual((p["diff"]["added"], p["diff"]["removed"]), (1, 1))
        self.assertEqual(p["sanitiser_verdict"], "clean")

    def test_new_page_target_is_pure_addition(self):
        stage(self.repo, "prop-00000002", "fresh\npage\n",
              draft_manifest("prop-00000002", "wiki/brand-new.md"))
        art = L.build_proposals_artefact(self.repo, {})
        p = art["proposals"][0]
        self.assertTrue(p["is_new"])
        self.assertIsNone(p["target_id"])
        self.assertEqual(p["diff"]["removed"], 0)
        self.assertEqual(p["diff"]["added"], 2)

    def test_promoted_proposal_is_excluded_not_rendered(self):
        stage(self.repo, "prop-00000003", "x",
              draft_manifest("prop-00000003", "wiki/target.md",
                             state="promoted"))
        art = L.build_proposals_artefact(self.repo, {})
        self.assertEqual(art["proposals"], [])
        self.assertEqual(len(art["excluded"]), 1)
        self.assertEqual(art["excluded"][0]["state"], "promoted")

    def test_legacy_md_without_manifest_is_skipped(self):
        d = self.repo / "staging" / "proposed"
        d.mkdir(parents=True)
        (d / "qa-q_1.md").write_text("ask filing", encoding="utf-8")
        art = L.build_proposals_artefact(self.repo, {})
        self.assertEqual(art["proposals"], [])
        self.assertEqual(len(art["skipped"]), 1)
        self.assertIn("no JSON manifest", art["skipped"][0]["reason"])

    def test_malformed_manifest_is_skipped_not_fatal(self):
        stage(self.repo, "prop-00000004", "x", None,
              raw_manifest="{not json")
        art = L.build_proposals_artefact(self.repo, {})
        self.assertEqual(art["proposals"], [])
        self.assertEqual(len(art["skipped"]), 1)
        self.assertIn("unreadable", art["skipped"][0]["reason"])

    def test_oldest_first_ordering(self):
        stage(self.repo, "prop-0000000b", "b",
              draft_manifest("prop-0000000b", "wiki/b.md",
                             submitted_at="2030-10-20T00:00:00Z"))
        stage(self.repo, "prop-0000000a", "a",
              draft_manifest("prop-0000000a", "wiki/a.md",
                             submitted_at="2030-10-13T00:00:00Z"))
        art = L.build_proposals_artefact(self.repo, {})
        self.assertEqual([p["proposal_id"] for p in art["proposals"]],
                         ["prop-0000000a", "prop-0000000b"])

    def test_eval_gate_verdict_read_when_present(self):
        stage(self.repo, "prop-00000005", "x",
              draft_manifest("prop-00000005", "wiki/t.md",
                             eval_gate={"verdict": "pass"}))
        art = L.build_proposals_artefact(self.repo, {})
        self.assertEqual(art["proposals"][0]["eval_gate_verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
