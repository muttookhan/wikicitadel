# test_wiki_synthetic_slices.py — unit tests for
# scripts/wiki_synthetic_slices.py (Wave 3, synthetic
# evaluation slices).
#
# The lane's one unforgivable outcome is contamination of the
# hand-written instruments, so the suite leads with the
# namespace/contamination guards, then the per-class derivation
# rules on a tiny fixture corpus, then determinism
# (regeneration byte-identity over the REAL corpus), then the
# on-disk slice's consistency. The full scorer is NOT run here
# (it ranks the whole corpus per question); the bakeoff suite
# covers the instruments it composes.
#
# Run: python3 -m unittest
#      scripts.tests.test_wiki_synthetic_slices -v
# (from the repo root)

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import wiki_synthetic_slices as ss  # noqa: E402


def write_page(root, name, title, body, extra_fm=""):
    p = root / "wiki" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\ntitle: {title}\n{extra_fm}---\n\n{body}\n",
        encoding="utf-8")
    return p


def fixture_tree(tmp):
    root = Path(tmp)
    (root / "wiki").mkdir(parents=True)
    write_page(root, "alpha.md", "Alpha Widget",
               "## Setup Steps\n\n"
               "The setup steps configure the alpha widget "
               "with the sprocket drive for every calibration "
               "run in the workshop.\n\n"
               "See [[beta]].\n")
    write_page(root, "beta.md", "Beta Widget",
               "## Details\n\n"
               "Beta links onward to [[gamma]] for the "
               "shared results.\n")
    write_page(root, "gamma.md", "Gamma Widget",
               "## Results Table\n\n"
               "The gamma results table records the final "
               "sprocket tension values measured.\n\n"
               "## Notes\n\n"
               "Gamma notes mention the sprocket tension "
               "audit trail in full detail here.\n")
    write_page(root, "delta.md", "Delta Table",
               "## Data\n\n"
               "| Item | Count |\n|---|---|\n"
               "| Sprockets | 420 |\n| Gears | 170 |\n")
    write_page(root, "epsilon.md", "Epsilon Table",
               "## Data\n\n"
               "| Item | Count |\n|---|---|\n"
               "| Sprockets | 990 |\n| Bolts | 310 |\n")
    write_page(root, "claimed.md", "Claimed Rig",
               "A page carrying a frontmatter claim about "
               "the calibration rig and its schedule.\n",
               extra_fm="claim: The calibration rig runs "
                        "every Tuesday morning.\n")
    write_page(root, "dated.md", "Dated Sprocket Guide",
               "A guide created on the ingest date about "
               "sprockets and their maintenance.\n",
               extra_fm="created: 2026-01-05\n")
    (root / "wiki" / "log.md").write_text(
        "# Log\n\n"
        "## [2026-01-05] ingest | Dated Sprocket Guide\n",
        encoding="utf-8")
    return root


class TestClassBuilders(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fixture_tree(self._tmp.name)
        self.pages = ss.load_pages(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_title_class(self):
        kept, _ex = ss.q_title(self.pages)
        titles = {q["must_cite"][0] for q in kept}
        self.assertIn("wiki/alpha.md", titles)

    def test_heading_class_answerable(self):
        kept, _ex = ss.q_heading(self.pages)
        anchors = {(q["derivation"]["anchor"]["page"],
                    q["derivation"]["anchor"]["heading"])
                   for q in kept}
        self.assertIn(("wiki/alpha.md", "Setup Steps"),
                      anchors)

    def test_claim_class(self):
        kept, _ex = ss.q_claim(self.pages)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["must_cite"],
                         ["wiki/claimed.md"])
        self.assertIn("calibration rig",
                      kept[0]["expected_answer"])

    def test_multihop_bridge(self):
        kept, _ex = ss.q_multihop(self.pages)
        chains = [q["derivation"]["anchor"]["chain"]
                  for q in kept]
        self.assertIn(["wiki/alpha.md", "wiki/beta.md",
                       "wiki/gamma.md"], chains)
        for q in kept:
            self.assertNotIn(q["must_cite"][0],
                             q["derivation"]["anchor"]["chain"]
                             [:1])

    def test_table_ambiguous_key_excluded(self):
        kept, ex = ss.q_table(self.pages)
        keys = {q["derivation"]["anchor"]["row_key"]
                for q in kept}
        # 'Sprockets' + 'Count' occurs on two pages ->
        # excluded; 'Gears' is unique to delta.
        self.assertNotIn("Sprockets", keys)
        self.assertIn("Gears", keys)
        self.assertGreaterEqual(
            ex.get("table-key-column-pair-on-another-page",
                   0), 1)

    def test_episodic_unique_match(self):
        log = (self.root / "wiki" / "log.md").read_text(
            encoding="utf-8")
        kept, _ex = ss.q_episodic(self.pages, log)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["must_cite"],
                         ["wiki/dated.md"])

    def test_zeromatch_nonces_absent(self):
        vocab = ss.corpus_vocab(self.pages)
        for n in ss.NONCES:
            self.assertNotIn(n, vocab)
        kept, _ex = ss.q_zeromatch(self.pages, vocab)
        self.assertTrue(kept)
        for q in kept:
            self.assertTrue(q["expected_abstain"])
            self.assertEqual(q["must_cite"], [])


class TestContaminationGuards(unittest.TestCase):
    """The protected hand-written instruments must be
    untouched and un-collided-with."""

    def test_protected_files_present_and_parse(self):
        # WikiCitadel has never carried two of the protected
        # instruments (conflict-questions.jsonl and the
        # abstention battery) — a standing gap on the record;
        # the guard covers the instruments this tree holds.
        present = [name for name in ss.PROTECTED
                   if (ROOT / "evaluation" / name).is_file()]
        self.assertIn("golden-questions.jsonl", present)
        for name in present:
            p = ROOT / "evaluation" / name
            self.assertTrue(p.is_file(), name)

    def test_slice_ids_disjoint_from_handwritten(self):
        slice_path = ROOT / "evaluation" / \
            "synthetic-questions.jsonl"
        self.assertTrue(slice_path.is_file(),
                        "run the generator first")
        _hdr, rows = ss.load_slice(slice_path)
        pids = ss.protected_ids()
        self.assertTrue(pids)
        for r in rows:
            self.assertNotIn(r["id"], pids)
            self.assertTrue(r["id"].startswith("SQ-"))
            self.assertTrue(r["synthetic"])
            self.assertIn("derivation", r)

    def test_protected_hashes_stable_under_generation(self):
        # Generating a slice must not modify any protected
        # file: hash, generate to a temp path, hash again.
        def hashes():
            out = {}
            for name in ss.PROTECTED:
                p = ROOT / "evaluation" / name
                if p.is_file():
                    out[name] = hashlib.sha256(
                        p.read_bytes()).hexdigest()
            return out
        before = hashes()
        with tempfile.TemporaryDirectory() as tmp:
            ss.cmd_generate(str(Path(tmp) / "out.jsonl"))
        self.assertEqual(before, hashes())


class TestDeterminism(unittest.TestCase):

    def test_regeneration_byte_identical_real_corpus(self):
        pages = ss.load_pages()
        log_text = (ROOT / "wiki" / "log.md").read_text(
            encoding="utf-8")
        rows1, ex1 = ss.build_slice(pages, log_text, "")
        rows2, ex2 = ss.build_slice(pages, log_text, "")
        t1, _ = ss.slice_text(rows1, ex1, "HEADX", len(pages))
        t2, _ = ss.slice_text(rows2, ex2, "HEADX", len(pages))
        self.assertEqual(t1, t2)
        self.assertGreater(len(rows1), 50)

    def test_slice_header_declares_bias_and_synthetic(self):
        slice_path = ROOT / "evaluation" / \
            "synthetic-questions.jsonl"
        header, rows = ss.load_slice(slice_path)
        self.assertTrue(header["synthetic"])
        self.assertIn("must never be pooled",
                      header["bias_statement"])
        self.assertEqual(
            sum(header["counts"].values()), len(rows))


if __name__ == "__main__":
    unittest.main()
