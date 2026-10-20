#!/usr/bin/env python3
"""Tests for scripts/wiki_memory_guard.py (batch 3.3).

Pins the refusal contract:
  - small changes pass; mass wiki deletion (file cap and line
    cap) is a POLICY refusal (exit 1);
  - modifying an existing raw/ file, deleting a raw/ file
    without an erasure certificate, and truncating an
    append-only access ledger are PROVENANCE breaches (exit 2);
  - the two raw/ carve-outs hold: *manifest*.json bookkeeping
    may change, and the agent-memory mirror may be refreshed;
  - a raw/ deletion WITH a matching erasure certificate
    passes (certificates issued by the real sibling script);
  - an --override proceeds AND records itself in the Black
    Box ledger, chain intact;
  - --range mode judges a committed change set; --pre-push
    refuses a non-fast-forward.

Builds a fixture git repo in a temp dir: the real guard and
erasure scripts copied into scripts/, the gateway ledger
module copied into tools/gateway/gateway/, so ROOT resolves
to the fixture everywhere.

Run:  python3 -m unittest discover -s scripts/tests -v
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
GATEWAY = SCRIPTS.parent / "tools" / "gateway" / "gateway"
PAGES = 20  # wiki pages in the fixture; caps: files max(3, 2)=3


class GuardFixture(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "tools" / "gateway" / "gateway").mkdir(parents=True)
        (self.root / "wiki" / "access").mkdir(parents=True)
        (self.root / "raw" / "sources" / "agent-memory").mkdir(parents=True)
        (self.root / "evaluation").mkdir()
        shutil.copy(SCRIPTS / "wiki_memory_guard.py",
                    self.root / "scripts" / "wiki_memory_guard.py")
        shutil.copy(SCRIPTS / "wiki_erasure.py",
                    self.root / "scripts" / "wiki_erasure.py")
        for name in ("__init__.py", "ledger.py"):
            shutil.copy(GATEWAY / name,
                        self.root / "tools" / "gateway" / "gateway" / name)
        self.guard = self.root / "scripts" / "wiki_memory_guard.py"
        self.erasure = self.root / "scripts" / "wiki_erasure.py"

        for i in range(1, PAGES + 1):
            lines = "\n".join(f"page {i} line {j}" for j in range(1, 11))
            (self.root / "wiki" / f"page-{i:02d}.md").write_text(
                lines + "\n", encoding="utf-8")
        (self.root / "wiki" / "index.md").write_text("# index\n",
                                                    encoding="utf-8")
        (self.root / "raw" / "sources" / "src.md").write_text(
            "a raw source\n", encoding="utf-8")
        (self.root / "raw" / "sources"
         / "2030-01-01-thing-manifest.json").write_text("{}\n",
                                                       encoding="utf-8")
        (self.root / "raw" / "sources" / "agent-memory"
         / "MEMORY.md").write_text("mirror v1\n", encoding="utf-8")
        (self.root / "evaluation"
         / "erasure-certificates.jsonl").write_text("", encoding="utf-8")

        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture base")
        # Black Box ledger with genesis + one entry (2 lines)
        ledger_mod = self.load_ledger_module()
        ledger = ledger_mod.Ledger(
            self.root / "wiki" / "access" / "black-box-2030.jsonl",
            id_prefix="bb", wiki_root=self.root)
        ledger.append_genesis("blackbox/1", str(self.root))
        ledger.append({"action": "note", "actor": "test",
                       "result": "allow"})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "ledger")

    def tearDown(self):
        self.tmp.cleanup()

    # -- helpers -----------------------------------------------------------
    def git(self, *args):
        out = subprocess.run(
            ["git", "-C", str(self.root),
             "-c", "user.email=test@example.com", "-c", "user.name=Test",
             *args], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return out

    def load_ledger_module(self):
        spec = importlib.util.spec_from_file_location(
            "fixture_ledger",
            self.root / "tools" / "gateway" / "gateway" / "ledger.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_guard(self, *args, stdin=""):
        return subprocess.run(
            [sys.executable, str(self.guard), *args],
            capture_output=True, text=True, input=stdin)

    def stage_all(self):
        self.git("add", "-A")

    def delete_pages(self, n):
        for i in range(1, n + 1):
            (self.root / "wiki" / f"page-{i:02d}.md").unlink()

    # -- policy refusals ---------------------------------------------------
    def test_small_edit_passes(self):
        p = self.root / "wiki" / "page-01.md"
        p.write_text(p.read_text(encoding="utf-8") + "one more line\n",
                     encoding="utf-8")
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_mass_page_deletion_is_policy_refusal(self):
        self.delete_pages(5)  # cap is max(3, 10% of 21) = 3
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("mass-deletion-files", out.stdout)

    def test_few_page_deletions_pass(self):
        self.delete_pages(2)
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_mass_line_removal_is_policy_refusal(self):
        # 21 files, 211 lines at base; removing 9 lines from each
        # of 5 pages removes 45 > 20% (42) without deleting a file
        for i in range(1, 6):
            p = self.root / "wiki" / f"page-{i:02d}.md"
            p.write_text(f"page {i} line 1\n", encoding="utf-8")
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("mass-deletion-lines", out.stdout)

    # -- provenance breaches ----------------------------------------------
    def test_raw_modification_is_provenance_breach(self):
        p = self.root / "raw" / "sources" / "src.md"
        p.write_text("rewritten source\n", encoding="utf-8")
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertIn("raw-modification", out.stdout)

    def test_raw_manifest_bookkeeping_may_change(self):
        p = self.root / "raw" / "sources" / "2030-01-01-thing-manifest.json"
        p.write_text('{"refreshed": true}\n', encoding="utf-8")
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_claude_memory_mirror_may_be_refreshed(self):
        p = self.root / "raw" / "sources" / "agent-memory" / "MEMORY.md"
        p.write_text("mirror v2\n", encoding="utf-8")
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_raw_deletion_without_certificate_is_breach(self):
        (self.root / "raw" / "sources" / "src.md").unlink()
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertIn("raw-deletion-uncertified", out.stdout)

    def test_raw_deletion_with_certificate_passes(self):
        out = subprocess.run(
            [sys.executable, str(self.erasure), "issue",
             "--path", "raw/sources/src.md",
             "--authorisation-kind", "owner-directive",
             "--authorisation-ref", "test directive",
             "--reason", "test forget"],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        (self.root / "raw" / "sources" / "src.md").unlink()
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_ledger_truncation_is_provenance_breach(self):
        ledger_path = self.root / "wiki" / "access" / "black-box-2030.jsonl"
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
        ledger_path.write_text("\n".join(lines[1:]) + "\n",
                               encoding="utf-8")
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertIn("ledger-truncation", out.stdout)

    def test_ledger_append_passes(self):
        ledger_mod = self.load_ledger_module()
        ledger = ledger_mod.Ledger(
            self.root / "wiki" / "access" / "black-box-2030.jsonl",
            id_prefix="bb", wiki_root=self.root)
        ledger.append({"action": "note", "actor": "test",
                       "result": "allow"})
        self.stage_all()
        out = self.run_guard("--staged")
        self.assertEqual(out.returncode, 0, out.stdout)

    # -- override ----------------------------------------------------------
    def test_override_proceeds_and_is_recorded_in_black_box(self):
        self.delete_pages(5)
        self.stage_all()
        out = self.run_guard("--staged", "--override",
                             "owner ordered the prune")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("OVERRIDDEN", out.stdout)
        ledger_mod = self.load_ledger_module()
        entries = ledger_mod.read_entries(
            self.root / "wiki" / "access" / "black-box-2030.jsonl")
        last = entries[-1]
        self.assertEqual(last["action"], "memory_guard_override")
        self.assertEqual(last["direction_source"]["ref"],
                         "owner ordered the prune")
        self.assertTrue(last["guard_refusals"])
        result = ledger_mod.verify_chain(
            self.root / "wiki" / "access" / "black-box-2030.jsonl")
        self.assertTrue(result["ok"], result)

    def test_override_on_clean_change_writes_nothing(self):
        p = self.root / "wiki" / "page-01.md"
        p.write_text(p.read_text(encoding="utf-8") + "x\n",
                     encoding="utf-8")
        self.stage_all()
        before = (self.root / "wiki" / "access"
                  / "black-box-2030.jsonl").read_bytes()
        out = self.run_guard("--staged", "--override", "not needed")
        self.assertEqual(out.returncode, 0, out.stdout)
        after = (self.root / "wiki" / "access"
                 / "black-box-2030.jsonl").read_bytes()
        self.assertEqual(before, after)

    # -- range + pre-push ---------------------------------------------------
    def test_range_mode_judges_a_committed_change(self):
        self.delete_pages(5)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "mass deletion (unguarded)")
        out = self.run_guard("--range", "HEAD~1..HEAD")
        self.assertEqual(out.returncode, 1, out.stdout)

    def test_pre_push_refuses_non_fast_forward(self):
        local = self.git("rev-parse", "HEAD").stdout.strip()
        empty_tree = self.git("hash-object", "-t", "tree",
                              "/dev/null").stdout.strip()
        unrelated = self.git("commit-tree", empty_tree, "-m",
                             "unrelated root").stdout.strip()
        line = f"refs/heads/master {local} refs/heads/master {unrelated}\n"
        out = self.run_guard("--pre-push", stdin=line)
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertIn("history-rewrite", out.stdout)

    def test_pre_push_fast_forward_passes(self):
        local = self.git("rev-parse", "HEAD").stdout.strip()
        parent = self.git("rev-parse", "HEAD~1").stdout.strip()
        line = f"refs/heads/master {local} refs/heads/master {parent}\n"
        out = self.run_guard("--pre-push", stdin=line)
        self.assertEqual(out.returncode, 0, out.stdout)


if __name__ == "__main__":
    unittest.main()
