#!/usr/bin/env python3
"""Tests for scripts/wiki_annotate.py — the annotation layer
over raw (wave-3 item C1).

Pins:
  - locator resolution: a line range must be in bounds; a quote
    anchor must be found (inside the given range, when both are
    given); a quote alone derives its line range; an
    unresolvable locator is REFUSED and nothing is written;
  - mark discipline: only a bare highlight may carry no text;
    kinds are closed; sources must live under raw/ and exist;
    ids sequence per source; every mark records by: owner;
  - addressing: a compiled page accounts for a mark by citing
    ^[mark: <source>#<id>] — the unaddressed report (the lint
    lanes' owner-marks eye) lists only actionable
    (correction/question) marks no page accounts for, and a
    reference inside a fenced code block does not count;
  - guard interaction: in a fixture git repo, staging a NEW
    annotations file under raw/ passes the real memory guard
    (an addition is neither a modification nor a deletion),
    while staging a modification of the source itself is a
    provenance breach (exit 2) — the contrast the layer rests
    on.

Builds a fixture wiki in a temp dir (the real scripts copied
in, so ROOT resolves to the fixture) and drives the library
plus the CLI.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SOURCE_REL = "raw/sources/fixture-source.md"
SOURCE_LINES = [
    "Fixture source title",
    "The vault holds fifty-one files in total.",
    "A slower correct corpus beats a faster incorrect one.",
    "Nothing here is canonical yet.",
]


def load_module(name, script_path):
    spec = importlib.util.spec_from_file_location(name, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnnotateFixture(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "raw" / "sources").mkdir(parents=True)
        (self.root / "wiki" / "sources").mkdir(parents=True)
        for name in ("wiki_annotate.py", "wiki_cite_lock.py",
                     "wiki_observe.py", "wiki_validate.py",
                     "wiki_memory_guard.py"):
            shutil.copy(SCRIPTS / name, self.root / "scripts" / name)
        (self.root / SOURCE_REL).write_text(
            "\n".join(SOURCE_LINES) + "\n", encoding="utf-8")
        self.ann = load_module("wiki_annotate_fixture",
                               self.root / "scripts" / "wiki_annotate.py")
        self.script = self.root / "scripts" / "wiki_annotate.py"

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True, text=True)

    def write_page(self, name, body, sources=None):
        fm = ["---", "title: Fixture page", "type: source",
              "created: 2030-10-20", "updated: 2030-10-20"]
        if sources:
            fm.append("sources:")
            fm += [f"  - {s}" for s in sources]
        fm.append("---")
        (self.root / "wiki" / "sources" / name).write_text(
            "\n".join(fm) + "\n\n" + body + "\n", encoding="utf-8")


class LocatorTests(AnnotateFixture):

    def test_add_by_line_range(self):
        mark = self.ann.add_mark(SOURCE_REL, "note", "a note",
                                 start=2, end=3, created="2030-10-20")
        self.assertEqual(mark["id"], "a0001")
        self.assertEqual(mark["by"], "owner")
        self.assertEqual(mark["locator"]["start"], 2)
        self.assertEqual(mark["locator"]["end"], 3)
        on_disk = self.ann.read_marks(SOURCE_REL)
        self.assertEqual(len(on_disk), 1)
        self.assertEqual(on_disk[0]["text"], "a note")

    def test_add_by_quote_derives_range(self):
        mark = self.ann.add_mark(SOURCE_REL, "highlight",
                                 quote="fifty-one files")
        self.assertEqual((mark["locator"]["start"],
                          mark["locator"]["end"]), (2, 2))

    def test_quote_spanning_lines(self):
        mark = self.ann.add_mark(
            SOURCE_REL, "highlight",
            quote="in total. A slower correct corpus")
        self.assertEqual((mark["locator"]["start"],
                          mark["locator"]["end"]), (2, 3))

    def test_quote_normalisation_smart_quotes(self):
        (self.root / "raw" / "sources" / "smart.md").write_text(
            "He said \u201cverbatim or nothing\u201d twice.\n",
            encoding="utf-8")
        mark = self.ann.add_mark("raw/sources/smart.md", "highlight",
                                 quote='"verbatim or nothing"')
        self.assertEqual(mark["locator"]["start"], 1)

    def test_out_of_bounds_range_refused(self):
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "note", "x", start=99)
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "note", "x", start=0)
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "note", "x",
                              start=3, end=2)
        self.assertEqual(self.ann.read_marks(SOURCE_REL), [])

    def test_missing_quote_refused(self):
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "note", "x",
                              quote="words that are not there")
        self.assertEqual(self.ann.read_marks(SOURCE_REL), [])

    def test_quote_outside_given_range_refused(self):
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "note", "x",
                              start=4, end=4,
                              quote="fifty-one files")

    def test_quote_inside_given_range_accepted(self):
        mark = self.ann.add_mark(SOURCE_REL, "note", "x",
                                 start=1, end=4,
                                 quote="fifty-one files")
        self.assertEqual((mark["locator"]["start"],
                          mark["locator"]["end"]), (1, 4))

    def test_no_locator_refused(self):
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "note", "x")

    def test_cli_refusal_exit_code(self):
        proc = self.cli("add", SOURCE_REL, "--kind", "note",
                        "--text", "x", "--lines", "99")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("refused", proc.stdout)
        proc = self.cli("add", SOURCE_REL, "--kind", "note",
                        "--text", "x", "--lines", "2")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("a0001", proc.stdout)


class MarkDisciplineTests(AnnotateFixture):

    def test_empty_text_only_for_highlight(self):
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "correction", "", start=1)
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "question", "  ", start=1)
        mark = self.ann.add_mark(SOURCE_REL, "highlight", "", start=1)
        self.assertEqual(mark["text"], "")

    def test_bad_kind_refused(self):
        with self.assertRaises(ValueError):
            self.ann.add_mark(SOURCE_REL, "bookmark", "x", start=1)

    def test_source_must_be_under_raw_and_exist(self):
        with self.assertRaises(ValueError):
            self.ann.add_mark("wiki/sources/x.md", "note", "x",
                              start=1)
        with self.assertRaises(ValueError):
            self.ann.add_mark("raw/sources/absent.md", "note", "x",
                              start=1)

    def test_ids_sequence_per_source(self):
        self.ann.add_mark(SOURCE_REL, "highlight", start=1)
        m2 = self.ann.add_mark(SOURCE_REL, "highlight", start=2)
        self.assertEqual(m2["id"], "a0002")
        (self.root / "raw" / "sources" / "other.md").write_text(
            "other\n", encoding="utf-8")
        m = self.ann.add_mark("raw/sources/other.md", "highlight",
                              start=1)
        self.assertEqual(m["id"], "a0001")

    def test_annotations_file_sits_beside_source(self):
        self.ann.add_mark(SOURCE_REL, "highlight", start=1)
        self.assertTrue(
            (self.root / (SOURCE_REL + ".annotations.jsonl")).is_file())
        # The source itself is byte-identical — never written to.
        self.assertEqual(
            (self.root / SOURCE_REL).read_text(encoding="utf-8"),
            "\n".join(SOURCE_LINES) + "\n")


class AddressingTests(AnnotateFixture):

    def setUp(self):
        super().setUp()
        self.ann.add_mark(SOURCE_REL, "correction",
                          "fifty-one should be fifty-two",
                          quote="fifty-one files",
                          created="2030-10-20")
        self.ann.add_mark(SOURCE_REL, "question",
                          "is this count as of when?",
                          start=2, created="2030-10-20")
        self.ann.add_mark(SOURCE_REL, "highlight",
                          quote="slower correct corpus",
                          created="2030-10-20")

    def test_unaddressed_lists_actionable_only(self):
        rows = self.ann.unaddressed_marks()
        self.assertEqual([r["mark"]["id"] for r in rows],
                         ["a0001", "a0002"])
        self.assertEqual(rows[0]["pages"], [])

    def test_page_accounts_by_mark_reference(self):
        self.write_page(
            "fixture-source.md",
            "The count is fifty-two, corrected per the owner's"
            f" mark. ^[mark: {SOURCE_REL}#a0001]",
            sources=[SOURCE_REL])
        rows = self.ann.unaddressed_marks()
        self.assertEqual([r["mark"]["id"] for r in rows], ["a0002"])
        self.assertEqual(rows[0]["pages"],
                         ["wiki/sources/fixture-source.md"])

    def test_fenced_reference_does_not_count(self):
        self.write_page(
            "fixture-source.md",
            "Syntax on display:\n\n```\n"
            f"^[mark: {SOURCE_REL}#a0001]\n```",
            sources=[SOURCE_REL])
        rows = self.ann.unaddressed_marks()
        self.assertEqual([r["mark"]["id"] for r in rows],
                         ["a0001", "a0002"])

    def test_export_renders_marks(self):
        md = self.ann.export_markdown(SOURCE_REL)
        self.assertIn("a0001", md)
        self.assertIn("fifty-one should be fifty-two", md)
        self.assertIn(f"{SOURCE_REL}#L2-L2", md)


class GuardInteractionTests(AnnotateFixture):

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root),
             "-c", "user.email=test@example.com", "-c", "user.name=Test",
             *args],
            capture_output=True, text=True)

    def guard_staged(self):
        return subprocess.run(
            [sys.executable,
             str(self.root / "scripts" / "wiki_memory_guard.py"),
             "--staged"],
            capture_output=True, text=True)

    def test_new_annotations_file_passes_guard(self):
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture base")
        # Annotate: a NEW file appears beside the source.
        self.ann.add_mark(SOURCE_REL, "correction",
                          "fifty-one should be fifty-two",
                          quote="fifty-one files",
                          created="2030-10-20")
        self.git("add", SOURCE_REL + ".annotations.jsonl")
        proc = self.guard_staged()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS", proc.stdout)

    def test_modifying_the_source_itself_is_refused(self):
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture base")
        path = self.root / SOURCE_REL
        path.write_text(path.read_text(encoding="utf-8")
                        + "an appended line\n", encoding="utf-8")
        self.git("add", SOURCE_REL)
        proc = self.guard_staged()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("raw-modification", proc.stdout)


if __name__ == "__main__":
    unittest.main()
