#!/usr/bin/env python3
"""Vault map generator: link resolution, backlinks, broken
links, duplicate titles, orphans, embeds, determinism, and the
check mode's staleness detection — on a fixture tree.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_vault_map", ROOT / "scripts" / "wiki_vault_map.py")
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


def fixture(tmp):
    root = Path(tmp)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "index.md").write_text(
        "# Index\n\n- [[alpha]]\n", encoding="utf-8")
    (root / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    (root / "wiki" / "concepts" / "alpha.md").write_text(
        "---\ntitle: Alpha\ntype: concept\ntags: [demo]\n"
        "sources:\n  - raw/sources/a.md\n---\n\n# Alpha\n\n"
        "See [[beta]] and [[missing-page]].\n\n![[diagram.png]]\n",
        encoding="utf-8")
    (root / "wiki" / "concepts" / "beta.md").write_text(
        "---\ntitle: Alpha\ntype: concept\n---\n\n# Beta\n",
        encoding="utf-8")
    (root / "wiki" / "concepts" / "gamma.md").write_text(
        "# Gamma\n\nNo frontmatter, no inbound links.\n",
        encoding="utf-8")
    (root / "wiki" / "concepts" / "diagram.png").write_bytes(b"\x89PNG")
    return root


class VaultMapTests(unittest.TestCase):
    def test_records_carry_the_map_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            _text, header, records = vm.build_map(root)
            self.assertEqual(header["pages"], 5)
            alpha = records["wiki/concepts/alpha.md"]
            self.assertEqual(alpha["title"], "Alpha")
            self.assertEqual(alpha["outlinks"], ["wiki/concepts/beta.md"])
            self.assertEqual(alpha["broken_links"], ["missing-page"])
            self.assertEqual(alpha["sources"], ["raw/sources/a.md"])
            beta = records["wiki/concepts/beta.md"]
            self.assertEqual(beta["backlinks"], ["wiki/concepts/alpha.md"])
            self.assertTrue(alpha["duplicate_title"])
            self.assertTrue(beta["duplicate_title"])
            gamma = records["wiki/concepts/gamma.md"]
            self.assertTrue(gamma["orphan"])
            self.assertEqual(gamma["title"], "Gamma")
            self.assertFalse(records["wiki/index.md"]["orphan"])
            emb = alpha["embeds"][0]
            self.assertEqual(emb["resolved"], "wiki/concepts/diagram.png")

    def test_deterministic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            first, _h, _r = vm.build_map(root)
            second, _h, _r = vm.build_map(root)
            self.assertEqual(first, second)
            lines = first.splitlines()
            self.assertEqual(json.loads(lines[0])["register"], "vault-map")

    def test_check_detects_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(tmp)
            out = root / "evaluation" / "vault-map.jsonl"
            out.parent.mkdir(parents=True)
            self.assertEqual(
                vm.main(["build", "--root", str(root), "--out", str(out)]), 0)
            self.assertEqual(
                vm.main(["check", "--root", str(root), "--out", str(out)]), 0)
            (root / "wiki" / "concepts" / "gamma.md").write_text(
                "# Gamma\n\nNow it links [[alpha]].\n", encoding="utf-8")
            self.assertEqual(
                vm.main(["check", "--root", str(root), "--out", str(out)]), 1)


if __name__ == "__main__":
    unittest.main()
