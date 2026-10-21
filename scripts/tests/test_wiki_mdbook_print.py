"""Tests for scripts/wiki_mdbook_print.py (Marathon R11 lane BB)."""
import importlib.util, json, stat, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_mdbook_print", SCRIPTS / "wiki_mdbook_print.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

FAKE_MDBOOK = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "mdbook v0.0.0-fake"; exit 0; fi
dest=""
prev=""
for a in "$@"; do if [ "$prev" = "--dest-dir" ]; then dest="$a"; fi; prev="$a"; done
mkdir -p "$dest"
printf '<html>print</html>' > "$dest/print.html"
exit 0
"""

class T(unittest.TestCase):
    def _tree(self, td):
        root = Path(td) / "root"; (root / "wiki").mkdir(parents=True)
        (root / "wiki" / "a.md").write_text("---\ntitle: A\n---\n# A\n\nBody.\n")
        pages = Path(td) / "pages.json"
        pages.write_text(json.dumps({"pages": ["wiki/a.md"]}))
        return root, pages

    def test_missing_binary_is_door_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root, pages = self._tree(td)
            man = Path(td) / "man.json"
            rc = MOD.main(["build", "--pages-file", str(pages), "--mdbook", "/nonexistent/mdbook",
                           "--work", str(Path(td) / "w"), "--out-dir", str(Path(td) / "o"),
                           "--manifest", str(man), "--root", str(root)])
            self.assertEqual(rc, 2)
            self.assertFalse(json.loads(man.read_text())["built"])

    def test_fake_binary_builds_artefact(self):
        with tempfile.TemporaryDirectory() as td:
            root, pages = self._tree(td)
            fake = Path(td) / "mdbook"; fake.write_text(FAKE_MDBOOK)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            man = Path(td) / "man.json"; out = Path(td) / "o"
            rc = MOD.main(["build", "--pages-file", str(pages), "--mdbook", str(fake),
                           "--work", str(Path(td) / "w"), "--out-dir", str(out),
                           "--manifest", str(man), "--root", str(root)])
            self.assertEqual(rc, 0)
            d = json.loads(man.read_text())
            self.assertTrue(d["built"]); self.assertTrue((out / "print.html").is_file())
            self.assertEqual(len(d["artefact_sha256"]), 64)

    def test_missing_declared_page_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = self._tree(td)
            pages = Path(td) / "pages.json"
            pages.write_text(json.dumps({"pages": ["wiki/nope.md"]}))
            fake = Path(td) / "mdbook"; fake.write_text(FAKE_MDBOOK)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            man = Path(td) / "man.json"
            rc = MOD.main(["build", "--pages-file", str(pages), "--mdbook", str(fake),
                           "--work", str(Path(td) / "w"), "--out-dir", str(Path(td) / "o"),
                           "--manifest", str(man), "--root", str(root)])
            self.assertEqual(rc, 1)

if __name__ == "__main__":
    unittest.main()
