"""Tests for the traverse door's `memos` command (Marathon
Round 4, lane C): the memo timeline inbox listed newest-first
through the existing read-only door, tag-filtered, an absent
store an empty timeline, unadmitted identities refused, and
no file changed by the read.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

TOOL = "wiki_traverse.py"
MEMOS = [
    {"kind": "memo", "id": "memo-20261020-a",
     "captured": "2026-10-20T09:00:00+00:00",
     "date": "2026-10-20", "text": "older memo",
     "tags": ["demo"], "by": "tester"},
    {"kind": "memo", "id": "memo-20261021-b",
     "captured": "2026-10-21T09:00:00+00:00",
     "date": "2026-10-21", "text": "newer memo",
     "tags": ["demo", "garden"], "by": "tester"},
]


def tree_checksums(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[p.relative_to(root).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class TraverseMemosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="trav-memos-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPTS / TOOL, scripts / TOOL)
        self.identity = self._admitted_identity()

    def _admitted_identity(self):
        # The door's admitted set differs between editions;
        # read it from the copied tool rather than assuming.
        text = (self.tmp / "scripts" / TOOL).read_text(
            encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("ADMITTED"):
                names = [w.strip(" \"(),") for w in
                         line.replace("ADMITTED = (", " ").split()]
                names = [n for n in names if n and n != "owner"]
                if names:
                    return names[0]
        return "owner"

    def _write_store(self):
        staging = self.tmp / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "memos.jsonl").write_text(
            "".join(json.dumps(m) + "\n" for m in MEMOS),
            encoding="utf-8")

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / TOOL),
             *args], capture_output=True, text=True)

    def test_memos_newest_first_and_tag_filter(self):
        self._write_store()
        r = self.run_tool("--as", self.identity, "memos", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["count"], 2)
        self.assertEqual([m["text"] for m in data["memos"]],
                         ["newer memo", "older memo"])
        r = self.run_tool("--as", self.identity, "memos",
                          "--tag", "garden", "--json")
        data = json.loads(r.stdout)
        self.assertEqual([m["text"] for m in data["memos"]],
                         ["newer memo"])
        r = self.run_tool("--as", self.identity, "memos")
        self.assertIn("newer memo", r.stdout)

    def test_absent_store_is_empty_timeline(self):
        r = self.run_tool("--as", self.identity, "memos", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["count"], 0)

    def test_unadmitted_refused_and_read_writes_nothing(self):
        self._write_store()
        before = tree_checksums(self.tmp)
        r = self.run_tool("--as", "nobody", "memos")
        self.assertEqual(r.returncode, 1)
        self.run_tool("--as", self.identity, "memos", "--json")
        self.assertEqual(tree_checksums(self.tmp), before)


if __name__ == "__main__":
    unittest.main()
