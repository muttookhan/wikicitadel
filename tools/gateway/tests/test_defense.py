#!/usr/bin/env python3
"""Memory Defense: secrets/PII scan on the gateway staging path.

Pattern (2026-10-19): Hindsight's opt-in "Memory Defense"
(vectorize-io/hindsight, MIT) — scan every incoming memory for
secrets/PII and stop the write. Here the governed behaviour is
BLOCK: the proposal is quarantined at staging, the caller gets an
error naming the pattern CLASS only, the Black Box ledger records
the block (classes only), and the secret value appears NOWHERE —
not in findings, not in proposal meta, not in the error, not in
the ledger. These tests are the contract for all of that.

Every secret below is a published test/example value or a clearly
synthetic string; none is a credential for anything real.

Run:  python3 -m unittest discover -s tests -v   (from tools/gateway)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
GW_DIR = HERE.parents[1]
sys.path.insert(0, str(GW_DIR))

from fixtures.make_fixtures import build_fixture  # noqa: E402
from gateway import defense as defense_mod  # noqa: E402
from gateway import ledger as ledger_mod  # noqa: E402
from gateway.config import Config  # noqa: E402
from gateway.store import GatewayStore, StoreError  # noqa: E402

GOOD_PAGE = ("---\ntitle: Clean Page\ntype: concept\ncreated: 2026-10-19\n"
             "updated: 2026-10-19\nsources: []\ntags: [fixture]\n---\n\n"
             "Ordinary compiled knowledge about irrigation scheduling.\n")

# The PEM header/footer are assembled from fragments so the
# literal pattern never appears in this file: the wiki validator's
# tree-wide secret scan (correctly) cannot tell a fixture from a
# real leak, and the fixture must not trip it.
_PEM_HDR = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
_PEM_FTR = "-----END " + "RSA PRIVATE KEY" + "-----"
# AWS's own published example key id, likewise assembled from
# fragments so the literal never sits in the tree.
_AWS_EXAMPLE = "AKIA" + "IOSFODNN7EXAMPLE"

# One sample per pattern class. (class, secret value, content)
SAMPLES = [
    ("private-key",
     _PEM_HDR,
     "# Leaked key\n\n" + _PEM_HDR + "\n"
     "MIIBogIBAAJBAKfakefixturebytesnotarealkey00\n"
     + _PEM_FTR + "\n"),
    ("aws-access-key-id",
     _AWS_EXAMPLE,  # AWS's own published example key id
     "# Notes\n\nThe access key " + _AWS_EXAMPLE + " was pasted here.\n"),
    ("github-token",
     "ghp_" + "A" * 36,
     "# Notes\n\nToken: " + "ghp_" + "A" * 36 + "\n"),
    ("github-token",
     "github_pat_" + "B" * 40,
     "# Notes\n\nFine-grained: " + "github_pat_" + "B" * 40 + "\n"),
    ("slack-token",
     "xoxb-123456789012-abcdefghijkl",
     "# Notes\n\nSlack: xoxb-123456789012-abcdefghijkl\n"),
    ("provider-api-key",
     "sk-proj-" + "x" * 30,
     "# Notes\n\nKey sk-proj-" + "x" * 30 + " for the provider.\n"),
    ("jwt",
     "eyJ" + "a" * 20 + "." + "eyJ" + "b" * 20 + "." + "c" * 30,
     "# Notes\n\nSession JWT: " + "eyJ" + "a" * 20 + "."
     + "eyJ" + "b" * 20 + "." + "c" * 30 + "\n"),
    ("bearer-token",
     "abcdef123456" + "7890XYZtoken",
     "# Notes\n\nAuthorization: Bearer " + "abcdef123456" + "7890XYZtoken" + "\n"),
    ("credential-assignment",
     "Zx9Qw8Er7Ty6Ui5Op4As3Df2",
     "# Config\n\napi_key = \"Zx9Qw8Er7Ty6Ui5Op4As3Df2\"\n"),
    ("credential-assignment",
     "correcthorsebatterystaple",
     "# Config\n\npassword: correcthorsebatterystaple\n"),
    ("connection-string",
     "Sup3rSecretPass",
     "# Config\n\nDB: postgres://wikiuser:Sup3rSecretPass@db.internal:5432/wiki\n"),
    ("ssn",
     "123-45-6789",
     "# Notes\n\nThe form lists SSN 123-45-6789 for the applicant.\n"),
    ("credit-card",
     "4242 4242 4242 4242",  # Stripe's published test card, Luhn-valid
     "# Notes\n\nCard on file: 4242 4242 4242 4242\n"),
]


def classes_of(report):
    return {f["pattern"] for f in report["findings"]}


class TestDefenseUnits(unittest.TestCase):
    def test_clean_prose_is_clean(self):
        report = defense_mod.scan_secrets(GOOD_PAGE)
        self.assertEqual(report["verdict"], "clean")
        self.assertEqual(report["findings"], [])

    def test_each_secret_class_detected(self):
        for cls, _value, content in SAMPLES:
            with self.subTest(pattern=cls):
                report = defense_mod.scan_secrets(content)
                self.assertEqual(report["verdict"], "blocked")
                self.assertIn(cls, classes_of(report))

    def test_findings_never_contain_the_value(self):
        for _cls, value, content in SAMPLES:
            with self.subTest(value=value[:12]):
                report = defense_mod.scan_secrets(content)
                self.assertNotIn(value, json.dumps(report))

    def test_luhn_invalid_number_is_not_a_card(self):
        report = defense_mod.scan_secrets(
            "# Notes\n\nReference 4242 4242 4242 4241 was cited.\n")
        self.assertNotIn("credit-card", classes_of(report))
        self.assertEqual(report["verdict"], "clean")

    def test_placeholders_and_paths_do_not_block(self):
        for content in (
            "# Docs\n\nSet api_key = \"your-api-key-here\" before use.\n",
            "# Docs\n\npassword = \"changeme123\" in the sample config.\n",
            "# Docs\n\nprivate_key = ~/.ssh/id_ed25519_azure\n",
            "# Docs\n\ntoken: ${GATEWAY_TOKEN}\n",
            "# Docs\n\nUse the Bearer token from the vault.\n",
        ):
            with self.subTest(content=content.strip()[:40]):
                report = defense_mod.scan_secrets(content)
                self.assertEqual(report["verdict"], "clean", report)

    def test_invalid_ssn_areas_do_not_block(self):
        for ssn in ("000-45-6789", "666-45-6789", "900-45-6789"):
            with self.subTest(ssn=ssn):
                report = defense_mod.scan_secrets(f"SSN {ssn} listed.\n")
                self.assertNotIn("ssn", classes_of(report))

    def test_zero_width_obfuscation_does_not_hide_a_secret(self):
        split = "AKIA​IOSF​ODNN7EXAMPLE"
        report = defense_mod.scan_secrets(f"Key {split} here.\n")
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("aws-access-key-id", classes_of(report))


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = build_fixture(Path(self.tmp.name))
        self.store = GatewayStore(Config(env=dict(self.fx["env"])))

    def tearDown(self):
        self.tmp.cleanup()

    def _stage(self, content, target="wiki/concepts/from-defense.md"):
        return self.store.stage_proposal(
            actor="collaborator-a", session_id="def", target_path=target,
            content=content, cites=[],
            direction_source={"kind": "owner"}, task_ref="fixture")


class TestStagingGate(FixtureCase):
    def test_clean_proposal_stages_as_draft(self):
        meta = self._stage(GOOD_PAGE)
        self.assertEqual(meta["state"], "draft")
        self.assertEqual(meta["defense"]["verdict"], "clean")
        self.assertEqual(meta["defense"]["findings"], [])

    def test_each_secret_class_quarantines_at_staging(self):
        for cls, value, content in SAMPLES:
            with self.subTest(pattern=cls):
                meta = self._stage(content)
                self.assertEqual(meta["state"], "quarantined")
                self.assertEqual(meta["defense"]["verdict"], "blocked")
                self.assertIn(cls, classes_of(meta["defense"]))
                self.assertIn("secret scan", meta["quarantine_reason"])
                self.assertIn(cls, meta["quarantine_reason"])
                pid = meta["proposal_id"]
                self.assertTrue(
                    (self.store.quarantine / f"{pid}.md").exists())
                # The value survives ONLY in the quarantined bytes
                # themselves (the recorded evidence); the meta —
                # everything derived from it — must not carry it.
                self.assertNotIn(value, json.dumps(meta))
                # And promotion of a quarantined proposal is
                # impossible.
                with self.assertRaises(StoreError):
                    self.store.promote(pid, {"identity": "agent",
                                             "scopes": ["wiki:publish"]})


class ServerProcess:
    """Minimal stdio client, same shape as test_gateway's."""

    def __init__(self, fixture):
        env = {**os.environ, **fixture["env"]}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gateway", "serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1, env=env, cwd=str(GW_DIR))
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method,
               "params": params or {}}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        return json.loads(line)

    def call(self, name, arguments, token, session):
        resp = self.send("tools/call", {
            "name": name, "arguments": arguments,
            "_meta": {"authorization": f"Bearer {token}",
                      "session_id": session,
                      "direction_source": {"kind": "owner",
                                           "ref": "fixture-test"},
                      "task_ref": "fixture-task"}})
        result = resp["result"]
        return result, json.loads(result["content"][0]["text"])

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()


class TestServerAndLedger(FixtureCase):
    def setUp(self):
        super().setUp()
        self.srv = ServerProcess(self.fx)
        self.token = self.fx["tokens"]["collaborator-a"]
        self.srv.send("initialize", {
            "clientInfo": {"name": "fixture-client"},
            "_meta": {"authorization": f"Bearer {self.token}",
                      "session_id": "def-sess",
                      "direction_source": {"kind": "owner",
                                           "ref": "fixture-test"},
                      "task_ref": "fixture-task"}})

    def tearDown(self):
        self.srv.close()
        super().tearDown()

    def _ledger_text(self):
        files = sorted((self.fx["state_dir"] / "ledger").glob("black-box-*.jsonl"))
        self.assertEqual(len(files), 1)
        return files[0], files[0].read_text(encoding="utf-8")

    def test_caller_error_names_class_only_and_ledger_records_block(self):
        value = _AWS_EXAMPLE
        result, payload = self.srv.call(
            "wiki_stage_proposal",
            {"target_path": "wiki/concepts/from-defense.md",
             "content": f"# Notes\n\nKey {value} pasted.\n",
             "cites": []},
            self.token, "def-sess")
        self.assertTrue(result["isError"])
        self.assertIn("aws-access-key-id", payload["error"])
        self.assertEqual(payload["state"], "quarantined")
        # The value is in NEITHER the caller's answer NOR the ledger.
        self.assertNotIn(value, json.dumps(result))
        ledger_path, ledger_text = self._ledger_text()
        self.assertNotIn(value, ledger_text)
        entries = ledger_mod.read_entries(ledger_path)
        blocks = [e for e in entries
                  if e.get("action") == "stage_proposal"
                  and e.get("result") == "deny"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["secret_scan"], "blocked")
        self.assertIn("aws-access-key-id", blocks[0]["secret_classes"])
        self.assertTrue(ledger_mod.verify_chain(ledger_path)["ok"])

    def test_clean_proposal_via_server_is_unaffected(self):
        result, payload = self.srv.call(
            "wiki_stage_proposal",
            {"target_path": "wiki/concepts/from-defense.md",
             "content": GOOD_PAGE, "cites": []},
            self.token, "def-sess")
        self.assertFalse(result["isError"])
        self.assertEqual(payload["state"], "draft")


if __name__ == "__main__":
    unittest.main()
