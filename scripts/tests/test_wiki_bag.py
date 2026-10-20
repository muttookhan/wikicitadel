"""Tests for scripts/wiki_bag.py — BagIt (RFC 8493) pack +
validate over a fixture corpus in a temp dir: a clean bag
validates; a corrupted payload byte, a deleted payload file, a
stray unmanifested file, and a tampered tag file are each
caught with the right reason class.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_bag", HERE.parents[1] / "wiki_bag.py")
bag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bag)


def make_root(tmp):
    root = Path(tmp) / "repo"
    (root / "wiki" / "rules").mkdir(parents=True)
    (root / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "rules" / "r.md").write_text(
        "rule text\n", encoding="utf-8")
    (root / "evaluation").mkdir()
    (root / "evaluation" / "register.jsonl").write_text(
        '{"a": 1}\n', encoding="utf-8")
    (root / "AGENTS.md").write_text("schema\n", encoding="utf-8")
    (root / "raw" / "sources").mkdir(parents=True)
    (root / "raw" / "sources" / "s.md").write_text(
        "source\n", encoding="utf-8")
    return root


class BagTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)
        self.dest = Path(self._tmp.name) / "out" / "bag1"

    def tearDown(self):
        self._tmp.cleanup()

    def test_pack_compiled_set_and_validate(self):
        stats = bag.pack(self.root, self.dest, "compiled",
                         bagging_date="2030-10-20")
        # compiled = wiki/ + evaluation/ + AGENTS.md; raw/ excluded.
        self.assertEqual(stats["files"], 4)
        self.assertTrue((self.dest / "data" / "wiki" / "index.md")
                        .is_file())
        self.assertFalse((self.dest / "data" / "raw").exists())
        info = (self.dest / "bag-info.txt").read_text(encoding="utf-8")
        total = sum((self.root / r).stat().st_size for r in
                    ("wiki/index.md", "wiki/rules/r.md",
                     "evaluation/register.jsonl", "AGENTS.md"))
        self.assertIn(f"Payload-Oxum: {total}.4", info)
        self.assertIn("BagIt-Version: 1.0",
                      (self.dest / "bagit.txt").read_text(encoding="utf-8"))
        ok, problems, vstats = bag.validate(self.dest)
        self.assertTrue(ok, problems)
        self.assertEqual(vstats["payload_files"], 4)
        self.assertEqual(vstats["payload_bytes"], total)

    def test_full_set_includes_raw(self):
        stats = bag.pack(self.root, self.dest, "full",
                         bagging_date="2030-10-20")
        self.assertEqual(stats["files"], 5)
        ok, problems, _ = bag.validate(self.dest)
        self.assertTrue(ok, problems)

    def test_corrupted_payload_byte_caught(self):
        bag.pack(self.root, self.dest, "compiled",
                 bagging_date="2030-10-20")
        target = self.dest / "data" / "wiki" / "index.md"
        data = bytearray(target.read_bytes())
        data[0] ^= 0xFF
        target.write_bytes(bytes(data))
        ok, problems, _ = bag.validate(self.dest)
        self.assertFalse(ok)
        self.assertTrue(any("fixity" in p and "index.md" in p
                            for p in problems), problems)
        # the oxum still matches (same size) — fixity is what fires
        self.assertFalse(any("Payload-Oxum" in p for p in problems))

    def test_deleted_payload_file_caught(self):
        bag.pack(self.root, self.dest, "compiled",
                 bagging_date="2030-10-20")
        (self.dest / "data" / "evaluation" / "register.jsonl").unlink()
        ok, problems, _ = bag.validate(self.dest)
        self.assertFalse(ok)
        self.assertTrue(any("incomplete" in p for p in problems),
                        problems)

    def test_stray_unmanifested_file_caught(self):
        bag.pack(self.root, self.dest, "compiled",
                 bagging_date="2030-10-20")
        (self.dest / "data" / "wiki" / "stray.md").write_text(
            "stray\n", encoding="utf-8")
        ok, problems, _ = bag.validate(self.dest)
        self.assertFalse(ok)
        self.assertTrue(any("unmanifested" in p for p in problems),
                        problems)

    def test_tampered_tag_file_caught_by_tagmanifest(self):
        bag.pack(self.root, self.dest, "compiled",
                 bagging_date="2030-10-20")
        info = self.dest / "bag-info.txt"
        info.write_text(info.read_text(encoding="utf-8").replace(
            "WikiCitadel", "someone else"),
            encoding="utf-8")
        ok, problems, _ = bag.validate(self.dest)
        self.assertFalse(ok)
        self.assertTrue(any("tag file" in p for p in problems),
                        problems)

    def test_manifest_lines_are_sorted_and_hashes_real(self):
        bag.pack(self.root, self.dest, "compiled",
                 bagging_date="2030-10-20")
        lines = (self.dest / "manifest-sha256.txt").read_text(
            encoding="utf-8").splitlines()
        paths = [ln.split(None, 1)[1] for ln in lines]
        self.assertEqual(paths, sorted(paths))
        for ln in lines:
            digest, rel = ln.split(None, 1)
            real = hashlib.sha256(
                (self.dest / rel.strip()).read_bytes()).hexdigest()
            self.assertEqual(digest, real)

    def test_pack_refuses_nonempty_dest_and_repo_interior(self):
        self.dest.mkdir(parents=True)
        (self.dest / "x").write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            bag.pack(self.root, self.dest, "compiled")
        with self.assertRaises(ValueError):
            bag.pack(self.root, self.root / "bag-in-repo", "compiled")

    def test_validate_non_bag(self):
        ok, problems, _ = bag.validate(self.root)
        self.assertFalse(ok)
        self.assertTrue(problems)


if __name__ == "__main__":
    unittest.main()
