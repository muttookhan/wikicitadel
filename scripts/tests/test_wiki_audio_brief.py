#!/usr/bin/env python3
"""Tests for scripts/wiki_audio_brief.py."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_audio_brief  # noqa: E402

PAGE = """---
title: "A Test Page"
type: concept
---

# A Test Page

This page explains **the thing** with a [[linked-page|link]] and a
claim. ^[cite: raw/sources/x.md#L1-L2]

- a list item with `code`
"""


class TestAudioBrief(unittest.TestCase):
    def test_script_shape(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "page.md"
            p.write_text(PAGE, encoding="utf-8")
            script = wiki_audio_brief.script_for_page(p)
        self.assertIn("Audio briefing script: A Test Page", script)
        self.assertIn("Script only — no audio is generated.", script)
        self.assertIn("[END]", script)

    def test_markdown_stripped(self):
        script_lines = wiki_audio_brief.strip_markdown(
            wiki_audio_brief.drop_frontmatter(PAGE))
        joined = " ".join(script_lines)
        self.assertNotIn("**", joined)
        self.assertNotIn("^[cite:", joined)
        self.assertNotIn("[[", joined)
        self.assertIn("the thing", joined)
        self.assertIn("link", joined)

    def test_duration_stated(self):
        script = wiki_audio_brief.build_script("T", ["one two three four"])
        self.assertIn("Estimated duration:", script)
        self.assertIn("150 wpm", script)


if __name__ == "__main__":
    unittest.main()
