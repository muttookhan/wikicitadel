#!/usr/bin/env python3
"""Eval-gate tests (the build): promotion precondition on the
extended eval, plus the recorded owner override.

Proves:
- evalgate.check: unarmed without a baseline; pass on a clean
  report; block on a regressed report, a missing report, a
  malformed baseline, and a missing gated metric; no block inside
  epsilon;
- store.promote: a regressed report blocks promotion with the
  reason in the eval-gate ledger (chain verifies); a clean report
  lets the full propose -> review -> authorise -> promote flow
  through and stamps the gate verdict on the proposal;
- the override: reason mandatory; a recorded override lets one
  blocked promotion through, stamps itself on the proposal, marks
  itself used (single-use), and writes both its recording and its
  use to the eval-gate ledger.

Run:  python3 -m unittest discover -s tests -v   (from tools/gateway)
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
GW_DIR = HERE.parents[1]
sys.path.insert(0, str(GW_DIR))

from fixtures.make_fixtures import build_fixture  # noqa: E402
from gateway import evalgate, ledger as ledger_mod  # noqa: E402
from gateway.config import Config  # noqa: E402
from gateway.registry import Registry  # noqa: E402
from gateway.store import GatewayStore, StoreError  # noqa: E402

BASELINE = {
    "schema": "extended-eval-baseline/1",
    "epsilon": 0.02,
    "abstain_threshold": 1.0,
    "gated_metrics": {
        "citation_coverage@10": 0.90,
        "hit_rate_topk": 0.90,
        "mrr_must_cite": 0.70,
        "abstention_rate": 0.50,
    },
}


def report(coverage=0.95, hit=0.95, mrr=0.75, abstention=0.60):
    return {
        "label": "extended-latest",
        "generated_at": "2026-10-20T00:00:00-04:00",
        "git_head": "fixture",
        "aggregates": {
            "citation_coverage": {"@1": 0.5, "@3": 0.8, "@5": 0.9, "@10": coverage},
            "hit_rate_topk": hit,
            "mrr_must_cite": mrr,
        },
        "abstention": {"abstention_rate": abstention},
    }


def write(root: Path, rel: str, obj) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


class TestEvalGateCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_armed_without_baseline(self):
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "not_armed")

    def test_pass_on_clean_report(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        write(self.root, "evaluation/results/extended-latest.json", report())
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "pass", out)

    def test_block_on_regression_beyond_epsilon(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        write(self.root, "evaluation/results/extended-latest.json",
              report(coverage=0.80))
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")
        self.assertTrue(any("citation_coverage@10" in r for r in out["reasons"]))

    def test_no_block_inside_epsilon(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        write(self.root, "evaluation/results/extended-latest.json",
              report(coverage=0.885))  # 0.015 below baseline 0.90 < epsilon 0.02
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "pass", out)

    def test_block_when_report_missing(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")
        self.assertTrue(any("no usable extended eval report" in r
                            for r in out["reasons"]))

    def test_block_on_malformed_baseline(self):
        p = self.root / "evaluation" / "extended-baseline.json"
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")

    def test_block_on_missing_gated_metric(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        bad = report()
        bad["abstention"] = {"abstention_rate": None}
        write(self.root, "evaluation/results/extended-latest.json", bad)
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")
        self.assertTrue(any("abstention_rate" in r for r in out["reasons"]))


class TestEvalGatePromotion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = build_fixture(Path(self.tmp.name))
        self.root = self.fx["root"]
        self.eval_dir = Path(self.tmp.name) / "eval"
        self.baseline_path = write(self.eval_dir, "baseline.json", BASELINE)
        self.report_path = write(self.eval_dir, "extended-latest.json", report())

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self):
        env = dict(self.fx["env"])
        env["GATEWAY_EVAL_BASELINE"] = str(self.baseline_path)
        env["GATEWAY_EVAL_REPORT"] = str(self.report_path)
        cfg = Config(env=env)
        cfg.wiki_root = self.fx["root"]
        cfg.state_dir = self.fx["state_dir"]
        cfg.registry_path = self.fx["state_dir"] / "registry.json"
        cfg.ledger_dir = self.fx["state_dir"] / "ledger"
        cfg.staging_dir = self.fx["state_dir"] / "staging"
        cfg.reviews_dir = self.fx["state_dir"] / "reviews"
        cfg.authorisations_dir = self.fx["state_dir"] / "authorisations"
        cfg.eval_overrides_dir = self.fx["state_dir"] / "eval-overrides"
        cfg.anchors_dir = self.fx["state_dir"] / "anchors"
        cfg.git_commit = True
        cfg.ensure_state_dirs()
        return GatewayStore(cfg), cfg

    def _promotable(self, store):
        meta = store.stage_proposal(
            actor="collaborator-a", session_id="evalgate", target_path="wiki/concepts/gated.md",
            content="# Gated\n\nStaged content.\n", cites=[],
            direction_source={"kind": "owner"}, task_ref="fixture")
        pid = meta["proposal_id"]
        store.write_review(pid, "agent", None)
        store.write_authorisation(pid, "owner", None)
        entry = Registry(store.cfg.registry_path).authenticate(
            self.fx["tokens"]["agent"])
        return pid, entry

    def _gate_ledger(self, cfg):
        files = sorted(cfg.ledger_dir.glob("eval-gate-*.jsonl"))
        self.assertEqual(len(files), 1)
        return files[0]

    def test_clean_report_promotes_and_stamps_gate(self):
        store, cfg = self._store()
        pid, entry = self._promotable(store)
        out = store.promote(pid, entry)
        self.assertEqual(out["proposal"]["state"], "promoted")
        self.assertEqual(out["proposal"]["eval_gate"]["status"], "pass")
        self.assertTrue((self.root / "wiki/concepts/gated.md").exists())

    def test_regression_blocks_and_ledgers_reason(self):
        write(self.eval_dir, "extended-latest.json", report(mrr=0.40))
        store, cfg = self._store()
        pid, entry = self._promotable(store)
        with self.assertRaises(StoreError) as ctx:
            store.promote(pid, entry)
        self.assertIn("eval gate", str(ctx.exception))
        self.assertIn("mrr_must_cite", str(ctx.exception))
        self.assertFalse((self.root / "wiki/concepts/gated.md").exists())
        # The block is in the eval-gate ledger, and the chain verifies.
        ledger_file = self._gate_ledger(cfg)
        entries = ledger_mod.read_entries(ledger_file)
        blocks = [e for e in entries if e["action"] == "eval_gate_block"]
        self.assertEqual(len(blocks), 1)
        self.assertTrue(any("mrr_must_cite" in r for r in blocks[0]["reasons"]))
        self.assertTrue(ledger_mod.verify_chain(ledger_file)["ok"])

    def test_override_requires_reason(self):
        store, _cfg = self._store()
        with self.assertRaises(StoreError):
            store.write_eval_override("prop-x", "owner", "   ")

    def test_override_records_itself_and_is_single_use(self):
        write(self.eval_dir, "extended-latest.json", report(coverage=0.50))
        store, cfg = self._store()
        pid, entry = self._promotable(store)
        with self.assertRaises(StoreError):
            store.promote(pid, entry)
        store.write_eval_override(pid, "owner", "shipping the fix tonight; eval rerun scheduled")
        out = store.promote(pid, entry)
        self.assertEqual(out["proposal"]["state"], "promoted")
        self.assertEqual(out["proposal"]["eval_gate"]["status"], "override")
        # Override record is spent.
        self.assertIsNone(store._read_eval_override(pid))
        rec = json.loads((cfg.eval_overrides_dir / f"{pid}.json").read_text())
        self.assertIsNotNone(rec["used_at"])
        # Both the recording and the use are in the eval-gate ledger.
        entries = ledger_mod.read_entries(self._gate_ledger(cfg))
        actions = [e["action"] for e in entries]
        self.assertIn("eval_gate_override", actions)
        self.assertIn("eval_gate_override_used", actions)
        ov = next(e for e in entries if e["action"] == "eval_gate_override")
        self.assertIn("shipping the fix tonight", ov["reason"])
        self.assertTrue(ledger_mod.verify_chain(self._gate_ledger(cfg))["ok"])

    def test_unarmed_fixture_promotes_as_before(self):
        # No baseline anywhere: the gate is inert (existing behaviour).
        env = dict(self.fx["env"])
        cfg = Config(env=env)
        cfg.eval_baseline_path = Path(self.tmp.name) / "absent-baseline.json"
        cfg.eval_report_path = Path(self.tmp.name) / "absent-report.json"
        store = GatewayStore(cfg)
        pid, entry = self._promotable(store)
        out = store.promote(pid, entry)
        self.assertEqual(out["proposal"]["state"], "promoted")
        self.assertNotIn("eval_gate", out["proposal"])


class TestEvalGateGuidance(unittest.TestCase):
    """Item 41: a block coaches — it names the metric, the
    delta, and the evidence that would change the verdict.
    Verdicts are exactly the pre-guidance ones (the sibling
    classes above pin them again on the same fixtures)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_regression_guidance_names_metric_threshold_and_route(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        write(self.root, "evaluation/results/extended-latest.json",
              report(coverage=0.80))
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")
        self.assertEqual(len(out["guidance"]), len(out["reasons"]))
        g = out["guidance"][0]
        self.assertIn("citation_coverage@10", g)
        self.assertIn("0.88", g)  # baseline 0.90 - epsilon 0.02
        self.assertIn("wiki_eval_extended.py", g)
        self.assertIn("override", g)

    def test_missing_metric_guidance(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        bad = report()
        bad["abstention"] = {"abstention_rate": None}
        write(self.root, "evaluation/results/extended-latest.json", bad)
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")
        g = " ".join(out["guidance"])
        self.assertIn("abstention_rate", g)
        self.assertIn("baseline", g)

    def test_missing_report_and_malformed_baseline_guidance(self):
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")
        self.assertTrue(any("wiki_eval_extended.py" in g
                            for g in out["guidance"]))
        p = self.root / "evaluation" / "extended-baseline.json"
        p.write_text("{not json", encoding="utf-8")
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "block")
        self.assertTrue(any("extended-baseline.json" in g
                            for g in out["guidance"]))

    def test_pass_and_not_armed_carry_no_blocking_guidance(self):
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "not_armed")
        self.assertEqual(out["reasons"], [])
        write(self.root, "evaluation/extended-baseline.json", BASELINE)
        write(self.root, "evaluation/results/extended-latest.json",
              report())
        out = evalgate.check(self.root)
        self.assertEqual(out["status"], "pass")
        self.assertEqual(out["guidance"], [])

    def test_block_ledger_and_error_carry_the_coaching(self):
        fx_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(fx_tmp.cleanup)
        fx = build_fixture(Path(fx_tmp.name))
        eval_dir = Path(fx_tmp.name) / "eval"
        baseline_path = write(eval_dir, "baseline.json", BASELINE)
        write(eval_dir, "extended-latest.json", report(mrr=0.40))
        env = dict(fx["env"])
        env["GATEWAY_EVAL_BASELINE"] = str(baseline_path)
        env["GATEWAY_EVAL_REPORT"] = str(
            eval_dir / "extended-latest.json")
        cfg = Config(env=env)
        cfg.wiki_root = fx["root"]
        cfg.state_dir = fx["state_dir"]
        cfg.registry_path = fx["state_dir"] / "registry.json"
        cfg.ledger_dir = fx["state_dir"] / "ledger"
        cfg.staging_dir = fx["state_dir"] / "staging"
        cfg.reviews_dir = fx["state_dir"] / "reviews"
        cfg.authorisations_dir = fx["state_dir"] / "authorisations"
        cfg.eval_overrides_dir = fx["state_dir"] / "eval-overrides"
        cfg.anchors_dir = fx["state_dir"] / "anchors"
        cfg.git_commit = True
        cfg.ensure_state_dirs()
        store = GatewayStore(cfg)
        meta = store.stage_proposal(
            actor="collaborator-a", session_id="evalgate-guidance",
            target_path="wiki/concepts/gated.md",
            content="# Gated\n\nStaged content.\n", cites=[],
            direction_source={"kind": "owner"}, task_ref="fixture")
        pid = meta["proposal_id"]
        store.write_review(pid, "agent", None)
        store.write_authorisation(pid, "owner", None)
        entry = Registry(store.cfg.registry_path).authenticate(
            fx["tokens"]["agent"])
        with self.assertRaises(StoreError) as ctx:
            store.promote(pid, entry)
        self.assertIn("mrr_must_cite", str(ctx.exception))
        self.assertIn("Coaching", str(ctx.exception))
        files = sorted(cfg.ledger_dir.glob("eval-gate-*.jsonl"))
        entries = ledger_mod.read_entries(files[0])
        blocks = [e for e in entries
                  if e["action"] == "eval_gate_block"]
        self.assertEqual(len(blocks), 1)
        self.assertTrue(any("mrr_must_cite" in g
                            for g in blocks[0]["guidance"]))


if __name__ == "__main__":
    unittest.main()
