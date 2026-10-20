#!/usr/bin/env python3
"""Tests for scripts/wiki_forecast.py (consolidated-queue
item 39: the Brier forecast register).

Pins the contract on a FIXTURE repo in a temp dir:

  - the register is hash-chained: verify passes on a
    freshly built register and FAILS after a line is
    altered;
  - THE RULE: an entry naming the OWNER as forecaster is
    refused (exit 2) and nothing is appended — the
    register scores the agent's judgements only, never
    the owner's;
  - probabilities at the endpoints (0, 1) are refused —
    the estimative lexicon runs 1–99%;
  - resolve computes the Brier score exactly:
    (p − o)^2 — p=0.8/true → 0.04, p=0.3/false → 0.09 —
    and a second resolution of the same forecast is
    refused (append-only);
  - score aggregates: mean Brier over resolved, the
    open count, and a calibration row per band.

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
TOOL = "wiki_forecast.py"
REGISTER = "evaluation/forecasts.jsonl"


def run_tool(repo, *args):
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / TOOL),
         "--root", str(repo), *args],
        capture_output=True, text=True)


def read_register(repo):
    path = repo / REGISTER
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


class ForecastFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wiki-forecast-"))
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPTS / TOOL, self.repo / "scripts" / TOOL)
        (self.repo / "evaluation").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, forecaster="agent", statement="S", p="0.8",
            rdate="2030-10-21"):
        return run_tool(self.repo, "add", "--forecaster", forecaster,
                        "--statement", statement, "--probability", p,
                        "--resolution-date", rdate)

    def forecasts(self):
        return [o for o in read_register(self.repo)
                if o.get("kind") == "forecast"]

    def resolutions(self):
        return [o for o in read_register(self.repo)
                if o.get("kind") == "resolution"]

    # -- the chain ------------------------------------------------

    def test_chain_verifies_then_detects_tamper(self):
        self.assertEqual(self.add().returncode, 0)
        self.assertEqual(self.add(statement="T", p="0.3").returncode,
                         0)
        ok = run_tool(self.repo, "verify")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        path = self.repo / REGISTER
        lines = path.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[1])
        obj["probability"] = 0.99  # quietly improve the forecast
        lines[1] = json.dumps(obj, sort_keys=True,
                              separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        bad = run_tool(self.repo, "verify")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("BROKEN", bad.stdout)

    # -- the rule: never the owner --------------------------------

    def test_owner_as_forecaster_is_refused(self):
        for name in ("owner", "Owner", "The Owner"):
            r = self.add(forecaster=name)
            self.assertEqual(r.returncode, 2, name)
            self.assertIn("never the owner", r.stdout)
        self.assertEqual(self.forecasts(), [])
        # and an agent identity is accepted
        self.assertEqual(self.add(forecaster="agent").returncode, 0)
        self.assertEqual(len(self.forecasts()), 1)

    def test_probability_endpoints_are_refused(self):
        for p in ("0", "1", "-0.5", "1.5"):
            r = self.add(p=p)
            self.assertEqual(r.returncode, 2, p)
        self.assertEqual(self.forecasts(), [])

    def test_band_is_recorded_beside_the_probability(self):
        self.add(p="0.75")
        self.add(p="0.25", statement="U")
        bands = [f["lexicon_band"] for f in self.forecasts()]
        self.assertEqual(bands, ["likely / probable", "unlikely"])

    # -- resolution + Brier ----------------------------------------

    def test_resolve_computes_brier_exactly(self):
        self.add(p="0.8")                       # fc-0001
        self.add(p="0.3", statement="U")        # fc-0002
        r1 = run_tool(self.repo, "resolve", "fc-0001", "true",
                      "--date", "2030-10-21")
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        r2 = run_tool(self.repo, "resolve", "fc-0002", "false",
                      "--date", "2030-10-21")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        res = {r["forecast"]: r for r in self.resolutions()}
        self.assertAlmostEqual(res["fc-0001"]["brier"], 0.04,
                               places=6)   # (0.8 − 1)^2
        self.assertAlmostEqual(res["fc-0002"]["brier"], 0.09,
                               places=6)   # (0.3 − 0)^2
        # the forecast lines themselves were never edited
        self.assertTrue(all(f["resolution"] == "unresolved"
                            for f in self.forecasts()))

    def test_double_resolution_is_refused(self):
        self.add()
        self.assertEqual(
            run_tool(self.repo, "resolve", "fc-0001", "true")
            .returncode, 0)
        again = run_tool(self.repo, "resolve", "fc-0001", "false")
        self.assertEqual(again.returncode, 2)
        self.assertEqual(len(self.resolutions()), 1)

    def test_resolve_unknown_id_is_refused(self):
        self.add()
        r = run_tool(self.repo, "resolve", "fc-9999", "true")
        self.assertEqual(r.returncode, 2)

    # -- score -------------------------------------------------------

    def test_score_aggregates(self):
        self.add(p="0.8")                       # fc-0001
        self.add(p="0.3", statement="U")        # fc-0002
        self.add(p="0.6", statement="V")        # fc-0003 stays open
        run_tool(self.repo, "resolve", "fc-0001", "true")
        run_tool(self.repo, "resolve", "fc-0002", "false")
        out = run_tool(self.repo, "score")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        # mean of 0.04 and 0.09
        self.assertIn("0.0650", out.stdout)
        self.assertIn("2 resolved, 1 open", out.stdout)
        self.assertIn("very likely", out.stdout)   # fc-0001's band
        self.assertIn("unlikely", out.stdout)      # fc-0002's band
        self.assertIn("fc-0003", out.stdout)       # named as open

    def test_score_with_nothing_resolved_is_honest(self):
        self.add()
        out = run_tool(self.repo, "score")
        self.assertEqual(out.returncode, 0)
        self.assertIn("No resolved forecasts yet", out.stdout)


if __name__ == "__main__":
    unittest.main()
