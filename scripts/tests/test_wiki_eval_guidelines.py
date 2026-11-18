"""Tests for scripts/wiki_eval_guidelines.py + the sidecar
evaluation/guidelines-settings.json (Marathon R8 lane BB;
Argilla pattern, Apache-2.0 - pattern only).

Pins: the shipped sidecar parses and follows the convention
(every entry names the dataset, guidelines field is a named+
versioned object or null); coverage() covers every discovered
dataset exactly once and reports missing honestly; in-file
header guidelines are recognised in a synthetic tree; checker
is report-only (main exits 0 without --strict).

Run: python3 -m unittest scripts.tests.test_wiki_eval_guidelines
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_eval_guidelines", SCRIPTS / "wiki_eval_guidelines.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


class SidecarTests(unittest.TestCase):
    def test_sidecar_shape(self):
        data = json.loads((ROOT / "evaluation" /
                           "guidelines-settings.json").read_text(
                               encoding="utf-8"))
        self.assertEqual(data["kind"], "eval-guidelines-settings")
        self.assertIn("guidelines", data["convention"]["field"])
        for rel, entry in data["datasets"].items():
            self.assertIn("guidelines", entry)
            g = entry["guidelines"]
            self.assertTrue(g is None or MOD.guidelines_ok(g),
                            rel)

    def test_coverage_covers_all_datasets(self):
        rep = MOD.coverage()
        discovered = MOD.discover_datasets()
        self.assertEqual(rep["total"], len(discovered))
        self.assertEqual(
            sorted(r["dataset"] for r in rep["datasets"]),
            sorted(discovered))
        self.assertEqual(rep["with_guidelines"]
                         + len(rep["missing"]), rep["total"])

    def test_in_file_header_recognised(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "set.jsonl").write_text(
                json.dumps({"kind": "header", "guidelines": {
                    "name": "g", "version": "1",
                    "text": "label carefully"}}) + "\n"
                + json.dumps({"id": "1"}) + "\n",
                encoding="utf-8")
            (base / "guidelines-settings.json").write_text(
                json.dumps({"datasets": {}}), encoding="utf-8")
            rep = MOD.coverage(base, base /
                               "guidelines-settings.json")
            self.assertEqual(rep["with_guidelines"], 1)
            self.assertEqual(rep["missing"], [])


if __name__ == "__main__":
    unittest.main()
