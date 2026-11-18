import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_source_availability", ROOT / "scripts/wiki_source_availability.py")

def _fetcher(mapping):
    def fetch(url):
        if url not in mapping:
            raise LookupError(url)
        return mapping[url]
    return fetch

class AvailabilityTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report()
        self.assertEqual(rep["urls"], 0)
        self.assertEqual(rep["flagged_for_human_decision"], [])

    def test_collect_only_from_named_registers(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cite.json"
            p.write_text(json.dumps({"citations": [
                {"quote": "see https://en.wikipedia.org/wiki/Nupedia for the count"},
                {"quote": "endpoint http://localhost:8888/mcp/{bank_id}/ here"}]}))
            urls = MOD.collect_urls([p])
            self.assertEqual(len(urls), 2)
            self.assertIn("https://en.wikipedia.org/wiki/Nupedia", urls)
            # the template URL is collected as cited, and is not probeable
            self.assertIn("http://localhost:8888/mcp/{bank_id}/", urls)
            self.assertFalse(MOD.probeable("http://localhost:8888/mcp/{bank_id}/"))
        # the tree's own default citation register parses cleanly
        own = MOD.collect_urls(MOD.DEFAULT_SOURCES)
        self.assertTrue(all("citation-lockfile" in s
                            for srcs in own.values() for s in srcs))

    def test_collect_cleans_prose_punctuation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "reg.json"
            p.write_text(json.dumps({"x": "see https://example.org/a, and (https://example.net/b)."}))
            urls = MOD.collect_urls([p])
            self.assertIn("https://example.org/a", urls)
            self.assertIn("https://example.net/b", urls)

    def test_flag_rules(self):
        self.assertEqual(MOD.flag_for("https://a.org/x", 200, "https://a.org/x"), "ok")
        self.assertEqual(MOD.flag_for("https://a.org/x", 404, "https://a.org/x"), "dead")
        self.assertEqual(MOD.flag_for("https://a.org/x", 410, "https://a.org/x"), "dead")
        self.assertEqual(MOD.flag_for("https://a.org/x", 301, "https://a.org/y"), "moved")
        self.assertEqual(MOD.flag_for("https://a.org/x", 200, "https://a.org/y"), "moved")
        self.assertEqual(MOD.flag_for("https://a.org/x", 503, "https://a.org/x"), "attention")
        self.assertEqual(MOD.flag_for("https://a.org/x", None, None), "error")
        self.assertEqual(MOD.flag_for("https://a.org/{t}", 200, "https://a.org/{t}"), "not-probeable")

    def test_probe_with_fixture_fetcher_never_network(self):
        urls = {"https://a.org/ok": ["reg"], "https://a.org/gone": ["reg"],
                "https://a.org/old": ["reg"], "https://a.org/{tpl}": ["reg"]}
        fetch = _fetcher({"https://a.org/ok": (200, "https://a.org/ok"),
                          "https://a.org/gone": (404, "https://a.org/gone"),
                          "https://a.org/old": (200, "https://a.org/new")})
        recs = MOD.run_probe(urls, fetch, checked="2026-10-21", mode="fixture")
        by_url = {r["url"]: r for r in recs}
        self.assertEqual(by_url["https://a.org/ok"]["flag"], "ok")
        self.assertEqual(by_url["https://a.org/gone"]["flag"], "dead")
        self.assertEqual(by_url["https://a.org/old"]["flag"], "moved")
        self.assertEqual(by_url["https://a.org/{tpl}"]["flag"], "not-probeable")
        self.assertTrue(all(r["checked"] == "2026-10-21" for r in recs))
        self.assertTrue(all(r["probe_mode"] == "fixture" for r in recs))

    def test_fetch_exception_becomes_error_record(self):
        recs = MOD.run_probe({"https://a.org/x": ["reg"]}, _fetcher({}), checked="2026-10-21")
        self.assertEqual(recs[0]["flag"], "error")
        self.assertIsNone(recs[0]["status"])
        self.assertIn("fetch error", recs[0]["note"])

    def test_probe_cli_appends_and_report_takes_latest(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "side.jsonl"
            reg.write_text('{"kind":"header"}\n')
            src = Path(td) / "cite.json"
            src.write_text(json.dumps({"u": "https://a.org/x"}))
            fx = Path(td) / "fx.json"
            fx.write_text(json.dumps({"https://a.org/x": {"status": 404, "final_url": "https://a.org/x"}}))
            rc = MOD.main(["probe", "--register", str(reg), "--source", str(src),
                           "--fixture", str(fx), "--checked", "2026-10-21"])
            self.assertEqual(rc, 0)
            fx.write_text(json.dumps({"https://a.org/x": {"status": 200, "final_url": "https://a.org/x"}}))
            rc = MOD.main(["probe", "--register", str(reg), "--source", str(src),
                           "--fixture", str(fx), "--checked", "2026-10-22"])
            self.assertEqual(rc, 0)
            rep = MOD.build_report(reg)
            self.assertEqual(rep["records"], 2); self.assertEqual(rep["urls"], 1)
            self.assertEqual(rep["by_flag"]["ok"], 1)  # latest wins in the report
            self.assertEqual(rep["flagged_for_human_decision"], [])

    def test_probe_refuses_without_fixture_or_live(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "cite.json"; src.write_text("{}")
            self.assertEqual(MOD.main(["probe", "--source", str(src),
                                       "--register", str(Path(td) / "r.jsonl")]), 2)
            self.assertEqual(MOD.main(["probe", "--source", str(src), "--fixture", "x",
                                       "--live", "--register", str(Path(td) / "r.jsonl")]), 2)

    def test_check_rejects_bad_flag(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps({"kind": "availability", "url": "https://a.org",
                                     "checked": "2026-10-21", "flag": "vanished",
                                     "status": 200}) + "\n")
            _r, errs = MOD.load_register(p)
            self.assertTrue(any("flag" in e for e in errs))
            self.assertEqual(MOD.main(["check", "--register", str(p)]), 1)

if __name__ == "__main__":
    unittest.main()
