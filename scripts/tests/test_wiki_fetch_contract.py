"""Tests for scripts/wiki_fetch_contract.py — the Jina Reader
fetch contract: a rendered record validates; a missing
source_url / fetched_at / title, a non-ISO fetch date, a
non-URL source, an edited body (hash mismatch), and a record
with no frontmatter are each caught; the fetcher is injected
so no test touches the network.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_fetch_contract", HERE.parents[1] / "wiki_fetch_contract.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)

URL = "https://example.org/some/page"
BODY = "# A Page\n\nSome fetched **Markdown** body.\n"


def good_record(**kw):
    args = {"source_url": URL, "title": "A Page",
            "body": BODY, "fetched_at": "2026-10-21"}
    args.update(kw)
    return fc.render_fetch_record(**args)


class RenderTest(unittest.TestCase):
    def test_rendered_record_validates_clean(self):
        record = good_record()
        self.assertEqual(fc.validate_fetch_record(record), [])
        fm, body = fc.parse_frontmatter(record)
        self.assertEqual(fm["kind"], "web-fetch")
        self.assertEqual(fm["source_url"], URL)
        self.assertEqual(fm["fetched_at"], "2026-10-21")
        self.assertEqual(fm["title"], "A Page")
        self.assertEqual(fm["content_sha256"], fc.content_hash(BODY))
        self.assertTrue(body.lstrip().startswith("# A Page"))

    def test_render_is_deterministic(self):
        self.assertEqual(good_record(), good_record())

    def test_title_with_colon_round_trips(self):
        record = good_record(title="Ratio: A Study")
        self.assertEqual(fc.validate_fetch_record(record), [])
        fm, _b = fc.parse_frontmatter(record)
        self.assertEqual(fm["title"], "Ratio: A Study")

    def test_datetime_fetched_at_accepted(self):
        record = good_record(fetched_at="2026-10-21T03:30:00+00:00")
        self.assertEqual(fc.validate_fetch_record(record), [])

    def test_render_refuses_bad_inputs(self):
        for kw in ({"source_url": "not-a-url"},
                   {"source_url": "ftp://example.org/x"},
                   {"fetched_at": "last Tuesday"},
                   {"title": "  "},
                   {"body": "   "}):
            with self.assertRaises(ValueError, msg=str(kw)):
                good_record(**kw)


class ValidateTest(unittest.TestCase):
    def test_each_required_field_is_enforced(self):
        record = good_record()
        for field in ("source_url", "fetched_at", "title"):
            broken = "\n".join(
                line for line in record.splitlines()
                if not line.startswith(field + ":"))
            problems = fc.validate_fetch_record(broken)
            self.assertTrue(
                any(field in p for p in problems),
                f"{field} removal not caught: {problems}")

    def test_bad_date_and_bad_url_named(self):
        record = good_record().replace("2026-10-21", "yesterday") \
                              .replace(URL, "example.org/no-scheme")
        problems = fc.validate_fetch_record(record)
        self.assertTrue(any("fetched_at" in p for p in problems))
        self.assertTrue(any("source_url" in p for p in problems))

    def test_body_tamper_breaks_content_hash(self):
        record = good_record().replace("Some fetched", "Some edited")
        problems = fc.validate_fetch_record(record)
        self.assertTrue(any("content_sha256" in p for p in problems))

    def test_no_frontmatter_is_not_a_record(self):
        problems = fc.validate_fetch_record(BODY)
        self.assertTrue(any("frontmatter" in p for p in problems))

    def test_wrong_kind_named(self):
        record = good_record().replace("kind: web-fetch",
                                       "kind: source")
        problems = fc.validate_fetch_record(record)
        self.assertTrue(any("kind" in p for p in problems))


class FetchTest(unittest.TestCase):
    def test_injected_fetcher_makes_a_valid_record_offline(self):
        seen = []

        def fake_fetcher(url):
            seen.append(url)
            return "Fetched Title", "# Fetched Title\n\nBody.\n"

        record = fc.fetch_record(URL, fake_fetcher, "2026-10-21")
        self.assertEqual(seen, [URL])
        self.assertEqual(fc.validate_fetch_record(record), [])
        fm, _b = fc.parse_frontmatter(record)
        self.assertEqual(fm["title"], "Fetched Title")

    def test_cli_new_and_check_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            body_file = Path(tmp) / "body.md"
            body_file.write_text(BODY, encoding="utf-8")
            out = Path(tmp) / "record.md"
            rc = fc.main(["new", "--url", URL, "--title", "A Page",
                          "--body-file", str(body_file),
                          "--fetched-at", "2026-10-21",
                          "--out", str(out)])
            self.assertEqual(rc, 0)
            self.assertEqual(fc.main(["check", str(out)]), 0)
            out.write_text(out.read_text(encoding="utf-8")
                           .replace("body", "BODY"),
                           encoding="utf-8")
            self.assertEqual(fc.main(["check", str(out)]), 1)


if __name__ == "__main__":
    unittest.main()
