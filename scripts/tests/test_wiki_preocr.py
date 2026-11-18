"""Tests for scripts/wiki_preocr.py (Marathon R3 TB5 row 7,
OCRmyPDF pattern): text sources pass through; scanned sources are
routed through the injected fake stage BEFORE conversion and the
confidence is recorded; an absent engine is a clean refusal, never
a silent pass-through. Run:
python3 -m unittest scripts.tests.test_wiki_preocr
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_preocr as wpo  # noqa: E402


def good_stage(path):
    return ("extracted text", 0.95)


def weak_stage(path):
    return ("fuzzy text", 0.42)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocr-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def touch(self, name):
        p = self.root / name
        p.write_bytes(b"%PDF-fake")
        return p


class RouteTests(Fixture):
    def test_text_native_passes_through(self):
        rec = wpo.route(self.touch("note.md"), stage=good_stage)
        self.assertEqual(rec["status"], "text-native")
        self.assertEqual(rec["confidence"], 1.0)

    def test_scanned_high_confidence_done(self):
        rec = wpo.route(self.touch("scan.png"), stage=good_stage)
        self.assertEqual(rec["status"], "ocr-done")
        self.assertAlmostEqual(rec["confidence"], 0.95)

    def test_scanned_low_confidence_queued_for_verification(self):
        rec = wpo.route(self.touch("scan.pdf"), stage=weak_stage)
        self.assertEqual(rec["status"], "needs-verification")
        self.assertAlmostEqual(rec["confidence"], 0.42)

    def test_absent_engine_is_clean_refusal(self):
        def absent(path):
            raise wpo.OcrUnavailable(wpo.REFUSAL)
        rec = wpo.route(self.touch("scan.tif"), stage=absent)
        self.assertEqual(rec["status"], "refused")
        self.assertIn("NOT passed through silently", rec["note"])


if __name__ == "__main__":
    unittest.main()
