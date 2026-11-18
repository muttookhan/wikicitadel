#!/usr/bin/env python3
"""Tests for scripts/wiki_erasure.py (batch 3.3).

Pins the certificate contract:
  - content-free: the erased bytes never appear in the register;
  - hash-chained: tampering with a certificate breaks verify;
  - absence is checked by BYTES, not just by path — the same
    content resurfacing under a new name is a failed verify
    (the resurrection failure Inspeximus measured);
  - issue refuses a path that exists neither on disk nor in
    git HEAD (nothing to take a hash of).

Builds a fixture tree in a temp dir (the real script copied
in, so ROOT resolves to the fixture) and drives the CLI.

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
SECRET = b"synthetic erased content, batch 3.3 test fixture\n"


class ErasureTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "raw" / "sources").mkdir(parents=True)
        (self.root / "wiki").mkdir()
        (self.root / "evaluation").mkdir()
        shutil.copy(SCRIPTS / "wiki_erasure.py",
                    self.root / "scripts" / "wiki_erasure.py")
        self.script = self.root / "scripts" / "wiki_erasure.py"
        self.target = self.root / "raw" / "sources" / "secret.md"
        self.target.write_bytes(SECRET)
        self.register = self.root / "evaluation" / "erasure-certificates.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True, text=True)

    def issue(self, path="raw/sources/secret.md"):
        return self.run_cli(
            "issue", "--path", path,
            "--authorisation-kind", "owner-directive",
            "--authorisation-ref", "test directive",
            "--reason", "test forget")

    def test_issue_then_erase_then_verify_clean(self):
        out = self.issue()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.target.unlink()
        out = self.run_cli("verify")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("CLEAN", out.stdout)

    def test_certificate_is_content_free(self):
        self.assertEqual(self.issue().returncode, 0)
        register_text = self.register.read_text(encoding="utf-8")
        self.assertNotIn(SECRET.decode().strip(), register_text)
        cert = json.loads(register_text.splitlines()[0])
        self.assertEqual(cert["scope"][0]["bytes"], len(SECRET))
        import hashlib
        self.assertEqual(cert["scope"][0]["sha256"],
                         hashlib.sha256(SECRET).hexdigest())
        self.assertEqual(cert["authorisation"]["kind"], "owner-directive")

    def test_erased_path_still_present_fails(self):
        self.assertEqual(self.issue().returncode, 0)
        out = self.run_cli("verify")  # file NOT erased
        self.assertEqual(out.returncode, 1)
        self.assertIn("PATH PRESENT", out.stdout)

    def test_resurrected_bytes_under_a_new_name_fail(self):
        self.assertEqual(self.issue().returncode, 0)
        self.target.unlink()
        (self.root / "wiki" / "copy.md").write_bytes(SECRET)
        out = self.run_cli("verify")
        self.assertEqual(out.returncode, 1)
        self.assertIn("BYTES PRESENT", out.stdout)

    def test_tampered_register_breaks_the_chain(self):
        self.assertEqual(self.issue().returncode, 0)
        text = self.register.read_text(encoding="utf-8")
        self.register.write_text(
            text.replace("test forget", "forged reason"),
            encoding="utf-8")
        out = self.run_cli("verify")
        self.assertEqual(out.returncode, 1)
        self.assertIn("CHAIN BROKEN", out.stdout)

    def test_second_certificate_chains_to_the_first(self):
        other = self.root / "raw" / "sources" / "other.md"
        other.write_bytes(b"other synthetic content\n")
        self.assertEqual(self.issue().returncode, 0)
        self.assertEqual(self.issue("raw/sources/other.md").returncode, 0)
        certs = [json.loads(ln) for ln in
                 self.register.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([c["seq"] for c in certs], [0, 1])
        self.assertEqual(certs[1]["prev_hash"], certs[0]["cert_hash"])
        self.target.unlink()
        other.unlink()
        self.assertEqual(self.run_cli("verify").returncode, 0)

    def test_issue_refuses_a_path_that_exists_nowhere(self):
        out = self.issue("raw/sources/never-existed.md")
        self.assertNotEqual(out.returncode, 0)
        self.assertFalse(self.register.exists())

    def test_verify_without_register_is_exit_2(self):
        out = self.run_cli("verify")
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
