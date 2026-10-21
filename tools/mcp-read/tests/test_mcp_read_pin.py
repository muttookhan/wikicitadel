#!/usr/bin/env python3
"""Tests for the --pin frozen-read follow-up in
tools/mcp-read/server.py (Marathon Round 3, Tier A: the MCP
door gains the traverse --pin <commit> parameter).

The fixture is a tiny GIT repo in a temp dir (the door's
dependencies copied in and committed, exactly as the
traverse pin suite builds its fixture): page alpha is
committed as VERSION ONE, then edited and committed as
VERSION TWO. Pins:

  - a per-call `pin` argument reads alpha as its PINNED text
    and stamps the result with the resolved commit; the same
    call unpinned returns the current text and carries NO
    pin field (unpinned behaviour unchanged);
  - a session `--pin` at startup pins every call;
  - a pinned wiki_search runs against the pinned tree;
  - an unresolvable pin is refused per call (error result
    naming the refusal) and at startup (exit 2 before
    serving);
  - a pinned battery writes nothing in the working tree
    (sha256 of every file outside .git / __pycache__ is
    identical before and after);
  - tools/list still names exactly the eight read tools,
    each now carrying the optional `pin` property.

Run:  python3 -m unittest discover -s tests   (from tools/mcp-read/)
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MCP_READ = HERE.parent
REPO = MCP_READ.parents[1]
SERVER = MCP_READ / "server.py"
SCRIPTS = REPO / "scripts"

ALPHA_V1 = """---
title: Alpha
type: entity
---

# Alpha

PINNED VERSION ONE body with a quixotic lantern.
"""

ALPHA_V2 = """---
title: Alpha
type: entity
---

# Alpha

CURRENT VERSION TWO body with a quixotic lantern.
"""


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
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp-read-pin-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self._mk("scripts")
        for name in ("wiki_traverse.py", "wiki_validate.py",
                     "wiki_search.py", "wiki_claims.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        lens = self._mk("tools", "lens")
        shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                    lens / "lenslib.py")
        ent = self._mk("wiki", "entities")
        self.alpha = ent / "alpha.md"
        self.alpha.write_text(ALPHA_V1, encoding="utf-8")
        src = self._mk("raw", "sources")
        (src / "note.md").write_text("pinned raw note v1\n",
                                      encoding="utf-8")
        ev = self._mk("evaluation")
        (ev / "sensitivity.json").write_text(json.dumps(
            {"classes": [], "assignments": []}), encoding="utf-8")
        (ev / "citation-lockfile.json").write_text(json.dumps(
            {"tool": "fixture", "generated": "2026-10-20",
             "citations": []}), encoding="utf-8")
        (ev / "outcomes.jsonl").write_text("", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "v1")
        self.pin = self.git("rev-parse", "HEAD").stdout.strip()
        self.alpha.write_text(ALPHA_V2, encoding="utf-8")
        (src / "note.md").write_text("pinned raw note v2\n",
                                     encoding="utf-8")
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

    def rpc(self, *requests, extra_args=()):
        inp = "".join(json.dumps(r) + "\n" for r in requests)
        proc = subprocess.run(
            [sys.executable, str(SERVER), "--root", str(self.tmp),
             *extra_args],
            input=inp, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = {}
        for line in proc.stdout.splitlines():
            if line.strip():
                msg = json.loads(line)
                if "id" in msg:
                    out[msg["id"]] = msg
        return out

    def call(self, name, arguments=None, extra_args=()):
        out = self.rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": name, "arguments": arguments or {}}},
            extra_args=extra_args)
        result = out[2]["result"]
        payload = json.loads(result["content"][0]["text"])
        return result.get("isError", False), payload


class TestPerCallPin(PinFixture):
    def test_pinned_read_returns_pinned_text_stamped(self):
        is_err, payload = self.call(
            "wiki_read_page", {"page": "alpha", "pin": self.pin})
        self.assertFalse(is_err, payload)
        self.assertIn("PINNED VERSION ONE", payload["text"])
        self.assertNotIn("CURRENT VERSION TWO", payload["text"])
        self.assertEqual(payload["pin"], self.pin)

    def test_unpinned_read_current_and_unstamped(self):
        is_err, payload = self.call("wiki_read_page",
                                    {"page": "alpha"})
        self.assertFalse(is_err, payload)
        self.assertIn("CURRENT VERSION TWO", payload["text"])
        self.assertNotIn("pin", payload)

    def test_pinned_source_and_census(self):
        is_err, payload = self.call(
            "wiki_read_source",
            {"path": "raw/sources/note.md", "pin": self.pin})
        self.assertFalse(is_err, payload)
        self.assertIn("v1", payload["text"])
        self.assertEqual(payload["pin"], self.pin)
        is_err, payload = self.call("wiki_census",
                                    {"pin": self.pin})
        self.assertFalse(is_err, payload)
        self.assertEqual(payload["pages"], 1)
        self.assertEqual(payload["pin"], self.pin)

    def test_pinned_search_searches_pinned_tree(self):
        is_err, payload = self.call(
            "wiki_search", {"query": "PINNED VERSION ONE",
                            "pin": self.pin})
        self.assertFalse(is_err, payload)
        ids = [r["page_id"] for r in payload["results"]]
        self.assertIn("wiki/entities/alpha.md", ids)
        self.assertEqual(payload["pin"], self.pin)

    def test_unresolvable_pin_refused_per_call(self):
        is_err, payload = self.call(
            "wiki_read_page",
            {"page": "alpha",
             "pin": "0000000000000000000000000000000000000000"})
        self.assertTrue(is_err)
        self.assertIn("does not resolve", payload["error"])


class TestSessionPin(PinFixture):
    def test_session_pin_pins_every_call(self):
        is_err, payload = self.call(
            "wiki_read_page", {"page": "alpha"},
            extra_args=("--pin", self.pin))
        self.assertFalse(is_err, payload)
        self.assertIn("PINNED VERSION ONE", payload["text"])
        self.assertEqual(payload["pin"], self.pin)

    def test_unresolvable_session_pin_exits_2(self):
        proc = subprocess.run(
            [sys.executable, str(SERVER), "--root", str(self.tmp),
             "--pin", "0000000000000000000000000000000000000000"],
            input="", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("does not resolve", proc.stderr)

    def test_pinned_battery_writes_nothing(self):
        before = tree_checksums(self.tmp)
        self.call("wiki_read_page", {"page": "alpha",
                                     "pin": self.pin})
        self.call("wiki_census", {"pin": self.pin})
        self.call("wiki_read_page", {"page": "alpha"},
                  extra_args=("--pin", self.pin))
        self.assertEqual(tree_checksums(self.tmp), before)


class TestToolsListPin(PinFixture):
    def test_tools_still_nine_each_with_optional_pin(self):
        out = self.rpc({"jsonrpc": "2.0", "id": 1,
                        "method": "tools/list"})
        tools = out[1]["result"]["tools"]
        self.assertEqual(len(tools), 9)
        for t in tools:
            props = t["inputSchema"]["properties"]
            self.assertIn("pin", props, t["name"])
            self.assertNotIn("pin", t["inputSchema"].get(
                "required", []))


if __name__ == "__main__":
    unittest.main()
