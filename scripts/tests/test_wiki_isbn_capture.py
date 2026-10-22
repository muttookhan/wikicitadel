#!/usr/bin/env python3
"""W4 ISBN book-capture door (Open Library): checksum validation
that refuses BEFORE any fetch, honest doors (not_found /
unreachable / malformed), partial metadata named as missing,
and the cover stored-or-absent beside the record.

Every network outcome is a recorded fixture: the module's single
_fetch choke point is stubbed with a URL router, so the suite
runs with no live network. One live smoke is run by hand at
build time and reported in the build note, never in tests.

Checksum fixtures are independently computed:
  9780134685991  valid ISBN-13 (check digit 1)
  0134685997     valid ISBN-10, converts to 9780134685991
  080442957X     valid ISBN-10 with an X check character,
                 converts to 9780804429573
  9780134685992  check digit wrong (should be 1)
  0134685998     check character wrong (should be 7)

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_isbn_capture", HERE.parents[1] / "wiki_isbn_capture.py")
bic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bic)

ISBN13 = "9780134685991"

EDITION_FULL = {
    "title": "Effective Java",
    "subtitle": "Best Practices for the Java Platform",
    "authors": [{"key": "/authors/OL0001A"}],
    "publishers": ["Addison-Wesley Professional"],
    "publish_date": "January 6, 2018",
    "number_of_pages": 412,
    "isbn_10": ["0134685997"],
    "isbn_13": ["9780134685991"],
    "oclc_numbers": ["1013724670"],
    "lccn": ["2017047241"],
    "languages": [{"key": "/languages/eng"}],
    "key": "/books/OL0001M",
    "works": [{"key": "/works/OL0001W"}],
}
AUTHOR_FULL = {"name": "Joshua Bloch", "key": "/authors/OL0001A"}
WORK_FULL = {
    "subjects": ["Java (Computer program language)",
                 "Object-oriented programming"],
    "description": {"type": "/type/text",
                    "value": "A fixture description."},
}
EDITION_SPARSE = {
    "title": "An Obscure Fixture Pamphlet",
    "key": "/books/OL0002M",
    "isbn_13": ["9780134685991"],
}
COVER_BYTES = b"\xff\xd8\xff\xe0" + b"fixture-cover" * 40


def http_error(code):
    return urllib.error.HTTPError("https://fixture", code,
                                  "fixture", {}, None)


def make_fetch(routes, calls):
    """routes: list of (url-substring, bytes-or-exception)."""
    def fetch(url, timeout=15):
        calls.append(url)
        for needle, outcome in routes:
            if needle in url:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected fetch: {url}")
    return fetch


def full_routes(cover=COVER_BYTES):
    # The covers route comes FIRST: a cover URL
    # (covers.openlibrary.org/b/isbn/...) also contains "/isbn/"
    # and must not fall through to the edition route.
    return [
        ("covers.openlibrary.org", cover),
        ("/isbn/", json.dumps(EDITION_FULL).encode()),
        ("/authors/", json.dumps(AUTHOR_FULL).encode()),
        ("/works/", json.dumps(WORK_FULL).encode()),
    ]


class TestValidateIsbn(unittest.TestCase):
    def test_isbn13_valid(self):
        r = bic.validate_isbn(ISBN13)
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["isbn13"], ISBN13)
        self.assertIsNone(r["normalised_from"])

    def test_isbn13_hyphenated(self):
        r = bic.validate_isbn("978-0-13-468599-1")
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["isbn13"], ISBN13)

    def test_isbn10_valid_and_converts(self):
        r = bic.validate_isbn("0-13-468599-7")
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["isbn13"], ISBN13)
        self.assertEqual(r["normalised_from"], "0134685997")

    def test_isbn10_x_check_character(self):
        r = bic.validate_isbn("080442957X")
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["isbn13"], "9780804429573")

    def test_isbn13_bad_checksum(self):
        r = bic.validate_isbn("9780134685992")
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("should be 1", r["errors"][0])
        self.assertIsNone(r["isbn13"])

    def test_isbn10_bad_checksum(self):
        r = bic.validate_isbn("0134685998")
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("should be 7", r["errors"][0])

    def test_bad_shapes(self):
        for raw in ("", "12345", "97801346859X1",
                    "9770134685991", "abcdefghij"):
            r = bic.validate_isbn(raw)
            self.assertTrue(r["errors"], raw)
            self.assertIsNone(r["isbn13"], raw)


class TestCapture(unittest.TestCase):
    def setUp(self):
        # Explicit dir: this VM intermittently fails tempfile's
        # default-tempdir probe (gettempdir) while explicit-dir
        # creation works; the explicit form never resolves the
        # default, so the suite is stable either way.
        self.tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.out = Path(self.tmp.name) / "rawish"
        self.calls = []
        patcher = mock.patch.object(bic, "PACE_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_capture(self, routes, isbn=ISBN13, **kw):
        fetch = make_fetch(routes, self.calls)
        with mock.patch.object(bic, "_fetch", fetch):
            return bic.capture(isbn, self.out, **kw)

    def sidecar(self, isbn13=ISBN13):
        p = self.out / f"book-{isbn13}.md.ingest.json"
        return json.loads(p.read_text(encoding="utf-8"))

    def test_full_capture(self):
        result = self.run_capture(full_routes())
        self.assertEqual(result["verdict"], "found")
        record = Path(result["record"])
        text = record.read_text(encoding="utf-8")
        self.assertIn("Effective Java", text)
        self.assertIn("Joshua Bloch", text)
        self.assertIn("Addison-Wesley Professional", text)
        self.assertIn("1013724670", text)
        self.assertIn("A fixture description.", text)
        doc = self.sidecar()
        block = doc["book_capture"]
        self.assertEqual(block["verdict"], "found")
        self.assertEqual(block["fields_missing"], [])
        self.assertEqual(block["isbn13"], ISBN13)
        self.assertTrue(block["fetched_at_utc"])
        self.assertTrue(any("/isbn/" in u
                            for u in block["fetch_urls"]))
        # The converter seam ran: trust tier + sanitiser are
        # in the sidecar beside the capture block.
        self.assertIn("trust_tier", doc)
        self.assertIn("sanitiser", doc)
        cover = block["cover"]
        self.assertEqual(cover["status"], "stored")
        cover_file = self.out / cover["file"]
        self.assertEqual(cover_file.read_bytes(), COVER_BYTES)
        self.assertEqual(cover["sha256"], hashlib.sha256(
            COVER_BYTES).hexdigest())
        self.assertIn("no rights over the", cover["terms_note"])

    def test_sparse_capture_names_missing_fields(self):
        routes = [("covers.openlibrary.org", http_error(404)),
                  ("/isbn/", json.dumps(EDITION_SPARSE).encode())]
        result = self.run_capture(routes)
        self.assertEqual(result["verdict"], "found-partial")
        doc = self.sidecar()
        missing = doc["book_capture"]["fields_missing"]
        for name in ("authors", "publishers", "publish_date",
                     "number_of_pages", "subjects",
                     "description", "cover"):
            self.assertIn(name, missing)
        text = Path(result["record"]).read_text(encoding="utf-8")
        self.assertIn("An Obscure Fixture Pamphlet", text)
        self.assertIn("Fields Open Library did not supply", text)
        self.assertFalse(list(self.out.glob("*cover*")))

    def test_isbn10_input_normalised_and_recorded(self):
        result = self.run_capture(full_routes(), isbn="0134685997")
        doc = self.sidecar()
        self.assertEqual(doc["book_capture"]
                         ["isbn_normalised_from"], "0134685997")
        self.assertTrue(self.calls[0].endswith(
            "/isbn/9780134685991.json"))

    def test_unknown_isbn_not_found(self):
        routes = [("/isbn/", http_error(404))]
        result = self.run_capture(routes)
        self.assertEqual(result["verdict"], "not_found")
        self.assertIsNone(result["record"])
        self.assertFalse(list(self.out.glob("*.md")))
        doc = self.sidecar()
        self.assertEqual(doc["book_capture"]["verdict"],
                         "not_found")
        self.assertIn("404", doc["book_capture"]
                      ["not_found_basis"])

    def test_unreachable_is_a_named_door(self):
        routes = [("/isbn/", urllib.error.URLError("no route"))]
        with mock.patch.object(
                bic, "_fetch", make_fetch(routes, self.calls)):
            code = bic.main([ISBN13, "--out-dir", str(self.out)])
        self.assertEqual(code, 4)
        doc = self.sidecar()
        self.assertEqual(doc["book_capture"]["door"]["name"],
                         "openlibrary-unreachable")
        self.assertFalse(list(self.out.glob("*.md")))

    def test_malformed_response_is_a_named_door(self):
        routes = [("/isbn/", b"<html>not json</html>")]
        with mock.patch.object(
                bic, "_fetch", make_fetch(routes, self.calls)):
            code = bic.main([ISBN13, "--out-dir", str(self.out)])
        self.assertEqual(code, 4)
        doc = self.sidecar()
        self.assertEqual(doc["book_capture"]["door"]["name"],
                         "openlibrary-malformed-response")

    def test_invalid_isbn_never_fetches(self):
        fetch = make_fetch([], self.calls)
        with mock.patch.object(bic, "_fetch", fetch):
            code = bic.main(["9780134685992", "--out-dir",
                             str(self.out)])
        self.assertEqual(code, 2)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.out.exists()
                         and list(self.out.iterdir()))

    def test_existing_record_refused(self):
        self.out.mkdir(parents=True)
        (self.out / f"book-{ISBN13}.md").write_text(
            "standing record\n", encoding="utf-8")
        fetch = make_fetch(full_routes(), self.calls)
        with mock.patch.object(bic, "_fetch", fetch):
            code = bic.main([ISBN13, "--out-dir", str(self.out)])
        self.assertEqual(code, 2)
        self.assertEqual(self.calls, [])

    def test_cover_placeholder_treated_as_not_served(self):
        routes = full_routes(cover=b"\x47\x49\x46\x38" + b"\x00" * 39)
        result = self.run_capture(routes)
        doc = self.sidecar()
        self.assertEqual(doc["book_capture"]["cover"]["status"],
                         "not-served")
        self.assertIn("cover", doc["book_capture"]
                      ["fields_missing"])
        self.assertFalse(list(self.out.glob("*cover.jpg")))

    def test_no_cover_flag(self):
        routes = [("/isbn/", json.dumps(EDITION_FULL).encode()),
                  ("/authors/", json.dumps(AUTHOR_FULL).encode()),
                  ("/works/", json.dumps(WORK_FULL).encode())]
        result = self.run_capture(routes, want_cover=False)
        doc = self.sidecar()
        self.assertEqual(doc["book_capture"]["cover"]["status"],
                         "not-requested")
        self.assertFalse(any("covers." in u for u in self.calls))

    def test_raw_dir_requires_sensitivity(self):
        # Refusal happens before any fetch or write, so this is
        # safe to run against the real tree's raw/ path.
        raw_dir = bic.ROOT / "raw" / "sources"
        fetch = make_fetch(full_routes(), self.calls)
        with mock.patch.object(bic, "_fetch", fetch):
            code = bic.main([ISBN13, "--out-dir", str(raw_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
