#!/usr/bin/env python3
"""Tests for scripts/wiki_bench_synth.py (Marathon R2 Lane G):
the deterministic synthetic bench corpus generator.

Pins: byte-identical regeneration, corpus/question shape,
must_cite targets that exist, and per-page focus words that
occur on exactly one page (the property that makes the
satellite questions' answers known by construction).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_bench_synth  # noqa: E402


def tree_bytes(root):
    root = Path(root)
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


class TestSynth(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench-synth-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_write_is_byte_identical_across_runs(self):
        a, b = self.tmp / "a", self.tmp / "b"
        wiki_bench_synth.write_corpus(a)
        wiki_bench_synth.write_corpus(b)
        self.assertEqual(tree_bytes(a), tree_bytes(b))

    def test_shape_and_manifest(self):
        files, questions, manifest = wiki_bench_synth.build_corpus()
        self.assertEqual(manifest["corpus_docs"], len(files))
        self.assertEqual(manifest["corpus_docs"], 6 * 8)
        self.assertEqual(manifest["questions_count"], len(questions))
        self.assertEqual(len(questions), 12)
        ids = [q["id"] for q in questions]
        self.assertEqual(len(ids), len(set(ids)))

    def test_must_cite_targets_exist(self):
        files, questions, _m = wiki_bench_synth.build_corpus()
        for q in questions:
            for target in q["must_cite"]:
                self.assertIn(target, files)

    def test_focus_words_are_owned_by_one_page(self):
        # A focus word may be *named* elsewhere only inside a
        # wikilink stem (the hub's and predecessor's link
        # lists); the page that owns it carries it in its
        # title and body, with the strictly highest count.
        files, _q, _m = wiki_bench_synth.build_corpus()
        for slug, _core, focus_words in wiki_bench_synth.TOPICS:
            for fw in focus_words[:7]:
                counts = {rel: text.count(fw)
                          for rel, text in files.items()}
                owner = f"wiki/{slug}/{slug}-{fw}.md"
                self.assertGreaterEqual(counts[owner], 3, fw)
                for rel, n in counts.items():
                    if rel != owner:
                        self.assertLess(n, counts[owner],
                                        f"{fw} in {rel}")

    def test_topic_vocabularies_are_disjoint(self):
        seen = {}
        for slug, core, focus_words in wiki_bench_synth.TOPICS:
            for word in list(core) + list(focus_words):
                self.assertNotIn(word, seen, word)
                seen[word] = slug

    def test_seed_changes_filler_but_not_shape(self):
        f1, q1, _ = wiki_bench_synth.build_corpus(seed=1)
        f2, q2, _ = wiki_bench_synth.build_corpus(seed=2)
        self.assertEqual(set(f1), set(f2))
        self.assertEqual([q["must_cite"] for q in q1],
                         [q["must_cite"] for q in q2])
        self.assertNotEqual(f1, f2)

    def test_pages_carry_synthetic_frontmatter(self):
        files, _q, _m = wiki_bench_synth.build_corpus()
        for text in files.values():
            self.assertIn("tags: [synthetic,", text)
            self.assertIn("type: concept", text)


if __name__ == "__main__":
    unittest.main()
