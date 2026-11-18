#!/usr/bin/env python3
"""Forgetting battery (landscape weekly 2026-10-27; Bemula pattern).

Pins: the QUERY-match rule (phrase contiguity; the >= half and
>= 3 distinctive-terms threshold), paraphrase-probe generation,
and the battery's four properties against fixture trees —
including both Bemula failure modes (a severed page deleted =
erasure, not deactivation; a control page severed =
over-deletion).

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
    "wiki_forgetting_check", ROOT / "scripts" / "wiki_forgetting_check.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ENTRY = {
    "id": "sev-0001", "page": "wiki/a.md",
    "claim": "The seat stays shut",
    "cues": {"phrases": [["seat", "stays", "shut"], ["seat", "is", "shut"]],
             "distinctive_terms": ["seat", "shut", "stays"]},
}


def fixture_tree(tmp: Path, severed_page_exists=True, control_severed=False):
    (tmp / "evaluation").mkdir(parents=True)
    (tmp / "wiki").mkdir()
    if severed_page_exists:
        (tmp / "wiki" / "a.md").write_text("history\n", encoding="utf-8")
    (tmp / "wiki" / "live.md").write_text("live\n", encoding="utf-8")
    entries = [ENTRY]
    if control_severed:
        entries.append({"id": "sev-0002", "page": "wiki/live.md",
                        "claim": "x", "cues": {"phrases": [],
                                               "distinctive_terms": ["x"]}})
    (tmp / "evaluation" / "retrieval-severance.json").write_text(
        json.dumps({"entries": entries}), encoding="utf-8")
    (tmp / "evaluation" / "forgetting-battery.jsonl").write_text(
        json.dumps({"kind": "control", "page": "wiki/live.md"}) + "\n",
        encoding="utf-8")


class QueryMatchTests(unittest.TestCase):
    def test_phrase_contiguous(self):
        self.assertTrue(mod.query_match("the seat stays shut today", ENTRY))

    def test_term_threshold(self):
        self.assertTrue(mod.query_match("explain stays seat shut please", ENTRY))
        self.assertFalse(mod.query_match("seat only", ENTRY))

    def test_probes_generated(self):
        probes = mod.paraphrase_probes(ENTRY)
        self.assertEqual(len(probes), 2)
        for p in probes:
            self.assertTrue(mod.query_match(p, ENTRY))


class BatteryTests(unittest.TestCase):
    def test_healthy_tree_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fixture_tree(tmp)
            rep = mod.run(tmp)
            self.assertEqual(rep["failures"], [])

    def test_erasure_is_a_failure(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fixture_tree(tmp, severed_page_exists=False)
            kinds = {f["kind"] for f in mod.run(tmp)["failures"]}
            self.assertIn("stored", kinds)

    def test_over_deletion_is_a_failure(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fixture_tree(tmp, control_severed=True)
            kinds = {f["kind"] for f in mod.run(tmp)["failures"]}
            self.assertIn("preservation", kinds)


if __name__ == "__main__":
    unittest.main()
