"""Tests for scripts/wiki_crud_tasks.py + the definitions
register evaluation/crud-lifecycle-tasks.json (Marathon R8
lane BB; CRUD-RAG taxonomy, definitions only).

Pins: shipped register valid with all four classes; Create/Read/
Update expect answer, Delete expects abstain; a register missing
a class or with a wrong verdict is flagged; the register does
not reference the golden set or battery as data.

Run: python3 -m unittest scripts.tests.test_wiki_crud_tasks
"""
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_crud_tasks", SCRIPTS / "wiki_crud_tasks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()
REGISTER = json.loads((ROOT / "evaluation" /
                     "crud-lifecycle-tasks.json").read_text(
                         encoding="utf-8"))


class RegisterTests(unittest.TestCase):
    def test_shipped_register_valid(self):
        self.assertEqual(MOD.check_register(REGISTER), [])

    def test_four_classes_and_verdicts(self):
        by = {t["crud_class"]: t for t in REGISTER["tasks"]}
        self.assertEqual(set(by), {"Create", "Read", "Update",
                                   "Delete"})
        self.assertEqual(by["Delete"]["expected_verdict"],
                         "abstain")
        self.assertEqual(by["Update"]["expected_verdict"],
                         "answer")

    def test_missing_class_flagged(self):
        broken = dict(REGISTER, tasks=[
            t for t in REGISTER["tasks"]
            if t["crud_class"] != "Delete"])
        self.assertTrue(MOD.check_register(broken))

    def test_wrong_verdict_flagged(self):
        broken = json.loads(json.dumps(REGISTER))
        for t in broken["tasks"]:
            if t["crud_class"] == "Delete":
                t["expected_verdict"] = "answer"
        self.assertTrue(MOD.check_register(broken))

    def test_definitions_only_no_task_data(self):
        # Definitions only: no task carries an actual question,
        # answer or dataset payload.
        for t in REGISTER["tasks"]:
            self.assertNotIn("question_id", t)
            self.assertNotIn("expected_answer", t)
            self.assertNotIn("answer", t)


if __name__ == "__main__":
    unittest.main()
