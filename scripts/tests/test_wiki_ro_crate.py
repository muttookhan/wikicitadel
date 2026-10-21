"""Tests for scripts/wiki_ro_crate.py — the RO-Crate sidecar
on export bundles: a generated sidecar describes every file
with its sha256, regenerates byte-identically, and `check`
catches a tampered payload byte, an added file, a removed
file, a hand-edited sidecar, and a missing sidecar. A bag
packed by scripts/wiki_bag.py still validates after gaining
a sidecar (the sidecar is not payload).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_ro_crate", HERE.parents[1] / "wiki_ro_crate.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

bag_spec = importlib.util.spec_from_file_location(
    "wiki_bag", HERE.parents[1] / "wiki_bag.py")
bag = importlib.util.module_from_spec(bag_spec)
bag_spec.loader.exec_module(bag)


def make_bundle(tmp):
    b = Path(tmp) / "bundle"
    (b / "data" / "wiki").mkdir(parents=True)
    (b / "data" / "wiki" / "index.md").write_text(
        "# Index\n", encoding="utf-8")
    (b / "data" / "notes.txt").write_text(
        "plain notes\n", encoding="utf-8")
    (b / "bagit.txt").write_text(
        "BagIt-Version: 1.0\n", encoding="utf-8")
    return b


class BuildTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bundle = make_bundle(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sidecar_describes_every_file(self):
        stats = rc.write_crate(self.bundle, name="Test Bundle",
                               date_published="2026-10-21")
        self.assertEqual(stats["files"], 3)
        crate = json.loads((self.bundle / "ro-crate-metadata.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(crate["@context"], rc.CRATE_CONTEXT)
        by_id = {e["@id"]: e for e in crate["@graph"]}
        self.assertEqual(by_id["./"]["@type"], "Dataset")
        self.assertEqual(by_id["./"]["datePublished"], "2026-10-21")
        self.assertEqual(
            {p["@id"] for p in by_id["./"]["hasPart"]},
            {"bagit.txt", "data/notes.txt", "data/wiki/index.md"})
        f = by_id["data/wiki/index.md"]
        self.assertEqual(f["@type"], "File")
        self.assertEqual(f["contentSize"], "8")
        self.assertEqual(f["encodingFormat"], "text/markdown")
        import hashlib
        self.assertEqual(
            f["sha256"],
            hashlib.sha256(b"# Index\n").hexdigest())
        descriptor = by_id["ro-crate-metadata.json"]
        self.assertEqual(descriptor["about"], {"@id": "./"})

    def test_generation_is_byte_deterministic(self):
        rc.write_crate(self.bundle, name="B")
        first = (self.bundle / "ro-crate-metadata.json").read_bytes()
        rc.write_crate(self.bundle, name="B")
        second = (self.bundle / "ro-crate-metadata.json").read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(rc.check_crate(self.bundle), [])

    def test_sidecar_and_caches_are_not_described(self):
        (self.bundle / "__pycache__").mkdir()
        (self.bundle / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        rc.write_crate(self.bundle)
        crate = json.loads((self.bundle / "ro-crate-metadata.json")
                           .read_text(encoding="utf-8"))
        ids = [e["@id"] for e in crate["@graph"]]
        self.assertNotIn("__pycache__/x.pyc", ids)
        self.assertEqual(ids.count("ro-crate-metadata.json"), 1)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bundle = make_bundle(self._tmp.name)
        rc.write_crate(self.bundle, name="B")

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_sidecar(self):
        (self.bundle / "ro-crate-metadata.json").unlink()
        problems = rc.check_crate(self.bundle)
        self.assertTrue(any("missing" in p for p in problems))

    def test_tampered_payload_byte_caught(self):
        (self.bundle / "data" / "notes.txt").write_text(
            "PLAIN NOTES\n", encoding="utf-8")
        problems = rc.check_crate(self.bundle)
        self.assertTrue(any("notes.txt" in p for p in problems),
                        problems)

    def test_added_and_removed_files_caught(self):
        (self.bundle / "extra.md").write_text("x\n", encoding="utf-8")
        problems = rc.check_crate(self.bundle)
        self.assertTrue(any("extra.md" in p for p in problems),
                        problems)
        (self.bundle / "extra.md").unlink()
        (self.bundle / "data" / "notes.txt").unlink()
        problems = rc.check_crate(self.bundle)
        self.assertTrue(any("notes.txt" in p for p in problems),
                        problems)

    def test_hand_edit_caught(self):
        sidecar = self.bundle / "ro-crate-metadata.json"
        crate = json.loads(sidecar.read_text(encoding="utf-8"))
        for entity in crate["@graph"]:
            if entity["@id"] == "data/notes.txt":
                entity["sha256"] = "0" * 64
        sidecar.write_text(json.dumps(crate, indent=2),
                           encoding="utf-8")
        problems = rc.check_crate(self.bundle)
        self.assertTrue(any("notes.txt" in p for p in problems),
                        problems)

    def test_cli_build_and_check(self):
        fresh = Path(self._tmp.name) / "fresh"
        fresh.mkdir()
        (fresh / "a.md").write_text("# A\n", encoding="utf-8")
        self.assertEqual(rc.main(["build", str(fresh)]), 0)
        self.assertEqual(rc.main(["check", str(fresh)]), 0)
        (fresh / "a.md").write_text("# A tampered\n",
                                     encoding="utf-8")
        self.assertEqual(rc.main(["check", str(fresh)]), 1)


class BagIntegrationTest(unittest.TestCase):
    def test_bag_still_validates_with_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / "wiki").mkdir(parents=True)
            (root / "wiki" / "index.md").write_text("# I\n",
                                                    encoding="utf-8")
            (root / "evaluation").mkdir()
            (root / "evaluation" / "r.jsonl").write_text(
                '{"a": 1}\n', encoding="utf-8")
            (root / "AGENTS.md").write_text("schema\n",
                                            encoding="utf-8")
            dest = Path(tmp) / "bag1"
            bag.pack(root, dest, "compiled",
                     bagging_date="2026-10-21", scan=False)
            rc.write_crate(dest, name="Bag with crate",
                           date_published="2026-10-21")
            self.assertEqual(rc.check_crate(dest), [])
            ok, problems, _stats = bag.validate(dest)
            self.assertTrue(ok, problems)
            crate = json.loads((dest / "ro-crate-metadata.json")
                               .read_text(encoding="utf-8"))
            ids = {e["@id"] for e in crate["@graph"]}
            self.assertIn("data/wiki/index.md", ids)
            self.assertIn("bagit.txt", ids)


if __name__ == "__main__":
    unittest.main()
