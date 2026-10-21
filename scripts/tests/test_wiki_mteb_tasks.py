"""Tests for scripts/wiki_mteb_tasks.py — the MTEB-style
task definitions for the benchmark pack (Marathon Round 6,
lane BA, item 3): the shipped register validates; it
carries exactly the stated coverage (one Reranking task,
one Retrieval task covering both jpn-Jpan and kor-Hang);
register defects (duplicate id, a non-MTEB task type, a
malformed eval_langs code, a licence null without its
note, a lost coverage half) are each caught; and the
register holds definitions only — no dataset paths, no
golden-set references. No dataset is downloaded.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_mteb_tasks", HERE.parents[1] / "wiki_mteb_tasks.py")
mteb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mteb)

ROOT = HERE.parents[2]


def shipped():
    return mteb.load_register(ROOT / "evaluation" / "mteb-tasks.json")


class RegisterTest(unittest.TestCase):
    def test_shipped_register_validates_clean(self):
        data = shipped()
        self.assertEqual(mteb.check_register(data), [])
        ids = [t["id"] for t in data["tasks"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_coverage_is_reranking_plus_ja_ko_retrieval(self):
        data = shipped()
        types = [t["type"] for t in data["tasks"]]
        self.assertIn("Reranking", types)
        retrieval = [t for t in data["tasks"]
                     if t["type"] == "Retrieval"]
        self.assertTrue(retrieval)
        langs = set()
        for t in retrieval:
            langs.update(t["eval_langs"])
        self.assertIn("jpn-Jpan", langs)
        self.assertIn("kor-Hang", langs)
        for t in data["tasks"]:
            self.assertIsNone(t["licence"])
            self.assertTrue(t["licence_note"])

    def test_register_holds_no_dataset_or_golden_paths(self):
        data = shipped()
        for task in data["tasks"]:
            self.assertNotIn("golden", json.dumps(task))
            self.assertTrue(task["reference"].startswith("http"))

    def test_register_defects_are_caught(self):
        data = shipped()

        dup = copy.deepcopy(data)
        dup["tasks"].append(copy.deepcopy(dup["tasks"][0]))
        self.assertTrue(any("duplicate" in p
                            for p in mteb.check_register(dup)))

        bad_type = copy.deepcopy(data)
        bad_type["tasks"][0]["type"] = "Searching"
        self.assertTrue(any("task type" in p
                            for p in mteb.check_register(bad_type)))

        bad_lang = copy.deepcopy(data)
        bad_lang["tasks"][1]["eval_langs"] = ["ja", "ko"]
        self.assertTrue(any("eval_langs" in p
                            for p in mteb.check_register(bad_lang)))

        silent = copy.deepcopy(data)
        silent["tasks"][0]["licence_note"] = ""
        self.assertTrue(any("licence_note" in p
                            for p in mteb.check_register(silent)))

        no_ja_ko = copy.deepcopy(data)
        no_ja_ko["tasks"][1]["eval_langs"] = ["eng-Latn"]
        self.assertTrue(any("kor-Hang" in p
                            for p in mteb.check_register(no_ja_ko)))

    def test_cli_list_show_check(self):
        self.assertEqual(mteb.main(["list"]), 0)
        self.assertEqual(mteb.main(["show", "scidocs-reranking"]), 0)
        self.assertEqual(
            mteb.main(["show", "mrtydi-ja-ko-retrieval"]), 0)
        self.assertEqual(mteb.main(["show", "no-such-task"]), 2)
        self.assertEqual(mteb.main(["check"]), 0)


if __name__ == "__main__":
    unittest.main()
