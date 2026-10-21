"""Tests for scripts/wiki_beir_eval.py — the BEIR zero-shot
eval slice: the shipped register validates; register defects
(duplicate id, missing field, a licence null without its
note, a layout pointing into this tree) are each caught;
the loader reads both qrels shapes from a fixture task
directory the test writes itself; the metrics are exact on
hand-computed fixtures, deterministic under score ties, and
the BEIR dict-of-dicts run shape is accepted. No dataset is
downloaded — fixture data only.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_beir_eval", HERE.parents[1] / "wiki_beir_eval.py")
beir = importlib.util.module_from_spec(spec)
spec.loader.exec_module(beir)

ROOT = HERE.parents[2]


def make_task_dir(tmp, qrels_shape="tsv"):
    d = Path(tmp) / "task"
    d.mkdir(parents=True)
    (d / "corpus.jsonl").write_text(
        '{"_id": "d1", "title": "One", "text": "alpha"}\n'
        '{"_id": "d2", "title": "Two", "text": "beta"}\n'
        '{"_id": "d3", "title": "Three", "text": "gamma"}\n',
        encoding="utf-8")
    (d / "queries.jsonl").write_text(
        '{"_id": "q1", "text": "alpha?"}\n', encoding="utf-8")
    if qrels_shape == "tsv":
        (d / "qrels").mkdir()
        (d / "qrels" / "test.tsv").write_text(
            "query-id\tcorpus-id\tscore\nq1\td1\t2\nq1\td2\t1\n",
            encoding="utf-8")
    else:
        (d / "qrels.jsonl").write_text(
            '{"query-id": "q1", "corpus-id": "d1", "score": 2}\n'
            '{"query-id": "q1", "corpus-id": "d2", "score": 1}\n',
            encoding="utf-8")
    return d


class RegisterTest(unittest.TestCase):
    def test_shipped_register_validates_clean(self):
        data = beir.load_register(ROOT / "evaluation" / "beir-tasks.json")
        self.assertEqual(beir.check_register(data), [])
        ids = [t["id"] for t in data["tasks"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 2)
        kinds = {t["task_type"] for t in data["tasks"]}
        self.assertGreaterEqual(len(kinds), 2)

    def test_shipped_register_holds_no_dataset_paths(self):
        data = beir.load_register(ROOT / "evaluation" / "beir-tasks.json")
        for task in data["tasks"]:
            self.assertNotIn("golden", json.dumps(task))

    def test_register_defects_are_caught(self):
        data = beir.load_register(ROOT / "evaluation" / "beir-tasks.json")

        dup = copy.deepcopy(data)
        dup["tasks"].append(copy.deepcopy(dup["tasks"][0]))
        self.assertTrue(any("duplicate" in p
                            for p in beir.check_register(dup)))

        missing = copy.deepcopy(data)
        del missing["tasks"][0]["homepage"]
        self.assertTrue(any("homepage" in p
                            for p in beir.check_register(missing)))

        silent = copy.deepcopy(data)
        silent["tasks"][0]["licence_note"] = ""
        self.assertTrue(any("licence_note" in p
                            for p in beir.check_register(silent)))

        in_tree = copy.deepcopy(data)
        in_tree["tasks"][0]["layout"]["corpus_file"] = \
            "evaluation/beir/corpus.jsonl"
        self.assertTrue(any("into this tree" in p
                            for p in beir.check_register(in_tree)))

    def test_cli_list_and_show(self):
        self.assertEqual(beir.main(["list"]), 0)
        self.assertEqual(beir.main(["show", "nfcorpus"]), 0)
        self.assertEqual(beir.main(["show", "no-such-task"]), 2)
        self.assertEqual(beir.main(["check"]), 0)


class LoaderTest(unittest.TestCase):
    def test_loader_reads_tsv_and_jsonl_qrels_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = beir.load_task_directory(make_task_dir(tmp, "tsv"))
        with tempfile.TemporaryDirectory() as tmp:
            b = beir.load_task_directory(make_task_dir(tmp, "jsonl"))
        self.assertEqual(a["qrels"], {"q1": {"d1": 2, "d2": 1}})
        self.assertEqual(a["qrels"], b["qrels"])
        self.assertEqual(a["corpus"]["d2"]["text"], "beta")
        self.assertEqual(a["queries"], {"q1": "alpha?"})

    def test_loader_without_qrels_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "task"
            d.mkdir()
            (d / "corpus.jsonl").write_text("", encoding="utf-8")
            (d / "queries.jsonl").write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                beir.load_task_directory(d)


class MetricsTest(unittest.TestCase):
    QRELS = {"q1": {"d1": 2, "d2": 1}}

    def test_perfect_run_scores_one(self):
        result = beir.evaluate_run({"q1": {"d1": 0.9, "d2": 0.8}},
                                   self.QRELS, k=10)
        self.assertEqual(result["ndcg"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["mrr"], 1.0)

    def test_reversed_run_metrics_are_hand_computed(self):
        # Run order d2 (rel 1), d1 (rel 2): DCG = 1/log2(2) +
        # 3/log2(3); IDCG = 3/log2(2) + 1/log2(3).
        import math
        want = (1 / math.log2(2) + 3 / math.log2(3)) / \
               (3 / math.log2(2) + 1 / math.log2(3))
        result = beir.evaluate_run({"q1": ["d2", "d1"]},
                                   self.QRELS, k=10)
        self.assertAlmostEqual(result["ndcg"], round(want, 4),
                               places=4)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["mrr"], 1.0)  # d2 is relevant

    def test_k_truncates_and_miss_scores_zero(self):
        result = beir.evaluate_run({"q1": ["d3", "d2", "d1"]},
                                   self.QRELS, k=1)
        self.assertEqual(result["ndcg"], 0.0)
        self.assertEqual(result["recall"], 0.0)
        self.assertEqual(result["mrr"], 0.0)
        empty = beir.evaluate_run({}, self.QRELS, k=10)
        self.assertEqual(empty["ndcg"], 0.0)

    def test_ties_break_deterministically(self):
        run = {"q1": {"d2": 0.5, "d1": 0.5}}  # tie -> id asc: d1 first
        first = beir.evaluate_run(run, self.QRELS, k=10)
        second = beir.evaluate_run(run, self.QRELS, k=10)
        self.assertEqual(first, second)
        self.assertEqual(first["ndcg"], 1.0)

    def test_cli_evaluate_over_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_task_dir(tmp)
            run_file = Path(tmp) / "run.json"
            run_file.write_text(json.dumps({"q1": {"d1": 0.9,
                                                    "d2": 0.8}}),
                                encoding="utf-8")
            self.assertEqual(
                beir.main(["evaluate", "--task-dir", str(d),
                           "--run", str(run_file)]), 0)


if __name__ == "__main__":
    unittest.main()
