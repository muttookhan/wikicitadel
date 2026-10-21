"""Tests for scripts/wiki_retraction_watch.py — pins: the
register folds (later line governs); a retracted source is
flagged with the compiled pages resting on it; a stale
check date and a malformed line each flag in their own
class; a missing register is the honest empty state; fetch
mode refuses with no fetcher and, driven by a fake fetcher,
reports a marker that disagrees with the recorded status
as a change candidate without touching the register.
Fixture trees in temp dirs only; no network anywhere.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_retraction_watch", HERE.parents[1] / "wiki_retraction_watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

TODAY = date(2026, 10, 21)


def make_root(tmp):
    root = Path(tmp) / "repo"
    (root / "wiki" / "sources").mkdir(parents=True)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "evaluation").mkdir()
    (root / "wiki" / "sources" / "paper-a.md").write_text(
        "---\ntitle: Paper A\ntype: source\nsources:\n"
        "  - raw/sources/paper-a.md\ntags: [demo]\n---\n\n# Paper A\n",
        encoding="utf-8")
    (root / "wiki" / "concepts" / "claim-x.md").write_text(
        "---\ntitle: Claim X\ntype: concept\nsources:\n"
        "  - wiki/sources/paper-a.md\ntags: [demo]\n---\n\n"
        "# Claim X\n\nRests on [[paper-a]].\n", encoding="utf-8")
    return root


def write_register(root, lines):
    p = root / "evaluation" / "retraction-watch.jsonl"
    p.write_text("\n".join(json.dumps(x) if not isinstance(x, str)
                           else x for x in lines) + "\n",
                 encoding="utf-8")
    return p


class RetractionWatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_register_is_empty_state(self):
        r = watch.check(self.root, today=TODAY)
        self.assertFalse(r["register_present"])
        self.assertEqual(r["watched"], 0)
        self.assertEqual(r["flagged_count"], 0)

    def test_retracted_flagged_with_citing_pages_and_fold(self):
        write_register(self.root, [
            {"kind": "header", "register": "retraction-watch"},
            {"source": "wiki/sources/paper-a.md",
             "url": "https://publisher.example/a",
             "status": "not-retracted", "checked": "2026-10-01"},
            {"source": "wiki/sources/paper-a.md",
             "status": "retracted", "checked": "2026-10-20",
             "note": "publisher notice"},
        ])
        r = watch.check(self.root, today=TODAY)
        self.assertEqual(r["watched"], 1)
        self.assertEqual(r["flagged_count"], 1)
        f = r["flagged"][0]
        self.assertEqual(f["status"], "retracted")
        self.assertIn("wiki/concepts/claim-x.md", f["citing_pages"])

    def test_clean_and_stale_and_malformed(self):
        write_register(self.root, [
            {"source": "wiki/sources/paper-a.md",
             "status": "not-retracted", "checked": "2026-01-01"},
            "{not json",
            {"source": "wiki/sources/other.md", "status": "bogus",
             "checked": "2026-10-20"},
        ])
        r = watch.check(self.root, today=TODAY, stale_days=180)
        self.assertEqual(r["flagged_count"], 0)
        self.assertEqual(r["stale_count"], 1)
        self.assertEqual(r["malformed_count"], 2)

    def test_record_appends_and_governs(self):
        watch.record(self.root, None,
                     {"source": "wiki/sources/paper-a.md",
                      "status": "not-retracted"}, today=TODAY)
        watch.record(self.root, None,
                     {"source": "wiki/sources/paper-a.md",
                      "status": "corrected",
                      "note": "erratum"}, today=TODAY)
        r = watch.check(self.root, today=TODAY)
        self.assertEqual(r["flagged_count"], 1)
        self.assertEqual(r["flagged"][0]["status"], "corrected")

    def test_fetch_seam_off_by_default(self):
        with self.assertRaises(ValueError):
            watch.fetch_check(self.root)

    def test_fetch_fake_fetcher_reports_change_candidate(self):
        reg = write_register(self.root, [
            {"source": "wiki/sources/paper-a.md",
             "url": "https://publisher.example/a",
             "status": "not-retracted", "checked": "2026-10-20"},
        ])
        before = reg.read_bytes()
        out = watch.fetch_check(
            self.root,
            fetch=lambda url: "Notice: this article has been Retracted.")
        self.assertEqual(out["candidate_count"], 1)
        self.assertEqual(out["candidates"][0]["fetched_marker"],
                         "retracted")
        self.assertEqual(reg.read_bytes(), before)  # never edited

    def test_detect_markers_strength_order(self):
        self.assertEqual(
            watch.detect_markers("a correction was issued"), "corrected")
        self.assertIsNone(watch.detect_markers("ordinary text"))


if __name__ == "__main__":
    unittest.main()
