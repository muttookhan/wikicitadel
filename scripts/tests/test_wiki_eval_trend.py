#!/usr/bin/env python3
"""Tests for scripts/wiki_eval_trend.py (Marathon R2 lane B2):
deterministic oldest->newest ordering, missing-field runs listed
as gaps (never dropped, never plotted with invented values), and
a byte-stable SVG."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


trend = _load("wiki_eval_trend")


def _run(label, date, docs, c10, mrr):
    return {"label": label, "generated_at": f"{date}T00:00:00+00:00",
            "corpus_docs": docs,
            "aggregates": {"citation_coverage": {"@10": c10},
                           "mrr_must_cite": mrr}}


class TestTrend(unittest.TestCase):
    def _dir(self, files):
        tmp = tempfile.TemporaryDirectory()
        for name, data in files.items():
            (Path(tmp.name) / name).write_text(
                json.dumps(data), encoding="utf-8")
        return tmp

    def test_oldest_to_newest_regardless_of_filename(self):
        tmp = self._dir({
            "b-newer.json": _run("newer", "2026-10-19", 71, 0.93, 0.43),
            "a-older.json": _run("older", "2026-10-13", 46, 1.0, 0.42),
        })
        with tmp:
            runs, gaps = trend.collect(tmp.name)
        self.assertEqual([r["label"] for r in runs], ["older", "newer"])
        self.assertEqual(gaps, [])

    def test_missing_fields_are_gaps_not_drops(self):
        tmp = self._dir({
            "good-2026-10-13.json": _run("good", "2026-10-13", 46, 1.0, 0.4),
            "no-mrr.json": {"label": "no-mrr",
                            "generated_at": "2026-10-14T00:00:00+00:00",
                            "corpus_docs": 50,
                            "aggregates": {"citation_coverage": {"@10": 0.5}}},
            "no-date-no-docs.json": {"label": "bare", "aggregates": {}},
            "scale-bench.json": {"kind": "scale-bench",
                                 "generated_at": "2026-10-20T00:00:00+00:00",
                                 "rows": [{"docs": 100, "median_ms": 4.7}]},
        })
        with tmp:
            runs, gaps = trend.collect(tmp.name)
        self.assertEqual([r["label"] for r in runs], ["good"])
        gap_sources = {g["source"] for g in gaps}
        self.assertEqual(gap_sources, {"no-mrr.json", "no-date-no-docs.json",
                                       "scale-bench.json"})
        md = trend.render_markdown(runs, gaps)
        self.assertIn("## Gaps", md)
        self.assertIn("no-mrr.json", md)

    def test_svg_is_deterministic_and_carries_both_series(self):
        runs = [
            {"date": "2026-10-13", "label": "a", "source": "a.json",
             "corpus_docs": 46, "coverage10": 1.0, "mrr": 0.42},
            {"date": "2026-10-19", "label": "b", "source": "b.json",
             "corpus_docs": 71, "coverage10": 0.93, "mrr": 0.43},
        ]
        svg1, svg2 = trend.render_svg(runs), trend.render_svg(runs)
        self.assertEqual(svg1, svg2)
        self.assertEqual(svg1.count("<polyline"), 2)
        self.assertIn("coverage@10", svg1)

    def test_empty_inputs_still_render(self):
        self.assertIn("No plottable runs", trend.render_svg([]))
        self.assertIn("None", trend.render_markdown([], []))


if __name__ == "__main__":
    unittest.main()
