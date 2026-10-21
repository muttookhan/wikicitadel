"""Tests for scripts/wiki_bookmarks.py (Marathon R7 lane BB;
Bookmarks Sync design, MIT — re-implemented).

Fixtures are INVENTED bookmark files (example.org etc.) built
inline in a temp tree. Pins: all three formats parse (Chrome
JSON, Netscape HTML, Firefox backup JSON) with folder paths;
drafts land in staging/bookmarks/ ONLY (nothing under wiki/);
URL dedupe is structural (case/default-port/fragment/trailing
slash) and persists across imports via the register; a URL
input is refused (manual-first, file only); an unrecognised
file is a door failure; dry-run writes nothing.

Run: python3 -m unittest scripts.tests.test_wiki_bookmarks
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

CHROME = {"roots": {"bookmark_bar": {"type": "folder", "name": "Bar",
          "children": [
              {"type": "url", "name": "Harbour Guide",
               "url": "https://example.org/harbour",
               "date_added": "13380000000000000"},
              {"type": "folder", "name": "Reading", "children": [
                  {"type": "url", "name": "Tide Tables",
                   "url": "https://example.net/tides",
                   "date_added": "13380000000000000"}]}]},
          "other": {"type": "folder", "name": "", "children": []}}}
NETSCAPE = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><H3>Reading</H3>
<DL><p>
<DT><A HREF="https://example.org/harbour" ADD_DATE="1700000000">Harbour Guide</A>
<DT><A HREF="https://example.com/about">About Example</A>
</DL><p>
</DL><p>
"""
FIREFOX = {"title": "", "type": "text/x-moz-place-container",
           "children": [{"title": "menu", "type": "text/x-moz-place-container",
                         "children": [
                             {"title": "Harbour Guide",
                              "type": "text/x-moz-place",
                              "uri": "https://example.org/harbour",
                              "dateAdded": 1700000000000000}]}]}


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_bookmarks", SCRIPTS / "wiki_bookmarks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


class ParseTests(unittest.TestCase):
    def test_normalise_url(self):
        self.assertEqual(
            MOD.normalise_url("HTTPS://Example.ORG:443/harbour/#top"),
            MOD.normalise_url("https://example.org/harbour"))

    def test_netscape_folders(self):
        import tempfile as tf
        with tf.NamedTemporaryFile("w", suffix=".html",
                                   delete=False) as fh:
            fh.write(NETSCAPE)
            path = Path(fh.name)
        fmt, items = MOD.detect_and_parse(path)
        self.assertEqual(fmt, "netscape")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["folder"], "Reading")
        self.assertEqual(items[0]["added"], "2023-11-14")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_bookmarks.py", self.root / "scripts")
        (self.root / "templates" / "capture").mkdir(parents=True)
        shutil.copy(SCRIPTS.parent / "templates" / "capture" / "bookmark.md",
                    self.root / "templates" / "capture" / "bookmark.md")
        (self.root / "evaluation").mkdir()
        (self.root / "wiki").mkdir()
        self.tool = self.root / "scripts" / "wiki_bookmarks.py"
        self.chrome_file = self.root / "Bookmarks"
        self.chrome_file.write_text(json.dumps(CHROME), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(self.tool), *argv],
                              capture_output=True, text=True)

    def import_chrome(self):
        proc = self.run_cli("import", str(self.chrome_file))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc


class ImportTests(Fixture):
    def test_chrome_import_stages_to_staging_only(self):
        self.import_chrome()
        drafts = list((self.root / "staging" / "bookmarks").glob("*.md"))
        self.assertEqual(len(drafts), 2)
        self.assertEqual(list((self.root / "wiki").rglob("*.md")), [])
        text = drafts[0].read_text(encoding="utf-8")
        self.assertIn("bookmark_url:", text)
        self.assertIn("sensitivity: TODO", text)

    def test_chrome_folders_recorded(self):
        report = MOD.import_file(self.root, self.chrome_file)
        self.assertEqual(report["format"], "chrome")
        known = MOD.read_register(self.root)
        folders = {e["folder"] for e in known.values()}
        self.assertIn("Bar/Reading", folders)

    def test_reimport_dedupes_via_register(self):
        self.import_chrome()
        report = MOD.import_file(self.root, self.chrome_file)
        self.assertEqual(report["stats"]["staged"], 0)
        self.assertEqual(report["stats"]["duplicates"], 2)

    def test_firefox_import_and_cross_format_dedupe(self):
        self.import_chrome()
        ff = self.root / "backup.json"
        ff.write_text(json.dumps(FIREFOX), encoding="utf-8")
        report = MOD.import_file(self.root, ff)
        self.assertEqual(report["format"], "firefox")
        self.assertEqual(report["stats"]["duplicates"], 1)

    def test_netscape_import(self):
        ns = self.root / "bookmarks.html"
        ns.write_text(NETSCAPE, encoding="utf-8")
        report = MOD.import_file(self.root, ns)
        self.assertEqual(report["stats"]["staged"], 2)

    def test_dry_run_writes_nothing(self):
        report = MOD.import_file(self.root, self.chrome_file,
                                 dry_run=True)
        self.assertEqual(report["stats"]["staged"], 2)
        self.assertFalse((self.root / "staging" / "bookmarks").exists())
        self.assertFalse(
            (self.root / "evaluation" / "bookmarks-register.jsonl").exists())

    def test_url_input_refused(self):
        self.assertEqual(
            self.run_cli("import", "https://example.org/x").returncode, 2)

    def test_unrecognised_file_door_failure(self):
        bad = self.root / "nope.txt"
        bad.write_text("not bookmarks at all", encoding="utf-8")
        self.assertEqual(self.run_cli("import", str(bad)).returncode, 1)


if __name__ == "__main__":
    unittest.main()
