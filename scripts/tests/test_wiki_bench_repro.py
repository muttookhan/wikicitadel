#!/usr/bin/env python3
"""Tests for wiki_bench_repro.compare + wiki_scale_bench.synthetic_docs."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_bench_repro  # noqa: E402
import wiki_bench_synth  # noqa: E402
import wiki_scale_bench  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent


def pack(coverage, mrr, hit=1.0):
    return {"results": {"bm25": {
        "citation_coverage": {"@1": 0.0, "@3": 0.0, "@5": 0.0, "@10": coverage},
        "mrr_must_cite": mrr, "hit_rate_topk": hit}}}


class TestCompare(unittest.TestCase):
    def test_regression_detected(self):
        reg, _ = wiki_bench_repro.compare(pack(0.9, 0.7), pack(0.8, 0.7))
        self.assertTrue(any("coverage@10" in r for r in reg))

    def test_improvement_not_regression(self):
        reg, imp = wiki_bench_repro.compare(pack(0.8, 0.6), pack(0.9, 0.6))
        self.assertEqual(reg, [])
        self.assertTrue(imp)

    def test_equal_is_neither(self):
        reg, imp = wiki_bench_repro.compare(pack(0.9, 0.7), pack(0.9, 0.7))
        self.assertEqual((reg, imp), ([], []))


class TestSynthetic(unittest.TestCase):
    def test_deterministic_and_sized(self):
        a = wiki_scale_bench.synthetic_docs(50)
        b = wiki_scale_bench.synthetic_docs(50)
        self.assertEqual(len(a), 50)
        self.assertEqual([t for _p, t in a], [t for _p, t in b])

    def test_probe_vocabulary_planted(self):
        docs = wiki_scale_bench.synthetic_docs(26)
        self.assertIn("alpha", docs[0][1])
        self.assertIn("alpha", docs[25][1])


class TestRunPackOnSyntheticRoot(unittest.TestCase):
    """Marathon R2 Lane G: run_pack over an alternate root
    (the wiki_bench_synth corpus), with a pinned HEAD."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench-repro-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in ("wiki_bench_repro.py", "wiki_benchmark.py",
                     "wiki_search.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        self.manifest = wiki_bench_synth.write_corpus(self.tmp)

    def test_pack_over_synthetic_root(self):
        pack, out = wiki_bench_repro.run_pack(
            "synth-test", root=self.tmp, git_head="f" * 40,
            corpus_kind="synthetic", note="test fixture run")
        self.assertTrue(out.is_file())
        self.assertEqual(out.parent,
                         self.tmp / "evaluation" / "results")
        self.assertEqual(pack["environment"]["git_head"], "f" * 40)
        self.assertEqual(pack["environment"]["corpus_docs"],
                         self.manifest["corpus_docs"])
        self.assertEqual(pack["recipe"]["questions_count"],
                         self.manifest["questions_count"])
        self.assertEqual(pack["recipe"]["questions_sha256"],
                         self.manifest["questions_sha256"])
        self.assertEqual(pack["corpus_kind"], "synthetic")
        self.assertEqual(pack["note"], "test fixture run")
        self.assertEqual(set(pack["results"]),
                         {"bm25", "hybrid", "hindsight"})
        for engine, res in pack["results"].items():
            self.assertEqual(res["citation_coverage"]["@10"], 1.0,
                             engine)
        # The pack is its own regression gate: no regressions
        # against itself, via the tool's own compare path.
        reg, imp = wiki_bench_repro.compare(pack, pack)
        self.assertEqual((reg, imp), ([], []))
        # And the file on disk parses back to the same results.
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["results"], pack["results"])

    def test_root_without_bench_scripts_is_a_named_error(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        with self.assertRaises(SystemExit):
            wiki_bench_repro.run_pack("nope", root=bare)


if __name__ == "__main__":
    unittest.main()
