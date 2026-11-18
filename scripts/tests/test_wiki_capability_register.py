#!/usr/bin/env python3
"""Capability register tool: validation, verdict vocabulary,
the rejected-owes-a-reason rule, and latest-row-per-id standing.

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
    "wiki_capability_register", ROOT / "scripts" / "wiki_capability_register.py")
reg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reg)

HEADER = {"kind": "header", "register": "capabilities", "version": 1,
          "created": "2026-10-22"}


def row(**kw):
    base = {"kind": "capability", "id": "cap-01", "capability": "X",
            "best_source": {"name": "Some Source", "licence": "MIT"},
            "verdict": "idea", "reason": "", "status": "Built.",
            "artefacts": ["scripts/x.py"], "source_ref": "raw/x.md §1",
            "recorded": "2026-10-22"}
    base.update(kw)
    return base


def write(tmp, rows):
    p = Path(tmp) / "capability-register.jsonl"
    lines = [json.dumps(HEADER)] + [json.dumps(r) for r in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class CapabilityRegisterTests(unittest.TestCase):
    def test_valid_register_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, [row(), row(id="cap-02", verdict="rejected",
                                       reason="by design")])
            _rows, errors = reg.load_register(p)
            self.assertEqual(errors, [])
            rep = reg.build_report(p)
            self.assertEqual(rep["counts"]["idea"], 1)
            self.assertEqual(rep["counts"]["rejected"], 1)

    def test_rejected_without_reason_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, [row(verdict="rejected", reason="")])
            _rows, errors = reg.load_register(p)
            self.assertTrue(any("owes its reason" in e for e in errors))

    def test_unknown_verdict_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, [row(verdict="maybe")])
            _rows, errors = reg.load_register(p)
            self.assertTrue(any("verdict" in e for e in errors))

    def test_missing_licence_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = row()
            bad["best_source"] = {"name": "Some Source", "licence": ""}
            p = write(tmp, [bad])
            _rows, errors = reg.load_register(p)
            self.assertTrue(any("licence" in e for e in errors))

    def test_latest_row_per_id_stands(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, [row(status="Open."),
                            row(status="Built.", verdict="code")])
            rep = reg.build_report(p)
            self.assertEqual(rep["current"], 1)
            self.assertEqual(rep["superseded_rows"], 1)
            self.assertEqual(rep["counts"]["code"], 1)

    def test_add_appends_a_valid_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, [])
            rc = reg.main(["add", "--register", str(p), "--id", "cap-09",
                           "--capability", "Y", "--source-name", "S",
                           "--licence", "Apache-2.0", "--verdict", "idea",
                           "--status", "Built."])
            self.assertEqual(rc, 0)
            _rows, errors = reg.load_register(p)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
