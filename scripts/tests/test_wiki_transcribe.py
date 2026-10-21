"""Tests for scripts/wiki_transcribe.py (Marathon R3 TB5 row 8,
Handy/Buzz pattern): with an injected fake engine a transcript
source file with provenance frontmatter is produced; with NO
engine configured the seam refuses cleanly (no downloads, no
network); non-media files are unsupported. Run:
python3 -m unittest scripts.tests.test_wiki_transcribe
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_transcribe as wtr  # noqa: E402


def fake_engine(path):
    return "hello from the recording"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="trans-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = self.root / "out"

    def touch(self, name):
        p = self.root / name
        p.write_bytes(b"fake-media")
        return p


class TranscribeTests(Fixture):
    def test_fake_engine_produces_transcript_with_provenance(self):
        rec = wtr.transcribe(self.touch("lecture.mp3"), self.out,
                             engine=fake_engine, engine_name="fake",
                             transcribed_at="2026-10-21")
        self.assertEqual(rec["status"], "transcribed")
        text = Path(rec["transcript"]).read_text(encoding="utf-8")
        self.assertIn("origin: offline-transcription", text)
        self.assertIn("engine: fake", text)
        self.assertIn("hello from the recording", text)

    def test_unconfigured_engine_refuses_cleanly(self):
        rec = wtr.transcribe(self.touch("lecture.mp4"), self.out,
                             engine=None)
        self.assertEqual(rec["status"], "refused")
        self.assertIn("offline-only", rec["note"])
        self.assertFalse(self.out.exists())

    def test_non_media_unsupported(self):
        rec = wtr.transcribe(self.touch("notes.md"), self.out,
                             engine=fake_engine)
        self.assertEqual(rec["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
