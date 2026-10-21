import importlib.util, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_integration_hygiene", ROOT / "scripts/wiki_integration_hygiene.py")

BASE = "# Doc\n\nbody\n"

class IntegrationHygieneTests(unittest.TestCase):
    def test_etag_is_sha256_of_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "f.txt"; p.write_bytes(b"hello\n")
            self.assertEqual(MOD.file_etag(p),
                "sha256:5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03")
    def test_verify_match_mismatch_missing_unrecorded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "a.md").write_text("A\n"); (root / "b.md").write_text("B\n")
            man = MOD.build_manifest(root, ["a.md", "b.md", "gone.md"])
            self.assertIsNone(man["gone.md"])
            rows = {r["path"]: r["status"] for r in MOD.verify_manifest(root, man)}
            self.assertEqual(rows, {"a.md": "match", "b.md": "match", "gone.md": "unrecorded"})
            (root / "b.md").write_text("CHANGED\n")
            rows = {r["path"]: r["status"] for r in MOD.verify_manifest(root, man)}
            self.assertEqual(rows["b.md"], "mismatch")
            man2 = dict(man); man2["gone.md"] = "sha256:" + "0" * 64
            rows = {r["path"]: r["status"] for r in MOD.verify_manifest(root, man2)}
            self.assertEqual(rows["gone.md"], "missing")
    def test_verify_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            import json
            root = Path(td); (root / "a.md").write_text("A\n")
            mp = root / "m.json"; mp.write_text(json.dumps(MOD.build_manifest(root, ["a.md"])))
            self.assertEqual(MOD.main(["verify", str(mp), "--root", str(root)]), 0)
            (root / "a.md").write_text("X\n")
            self.assertEqual(MOD.main(["verify", str(mp), "--root", str(root)]), 1)
    def test_coalesce_two_appends_no_loss(self):
        lane_a = BASE + "\n## Lane A section\n\naaa\n"
        lane_b = BASE + "\n## Lane B section\n\nbbb\n"
        merged, report = MOD.coalesce_appends(BASE, [lane_a, lane_b])
        self.assertIn("## Lane A section", merged); self.assertIn("## Lane B section", merged)
        self.assertLess(merged.index("Lane A"), merged.index("Lane B"))
        self.assertTrue(all(r["status"] == "appended" for r in report))
        # every non-empty line of each append survives (no loss)
        for cand in (lane_a, lane_b):
            for line in cand.splitlines():
                if line.strip():
                    self.assertIn(line, merged)
    def test_coalesce_duplicate_append_collapses(self):
        lane = BASE + "\n## Same section\n\nsame\n"
        merged, report = MOD.coalesce_appends(BASE, [lane, lane])
        self.assertEqual(merged.count("## Same section"), 1)
        self.assertEqual(report[1]["blocks_duplicated"], 1); self.assertEqual(report[1]["blocks_taken"], 0)
    def test_not_an_append_excluded_and_cli_fails_loudly(self):
        rewritten = "# Doc\n\nREWRITTEN body\n"
        merged, report = MOD.coalesce_appends(BASE, [rewritten])
        self.assertEqual(merged, BASE); self.assertEqual(report[0]["status"], "not-an-append")
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td) / "base.md"; bp.write_text(BASE)
            cp = Path(td) / "cand.md"; cp.write_text(rewritten)
            self.assertEqual(MOD.main(["coalesce", str(bp), str(cp)]), 1)
    def test_coalesce_log_blocks_and_empty_append(self):
        lane_a = BASE + "## [2026-10-21] entry one\n\nx\n"
        lane_b = BASE + "## [2026-10-21] entry two\n\ny\n"
        merged, report = MOD.coalesce_appends(BASE, [lane_a, lane_b, BASE])
        self.assertIn("entry one", merged); self.assertIn("entry two", merged)
        self.assertEqual(report[2]["status"], "empty")

if __name__ == "__main__":
    unittest.main()
