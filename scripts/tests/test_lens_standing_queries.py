#!/usr/bin/env python3
"""Items 58 + 60: standing queries — the register, the build-time
diff, and the filing CLI.

The logic lives in tools/lens/lenslib.py (load/write the register,
run a query over a PostingsIndex-shaped object, diff hits against
the record's seen-snapshot and advance its last-looked stamp) and
scripts/wiki_standing_queries.py (the agent filing path — the
Lens itself is read-only, so a watch is filed, never saved by the
page). These tests pin the stamp discipline: a stamp advances
only in a build that reports the query — its first build (the
baseline, reported as a baseline, never as "new") or a build that
found new/changed hits — and a build that finds nothing new
leaves the record untouched. Paused records are reported as
paused and never re-run or advanced.

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
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

spec_cli = importlib.util.spec_from_file_location(
    "wiki_standing_queries", ROOT / "scripts" / "wiki_standing_queries.py")
CLI = importlib.util.module_from_spec(spec_cli)
spec_cli.loader.exec_module(CLI)


class FakeIndex:
    """A PostingsIndex-shaped stub: hybrid_rank returns a fixed
    ranked list of (score, doc_idx, detail)."""

    def __init__(self, ranked):
        self.ranked = ranked
        self.calls = 0

    def hybrid_rank(self, terms, adj):
        self.calls += 1
        return list(self.ranked)


DOC_META = [
    {"id": "alpha", "title": "Alpha", "path": "wiki/alpha.md"},
    {"id": "beta", "title": "Beta", "path": "wiki/beta.md"},
    {"id": None, "title": "unrouted", "path": "wiki/unrouted.md"},
]
TEXTS = ["alpha text v1", "beta text v1", "unrouted text"]


def record(**over):
    rec = {"id": "sq-0001", "name": "Test watch", "query": "alpha",
           "saved_from": "zero-results", "created_at": "2030-10-20T00:00:00+00:00",
           "last_looked_at": None, "last_looked_head": None,
           "seen": {}, "advances": 0}
    rec.update(over)
    return rec


def report(records, ranked, texts=TEXTS, stamp="2030-10-20 09:00 EDT"):
    idx = FakeIndex(ranked)
    lines, out, advanced = L.standing_queries_report(
        records, idx, [], DOC_META, texts, stamp, "abc1234")
    return lines, out, advanced, idx


class StandingQueryDiffTests(unittest.TestCase):
    def test_first_build_sets_baseline_not_news(self):
        lines, out, advanced, _ = report([record()], [(3.0, 0, None), (2.0, 1, None)])
        self.assertTrue(lines[0]["baseline"])
        self.assertEqual(lines[0]["new_count"], 0)
        self.assertEqual(lines[0]["total_hits"], 2)
        self.assertEqual(advanced, ["sq-0001"])
        self.assertEqual(out[0]["last_looked_at"], "2030-10-20 09:00 EDT")
        self.assertEqual(out[0]["last_looked_head"], "abc1234")
        self.assertEqual(out[0]["advances"], 1)
        self.assertEqual(set(out[0]["seen"]), {"alpha", "beta"})
        self.assertEqual(out[0]["seen"]["alpha"], L.standing_query_sha("alpha text v1"))

    def test_unrouted_docs_are_not_hits(self):
        lines, _out, _adv, _idx = report([record()], [(3.0, 2, None)])
        self.assertEqual(lines[0]["total_hits"], 0)

    def test_second_build_no_change_no_advance(self):
        seen = {"alpha": L.standing_query_sha("alpha text v1")}
        rec = record(last_looked_at="2030-10-19 09:00 EDT", seen=seen, advances=1)
        lines, out, advanced, _ = report([rec], [(3.0, 0, None)])
        self.assertFalse(lines[0]["baseline"])
        self.assertEqual(lines[0]["new_count"], 0)
        self.assertEqual(lines[0]["since"], "2030-10-19 09:00 EDT")
        self.assertEqual(advanced, [])
        self.assertEqual(out[0], rec)  # untouched, byte-for-byte shape

    def test_changed_page_reports_changed_and_advances(self):
        seen = {"alpha": L.standing_query_sha("alpha text v1")}
        rec = record(last_looked_at="2030-10-19 09:00 EDT", seen=seen, advances=1)
        texts2 = ["alpha text v2", "beta text v1", "unrouted text"]
        lines, out, advanced, _ = report([rec], [(3.0, 0, None)], texts=texts2)
        self.assertEqual(lines[0]["new_count"], 1)
        self.assertEqual(lines[0]["new_pages"][0]["id"], "alpha")
        self.assertEqual(lines[0]["new_pages"][0]["kind"], "changed")
        self.assertEqual(advanced, ["sq-0001"])
        self.assertEqual(out[0]["seen"]["alpha"], L.standing_query_sha("alpha text v2"))
        self.assertEqual(out[0]["advances"], 2)

    def test_new_page_reports_new(self):
        seen = {"alpha": L.standing_query_sha("alpha text v1")}
        rec = record(last_looked_at="2030-10-19 09:00 EDT", seen=seen, advances=1)
        lines, _out, advanced, _ = report([rec], [(3.0, 0, None), (2.0, 1, None)])
        kinds = {p["id"]: p["kind"] for p in lines[0]["new_pages"]}
        self.assertEqual(kinds, {"beta": "new"})
        self.assertEqual(advanced, ["sq-0001"])

    def test_paused_is_reported_never_run_never_advanced(self):
        rec = record(paused=True)
        lines, out, advanced, idx = report([rec], [(3.0, 0, None)])
        self.assertTrue(lines[0]["paused"])
        self.assertIsNone(lines[0]["total_hits"])
        self.assertEqual(idx.calls, 0)
        self.assertEqual(advanced, [])
        self.assertEqual(out[0], rec)

    def test_hit_cap_applies(self):
        meta = [{"id": f"p{i:02d}", "title": f"P{i}", "path": f"wiki/p{i}.md"}
                for i in range(12)]
        texts = [f"text {i}" for i in range(12)]
        ranked = [(float(20 - i), i, None) for i in range(12)]
        idx = FakeIndex(ranked)
        lines, _o, _a = L.standing_queries_report(
            [record()], idx, [], meta, texts, "2030-10-20 09:00 EDT", "abc1234")
        self.assertEqual(lines[0]["total_hits"], L.STANDING_QUERY_HIT_CAP)


class RegisterIoTests(unittest.TestCase):
    def test_missing_register_is_empty_not_error(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(L.load_standing_queries(Path(td)), [])

    def test_malformed_lines_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "evaluation").mkdir()
            (repo / "evaluation" / "standing-queries.jsonl").write_text(
                '{"id": "sq-0001", "query": "alpha"}\nnot json\n'
                '{"query": "no id"}\n\n# a comment\n', encoding="utf-8")
            recs = L.load_standing_queries(repo)
            self.assertEqual([r["id"] for r in recs], ["sq-0001"])

    def test_write_load_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            recs = [record(), record(id="sq-0002", name="Two", query="beta")]
            L.write_standing_queries(repo, recs)
            back = L.load_standing_queries(repo)
            self.assertEqual([r["id"] for r in back], ["sq-0001", "sq-0002"])
            self.assertEqual(back[1]["query"], "beta")


class FilingCliTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def run_cli(self, *argv):
        return CLI.main(["--repo", str(self.repo), *argv])

    def test_add_then_list(self):
        self.assertEqual(self.run_cli("add", "--name", "Glyphs", "--query",
                                      "qxjzv", "--from", "zero-results"), 0)
        recs = CLI.load(self.repo)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["id"], "sq-0001")
        self.assertEqual(recs[0]["saved_from"], "zero-results")
        self.assertIsNone(recs[0]["last_looked_at"])
        self.assertEqual(self.run_cli("list"), 0)

    def test_add_refuses_duplicate_query(self):
        self.run_cli("add", "--name", "One", "--query", "qxjzv")
        self.assertEqual(self.run_cli("add", "--name", "Two", "--query", "QXJZV"), 0)
        self.assertEqual(len(CLI.load(self.repo)), 1)

    def test_ids_increment_and_pause_resume_remove(self):
        self.run_cli("add", "--name", "One", "--query", "aaa")
        self.run_cli("add", "--name", "Two", "--query", "bbb")
        self.assertEqual([r["id"] for r in CLI.load(self.repo)],
                         ["sq-0001", "sq-0002"])
        self.assertEqual(self.run_cli("pause", "sq-0001"), 0)
        self.assertTrue(CLI.load(self.repo)[0]["paused"])
        self.assertEqual(self.run_cli("resume", "sq-0001"), 0)
        self.assertNotIn("paused", CLI.load(self.repo)[0])
        self.assertEqual(self.run_cli("remove", "sq-0002"), 0)
        self.assertEqual([r["id"] for r in CLI.load(self.repo)], ["sq-0001"])
        self.assertEqual(self.run_cli("pause", "sq-9999"), 2)

    def test_register_written_by_cli_reads_in_lenslib(self):
        self.run_cli("add", "--name", "Shared shape", "--query", "alpha")
        recs = L.load_standing_queries(self.repo)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["name"], "Shared shape")
        raw = (self.repo / "evaluation" / "standing-queries.jsonl").read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw.splitlines()[0])["query"], "alpha")


if __name__ == "__main__":
    unittest.main()
