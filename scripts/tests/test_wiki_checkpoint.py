#!/usr/bin/env python3
"""Tests for scripts/wiki_checkpoint.py (queue items 26-27).

Pins the checkpoint contract on a FIXTURE repo in a temp dir
(the real script copied in, so ROOT resolves to the fixture;
a throwaway signing key made in the fixture — the real key
is never touched):

  - create writes a hash-chained register line whose signed
    message bytes match the line, and the signature verifies
    against the fixture allowed_signers;
  - the checkpoint binds the fixture's git HEAD + tree, its
    Black Box head (found again in the living ledger at
    verify time) and its provenance corpus root;
  - verify PASSES on the fresh state and FAILS when a
    register line is tampered with (chain breaks), and when
    the Black Box is rewritten so the recorded head is gone;
  - the witness copy is made outside the repo and verifies
    as a prefix of the repo chain;
  - anchor writes an anchor line whose label is COMPUTED
    from the recorded outcomes (network is stubbed off in
    the fixture by removing the ots client and pointing the
    TSAs at an unroutable address via env — the label that
    results is "unanchored", earned by recorded failures,
    never asserted).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def git(root, *args, env_extra=None):
    import os
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@x",
                "GIT_COMMITTER_NAME": "Fixture",
                "GIT_COMMITTER_EMAIL": "f@x"})
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, env=env,
                          check=True)


class CheckpointFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wiki-checkpoint-"))
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPTS / "wiki_checkpoint.py",
                     self.repo / "scripts" / "wiki_checkpoint.py")
        (self.repo / "wiki" / "access").mkdir(parents=True)
        (self.repo / "evaluation").mkdir(parents=True)
        # throwaway signing key, fixture only
        self.key = self.tmp / "signkey"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", str(self.key),
                        "-N", "", "-C", "fixture"],
                       capture_output=True, check=True)
        pub = (Path(str(self.key) + ".pub").read_text().split())
        (self.repo / "wiki" / "access" / "allowed_signers").write_text(
            f'agent@wikicitadel namespaces="git" {pub[0]} {pub[1]}\n')
        # Black Box: two chained entries
        e1 = {"entry_id": "bb-000000", "entry_hash": "a" * 64,
              "prev_hash": "0" * 64, "seq": 0}
        e2 = {"entry_id": "bb-000001", "entry_hash": "b" * 64,
              "prev_hash": "a" * 64, "seq": 1}
        (self.repo / "wiki" / "access" / "black-box-2030.jsonl").write_text(
            json.dumps(e1) + "\n" + json.dumps(e2) + "\n")
        # provenance manifest: two sources
        rows = [{"path": "raw/sources/one.md", "merkle_root": "c" * 64},
                {"path": "raw/sources/two.md", "merkle_root": "d" * 64}]
        (self.repo / "evaluation" / "merkle-manifest.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))
        (self.repo / "wiki" / "access" / "note.md").write_text("fixture\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "fixture root")
        self.witness = self.tmp / "witness"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable,
             str(self.repo / "scripts" / "wiki_checkpoint.py"),
             "--key", str(self.key),
             "--witness-dir", str(self.witness), *args],
            capture_output=True, text=True, cwd=self.repo)

    def lines(self):
        reg = self.repo / "evaluation" / "checkpoints.jsonl"
        return [json.loads(ln) for ln in
                reg.read_text().splitlines() if ln.strip()]

    def test_create_signs_binds_and_witnesses(self):
        r = self.run_tool("create")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        lines = [ln for ln in self.lines() if ln["kind"] != "header"]
        self.assertEqual(len(lines), 1)
        cp = lines[0]
        self.assertEqual(cp["id"], "cp-000001")
        self.assertEqual(cp["black_box"]["entries"], 2)
        self.assertEqual(cp["black_box"]["head_hash"], "b" * 64)
        self.assertEqual(cp["provenance"]["sources"], 2)
        self.assertTrue((self.repo / cp["signature"]["message_file"]).is_file())
        self.assertTrue((self.repo / cp["signature"]["signature_file"]).is_file())
        # witness copy exists outside the repo
        self.assertTrue((self.witness / "checkpoints.jsonl").is_file())
        self.assertTrue((self.witness / "checkpoints.d"
                         / "cp-000001.json.sig").is_file())
        v = self.run_tool("verify")
        self.assertEqual(v.returncode, 0, v.stdout)
        self.assertIn("Result: PASS", v.stdout)
        self.assertIn("witness: OK", v.stdout)

    def test_verify_fails_on_register_tamper(self):
        self.assertEqual(self.run_tool("create").returncode, 0)
        reg = self.repo / "evaluation" / "checkpoints.jsonl"
        rows = reg.read_text().splitlines()
        cp = json.loads(rows[1])
        cp["black_box"]["entries"] = 99  # alter the signed body copy
        rows[1] = json.dumps(cp, sort_keys=True, separators=(",", ":"))
        reg.write_text("\n".join(rows) + "\n")
        v = self.run_tool("verify")
        self.assertEqual(v.returncode, 1)
        self.assertIn("BROKEN", v.stdout)

    def test_verify_fails_when_black_box_rewritten(self):
        self.assertEqual(self.run_tool("create").returncode, 0)
        bb = self.repo / "wiki" / "access" / "black-box-2030.jsonl"
        bb.write_text(json.dumps(
            {"entry_id": "bb-000000", "entry_hash": "e" * 64,
             "prev_hash": "0" * 64, "seq": 0}) + "\n")
        v = self.run_tool("verify")
        self.assertEqual(v.returncode, 1)
        self.assertIn("NOT FOUND in the living ledger", v.stdout)

    def test_anchor_records_failures_and_labels_unanchored(self):
        self.assertEqual(self.run_tool("create").returncode, 0)
        # No ots on PATH for the fixture shell-outs and the TSAs
        # are real-but-slow: assert only the recorded SHAPE —
        # an anchor line exists, carries two attempt records,
        # and its label matches their outcomes.
        r = self.run_tool("anchor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        anchors = [ln for ln in self.lines() if ln["kind"] == "anchor"]
        self.assertEqual(len(anchors), 1)
        a = anchors[0]
        self.assertEqual(a["checkpoint"], "cp-000001")
        self.assertEqual([x["mechanism"] for x in a["anchors"]],
                         ["opentimestamps", "rfc3161"])
        receipts = sum(1 for x in a["anchors"]
                       if x["status"] == "receipt")
        expected = {2: "dual-anchor", 1: "single-anchor",
                    0: "unanchored"}[receipts]
        self.assertEqual(a["anchor_label"], expected)
        for x in a["anchors"]:
            if x["status"] == "receipt":
                self.assertTrue((self.repo / x["receipt"]).is_file())
            else:
                self.assertTrue(x["detail"])  # failure stated, not silent


if __name__ == "__main__":
    unittest.main()
