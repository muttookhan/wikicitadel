#!/usr/bin/env python3
"""Phase-2 harvest item 4: neighbour-evolution proposals
(pattern: agiresearch/A-mem, MIT). A changed page's stale
neighbour gets a PROPOSAL in gateway staging; the neighbour
itself is never edited; a current neighbour gets nothing.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gateway"))
spec = importlib.util.spec_from_file_location(
    "wiki_evolve", ROOT / "scripts" / "wiki_evolve.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
from gateway.config import Config  # noqa: E402
from gateway.store import GatewayStore  # noqa: E402

CHANGED = """---
title: Irrigation Scheduling
type: concept
created: 2030-10-01
updated: 2030-10-13
sources: [raw/sources/new-evidence.md]
tags: [fixture]
---

The irrigation scheduling method now uses soil moisture telemetry.
See [[stale-neighbour]] and [[fresh-neighbour]].
"""

STALE = """---
title: Stale Neighbour
type: concept
created: 2030-09-01
updated: 2030-10-01
sources: [raw/sources/old-evidence.md]
tags: [fixture]
---

An older framing of watering practice, linked to
[[irrigation-scheduling]].
"""

FRESH = """---
title: Fresh Neighbour
type: concept
created: 2030-10-01
updated: 2030-10-13
sources: [raw/sources/new-evidence.md]
tags: [fixture]
---

Current framing: irrigation scheduling with soil moisture
telemetry, linked to [[irrigation-scheduling]].
"""


class TestEvolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for sub in ("wiki/concepts", "raw/sources", "staging", "state"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "wiki/concepts/irrigation-scheduling.md").write_text(
            CHANGED, encoding="utf-8")
        (self.root / "wiki/concepts/stale-neighbour.md").write_text(
            STALE, encoding="utf-8")
        (self.root / "wiki/concepts/fresh-neighbour.md").write_text(
            FRESH, encoding="utf-8")
        env = {"GATEWAY_WIKI_ROOT": str(self.root),
               "GATEWAY_STAGING_DIR": str(self.root / "staging"),
               "GATEWAY_STATE_DIR": str(self.root / "state"),
               "GATEWAY_REGISTRY": str(self.root / "state" / "registry.json"),
               "GATEWAY_PROFILE": str(self.root / "absent-profile.json")}
        self.store = GatewayStore(Config(env=env))

    def tearDown(self):
        self.tmp.cleanup()

    def test_stale_neighbour_gets_proposal_fresh_gets_none(self):
        emitted = ev.evolve(self.store, "wiki/concepts/irrigation-scheduling.md")
        targets = {e["neighbour"] for e in emitted}
        self.assertEqual(targets, {"wiki/concepts/stale-neighbour.md"})
        entry = emitted[0]
        kinds = {s["signal"] for s in entry["signals"]}
        self.assertIn("predates-change", kinds)
        self.assertIn("evidence-divergence", kinds)
        # The canonical neighbour is UNEDITED.
        on_disk = (self.root / "wiki/concepts/stale-neighbour.md").read_text(
            encoding="utf-8")
        self.assertEqual(on_disk, STALE)
        # The proposal carries the original text + the review note.
        meta = self.store.get_proposal(entry["proposal_id"])
        staged = (self.store.proposed
                  / f"{entry['proposal_id']}.md").read_text(encoding="utf-8")
        self.assertIn("An older framing of watering practice", staged)
        self.assertIn("Framing review", staged)
        self.assertEqual(meta["submitted_by"], "wiki-evolve")


if __name__ == "__main__":
    unittest.main()
