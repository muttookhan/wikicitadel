#!/usr/bin/env python3
"""in-toto attestation for checkpoints — PILOT (Marathon R8).

Pins scripts/wiki_checkpoint_attestation.py on fixtures: a
signed layout names which agent may perform which step; a
link by an unauthorised agent is refused at build time and
fails at verify time; links chain source hashes to
compiled-page hashes by prev_link_hash; a tampered product,
a re-ordered chain and a forged layout signature all fail.
The pilot is additive — the checkpoint register and format
are untouched, which a test asserts by shape.
Run: python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


at = load("wiki_checkpoint_attestation",
          "scripts/wiki_checkpoint_attestation.py")
KEY = b"pilot-fixture-key-not-a-real-secret"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="intoto-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "src.md").write_text("source bytes\n",
                                         encoding="utf-8")
        (self.root / "page.md").write_text("compiled bytes\n",
                                          encoding="utf-8")
        self.layout = at.sign_layout(at.build_layout(
            {"ingest": ["agent-a"], "compile": ["agent-a", "agent-b"]},
            signer="layout-signer", expires="2027-01-01"), KEY)


class TestLayout(Fixture):
    def test_layout_is_labelled_pilot_and_signed(self):
        self.assertIn("PILOT", self.layout["pilot"])
        self.assertEqual(at.verify_layout_signature(self.layout, KEY), [])

    def test_forged_layout_fails_signature(self):
        forged = dict(self.layout)
        forged["steps"] = [{"name": "ingest",
                            "authorised_by": ["mallory"],
                            "expected_materials": [],
                            "expected_products": []}]
        self.assertTrue(at.verify_layout_signature(forged, KEY))
        self.assertTrue(at.verify_layout_signature(self.layout,
                                                   b"wrong-key"))


class TestLinks(Fixture):
    def _links(self):
        l1 = at.make_link(self.layout, "ingest", "agent-a",
                          [], ["src.md"], root=self.root)
        l2 = at.make_link(self.layout, "compile", "agent-b",
                          ["src.md"], ["page.md"], prev_link=l1,
                          root=self.root)
        return [l1, l2]

    def test_chain_verifies_source_to_compiled(self):
        self.assertEqual(
            at.verify_chain(self.layout, self._links(),
                            root=self.root, key=KEY), [])

    def test_unauthorised_agent_refused_and_fails(self):
        with self.assertRaises(ValueError):
            at.make_link(self.layout, "ingest", "agent-b",
                         [], ["src.md"], root=self.root)
        links = self._links()
        links[0]["by"] = "agent-b"
        problems = at.verify_chain(self.layout, links,
                                   root=self.root, key=KEY)
        self.assertTrue(any("not authorised" in p for p in problems))

    def test_tampered_product_and_reordered_chain_fail(self):
        links = self._links()
        (self.root / "page.md").write_text("altered\n", encoding="utf-8")
        problems = at.verify_chain(self.layout, links,
                                   root=self.root, key=KEY)
        self.assertTrue(any("hash mismatch" in p for p in problems))
        problems = at.verify_chain(self.layout, list(reversed(links)),
                                   root=self.root, key=KEY)
        self.assertTrue(any("prev_link_hash" in p for p in problems))

    def test_pilot_does_not_touch_checkpoint_register_shape(self):
        # Additive means additive: no existing checkpoint line
        # gains an in-toto field from this module existing.
        import json
        reg = ROOT / "evaluation" / "checkpoints.jsonl"
        if reg.exists():
            for line in reg.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.assertNotIn("intoto", line)


if __name__ == "__main__":
    unittest.main()
