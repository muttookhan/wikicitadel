#!/usr/bin/env python3
"""Tests for the frozen-read `--pin` option of
scripts/wiki_traverse.py (B3 governance round).

Pins, on a FIXTURE git repo in a temp dir:
  - a pinned session reads a page as its PINNED text even
    after the page has been edited and committed past the pin;
  - the same read unpinned returns the current text;
  - the pinned output is stamped with the resolved commit,
    and --json carries the pin;
  - THE NO-WRITE PROOF for pinned sessions: sha256 of every
    working-tree file (excluding .git internals and bytecode
    caches) is identical before and after a pinned battery;
  - an unresolvable pin is refused (exit 1) before any read;
  - the tool's source still names no write API (the standing
    read-only scan, re-run against the pin code).

The fixture's dependency modules (wiki_validate / wiki_claims
/ wiki_search / lenslib) are copied from the tree under test
when present there, else from a sibling real tree — the pin
behaviour under test lives entirely in wiki_traverse.py.

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

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
TOOL = "wiki_traverse.py"

ALPHA_V1 = """---
title: Alpha
type: entity
---

# Alpha

PINNED VERSION ONE body.
"""

ALPHA_V2 = """---
title: Alpha
type: entity
---

# Alpha

CURRENT VERSION TWO body.
"""

SENSITIVITY = {"classes": [], "assignments": []}
LOCKFILE = {"tool": "fixture", "generated": "2026-10-20",
            "citations": []}


def find_dependency(rel):
    for base in (REPO, Path.home() / "workspace" / "llm-wiki",
                 Path.home() / "workspace" / "wikicitadel"):
        cand = base / rel
        if cand.is_file():
            return cand
    raise FileNotFoundError(rel)


def tree_checksums(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts \
                and ".git" not in p.parts:
            out[p.relative_to(root).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class PinFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="traverse-pin-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self._mk("scripts")
        shutil.copy(SCRIPTS / TOOL, scripts / TOOL)
        for name in ("wiki_validate.py", "wiki_claims.py",
                     "wiki_search.py"):
            shutil.copy(find_dependency(f"scripts/{name}"),
                        scripts / name)
        lens = self._mk("tools", "lens")
        shutil.copy(find_dependency("tools/lens/lenslib.py"),
                    lens / "lenslib.py")
        ent = self._mk("wiki", "entities")
        self.alpha = ent / "alpha.md"
        self.alpha.write_text(ALPHA_V1, encoding="utf-8")
        ev = self._mk("evaluation")
        (ev / "sensitivity.json").write_text(
            json.dumps(SENSITIVITY), encoding="utf-8")
        (ev / "citation-lockfile.json").write_text(
            json.dumps(LOCKFILE), encoding="utf-8")
        (ev / "outcomes.jsonl").write_text("", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "v1")
        self.pin = self.git("rev-parse", "HEAD").stdout.strip()
        # Edit past the pin and commit the edit.
        self.alpha.write_text(ALPHA_V2, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "v2")

    def _mk(self, *parts):
        d = self.tmp.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def git(self, *args):
        proc = subprocess.run(["git", "-C", str(self.tmp), *args],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / TOOL),
             *args], capture_output=True, text=True)


class TestPin(PinFixture):
    def test_pinned_read_returns_pinned_text(self):
        r = self.run_tool("--as", "owner", "--pin", self.pin,
                          "page", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PINNED VERSION ONE", r.stdout)
        self.assertNotIn("CURRENT VERSION TWO", r.stdout)
        self.assertIn(self.pin, r.stdout)

    def test_unpinned_read_returns_current_text(self):
        r = self.run_tool("--as", "owner", "page", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CURRENT VERSION TWO", r.stdout)

    def test_pinned_json_carries_pin(self):
        r = self.run_tool("--as", "owner", "--pin", self.pin,
                          "census", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["pin"], self.pin)
        self.assertEqual(data["pages"], 1)

    def test_pinned_session_writes_nothing(self):
        before = tree_checksums(self.tmp)
        for args in (("page", "alpha"), ("census",),
                     ("neighbours", "alpha"), ("claim",)):
            r = self.run_tool("--as", "owner", "--pin", self.pin,
                              *args)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, tree_checksums(self.tmp))

    def test_unresolvable_pin_refused(self):
        r = self.run_tool("--as", "owner", "--pin",
                          "0000000000000000000000000000000000000000",
                          "page", "alpha")
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not resolve", r.stderr)

    def test_source_names_no_write_api(self):
        text = (SCRIPTS / TOOL).read_text(encoding="utf-8")
        for token in ("write_text", "write_bytes", "os.remove",
                      ".unlink(", "import shutil", "os.replace",
                      "os.rename", ".mkdir(", "open(", "'a')",
                      '"a")', "'w')", '"w")'):
            self.assertNotIn(token, text, token)


if __name__ == "__main__":
    unittest.main()
