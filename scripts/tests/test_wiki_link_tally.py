import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_link_health", ROOT / "scripts/wiki_link_health.py")

def _wiki(td):
    root = Path(td); (root / "wiki").mkdir(parents=True)
    (root / "wiki/a.md").write_text(
        "---\ntitle: A\ntype: entity\n---\n\n# A\n\n"
        "Links [[b]] and [[missing-page]]. External: "
        "[ok](https://example.org/page) and a bare "
        "https://example.net/x, a bad [hostless](https://) "
        "and a protocol-relative //cdn.example.org/lib.js "
        "reference.\n\n```\nhttps://code.example.org/not-counted\n"
        "[[also-not-counted]]\n```\n")
    (root / "wiki/b.md").write_text(
        "---\ntitle: B\ntype: entity\n---\n\n# B\n\nBack to [[a]].\n")
    (root / "wiki/index.md").write_text("# Index\n\n[[a]]\n")
    return root

class LinkTallyTests(unittest.TestCase):
    def test_classify_external(self):
        self.assertEqual(MOD.classify_external("https://example.org/x"), "external-dereferenceable")
        self.assertEqual(MOD.classify_external("http://localhost:8888/mcp"), "external-dereferenceable")
        self.assertEqual(MOD.classify_external("https://"), "external-unresolved")
        self.assertEqual(MOD.classify_external("//cdn.example.org/lib.js"), "external-unresolved")
        self.assertEqual(MOD.classify_external("https://nodot/x"), "external-unresolved")
        self.assertEqual(MOD.classify_external("www.example.org/x"), "external-unresolved")

    def test_tally_counts_by_type_recomputed_from_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = _wiki(td)
            tally, per_page = MOD.compute_tally(root)
            # in-scope pages: a.md + b.md (index is structural)
            self.assertEqual(tally["pages_scanned"], 2)
            # a: [[b]] resolved, [[missing-page]] broken; b: [[a]] resolved
            self.assertEqual(tally["internal-wikilink"], 3)
            self.assertEqual(tally["internal-wikilink-resolved"], 2)
            self.assertEqual(tally["internal-wikilink-broken"], 1)
            # dereferenceable: md-link example.org + bare example.net
            self.assertEqual(tally["external-dereferenceable"], 2)
            # unresolved: hostless https:// + protocol-relative //cdn...
            self.assertEqual(tally["external-unresolved"], 2)
            a = [p for p in per_page if p["page"] == "wiki/a.md"][0]
            self.assertEqual(a["internal-wikilink"], 2)

    def test_markdown_linked_url_counted_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = _wiki(td)
            tally, _pp = MOD.compute_tally(root)
            total_ext = tally["external-dereferenceable"] + tally["external-unresolved"]
            self.assertEqual(total_ext, 4)

    def test_tally_cli_json_and_report_still_work(self):
        with tempfile.TemporaryDirectory() as td:
            root = _wiki(td)
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = MOD.main(["--root", str(root), "tally", "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["tally"]["internal-wikilink"], 3)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = MOD.main(["--root", str(root), "report"])
            self.assertEqual(rc, 0)
            self.assertIn("Link health", buf.getvalue())

    def test_tally_no_wiki_layer_is_usage_error(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(MOD.main(["--root", td, "tally"]), 2)

if __name__ == "__main__":
    unittest.main()
