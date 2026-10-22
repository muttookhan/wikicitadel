"""Tests for scripts/wiki_corrections_lifecycle.py
(build-list wave 5, 2026-10-22)."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load():
    s = importlib.util.spec_from_file_location(
        "wiki_corrections_lifecycle",
        SCRIPTS / "wiki_corrections_lifecycle.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


MOD = load()

LEDGER = """# Corrections ledger (fixture)

## Entries

### 2026-01-01 — Alpha error

- **What was wrong:** the alpha count was asserted from a
  summary; the artifact held a different number.
- **Standing rule:** alpha counts are read from the
  artifact on disk, never from a summary.
- **Recorded:** [[alpha-fix]]; raw record
  `raw/sources/alpha.md`; fix commit `abc1234`.

### 2026-01-02 — Beta error

- **What was wrong:** the beta deadline was stated a day
  late.
- **Standing rule:** beta deadlines are quoted from the
  notice itself.
- **Recorded:** [[beta-fix]].

### 2026-01-03 — Gamma error again (recurrence of "Alpha error")

- **What was wrong:** an alpha count was again taken from
  a summary. This is the 2026-01-01 rule-alpha rule
  recurring — counted as a recurrence under that rule,
  not a new rule.
- **Standing rule:** alpha counts are read from the
  artifact on disk, never from a summary.
- **Recorded:** [[gamma-fix]].

### 2026-01-04 — Delta verdict change

- **What was wrong:** nothing was misstated; the beta
  ruling itself changed. This entry supersedes the
  2026-01-02 — Beta error ruling: beta deadlines are
  now quoted from the register, not the notice.
- **Standing rule:** beta deadlines are quoted from the
  register.
- **Recorded:** [[delta-note]].

### 2026-01-05 — Epsilon open case

- **What was wrong:** the epsilon figure was wrong.
- **Standing rule:** epsilon figures are checked twice
  before they are stated.
- **Recorded:** noted in the session log at the time.

### 2026-01-06 — Zeta ungrounded

- **What was wrong:** the zeta claim was wrong, and this
  entry was filed without its rule or its record.

### 2026-01-07 — Eta surface rule

- **What was wrong:** the eta valve was started unchecked.
- **Standing rule:** always check the frobnicate valve
  before starting the engine.
- **Recorded:** [[eta-fix]].

## Classification

| Entry | Class | Error kind | Standing rule |
|---|---|---|---|
| 2026-01-01 — Alpha error | correction | wrong-fact | rule-alpha |
| 2026-01-02 — Beta error | correction | wrong-date | rule-beta |
| 2026-01-03 — Gamma error again (recurrence of "Alpha error") | correction | wrong-fact | rule-alpha (RECURRENCE of the 2026-01-01 Alpha error entry) |
| 2026-01-04 — Delta verdict change | verdict-change | stale-after-change | rule-delta |
| 2026-01-05 — Epsilon open case | correction | wrong-fact | rule-epsilon |
| 2026-01-07 — Eta surface rule | correction | wrong-fact | rule-eta |
"""

SURFACE = ("# Standing guidance (fixture)\n\n"
           "Standing guidance: check the frobnicate valve "
           "before starting any run, every time.\n")

OUTCOMES = [
    {"entry": "2026-01-01 — Alpha error", "retrieved": True,
     "heeded": True, "recurred": False,
     "recorded": "2026-01-10", "note": "fixture"},
    {"entry": "2026-01-05 — Epsilon open case",
     "retrieved": False, "heeded": None, "recurred": True,
     "recorded": "2026-01-12", "note": "fixture"},
]

ALPHA = "2026-01-01 — Alpha error"
BETA = "2026-01-02 — Beta error"
GAMMA = ('2026-01-03 — Gamma error again '
         '(recurrence of "Alpha error")')
DELTA = "2026-01-04 — Delta verdict change"
EPSILON = "2026-01-05 — Epsilon open case"
ZETA = "2026-01-06 — Zeta ungrounded"
ETA = "2026-01-07 — Eta surface rule"


def fixture_report(root, surface):
    outcomes = {}
    for o in OUTCOMES:
        outcomes.setdefault(o["entry"], []).append(o)
    return MOD.build_report(LEDGER, outcomes, date(2026, 1, 31),
                            root, extra_surfaces=[surface])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.surface = self.root / "guidance.md"
        self.surface.write_text(SURFACE, encoding="utf-8")
        self.rep = fixture_report(self.root, self.surface)
        self.rows = {r["entry"]: r for r in self.rep["entries"]}

    def tearDown(self):
        self._td.cleanup()

    def test_states_cover_the_closed_set(self):
        self.assertEqual(self.rows[ALPHA]["state"], "promoted-to-rule")
        self.assertEqual(self.rows[BETA]["state"],
                         "superseded-by-later-entry")
        self.assertEqual(self.rows[GAMMA]["state"], "acted-on")
        self.assertEqual(self.rows[DELTA]["state"], "acted-on")
        self.assertEqual(self.rows[EPSILON]["state"], "open")
        self.assertEqual(self.rows[ZETA]["state"], "unstated")
        self.assertEqual(self.rows[ETA]["state"], "promoted-to-rule")
        self.assertEqual(sum(self.rep["by_state"].values()), 7)
        self.assertEqual(self.rep["unclassified"], [ZETA])

    def test_promotion_evidence_is_cited(self):
        ev = self.rows[ALPHA]["state_evidence"]
        self.assertTrue(any(e["ref"] == GAMMA for e in ev))
        ev_eta = self.rows[ETA]["state_evidence"]
        self.assertTrue(any(e.get("surface", "").endswith("guidance.md")
                            for e in ev_eta))

    def test_gate_hardens_only_on_recurrence(self):
        g = self.rep["rules_gate"]["rule-alpha"]
        self.assertEqual(g["posture"], "blocking")
        self.assertEqual(g["originating_feedback"]["first_ruled"],
                         ALPHA)
        self.assertEqual(g["originating_feedback"]["hardened_by"],
                         GAMMA)
        self.assertEqual(self.rows[ALPHA]["gate"]["posture"],
                         "blocking")
        self.assertEqual(self.rows[DELTA]["gate"]["posture"],
                         "warning")
        # the outcomes register can harden a gate on its own
        self.assertEqual(self.rows[EPSILON]["gate"]["posture"],
                         "blocking")

    def test_evidence_grades(self):
        a = self.rows[ALPHA]
        self.assertTrue(a["evidence_rungs"]["landed"])
        self.assertTrue(a["evidence_rungs"]["reuse-observed"])
        self.assertTrue(a["evidence_rungs"]["measured-heeded"])
        # top grade needs every rung — not this entry's
        self.assertEqual(a["grade"], "measured-heeded")
        self.assertEqual(self.rows[ETA]["grade"], "landed")
        self.assertEqual(self.rows[ZETA]["grade"], "recorded")

    def test_trends(self):
        t = self.rep["trends"]
        self.assertEqual(t["by_month"]["2026-01"]["entries"], 7)
        self.assertEqual(
            t["repeat_offence_rules"]["rule-alpha"], [ALPHA, GAMMA])
        self.assertTrue(any(
            r["title"].startswith("Gamma")
            for r in t["repeated_since_ruled"]))
        self.assertEqual(t["span"]["first"], "2026-01-01")
        self.assertEqual(t["span"]["days_since_latest"], 24)

    def test_promotion_candidates(self):
        cands = {c["entry"] for c in self.rep["promotion_candidates"]}
        self.assertIn(DELTA, cands)
        self.assertNotIn(GAMMA, cands)    # its rule is promoted
        self.assertNotIn(EPSILON, cands)  # still open
        self.assertNotIn(ETA, cands)      # already promoted

    def test_deterministic(self):
        again = fixture_report(self.root, self.surface)
        self.assertEqual(
            json.dumps(self.rep, sort_keys=True),
            json.dumps(again, sort_keys=True))

    def test_ledger_never_written(self):
        led = self.root / "ledger.md"
        led.write_text(LEDGER, encoding="utf-8")
        reg = self.root / "outcomes.jsonl"
        reg.write_text(
            "".join(json.dumps(o) + "\n" for o in OUTCOMES),
            encoding="utf-8")
        before = hashlib.sha256(led.read_bytes()).hexdigest()
        rc = MOD.main(["report", "--ledger", str(led),
                       "--register", str(reg),
                       "--root", str(self.root),
                       "--today", "2026-01-31",
                       "--surface", str(self.surface),
                       "--out", str(self.root / "artefact.json")])
        self.assertEqual(rc, 0)
        after = hashlib.sha256(led.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        art = json.loads(
            (self.root / "artefact.json").read_text(encoding="utf-8"))
        self.assertEqual(art["ledger_sha256"], before)


class RealLedgerTests(unittest.TestCase):
    def test_real_ledger(self):
        ledger = ROOT / "wiki/rules/corrections-ledger.md"
        if not ledger.is_file():
            self.skipTest("this tree has no corrections ledger")
        text = ledger.read_text(encoding="utf-8")
        outcomes = MOD.load_outcomes(
            ROOT / "evaluation/correction-outcomes.jsonl")
        rep = MOD.build_report(text, outcomes, date(2026, 10, 22),
                               ROOT)
        # WikiCitadel's ledger stands empty (created
        # 2026-10-22 with the lifecycle port; the private
        # tree's entries are its own record and never port).
        # The private copy of this test pins that ledger's
        # counts and recurrences; here the honest pins are
        # the zero state and the consistency invariants.
        self.assertEqual(rep["entries_total"], 0)
        self.assertEqual(sum(rep["by_state"].values()),
                         rep["entries_total"])
        for r in rep["entries"]:
            self.assertIn(r["state"], MOD.STATES)
            self.assertIn(r["grade"], MOD.GRADE_ORDER)
        self.assertEqual(rep["unclassified"], [])


if __name__ == "__main__":
    unittest.main()
