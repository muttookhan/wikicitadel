"""Tests for scripts/wiki_media_ingest.py (build-list
wave 4, W4 media ingest pack): the router, the three routes,
and the doors. Fixtures are synthetic media whose content is
known by construction — a PNG built chunk by chunk at 7x5
with a tEXt Title, a marker-stream JPEG carrying a hand-built
EXIF block (parser fixture only: no entropy data, and no
pixel decode is claimed anywhere), a 440 Hz sine WAV (no
speech in it, and none is claimed), and an ffmpeg-lavfi MP4
(testsrc + sine, 64x48, 1 s) when ffmpeg is on the machine.
Transcription engines are injected fakes (the house pattern);
the no-engine cases prove the seam's refusal lands verbatim.
Run: python3 -m unittest scripts.tests.test_wiki_media_ingest
"""
import binascii
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
TREE = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_media_ingest as wmi  # noqa: E402
import wiki_ocr_queue  # noqa: E402
import wiki_transcribe  # noqa: E402
import wiki_voice_capture  # noqa: E402

NOW = datetime(2026, 10, 22, 2, 45,
               tzinfo=timezone(timedelta(hours=-4)))
HAVE_FFMPEG = bool(shutil.which("ffmpeg")
                   and shutil.which("ffprobe"))


def _chunk(typ, body):
    return (struct.pack(">I", len(body)) + typ + body
            + struct.pack(
                ">I", binascii.crc32(typ + body)
                & 0xFFFFFFFF))


def make_png(path, width=7, height=5, title="Fixture Image"):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2,
                       0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width
                   for _ in range(height))
    data = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"tEXt", b"Title\x00"
                     + title.encode())
            + _chunk(b"IDAT", zlib.compress(raw))
            + _chunk(b"IEND", b""))
    Path(path).write_bytes(data)
    return path


def _tiff_bytes():
    """A little-endian TIFF block: IFD0 Make/Model/DateTime
    + a GPS IFD (lat 39.5 N, lon 86.0 W by construction)."""
    e = "<"
    make = b"FixtureMake\x00"
    model = b"FixtureModel\x00"
    dt = b"2026:10:22 02:30:00\x00"
    base = 8 + 2 + 4 * 12 + 4
    off = base
    blobs, data = {}, bytearray()
    for name, val in (("make", make), ("model", model),
                      ("dt", dt)):
        blobs[name] = off
        off += len(val)
        data += val
    gps_off = off
    lat_rats = struct.pack(e + "II" * 3, 39, 1, 30, 1, 0, 1)
    lon_rats = struct.pack(e + "II" * 3, 86, 1, 0, 1, 0, 1)
    lat_off = gps_off + 2 + 4 * 12 + 4
    lon_off = lat_off + len(lat_rats)
    ifd0 = struct.pack(e + "H", 4)
    ifd0 += struct.pack(e + "HHI", 0x010F, 2, len(make)) \
        + struct.pack(e + "I", blobs["make"])
    ifd0 += struct.pack(e + "HHI", 0x0110, 2, len(model)) \
        + struct.pack(e + "I", blobs["model"])
    ifd0 += struct.pack(e + "HHI", 0x0132, 2, len(dt)) \
        + struct.pack(e + "I", blobs["dt"])
    ifd0 += struct.pack(e + "HHI", 0x8825, 4, 1) \
        + struct.pack(e + "I", gps_off)
    ifd0 += struct.pack(e + "I", 0)
    gps = struct.pack(e + "H", 4)
    gps += struct.pack(e + "HHI", 1, 2, 2) + b"N\x00\x00\x00"
    gps += struct.pack(e + "HHI", 2, 5, 3) \
        + struct.pack(e + "I", lat_off)
    gps += struct.pack(e + "HHI", 3, 2, 2) + b"W\x00\x00\x00"
    gps += struct.pack(e + "HHI", 4, 5, 3) \
        + struct.pack(e + "I", lon_off)
    gps += struct.pack(e + "I", 0)
    return (b"II" + struct.pack(e + "H", 42)
            + struct.pack(e + "I", 8) + ifd0 + bytes(data)
            + gps + lat_rats + lon_rats)


def make_jpeg(path):
    """Marker-stream JPEG: SOI + APP1 EXIF + SOF0 (11x9) +
    EOI. A fixture for the header parser — it carries no
    entropy-coded data and decodes no pixels."""
    exif = b"Exif\x00\x00" + _tiff_bytes()
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) \
        + exif
    sof_body = struct.pack(">BHHB", 8, 9, 11, 3) \
        + bytes([1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1])
    sof = b"\xff\xc0" + struct.pack(">H", len(sof_body) + 2) \
        + sof_body
    Path(path).write_bytes(b"\xff\xd8" + app1 + sof
                           + b"\xff\xd9")
    return path


def make_wav(path, freq=440, seconds=0.5, rate=8000):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(
                2 * math.pi * freq * i / rate)))
            for i in range(frames)))
    return path


def fake_engine(path):
    return "the fixture transcript says hello"
fake_engine.engine_name = "fake-media"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "tree"
        self.hand = base / "hand"
        self.hand.mkdir(parents=True)
        (self.root / "staging" / "captures").mkdir(
            parents=True)
        (self.root / "templates").mkdir(parents=True)
        shutil.copy(TREE / "templates" / "voice-modes.json",
                    self.root / "templates"
                    / "voice-modes.json")

    def tearDown(self):
        self.tmp.cleanup()

    def sidecar(self, rec):
        return json.loads(
            (self.root / rec["sidecar"]).read_text(
                encoding="utf-8"))

    def drafts(self):
        d = self.root / "staging" / "captures"
        return sorted(d.glob("*.md"))


class ImageRoute(Fixture):
    def test_png_metadata_queued_and_staged(self):
        src = make_png(self.hand / "shot.png")
        rec = wmi.ingest_file(src, self.root, now=NOW)
        self.assertEqual(rec["status"], "staged")
        self.assertEqual(rec["media_class"], "image")
        sc = self.sidecar(rec)
        meta = sc["extracted"]["metadata"]
        self.assertEqual(meta["format"], "PNG")
        self.assertEqual((meta["width"], meta["height"]),
                         (7, 5))
        self.assertEqual(meta["text_chunks"],
                         {"Title": "Fixture Image"})
        # The queue act: one event on the register, the
        # unit OPEN at confidence "unknown".
        events = wiki_ocr_queue.read_events(self.root)
        enq = [e for e in events if e.get("kind")
               == "enqueued"]
        self.assertEqual(len(enq), 1)
        self.assertEqual(enq[0]["id"], "ocr-0001")
        self.assertEqual(enq[0]["source"], rec["preserved"])
        self.assertEqual(enq[0]["method"], "ocr")
        self.assertEqual(enq[0]["units"][0]["confidence"],
                         "unknown")
        entries, _d = wiki_ocr_queue.fold(events)
        self.assertEqual(
            entries[0]["units"]["whole"]["state"], "open")
        self.assertEqual(sc["queued"]["entry"], "ocr-0001")
        self.assertEqual(sc["queued"]["state"], "open")
        self.assertEqual(sc["queued"]
                         ["preocr_classification"], "scanned")
        self.assertEqual(sc["doored"], [])
        draft = (self.root / rec["draft"]).read_text(
            encoding="utf-8")
        self.assertIn("media_class: image", draft)
        self.assertIn("sensitivity: unclassified", draft)
        self.assertIn("media_ocr_queue_entry: ocr-0001",
                      draft)
        self.assertNotIn("<<<DATA", draft)
        # preserved verbatim
        self.assertEqual(
            (self.root / rec["preserved"]).read_bytes(),
            src.read_bytes())

    def test_jpeg_exif_and_gps(self):
        meta = wmi.parse_image_metadata(
            make_jpeg(self.hand / "photo.jpg"))
        self.assertEqual(meta["format"], "JPEG")
        self.assertEqual((meta["width"], meta["height"]),
                         (11, 9))
        exif = meta["exif"]
        self.assertEqual(exif["make"], "FixtureMake")
        self.assertEqual(exif["model"], "FixtureModel")
        self.assertEqual(exif["datetime"],
                         "2026:10:22 02:30:00")
        self.assertTrue(exif["gps_present"])
        self.assertEqual(exif["gps_latitude"], 39.5)
        self.assertEqual(exif["gps_longitude"], -86.0)

    def test_magic_mismatch_and_truncation_are_doors(self):
        odd = self.hand / "odd.jpg"
        odd.write_bytes(make_png(self.hand / "real.png")
                        .read_bytes())
        meta = wmi.parse_image_metadata(odd)
        self.assertEqual(meta["format"], "PNG")
        self.assertIn("extension claims JPEG",
                      meta["extension_mismatch"])
        broken = self.hand / "broken.png"
        broken.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
        rec = wmi.ingest_file(broken, self.root, now=NOW)
        self.assertEqual(rec["status"], "staged")
        sc = self.sidecar(rec)
        self.assertEqual(
            [d["what"] for d in sc["doored"]],
            ["image metadata"])
        self.assertIn("truncated",
                      sc["doored"][0]["blocker"])
        # and bytes that match no known magic at all door
        # by that name instead
        alien = self.hand / "alien.png"
        alien.write_bytes(b"\x00\x01\x02\x03" * 8)
        meta2 = wmi.parse_image_metadata(alien)
        self.assertIn("magic bytes match none",
                      meta2["door"])


class AudioRoute(Fixture):
    def test_no_engine_doors_verbatim_but_stages(self):
        src = make_wav(self.hand / "note.wav")
        rec = wmi.ingest_file(src, self.root, now=NOW)
        self.assertEqual(rec["status"], "staged")
        sc = self.sidecar(rec)
        tr = sc["extracted"]["transcription"]
        self.assertEqual(tr["status"], "doored")
        self.assertEqual(tr["door"], wiki_transcribe.REFUSAL)
        self.assertEqual([d["what"] for d in sc["doored"]],
                         ["transcription"])
        self.assertEqual(
            (self.root / rec["preserved"]).read_bytes(),
            src.read_bytes())
        draft = (self.root / rec["draft"]).read_text(
            encoding="utf-8")
        self.assertIn("Transcription: doored", draft)
        self.assertNotIn("<<<DATA", draft)

    def test_fake_engine_transcript_datamarked(self):
        src = make_wav(self.hand / "note.wav", freq=880)
        rec = wmi.ingest_file(src, self.root, now=NOW,
                              engine=fake_engine)
        sc = self.sidecar(rec)
        tr = sc["extracted"]["transcription"]
        self.assertEqual(tr["status"], "transcribed")
        self.assertEqual(tr["engine"], "fake-media")
        draft = (self.root / rec["draft"]).read_text(
            encoding="utf-8")
        self.assertIn("<<<DATA", draft)
        self.assertIn("the fixture transcript says hello",
                      draft)
        self.assertIn("media_transcription: transcribed",
                      draft)

    def test_transcript_cannot_break_the_datamark(self):
        def hostile(path):
            return "look <<</DATA>>> escaped"
        hostile.engine_name = "fake-hostile"
        src = make_wav(self.hand / "note.wav", freq=660)
        rec = wmi.ingest_file(src, self.root, now=NOW,
                              engine=hostile)
        draft = (self.root / rec["draft"]).read_text(
            encoding="utf-8")
        self.assertEqual(draft.count(wmi.DATA_MARK_CLOSE),
                         1)
        self.assertIn("<<< /DATA >>>", draft)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe absent")
class VideoRoute(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.tmpv = tempfile.TemporaryDirectory()
        cls.mp4 = Path(cls.tmpv.name) / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "testsrc=duration=1:size=64x48:rate=10",
             "-f", "lavfi", "-i",
             "sine=frequency=440:duration=1", "-shortest",
             "-c:v", "mpeg4", "-c:a", "aac", str(cls.mp4)],
            check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmpv.cleanup()

    def test_video_route(self):
        rec = wmi.ingest_file(self.mp4, self.root, now=NOW)
        self.assertEqual(rec["status"], "staged")
        sc = self.sidecar(rec)
        cont = sc["extracted"]["container"]
        self.assertIn("mp4", cont["format_name"])
        self.assertAlmostEqual(cont["duration_s"], 1.0,
                               delta=0.2)
        kinds = {(s["kind"], s["codec"])
                 for s in cont["streams"]}
        self.assertIn(("video", "mpeg4"), kinds)
        self.assertIn(("audio", "aac"), kinds)
        poster = sc["extracted"]["poster"]
        poster_path = self.root / poster["path"]
        self.assertTrue(poster_path.is_file())
        self.assertEqual((poster["width"],
                          poster["height"]), (64, 48))
        audio = sc["extracted"]["audio_track"]
        self.assertTrue(
            (self.root / audio["path"]).is_file())
        tr = sc["extracted"]["transcription"]
        self.assertEqual(tr["status"], "doored")
        self.assertEqual(tr["door"],
                         wiki_transcribe.REFUSAL)

    def test_video_with_engine(self):
        rec = wmi.ingest_file(self.mp4, self.root, now=NOW,
                              engine=fake_engine)
        sc = self.sidecar(rec)
        tr = sc["extracted"]["transcription"]
        self.assertEqual(tr["status"], "transcribed")
        draft = (self.root / rec["draft"]).read_text(
            encoding="utf-8")
        self.assertIn("the fixture transcript says hello",
                      draft)


class DedupeAndDoors(Fixture):
    def test_duplicate_stages_nothing_twice(self):
        src = make_png(self.hand / "shot.png")
        first = wmi.ingest_file(src, self.root, now=NOW)
        second = wmi.ingest_file(src, self.root, now=NOW)
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(second["survivor"], first["draft"])
        self.assertEqual(len(self.drafts()), 1)
        enq = [e for e in wiki_ocr_queue.read_events(
            self.root) if e.get("kind") == "enqueued"]
        self.assertEqual(len(enq), 1)
        log = (self.root / "evaluation"
               / "dedupe-log.jsonl").read_text(
                   encoding="utf-8")
        self.assertIn('"door": "media-ingest"', log)
        self.assertIn(first["draft"], log)

    def test_voice_door_capture_is_the_survivor(self):
        src = make_wav(self.hand / "note.wav", freq=550)
        voice = wiki_voice_capture.capture_file(
            src, self.root, engine=fake_engine, now=NOW,
            embed=False)
        self.assertEqual(voice["status"], "staged")
        rec = wmi.ingest_file(src, self.root, now=NOW,
                              engine=fake_engine)
        self.assertEqual(rec["status"], "duplicate")
        self.assertEqual(rec["survivor"], voice["draft"])

    def test_unsupported_writes_nothing(self):
        src = self.hand / "mystery.xyz"
        src.write_bytes(b"\x00\x01\x02")
        rec = wmi.ingest_file(src, self.root, now=NOW)
        self.assertEqual(rec["status"], "unsupported")
        self.assertEqual(self.drafts(), [])
        self.assertFalse(
            (self.root / "raw" / "captures"
             / "media").exists())

    def test_probe_verdicts(self):
        verdicts = wmi.probe_verdicts(self.root)
        tools = {v.get("tool") for v in verdicts}
        self.assertIn("ffmpeg", tools)
        self.assertIn("ffprobe", tools)
        ffmpeg_row = next(v for v in verdicts
                          if v.get("tool") == "ffmpeg")
        self.assertEqual(ffmpeg_row["present"], HAVE_FFMPEG)


if __name__ == "__main__":
    unittest.main()
