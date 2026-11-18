#!/usr/bin/env python3
"""Tests for scripts/wiki_compact_proposal.py (Marathon R3
TA5; ReMe compaction as a recoverable PROPOSAL).

Pins, on a FIXTURE tree in a temp dir:
  - a long page yields a proposal whose draft keeps the
    heading skeleton, a trimmed extract per section and the
    sections' wikilinks, and is shorter than the original;
  - the manifest records the original's sha256 and the
    restore path states the original was not modified;
  - PROPOSAL-ONLY: writing the artefact leaves the target
    page byte-identical;
  - a short page is refused without --force; a missing page
    is refused;
  - trim_extract cuts at a sentence boundary within budget.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module(root):
    spec = importlib.util.spec_from_file_location(
        "wiki_compact_proposal",
        root / "scripts" / "wiki_compact_proposal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LONG_PAGE = "---\ntitle: Long Fable\ntype: concept\n---\n\n# Long Fable\n\n" + \
    "\n".join(
        f"## Section {i}\n\n"
        + " ".join([f"Sentence {i}-{j} of the fable holds a small "
                    f"fact worth keeping." for j in range(6)])
        + f"\n\nSee [[target-{i}]] for more.\n"
        for i in range(8))


class TestCompactProposal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="compact-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_compact_proposal.py",
                    scripts / "wiki_compact_proposal.py")
        (self.tmp / "wiki" / "concepts").mkdir(parents=True)
        self.page = self.tmp / "wiki" / "concepts" / "long-fable.md"
        self.page.write_text(LONG_PAGE, encoding="utf-8")
        (self.tmp / "wiki" / "concepts" / "short.md").write_text(
            "# Short\n\nTiny.\n", encoding="utf-8")
        self.mod = load_module(self.tmp)

    def test_draft_keeps_skeleton_links_and_shrinks(self):
        m = self.mod.build_proposal(
            self.tmp, "wiki/concepts/long-fable.md", min_lines=10)
        draft = m["draft_text"]
        for i in range(8):
            self.assertIn(f"## Section {i}", draft)
            self.assertIn(f"[[target-{i}]]", draft)
        self.assertLess(m["draft"]["chars"], m["original"]["chars"])
        self.assertEqual(m["original"]["sha256"],
                         hashlib.sha256(
                             LONG_PAGE.encode()).hexdigest())

    def test_restore_path_and_original_untouched(self):
        before = self.page.read_bytes()
        m = self.mod.build_proposal(
            self.tmp, "wiki/concepts/long-fable.md", min_lines=10)
        md_path, json_path = self.mod.write_proposal(self.tmp, m)
        self.assertIn("NOT modified", m["restore_path"])
        self.assertIn("git history", m["restore_path"])
        artefact = md_path.read_text(encoding="utf-8")
        self.assertIn("## Restore path", artefact)
        self.assertIn("## Draft compaction", artefact)
        self.assertEqual(self.page.read_bytes(), before)

    def test_short_and_missing_refused(self):
        with self.assertRaises(ValueError):
            self.mod.build_proposal(self.tmp, "wiki/concepts/short.md")
        with self.assertRaises(ValueError):
            self.mod.build_proposal(self.tmp, "wiki/concepts/nope.md")
        m = self.mod.build_proposal(self.tmp, "wiki/concepts/short.md",
                                    force=True)
        self.assertEqual(m["target"], "wiki/concepts/short.md")

    def test_trim_extract_sentence_boundary(self):
        lines = ["One short sentence. " + "Filler " * 60 + "tail."]
        out = self.mod.trim_extract(lines)
        self.assertLessEqual(len(out), self.mod.SECTION_CHARS + 4)
        self.assertTrue(out.startswith("One short sentence."))


if __name__ == "__main__":
    unittest.main()
