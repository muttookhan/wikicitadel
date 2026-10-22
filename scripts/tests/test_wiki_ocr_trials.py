#!/usr/bin/env python3
"""Tests for scripts/wiki_ocr_trials.py — the W4 OCR engine
trials harness: registry/licence discipline, probe honesty
(an unavailable engine doors with a verbatim blocker and the
trial records it, never fakes a run), the CER/WER metrics,
the synthetic fixtures (deterministic, ground truth by
construction), the template-matcher reference recognizer run
end to end, the preocr stage adapter, and the hand-off into
the real OCR verification queue's fold.

Run:  python3 -m unittest scripts.tests.test_wiki_ocr_trials
"""
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_ocr_trials as t  # noqa: E402
import wiki_preocr as wpo  # noqa: E402
import wiki_ocr_queue as woq  # noqa: E402


def scratch_dir(case):
    """Temp dir that survives tonight's /tmp write fault: the
    house tempfile route first, a workspace scratch second."""
    try:
        td = tempfile.TemporaryDirectory()
        case.addCleanup(td.cleanup)
        return Path(td.name)
    except OSError:
        root = Path.home() / "workspace" / ".tmp-ocr-tests"
        root.mkdir(parents=True, exist_ok=True)
        case.addCleanup(shutil.rmtree, root, True)
        return root


class RegistryTests(unittest.TestCase):
    def test_every_engine_carries_licence_and_route(self):
        allowed = {"adapt-with-credit", "native"}
        for name, spec in t.ENGINES.items():
            self.assertTrue(spec["licence"], name)
            route = spec["licence_route"]
            self.assertTrue(
                route in allowed or route.startswith("ideas-only"),
                f"{name}: unexpected route {route!r}")

    def test_ocrmypdf_is_ideas_only(self):
        self.assertTrue(t.ENGINES["ocrmypdf"]["licence_route"]
                        .startswith("ideas-only"))
        self.assertEqual(t.ENGINES["ocrmypdf"]["licence"],
                         "MPL-2.0")

    def test_matcher_is_labelled_reference_not_candidate(self):
        self.assertIn("reference", t.ENGINES["template-matcher"]
                      ["role"])

    def test_probe_record_shape(self):
        for name in t.ENGINES:
            rec = t.probe_engine(name)
            probe = rec["probe"]
            self.assertIn("available", probe)
            if probe["available"]:
                self.assertIsNone(probe["blocker"])
            else:
                self.assertIsInstance(probe["blocker"], str)
                self.assertTrue(probe["blocker"].strip(),
                                f"{name}: empty blocker")

    def test_unavailable_engine_doors_never_fakes(self):
        doored = [n for n in t.ENGINES
                  if not t.probe_engine(n)["probe"]["available"]]
        self.assertTrue(doored, "expected some doored engines "
                                "in this environment")
        img, truth = t.render_fixture("clean")
        for name in doored:
            run = t.trial_run(name, img, truth, "clean")
            self.assertFalse(run["available"], name)
            self.assertTrue(run["blocker"], name)
            self.assertNotIn("text", run, name)


class MetricTests(unittest.TestCase):
    def test_edit_distance(self):
        self.assertEqual(t.edit_distance("kitten", "sitting"), 3)
        self.assertEqual(t.edit_distance("", "abc"), 3)
        self.assertEqual(t.edit_distance("same", "same"), 0)

    def test_cer_wer_known_cases(self):
        self.assertEqual(t.char_error_rate("abc", "abc"), 0.0)
        self.assertEqual(t.char_error_rate("abc", "axc"),
                         round(1 / 3, 4))
        self.assertEqual(t.word_error_rate("a b c", "a x c"),
                         round(1 / 3, 4))

    def test_align_words(self):
        pairs = t.align_words(["a", "b", "c"], ["a", "x", "c"])
        self.assertEqual([p[2] for p in pairs],
                         [True, False, True])

    def test_confidence_report_separates_wrong_words(self):
        words = [{"text": "right", "confidence": 0.99},
                 {"text": "wrng", "confidence": 0.55}]
        rep = t.confidence_report("right wrong", words)
        self.assertEqual(rep["mean_confidence_correct_words"],
                         0.99)
        self.assertEqual(rep["mean_confidence_wrong_words"],
                         0.55)
        self.assertEqual(rep["share_below_queue_threshold"], 0.5)
        self.assertEqual(rep["queue_threshold"],
                         woq.CONFIDENCE_THRESHOLD)


class FixtureTests(unittest.TestCase):
    def test_fixtures_deterministic(self):
        for kind in t.FIXTURE_KINDS:
            a, truth_a = t.render_fixture(kind)
            b, truth_b = t.render_fixture(kind)
            self.assertEqual(truth_a, t.FIXTURE_TEXT)
            self.assertEqual(truth_a, truth_b)
            ba, bb = io.BytesIO(), io.BytesIO()
            a.save(ba, format="PNG")
            b.save(bb, format="PNG")
            self.assertEqual(ba.getvalue(), bb.getvalue(), kind)

    def test_ground_truth_is_the_stated_text(self):
        self.assertIn("Muttoo Home School", t.FIXTURE_TEXT)
        for ch in set(t.FIXTURE_TEXT) - {"\n", " "}:
            self.assertIn(ch, t.CHARSET)


class MatcherTests(unittest.TestCase):
    def test_clean_fixture_recognised_with_confidences(self):
        img, truth = t.render_fixture("clean")
        run = t.trial_run("template-matcher", img, truth, "clean")
        self.assertTrue(run["available"])
        self.assertLess(run["cer"], 0.10)
        self.assertGreater(run["confidence"]["word_accuracy"],
                           0.7)
        for w in run["words"]:
            self.assertGreaterEqual(w["confidence"], 0.0)
            self.assertLessEqual(w["confidence"], 1.0)

    def test_serif_fixture_degrades_honestly(self):
        clean, truth = t.render_fixture("clean")
        serif, _ = t.render_fixture("serif")
        acc_clean = t.trial_run("template-matcher", clean, truth,
                                "clean")["confidence"][
                                    "word_accuracy"]
        acc_serif = t.trial_run("template-matcher", serif, truth,
                                "serif")["confidence"][
                                    "word_accuracy"]
        self.assertLess(acc_serif, acc_clean)


class StageAndQueueTests(unittest.TestCase):
    def test_preocr_stage_runs_matcher(self):
        root = scratch_dir(self)
        img, _truth = t.render_fixture("clean")
        p = root / "page.png"
        img.save(p)
        rec = wpo.route(p, stage=t.make_preocr_stage(
            "template-matcher"))
        self.assertIn(rec["status"],
                      ("ocr-done", "needs-verification"))
        self.assertGreater(rec["confidence"], 0.5)

    def test_preocr_stage_doors_unavailable_engine(self):
        doored = next(n for n in t.ENGINES
                      if not t.probe_engine(n)["probe"]
                      ["available"])
        stage = t.make_preocr_stage(doored)
        with self.assertRaises(wpo.OcrUnavailable) as ctx:
            stage(Path("whatever.png"))
        self.assertIn(doored, str(ctx.exception))

    def test_trial_units_fold_in_the_real_queue(self):
        root = scratch_dir(self)
        (root / "raw").mkdir(parents=True)
        (root / "raw" / "scan.pdf").write_bytes(b"%PDF-fake")
        img, _truth = t.render_fixture("clean")
        run = t.trial_run("template-matcher", img, _truth,
                          "clean")
        units = [{"unit": f"w{i}", "locator": {"fixture":
                                              "clean"},
                  "text": w["text"],
                  "confidence": w["confidence"]}
                 for i, w in enumerate(run["words"][:6])]
        units.append({"unit": "wx", "locator": {},
                      "confidence": "unknown"})
        woq.append_event(root, {
            "kind": "enqueued", "id": "ocr-0001",
            "date": "2026-10-22", "source": "raw/scan.pdf",
            "method": "ocr", "tool": "template-matcher",
            "sensitivity": "unclassified", "note": "test",
            "units": units})
        entries, _d = woq.fold(woq.read_events(root))
        states = {u["unit"]: u["state"]
                  for u in entries[0]["units"].values()}
        self.assertEqual(states["wx"], "open")
        for u in units[:-1]:
            expected = ("above-threshold"
                        if u["confidence"]
                        >= woq.CONFIDENCE_THRESHOLD else "open")
            self.assertEqual(states[u["unit"]], expected)


class MeasurePdfTests(unittest.TestCase):
    def test_ocr_0001_pdf_measured_read_only(self):
        pdf = REPO / "raw" / "sources" / \
            "2026-10-13-grok-homeschool-plan.pdf"
        if not pdf.is_file():
            self.skipTest("ocr-0001 source not on disk")
        before = pdf.stat().st_mtime_ns
        result = t.measure_pdf(pdf)
        self.assertEqual(pdf.stat().st_mtime_ns, before)
        self.assertTrue(result["read_only"])
        if result.get("extractor", "").startswith("pypdf"):
            self.assertEqual(result["pages"], 27)
            self.assertEqual(result["total_chars"], 27894)
            self.assertEqual(result["image_xobjects"], 0)
        elif result.get("extractor"):
            self.assertGreater(result["total_chars"], 0)
        else:
            self.skipTest("no PDF extractor available here")


if __name__ == "__main__":
    unittest.main()
