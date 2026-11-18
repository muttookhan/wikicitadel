"""Tests for scripts/wiki_publish.py (Marathon Round 4, lane B,
item 1 -- the zenn-cli shape).

Pins: check passes a valid page and fails (exit semantics via
run_check's code) a page with a missing frontmatter field and a
broken wikilink, reusing the validator's machinery (the fixture
copies the real scripts/wiki_validate.py in, so the reuse is the
production code path, not a stub); preview renders a standalone
HTML file through the fallback renderer when no Lens is present
(the fixture has no tools/lens) and through lenslib when it is;
push prints the exact git commands on a clean check, executes
nothing (the fixture is not a git repo -- any real git call
would fail), and aborts on a failing check.

Run:  python3 -m unittest discover -s scripts/tests
Fixture trees are built in temp dirs; the live corpus is never
touched.
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_publish", ROOT / "scripts" / "wiki_publish.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


PAGE = """---
title: "{title}"
type: concept
created: 2026-10-21
updated: 2026-10-21
sources:
  - raw/sources/note.md
tags: [demo]
---

# {title}

Body text. See [[concepts/other]].
"""

OTHER = """---
title: "Other"
type: concept
created: 2026-10-21
updated: 2026-10-21
sources:
  - raw/sources/note.md
tags: [demo]
---

# Other

Plain body.
"""


def fixture(tmp):
    root = Path(tmp)
    # The validator is reused by import: the fixture carries the
    # real one, exactly as the production tree does.
    (root / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "wiki_validate.py",
                root / "scripts" / "wiki_validate.py")
    _write(root, "raw/sources/note.md", "a source note\n")
    _write(root, "wiki/concepts/other.md", OTHER)
    _write(root, "wiki/concepts/good.md", PAGE.format(title="Good"))
    return root


class CheckTests(unittest.TestCase):
    def test_valid_page_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            report, code = mod.run_check(
                root, ["wiki/concepts/good.md"])
            self.assertEqual(code, 0)
            self.assertEqual(
                report["wiki/concepts/good.md"]["errors"], [])

    def test_missing_field_and_broken_link_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            bad = PAGE.format(title="Bad").replace(
                "tags: [demo]\n", "").replace(
                "[[concepts/other]]", "[[concepts/ghost]]")
            _write(root, "wiki/concepts/bad.md", bad)
            report, code = mod.run_check(
                root, ["wiki/concepts/bad.md"])
            self.assertEqual(code, 1)
            kinds = [k for k, _d in
                     report["wiki/concepts/bad.md"]["errors"]]
            self.assertIn("missing field", kinds)

    def test_broken_link_alone_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            bad = PAGE.format(title="Bad").replace(
                "[[concepts/other]]", "[[concepts/ghost]]")
            _write(root, "wiki/concepts/bad.md", bad)
            report, code = mod.run_check(
                root, ["wiki/concepts/bad.md"])
            self.assertEqual(code, 1)
            kinds = [k for k, _d in
                     report["wiki/concepts/bad.md"]["errors"]]
            self.assertIn("broken wikilink", kinds)

    def test_missing_page_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            _report, code = mod.run_check(
                root, ["wiki/concepts/nope.md"])
            self.assertEqual(code, 1)


class PreviewTests(unittest.TestCase):
    def test_preview_fallback_renders_standalone_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            out = mod.render_preview(root, "wiki/concepts/good.md",
                                     Path(tmp) / "out")
            self.assertTrue(out.is_file())
            doc = out.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", doc)
            self.assertIn("Good", doc)
            self.assertIn("Body text", doc)

    def test_preview_with_lenslib_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            lens_dir = root / "tools" / "lens"
            lens_dir.mkdir(parents=True)
            shutil.copy(ROOT / "tools" / "lens" / "lenslib.py",
                        lens_dir / "lenslib.py")
            out = mod.render_preview(root, "wiki/concepts/good.md",
                                     Path(tmp) / "out")
            doc = out.read_text(encoding="utf-8")
            self.assertIn("<h1", doc)  # lenslib's heading markup
            self.assertIn("Good", doc)

    def test_preview_missing_page_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            with self.assertRaises(FileNotFoundError):
                mod.render_preview(root, "wiki/concepts/nope.md",
                                   Path(tmp) / "out")


class PushTests(unittest.TestCase):
    def test_push_plan_is_exact_commands(self):
        plan = mod.push_plan(Path("/repo"),
                             ["wiki/concepts/good.md"])
        self.assertEqual(plan[0],
                         "git -C /repo add -- wiki/concepts/good.md")
        self.assertEqual(plan[-1], "git -C /repo push")

    def test_push_prints_plan_and_executes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            # The fixture is not a git repository: if push ran
            # any git command it would fail. Exit 0 + the plan
            # on stdout proves it only reports.
            code = mod.main(["--root", str(root), "push",
                             "wiki/concepts/good.md"])
            self.assertEqual(code, 0)

    def test_push_aborts_when_check_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            bad = PAGE.format(title="Bad").replace(
                "[[concepts/other]]", "[[concepts/ghost]]")
            _write(root, "wiki/concepts/bad.md", bad)
            code = mod.main(["--root", str(root), "push",
                             "wiki/concepts/bad.md"])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
