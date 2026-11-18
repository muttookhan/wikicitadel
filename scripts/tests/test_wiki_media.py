#!/usr/bin/env python3
"""Tests for scripts/wiki_media.py — temp fixture trees only."""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_media as wm  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "raw" / "img").mkdir(parents=True)
        (self.root / "wiki" / "concepts").mkdir(parents=True)
        (self.root / "raw" / "img" / "diagram.svg").write_text(
            "<svg/>\n", encoding="utf-8")
        (self.root / "raw" / "img" / "photo.png").write_bytes(b"\x89PNG")
        (self.root / "raw" / "talk.mp3").write_bytes(b"ID3")
        (self.root / "raw" / "clip.mp4").write_bytes(b"\x00")
        (self.root / "raw" / "notes.md").write_text(
            "not media\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, name, text):
        p = self.root / "wiki" / "concepts" / name
        p.write_text(text, encoding="utf-8")
        return p


class TestInventory(Fixture):
    def test_inventory_classifies_by_extension(self):
        inv = wm.inventory_media(self.root)
        by_kind = {}
        for item in inv:
            by_kind.setdefault(item["kind"], []).append(item["path"])
        self.assertEqual(by_kind["image"],
                         ["raw/img/diagram.svg", "raw/img/photo.png"])
        self.assertEqual(by_kind["audio"], ["raw/talk.mp3"])
        self.assertEqual(by_kind["video"], ["raw/clip.mp4"])

    def test_inventory_deterministic_order(self):
        self.assertEqual(wm.inventory_media(self.root),
                         wm.inventory_media(self.root))


class TestCheckPages(Fixture):
    def test_good_reference_no_violation(self):
        self.page("a.md", "# A\n\n![Diagram](../../raw/img/diagram.svg)\n")
        self.assertEqual(wm.check_pages(self.root), [])

    def test_missing_file_reported_kind_path_line_only(self):
        self.page("a.md", "# A\n\n![Diagram](../../raw/img/nope.svg)\n")
        v = wm.check_pages(self.root)
        self.assertEqual(v, [{"kind": "missing-file",
                              "path": "wiki/concepts/a.md", "line": 3}])

    def test_missing_alt_reported(self):
        self.page("a.md", "![](../../raw/img/photo.png)\n")
        v = wm.check_pages(self.root)
        self.assertEqual([x["kind"] for x in v], ["missing-alt"])

    def test_adjacent_italic_caption_satisfies_alt(self):
        self.page("a.md", "![](../../raw/img/photo.png)\n"
                          "*A caption line.*\n")
        self.assertEqual(wm.check_pages(self.root), [])

    def test_adjacent_caption_prefix_satisfies_alt(self):
        self.page("a.md", "![](../../raw/img/photo.png)\n"
                          "Caption: A caption line.\n")
        self.assertEqual(wm.check_pages(self.root), [])

    def test_caption_not_adjacent_does_not_satisfy(self):
        self.page("a.md", "![](../../raw/img/photo.png)\n\n"
                          "*A caption line, one line too late.*\n")
        v = wm.check_pages(self.root)
        self.assertEqual([x["kind"] for x in v], ["missing-alt"])

    def test_external_target_skipped_for_file_but_alt_still_checked(self):
        self.page("a.md", "![Alt](https://example.invalid/x.png)\n")
        self.assertEqual(wm.check_pages(self.root), [])

    def test_root_relative_and_rooted_targets_resolve(self):
        self.page("a.md", "![D](raw/img/diagram.svg)\n\n"
                          "![D](/raw/img/photo.png)\n")
        self.assertEqual(wm.check_pages(self.root), [])

    def test_report_is_deterministic_and_counts(self):
        self.page("a.md", "![](../../raw/img/nope.png)\n")
        text1, v1 = wm.build_report(self.root)
        text2, v2 = wm.build_report(self.root)
        self.assertEqual(text1, text2)
        self.assertIn("image 2, audio 1, video 1, total 4", text1)
        # Both kinds on the same line, kind+path+line only.
        self.assertIn("missing-alt: wiki/concepts/a.md:1", text1)
        self.assertIn("missing-file: wiki/concepts/a.md:1", text1)
        self.assertEqual(len(v1), 2)

    def test_main_exit_codes(self):
        self.page("a.md", "![D](../../raw/img/diagram.svg)\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wm.main(["--root", str(self.root)]), 0)
        self.page("b.md", "![](../../raw/img/photo.png)\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wm.main(["--root", str(self.root)]), 1)

    def test_report_only_writes_nothing(self):
        before = sorted(str(p.relative_to(self.root))
                        for p in self.root.rglob("*") if p.is_file())
        with redirect_stdout(io.StringIO()):
            wm.main(["--root", str(self.root), "--list-media"])
        after = sorted(str(p.relative_to(self.root))
                       for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
