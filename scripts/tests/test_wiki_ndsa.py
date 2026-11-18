#!/usr/bin/env python3
"""Tests for scripts/wiki_ndsa.py — the mechanical checks on
fixture trees (queue item 29). The judgement rows are data,
reviewed by a human; what is tested here is that the tool
derives the mechanical facts from the tree it is pointed at
and renders both halves."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "wiki_ndsa.py"
_spec = importlib.util.spec_from_file_location("wiki_ndsa", SCRIPT)
ndsa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ndsa)


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args],
                   capture_output=True, text=True, check=True)


def make_fixture(with_remote=True, with_drive=True, with_fixity=True):
    root = Path(tempfile.mkdtemp(prefix="ndsa-fixture-"))
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    if with_remote:
        git(root, "remote", "add", "azure",
            "git@ssh.dev.azure.com:v3/example/example/example")
    agents = "# Fixture\n\n## Security\n\nPrivate.\n"
    if with_drive:
        agents += "\nNightly, the newest take-home zip goes to Google Drive.\n"
    (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    (root / "wiki" / "access").mkdir(parents=True)
    (root / "wiki" / "access" / "identity-scopes.md").write_text(
        "# scopes\n", encoding="utf-8")
    (root / "tools" / "gateway").mkdir(parents=True)
    (root / "tools" / "gateway" / "README.md").write_text(
        "# gateway\n", encoding="utf-8")
    if with_fixity:
        (root / "raw" / "sources").mkdir(parents=True)
        (root / "raw" / "sources" / "provenance-manifest.json").write_text(
            json.dumps({"files": {"a.md": {}, "b.md": {}}}),
            encoding="utf-8")
        (root / "evaluation").mkdir()
        (root / "evaluation" / "source-manifest.jsonl").write_text(
            '{"path": "raw/sources/a.md"}\n', encoding="utf-8")
    (root / "notes.md").write_text("# notes\n", encoding="utf-8")
    (root / "data.json").write_text("{}\n", encoding="utf-8")
    (root / "photo.png").write_bytes(b"\x89PNG")
    return root


class CopiesCheck(unittest.TestCase):
    def test_three_copies_met(self):
        root = make_fixture()
        check = ndsa.check_copies(root)
        self.assertEqual(check["verdict"], "MET")
        self.assertIn("3 copies", check["detail"])

    def test_two_copies_partial(self):
        root = make_fixture(with_drive=False)
        check = ndsa.check_copies(root)
        self.assertEqual(check["verdict"], "PARTIAL")

    def test_one_copy_not_met(self):
        root = make_fixture(with_remote=False, with_drive=False)
        check = ndsa.check_copies(root)
        self.assertEqual(check["verdict"], "NOT MET")


class FixityCheck(unittest.TestCase):
    def test_fixity_stored(self):
        root = make_fixture()
        check = ndsa.check_fixity_stored(root)
        self.assertEqual(check["verdict"], "MET")
        self.assertIn("2 entries", check["detail"])

    def test_no_fixity_not_met(self):
        root = make_fixture(with_fixity=False)
        check = ndsa.check_fixity_stored(root)
        self.assertEqual(check["verdict"], "NOT MET")


class CensusAndAccess(unittest.TestCase):
    def test_census_counts_extensions(self):
        root = make_fixture()
        counts, total = ndsa.format_census(root)
        self.assertEqual(counts[".md"], 4)
        self.assertEqual(counts[".json"], 2)
        self.assertEqual(counts[".png"], 1)
        self.assertGreaterEqual(total, 7)

    def test_access_documented(self):
        root = make_fixture()
        check = ndsa.check_access_documented(root)
        self.assertEqual(check["verdict"], "MET")

    def test_access_missing(self):
        root = make_fixture()
        (root / "AGENTS.md").write_text("# no security here\n",
                                        encoding="utf-8")
        (root / "wiki" / "access" / "identity-scopes.md").unlink()
        (root / "tools" / "gateway" / "README.md").unlink()
        check = ndsa.check_access_documented(root)
        self.assertEqual(check["verdict"], "NOT MET")


class Render(unittest.TestCase):
    def test_render_includes_judgements_and_tally(self):
        root = make_fixture()
        (root / "evaluation").mkdir(exist_ok=True)
        rows = [{
            "area": "Storage", "level": 1, "practice": "Two copies",
            "verdict": "MET", "evidence": "AGENTS.md", "note": "n",
        }]
        (root / "evaluation" / "ndsa-judgements.json").write_text(
            json.dumps(rows), encoding="utf-8")
        out = ndsa.render_markdown(
            root, ndsa.mechanical_checks(root), ndsa.load_judgements(root))
        self.assertIn("MET 1", out)
        self.assertIn("Two copies", out)

    def test_main_json_mode(self):
        root = make_fixture()
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), "--json"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data["mechanical"]), 4)


if __name__ == "__main__":
    unittest.main()
