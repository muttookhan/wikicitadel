#!/usr/bin/env python3
"""Tests for tools/gateway/gateway/destructive.py — the env-flag
gate for destructive gateway tools (Scrapbox MCP pattern,
Marathon Round 3 TB8 row 1).

Pins:
  * the flag is OFF by default and only the exact value 'true'
    enables it ('1', 'yes', '' all stay off);
  * while off, no destructive tool is visible/registered;
  * an invocation attempt while off is REFUSED and ledgered
    exactly once (via the record callback);
  * with the flag on, the harmless fixture tool deletes only a
    file strictly inside the scratch dir; escaping paths and
    missing files are refused and ledgered;
  * no recorder -> refusal (an unledgered attempt never runs).

Fixture-based only; no live corpus, no network.
Run:  python3 -m unittest discover -s tools/gateway/tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gateway import destructive  # noqa: E402


class Recorder:
    def __init__(self):
        self.entries = []

    def __call__(self, action, result, detail):
        self.entries.append(
            {"action": action, "result": result, "detail": detail})


OFF = {}
ON = {destructive.ENV_FLAG: "true"}


class TestFlag(unittest.TestCase):
    def test_default_off(self):
        self.assertFalse(destructive.destructive_enabled(OFF))
        self.assertEqual(destructive.visible_tools(OFF), [])

    def test_only_exact_true_enables(self):
        for val in ("1", "yes", "on", "", "TRUE-ish"):
            self.assertFalse(
                destructive.destructive_enabled(
                    {destructive.ENV_FLAG: val}), val)
        self.assertTrue(destructive.destructive_enabled(ON))
        self.assertTrue(destructive.destructive_enabled(
            {destructive.ENV_FLAG: " True "}))

    def test_visible_only_when_on(self):
        names = [t["name"] for t in destructive.visible_tools(ON)]
        self.assertEqual(names, ["wiki_fixture_delete_scratch"])


class TestInvoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scratch = Path(self.tmp.name) / "scratch"
        self.scratch.mkdir()
        (self.scratch / "victim.txt").write_text("x",
                                                 encoding="utf-8")
        self.rec = Recorder()

    def tearDown(self):
        self.tmp.cleanup()

    def test_refused_by_default_and_ledgered(self):
        payload, is_err = destructive.invoke(
            "wiki_fixture_delete_scratch", {"path": "victim.txt"},
            scratch_root=self.scratch, record=self.rec, env=OFF)
        self.assertTrue(is_err)
        self.assertIn("refused", payload["error"])
        self.assertTrue((self.scratch / "victim.txt").exists())
        self.assertEqual(len(self.rec.entries), 1)
        self.assertEqual(self.rec.entries[0]["result"], "deny")
        self.assertEqual(self.rec.entries[0]["action"],
                         "destructive_refused")

    def test_allowed_when_flag_on(self):
        payload, is_err = destructive.invoke(
            "wiki_fixture_delete_scratch", {"path": "victim.txt"},
            scratch_root=self.scratch, record=self.rec, env=ON)
        self.assertFalse(is_err, payload)
        self.assertFalse((self.scratch / "victim.txt").exists())
        self.assertEqual(len(self.rec.entries), 1)
        self.assertEqual(self.rec.entries[0]["result"], "allow")

    def test_escape_refused_even_when_on(self):
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        payload, is_err = destructive.invoke(
            "wiki_fixture_delete_scratch", {"path": "../outside.txt"},
            scratch_root=self.scratch, record=self.rec, env=ON)
        self.assertTrue(is_err)
        self.assertTrue(outside.exists())
        self.assertEqual(self.rec.entries[0]["result"], "deny")

    def test_missing_file_refused_and_ledgered(self):
        payload, is_err = destructive.invoke(
            "wiki_fixture_delete_scratch", {"path": "nope.txt"},
            scratch_root=self.scratch, record=self.rec, env=ON)
        self.assertTrue(is_err)
        self.assertEqual(len(self.rec.entries), 1)
        self.assertEqual(self.rec.entries[0]["result"], "deny")

    def test_unknown_tool_refused_and_ledgered(self):
        payload, is_err = destructive.invoke(
            "wiki_delete_everything", {},
            scratch_root=self.scratch, record=self.rec, env=ON)
        self.assertTrue(is_err)
        self.assertEqual(len(self.rec.entries), 1)

    def test_no_recorder_never_runs(self):
        payload, is_err = destructive.invoke(
            "wiki_fixture_delete_scratch", {"path": "victim.txt"},
            scratch_root=self.scratch, record=None, env=ON)
        self.assertTrue(is_err)
        self.assertTrue((self.scratch / "victim.txt").exists())


class TestServerIntegration(unittest.TestCase):
    """End to end through the real Gateway: the fixture tool is
    absent from tools/list by default, an authenticated call is
    refused, and the refusal lands in the Black Box ledger."""

    def test_gateway_refuses_and_ledgers_by_default(self):
        from fixtures.make_fixtures import build_fixture
        from gateway import ledger as ledger_mod
        from gateway.server import Gateway
        import os
        os.environ.pop(destructive.ENV_FLAG, None)
        with tempfile.TemporaryDirectory() as td:
            fx = build_fixture(Path(td))
            gw = Gateway(fx["config"])
            token = fx["tokens"]["owner"] \
                if "owner" in fx["tokens"] else \
                next(iter(fx["tokens"].values()))
            meta = {"authorization": f"Bearer {token}",
                    "session_id": "destructive-test"}
            listed = gw.handle({"jsonrpc": "2.0", "id": 1,
                                "method": "tools/list", "params": {}})
            names = [t["name"]
                     for t in listed["result"]["tools"]]
            self.assertNotIn("wiki_fixture_delete_scratch", names)
            resp = gw.handle({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "wiki_fixture_delete_scratch",
                           "arguments": {"path": "victim.txt"},
                           "_meta": meta}})
            result = resp["result"]
            self.assertTrue(result["isError"])
            entries = ledger_mod.read_entries(gw.ledger.path)
            refusals = [e for e in entries
                        if e.get("action") == "destructive_refused"]
            self.assertEqual(len(refusals), 1)
            self.assertEqual(refusals[0]["result"], "deny")
            self.assertEqual(
                refusals[0]["destructive_gate"]["tool"],
                "wiki_fixture_delete_scratch")


if __name__ == "__main__":
    unittest.main()
