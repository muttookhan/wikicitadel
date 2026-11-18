#!/usr/bin/env python3
"""Tests for the Merkle layer of scripts/wiki_provenance.py
(batch 3.3, provenance hardening).

The whole-file provenance manifest says THAT a source changed;
the Merkle layer must say WHERE — these tests pin the
localisation: flip one byte in a known chunk and the verify
report must name that chunk index. Also pins the exclusions
(the generated provenance manifest is not itself merkle'd),
the added/missing classes, and the tree-reduction conventions
at module level.

Builds a fixture tree in a temp dir (the real script copied
in, so ROOT resolves to the fixture) and drives the CLI.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_provenance_module(script_path):
    spec = importlib.util.spec_from_file_location(
        "wiki_provenance_fixture", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MerkleRootTests(unittest.TestCase):
    """Tree-reduction conventions, no fixture needed."""

    @classmethod
    def setUpClass(cls):
        cls.prov = load_provenance_module(SCRIPTS / "wiki_provenance.py")

    def test_empty_tree_root_is_empty_hash(self):
        self.assertEqual(self.prov.merkle_root([]),
                         hashlib.sha256(b"").hexdigest())

    def test_single_leaf_is_its_own_root(self):
        leaf = hashlib.sha256(b"x").hexdigest()
        self.assertEqual(self.prov.merkle_root([leaf]), leaf)

    def test_root_is_order_sensitive(self):
        a = hashlib.sha256(b"a").hexdigest()
        b = hashlib.sha256(b"b").hexdigest()
        self.assertNotEqual(self.prov.merkle_root([a, b]),
                            self.prov.merkle_root([b, a]))

    def test_odd_leaf_is_duplicated(self):
        a = hashlib.sha256(b"a").hexdigest()
        b = hashlib.sha256(b"b").hexdigest()
        c = hashlib.sha256(b"c").hexdigest()
        pair = lambda x, y: hashlib.sha256(  # noqa: E731
            bytes.fromhex(x) + bytes.fromhex(y)).hexdigest()
        expected = pair(pair(a, b), pair(c, c))
        self.assertEqual(self.prov.merkle_root([a, b, c]), expected)


class MerkleCliTests(unittest.TestCase):
    """End-to-end: generate, verify, localise, add, remove."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "raw" / "sources" / "sub").mkdir(parents=True)
        (self.root / "evaluation").mkdir()
        import shutil
        shutil.copy(SCRIPTS / "wiki_provenance.py",
                    self.root / "scripts" / "wiki_provenance.py")
        self.script = self.root / "scripts" / "wiki_provenance.py"
        (self.root / "raw" / "sources" / "a.txt").write_bytes(
            b"small source\n")
        # 200_000 deterministic bytes: chunks 0,1,2 full + partial 3
        self.big = self.root / "raw" / "sources" / "sub" / "b.bin"
        self.big.write_bytes(bytes(i % 251 for i in range(200_000)))
        # the generated provenance manifest must be excluded
        (self.root / "raw" / "sources"
         / "provenance-manifest.json").write_text("{}")
        self.run_cli("--merkle-generate")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True, text=True)

    def test_generate_records_sources_and_excludes_manifest(self):
        import json
        manifest = self.root / "evaluation" / "merkle-manifest.jsonl"
        records = [json.loads(ln) for ln in
                   manifest.read_text(encoding="utf-8").splitlines()]
        paths = {r["path"] for r in records}
        self.assertEqual(paths, {"raw/sources/a.txt",
                                 "raw/sources/sub/b.bin"})
        big = next(r for r in records if r["path"].endswith("b.bin"))
        self.assertEqual(big["chunks"], 4)
        self.assertEqual(len(big["leaves"]), 4)
        self.assertEqual(len(big["merkle_root"]), 64)

    def test_verify_clean(self):
        out = self.run_cli("--merkle")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("CLEAN", out.stdout)

    def test_verify_without_manifest_is_exit_2(self):
        (self.root / "evaluation" / "merkle-manifest.jsonl").unlink()
        out = self.run_cli("--merkle")
        self.assertEqual(out.returncode, 2)

    def test_changed_byte_is_localised_to_its_chunk(self):
        data = bytearray(self.big.read_bytes())
        data[70_000] ^= 0xFF  # inside chunk 1 (65536..131071)
        self.big.write_bytes(bytes(data))
        out = self.run_cli("--merkle")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("CHANGED", out.stdout)
        self.assertIn("chunk 1 differs", out.stdout)
        self.assertNotIn("chunk 0 differs", out.stdout)
        self.assertNotIn("chunk 2 differs", out.stdout)

    def test_missing_and_added(self):
        (self.root / "raw" / "sources" / "a.txt").unlink()
        (self.root / "raw" / "sources" / "c.txt").write_bytes(b"new\n")
        out = self.run_cli("--merkle")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("MISSING", out.stdout)
        self.assertIn("ADDED", out.stdout)


if __name__ == "__main__":
    unittest.main()
