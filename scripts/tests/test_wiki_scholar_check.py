#!/usr/bin/env python3
"""Tests for scripts/wiki_scholar_check.py — scholarly
citation truth-checking (staged Crossref/OpenAlex verification,
field-level verdicts, retraction alerts, graded quotes).

The discriminations that matter:
  * a citation whose fields agree with the registry record is
    verified, with the compared fields named in the basis;
  * a wrong year / wrong author against a resolving DOI is
    field-mismatch, and the disagreeing fields are NAMED with
    cited vs registry values side by side;
  * a fabricated DOI is not_found — never verified, and the
    DOI path never falls back to title search;
  * a failed registry door is cannot_determine, NEVER
    not_found: one registry's 404 plus another's failure does
    not establish a negative;
  * cannot_determine is genuinely reachable (no identifiers,
    ambiguous title-search candidates);
  * a retracted work still verifies on its fields AND carries
    retraction alerts naming the registry evidence — the
    alert never silently changes the verdict;
  * quote grades discriminate exact / close (differences
    shown) / distorted / not_found.

No live network in tests: registry answers come from a
FakeFetcher serving RECORDED fixtures — the Crossref/OpenAlex
payloads below are trimmed reductions of the real API
responses for those DOIs, fetched 2026-10-22 (the Higgins and
Wakefield records verbatim in the fields the tool reads; the
Murre & Dros search results are constructed in the recorded
shape). One CLI test serves the same fixtures over a real
localhost HTTP server so the tool's own HTTP layer, including
its 404 handling, is exercised end to end.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import http.server
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scholar = _load("wiki_scholar_check")
RegistryMiss = scholar.RegistryMiss
DoorFailed = scholar.DoorFailed


# -- Recorded fixtures (trimmed real responses, 2026-10-22) -------------------

CROSSREF_HIGGINS = {
    "DOI": "10.2218/ijdc.v3i1.48",
    "title": ["The DCC Curation Lifecycle Model"],
    "author": [{"given": "Sarah", "family": "Higgins",
                "sequence": "first"}],
    "issued": {"date-parts": [[2008, 12, 2]]},
    "published-online": {"date-parts": [[2008, 12, 2]]},
    "container-title": ["International Journal of Digital"
                        " Curation"],
    "type": "journal-article",
    "URL": "https://doi.org/10.2218/ijdc.v3i1.48",
    "relation": {},
}

OPENALEX_HIGGINS = {
    "id": "https://openalex.org/W2159818719",
    "doi": "https://doi.org/10.2218/ijdc.v3i1.48",
    "title": "The DCC Curation Lifecycle Model",
    "publication_year": 2008,
    "type": "article",
    "is_retracted": False,
    "authorships": [{"author": {"display_name": "Sarah"
                                                " Higgins"}}],
    "primary_location": {"source": {
        "display_name": "International Journal of Digital"
                        " Curation"}},
}

CROSSREF_SETTLES = {
    "DOI": "10.18653/v1/p16-1174",
    "title": ["A Trainable Spaced Repetition Model for"
              " Language Learning"],
    "author": [{"given": "Burr", "family": "Settles",
                "sequence": "first"},
               {"given": "Brendan", "family": "Meeder",
                "sequence": "additional"}],
    "issued": {"date-parts": [[2016]]},
    "container-title": [
        "Proceedings of the 54th Annual Meeting of the"
        " Association for Computational Linguistics"
        " (Volume 1: Long Papers)"],
    "type": "proceedings-article",
    "URL": "https://doi.org/10.18653/v1/p16-1174",
    "relation": {},
}

CROSSREF_WAKEFIELD = {
    "DOI": "10.1016/s0140-6736(97)11096-0",
    "title": ["RETRACTED: Ileal-lymphoid-nodular hyperplasia,"
              " non-specific colitis, and pervasive"
              " developmental disorder in children"],
    "author": [{"given": "AJ", "family": "Wakefield",
                "sequence": "first"},
               {"given": "SH", "family": "Murch",
                "sequence": "additional"},
               {"given": "A", "family": "Anthony",
                "sequence": "additional"}],
    "issued": {"date-parts": [[1998, 2]]},
    "container-title": ["The Lancet"],
    "type": "journal-article",
    "URL": "https://doi.org/10.1016/s0140-6736(97)11096-0",
    "relation": {},
    "updated-by": [
        {"DOI": "10.1016/s0140-6736(04)15715-2",
         "type": "correction", "label": "Correction",
         "source": "retraction-watch"},
        {"DOI": "10.1016/s0140-6736(10)60175-4",
         "type": "retraction", "label": "Retraction",
         "source": "retraction-watch"},
    ],
}

OPENALEX_WAKEFIELD = {
    "id": "https://openalex.org/W2117847125",
    "doi": "https://doi.org/10.1016/s0140-6736(97)11096-0",
    "title": "RETRACTED: Ileal-lymphoid-nodular hyperplasia,"
             " non-specific colitis, and pervasive"
             " developmental disorder in children",
    "publication_year": 1998,
    "type": "article",
    "is_retracted": True,
    "authorships": [{"author": {"display_name":
                                "Andrew J. Wakefield"}},
                    {"author": {"display_name":
                                "SIMON H MURCH"}},
                    {"author": {"display_name":
                                "Andrew Anthony"}}],
    "primary_location": {"source": {
        "display_name": "The Lancet"}},
}

# Search-result fixtures in the recorded shape (Murre & Dros
# 2015, PLoS ONE 10(7): e0120644 — the corpus's own citation).
CROSSREF_MURRE_ITEMS = [{
    "DOI": "10.1371/journal.pone.0120644",
    "title": ["Replication and Analysis of Ebbinghaus'"
              " Forgetting Curve"],
    "author": [{"given": "Jaap M. J.", "family": "Murre",
                "sequence": "first"},
               {"given": "Joeri", "family": "Dros",
                "sequence": "additional"}],
    "issued": {"date-parts": [[2015]]},
    "container-title": ["PLOS ONE"],
    "type": "journal-article",
    "URL": "https://doi.org/10.1371/journal.pone.0120644",
    "relation": {},
}]

OPENALEX_MURRE_RESULTS = [{
    "id": "https://openalex.org/W2012345678",
    "doi": "https://doi.org/10.1371/journal.pone.0120644",
    "title": "Replication and Analysis of Ebbinghaus'"
             " Forgetting Curve",
    "publication_year": 2015,
    "type": "article",
    "is_retracted": False,
    "authorships": [{"author": {"display_name":
                                "Jaap M. J. Murre"}},
                    {"author": {"display_name":
                                "Joeri Dros"}}],
    "primary_location": {"source": {
        "display_name": "PLOS ONE"}},
}]


class FakeFetcher:
    """The registry-door seam, fed recorded fixtures.
    Table values: a payload dict/list, "miss" (the registry
    answered: no record), or "fail" (the door did not
    answer). Unrouted DOIs default to "miss"."""

    def __init__(self):
        self.cr_works = {}
        self.oa_works = {}
        self.cr_search_result = []
        self.oa_search_result = []
        self.calls = []

    def _one(self, table, doi, kind):
        self.calls.append((kind, doi))
        value = table.get(doi, "miss")
        if value == "miss":
            raise RegistryMiss(f"no record for {doi}")
        if value == "fail":
            raise DoorFailed("fixture door failure")
        return value

    def crossref_work(self, doi):
        return self._one(self.cr_works, doi, "crossref_work")

    def openalex_work(self, doi):
        return self._one(self.oa_works, doi, "openalex_work")

    def crossref_search(self, cit):
        self.calls.append(("crossref_search", cit.get("title")))
        if self.cr_search_result == "fail":
            raise DoorFailed("fixture door failure")
        return self.cr_search_result

    def openalex_search(self, cit):
        self.calls.append(("openalex_search", cit.get("title")))
        if self.oa_search_result == "fail":
            raise DoorFailed("fixture door failure")
        return self.oa_search_result


def higgins_fetcher():
    f = FakeFetcher()
    f.cr_works["10.2218/ijdc.v3i1.48"] = CROSSREF_HIGGINS
    f.oa_works["10.2218/ijdc.v3i1.48"] = OPENALEX_HIGGINS
    return f


HIGGINS_CITATION = {
    "doi": "10.2218/ijdc.v3i1.48",
    "title": "The DCC Curation Lifecycle Model",
    "authors": ["Sarah Higgins"],
    "year": 2008,
    "venue": "International Journal of Digital Curation",
}


class TestDoiPath(unittest.TestCase):

    def test_verified_full_fields(self):
        entry = scholar.verify_citation(
            dict(HIGGINS_CITATION), higgins_fetcher())
        self.assertEqual(entry["verdict"], "verified")
        self.assertEqual(entry["queried"],
                         ["crossref", "openalex"])
        for field in ("title", "authors", "year", "venue"):
            self.assertEqual(
                entry["fields"][field]["result"], "agree",
                field)
        self.assertIn("title", entry["basis"])
        self.assertEqual(entry["alerts"], [])

    def test_verified_doi_only(self):
        entry = scholar.verify_citation(
            {"doi": "10.2218/ijdc.v3i1.48"}, higgins_fetcher())
        self.assertEqual(entry["verdict"], "verified")
        self.assertIn("doi-resolution-only", entry["basis"])

    def test_field_mismatch_names_fields(self):
        cit = dict(HIGGINS_CITATION)
        cit["year"] = 2011
        cit["authors"] = ["Higgens"]
        entry = scholar.verify_citation(cit, higgins_fetcher())
        self.assertEqual(entry["verdict"], "field-mismatch")
        self.assertEqual(entry["fields"]["year"]["result"],
                         "disagree")
        self.assertEqual(entry["fields"]["year"]["cited"],
                         2011)
        self.assertEqual(
            entry["fields"]["year"]["per"][0]["value"], [2008])
        self.assertEqual(entry["fields"]["authors"]["result"],
                         "disagree")
        self.assertIn("year", entry["basis"])
        self.assertIn("authors", entry["basis"])
        # The title still agrees — mismatch is per-field.
        self.assertEqual(entry["fields"]["title"]["result"],
                         "agree")

    def test_fabricated_doi_not_found_never_verified(self):
        f = FakeFetcher()
        entry = scholar.verify_citation(
            {"doi": "10.1234/fabricated.999999",
             "title": "A Paper That Does Not Exist",
             "authors": ["Nobody"], "year": 2020}, f)
        self.assertEqual(entry["verdict"], "not_found")
        # The DOI path never falls back to title search.
        self.assertFalse(any(kind.endswith("search")
                             for kind, _ in f.calls))

    def test_door_failure_is_cannot_determine(self):
        f = FakeFetcher()
        f.cr_works["10.2218/ijdc.v3i1.48"] = "fail"
        f.oa_works["10.2218/ijdc.v3i1.48"] = "fail"
        entry = scholar.verify_citation(
            dict(HIGGINS_CITATION), f)
        self.assertEqual(entry["verdict"], "cannot_determine")
        self.assertEqual(set(entry["doors_failed"]),
                         {"crossref", "openalex"})

    def test_miss_plus_failure_is_not_a_negative(self):
        f = FakeFetcher()
        f.oa_works["10.2218/ijdc.v3i1.48"] = "fail"
        entry = scholar.verify_citation(
            dict(HIGGINS_CITATION), f)
        self.assertEqual(entry["verdict"], "cannot_determine")
        self.assertIn("not established", entry["basis"])

    def test_one_registry_resolving_is_enough(self):
        f = FakeFetcher()
        f.cr_works["10.18653/v1/p16-1174"] = CROSSREF_SETTLES
        entry = scholar.verify_citation(
            {"doi": "10.18653/v1/P16-1174",
             "title": "A Trainable Spaced Repetition Model"
                      " for Language Learning",
             "authors": ["Settles", "Meeder"], "year": 2016},
            f)
        self.assertEqual(entry["verdict"], "verified")
        self.assertEqual(entry["queried"], ["crossref",
                                            "openalex"])

    def test_venue_disagreement_is_a_note_not_a_verdict(self):
        f = FakeFetcher()
        f.cr_works["10.18653/v1/p16-1174"] = CROSSREF_SETTLES
        entry = scholar.verify_citation(
            {"doi": "10.18653/v1/p16-1174",
             "title": "A Trainable Spaced Repetition Model"
                      " for Language Learning",
             "authors": ["Settles", "Meeder"], "year": 2016,
             "venue": "Proc. ACL 2016"}, f)
        self.assertEqual(entry["verdict"], "verified")
        self.assertEqual(entry["fields"]["venue"]["result"],
                         "disagree")
        self.assertTrue(any("venue" in n
                            for n in entry["field_notes"]))


class TestInsufficientAndTitlePath(unittest.TestCase):

    def test_no_identifiers(self):
        f = FakeFetcher()
        entry = scholar.verify_citation({}, f)
        self.assertEqual(entry["verdict"], "cannot_determine")
        self.assertEqual(f.calls, [])

    def test_unusable_title(self):
        f = FakeFetcher()
        entry = scholar.verify_citation(
            {"title": "Proceedings"}, f)
        self.assertEqual(entry["verdict"], "cannot_determine")
        self.assertEqual(f.calls, [])

    def test_title_search_verified(self):
        f = FakeFetcher()
        f.cr_search_result = CROSSREF_MURRE_ITEMS
        f.oa_search_result = OPENALEX_MURRE_RESULTS
        entry = scholar.verify_citation(
            {"title": "Replication and Analysis of"
                      " Ebbinghaus' Forgetting Curve",
             "authors": ["Murre", "Dros"], "year": 2015,
             "venue": "PLoS ONE"}, f)
        self.assertEqual(entry["verdict"], "verified")
        self.assertEqual(
            entry["resolved"]["crossref"]["doi"],
            "10.1371/journal.pone.0120644")

    def test_title_search_not_found(self):
        f = FakeFetcher()
        f.cr_search_result = CROSSREF_MURRE_ITEMS
        f.oa_search_result = OPENALEX_MURRE_RESULTS
        entry = scholar.verify_citation(
            {"title": "Quantum Gardening in Zero Gravity"
                      " Environments",
             "authors": ["Murre"], "year": 2015}, f)
        self.assertEqual(entry["verdict"], "not_found")

    def test_title_search_ambiguous(self):
        def item(doi, title):
            return {"DOI": doi, "title": [title],
                    "author": [{"given": "A", "family": "Reyes",
                                "sequence": "first"}],
                    "issued": {"date-parts": [[2021]]},
                    "container-title": ["Journal of Tests"],
                    "type": "journal-article",
                    "URL": f"https://doi.org/{doi}",
                    "relation": {}}
        f = FakeFetcher()
        f.cr_search_result = [
            item("10.5555/attn.survey",
                 "Attention Mechanisms in Neural Networks:"
                 " A Survey"),
            item("10.5555/attn.overview",
                 "Attention Mechanisms in Neural Networks:"
                 " An Overview"),
        ]
        entry = scholar.verify_citation(
            {"title": "Attention Mechanisms in Neural"
                      " Networks",
             "authors": ["Reyes"], "year": 2021}, f)
        self.assertEqual(entry["verdict"], "cannot_determine")
        self.assertIn("ambiguous", entry["basis"])

    def test_title_search_door_failure(self):
        f = FakeFetcher()
        f.cr_search_result = "fail"
        f.oa_search_result = "fail"
        entry = scholar.verify_citation(
            {"title": "Replication and Analysis of"
                      " Ebbinghaus' Forgetting Curve",
             "authors": ["Murre", "Dros"], "year": 2015}, f)
        self.assertEqual(entry["verdict"], "cannot_determine")


class TestRetractionAlerts(unittest.TestCase):

    def test_retracted_work_alerts_with_verdict_intact(self):
        f = FakeFetcher()
        f.cr_works["10.1016/s0140-6736(97)11096-0"] = \
            CROSSREF_WAKEFIELD
        f.oa_works["10.1016/s0140-6736(97)11096-0"] = \
            OPENALEX_WAKEFIELD
        entry = scholar.verify_citation(
            {"doi": "10.1016/S0140-6736(97)11096-0",
             "title": "Ileal-lymphoid-nodular hyperplasia,"
                      " non-specific colitis, and pervasive"
                      " developmental disorder in children",
             "authors": ["Wakefield"], "year": 1998,
             "venue": "The Lancet"}, f)
        # Fields agree — the verdict is about identity...
        self.assertEqual(entry["verdict"], "verified")
        # ...and the retraction rides as alerts, one per
        # registry signal, each naming its evidence.
        kinds = [(a["kind"], a["registry"])
                 for a in entry["alerts"]]
        self.assertIn(("retraction", "crossref"), kinds)
        self.assertIn(("retraction", "openalex"), kinds)
        self.assertIn(("status", "crossref"), kinds)
        for a in entry["alerts"]:
            self.assertTrue(a["evidence"])
        self.assertEqual(entry["queried"],
                         ["crossref", "openalex"])


class TestQuoteGrades(unittest.TestCase):

    RANGE = ("The engineer said the server hums quietly"
             " during the morning rounds while the log"
             " scrolled past the window")

    def test_exact_despite_smart_quotes_and_whitespace(self):
        g = scholar.grade_quote_against(
            "the server  hums   quietly", self.RANGE)
        self.assertEqual(g["grade"], "exact")

    def test_close_shows_differences(self):
        quote = ("the server hums quietly during the morning"
                 " rounds while the log scrolled past the"
                 " doorway")
        g = scholar.grade_quote_against(quote, self.RANGE)
        self.assertEqual(g["grade"], "close")
        self.assertGreaterEqual(g["token_ratio"], 0.85)
        self.assertIn("diverges after", g["divergence"])

    def test_distorted(self):
        quote = ("the server hums quietly during unrelated"
                 " fabricated nonsense words appear here")
        g = scholar.grade_quote_against(quote, self.RANGE)
        self.assertEqual(g["grade"], "distorted")
        self.assertLess(g["token_ratio"], 0.85)

    def test_not_found(self):
        g = scholar.grade_quote_against(
            "photosynthesis converts sunlight into chemical"
            " energy inside chloroplasts", self.RANGE)
        self.assertEqual(g["grade"], "not_found")


class TestExtractionAndInput(unittest.TestCase):

    def test_extract_full_prose_citation(self):
        line = ('- **Source opened:** Settles & Meeder,'
                ' "A Trainable Spaced Repetition Model for'
                ' Language Learning," *Proc. ACL 2016*,'
                ' pp. 1848–1858 (ACL Anthology page P16-1174'
                ' opened; DOI 10.18653/v1/P16-1174).')
        rec = scholar.extract_from_line(line)
        self.assertEqual(rec["doi"], "10.18653/v1/p16-1174")
        self.assertEqual(
            rec["title"],
            "A Trainable Spaced Repetition Model for"
            " Language Learning,")
        self.assertEqual(rec["authors"],
                         ["Settles", "Meeder"])
        self.assertEqual(rec["year"], 2016)
        self.assertEqual(rec["venue"], "Proc. ACL 2016")

    def test_extract_parenthetical_doi_only(self):
        line = ("(IJDC 3(1) 134–140, DOI 10.2218/ijdc.v3i1.48)"
                " matches at source; re-verified here).")
        rec = scholar.extract_from_line(line)
        self.assertEqual(rec["doi"], "10.2218/ijdc.v3i1.48")
        self.assertNotIn("title", rec)
        self.assertNotIn("year", rec)

    def test_extract_no_doi_no_record(self):
        self.assertIsNone(scholar.extract_from_line(
            "Murre & Dros 2015 — the forgetting curve,"
            " replicated."))

    def test_csl_record_normalised(self):
        rec = scholar.normalise_record({
            "DOI": "10.2218/IJDC.v3i1.48",
            "title": ["The DCC Curation Lifecycle Model"],
            "author": [{"family": "Higgins",
                        "given": "Sarah"}],
            "issued": {"date-parts": [[2008]]},
            "container-title": ["International Journal of"
                                " Digital Curation"],
        })
        self.assertEqual(rec["doi"], "10.2218/ijdc.v3i1.48")
        self.assertEqual(rec["authors"], ["Sarah Higgins"])
        self.assertEqual(rec["year"], 2008)
        self.assertEqual(rec["venue"],
                         "International Journal of Digital"
                         " Curation")


# -- CLI on a fixture tree ---------------------------------------------------------

SOURCE_LINES = [
    "Fixture source title",
    "alpha bravo charlie",
    "delta echo foxtrot",
    "golf hotel india",
    "juliet kilo lima",
    'The engineer said "the server hums quietly" during'
    " rounds.",
]

PAGE_FRONT = """---
title: {title}
type: source
created: 2026-10-22
updated: 2026-10-22
sources:
  - raw/sources/fixture-source.md
tags: [fixture]
---

"""


class _RegistryHandler(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        payload = self.routes.get(path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestCli(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        for name in ("wiki_scholar_check.py",
                     "wiki_cite_lock.py", "wiki_observe.py",
                     "wiki_validate.py"):
            shutil.copy(SCRIPTS / name,
                        self.tmp / "scripts" / name)
        (self.tmp / "wiki" / "sources").mkdir(parents=True)
        (self.tmp / "raw" / "sources").mkdir(parents=True)
        (self.tmp / "evaluation").mkdir()
        (self.tmp / "raw" / "sources"
         / "fixture-source.md").write_text(
            "\n".join(SOURCE_LINES) + "\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable,
             str(self.tmp / "scripts" / "wiki_scholar_check.py"),
             *argv], capture_output=True, text=True,
            timeout=60)

    def add_page(self, name, body):
        (self.tmp / "wiki" / "sources" / name).write_text(
            PAGE_FRONT.format(title=name) + body,
            encoding="utf-8")

    def test_quotes_command_grades_corpus(self):
        self.add_page("good.md",
                      'The report said "the server hums'
                      ' quietly" in the log.'
                      "^[cite: raw/sources/fixture-source.md"
                      "#L6]\n")
        self.add_page("bent.md",
                      'The report said "the server hums'
                      ' loudly" in the log.'
                      "^[cite: raw/sources/fixture-source.md"
                      "#L6]\n")
        out = self.tmp / "evaluation" / "quote-report.json"
        proc = self.run_cli("quotes", "--out", str(out))
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        grades = {r["page"]: r["grade"]
                  for r in report["results"]}
        self.assertEqual(grades["wiki/sources/good.md"],
                         "exact")
        bent = [r for r in report["results"]
                if r["page"] == "wiki/sources/bent.md"][0]
        self.assertEqual(bent["grade"], "distorted")
        self.assertTrue(bent["divergence"])

    def test_verify_command_against_local_registry(self):
        _RegistryHandler.routes = {
            "/cr/works/10.2218%2Fijdc.v3i1.48":
                {"message": CROSSREF_HIGGINS},
            "/oa/works/doi:10.2218/ijdc.v3i1.48":
                OPENALEX_HIGGINS,
        }
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _RegistryHandler)
        thread = threading.Thread(target=server.serve_forever,
                                  daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            cits = self.tmp / "citations.jsonl"
            cits.write_text(
                json.dumps(HIGGINS_CITATION) + "\n"
                + json.dumps({
                    "doi": "10.1234/fabricated.999999",
                    "title": "A Paper That Does Not Exist",
                    "year": 2020}) + "\n",
                encoding="utf-8")
            out = self.tmp / "evaluation" / "report.json"
            proc = self.run_cli(
                "verify", "--citations", str(cits),
                "--crossref-base", f"http://127.0.0.1:{port}/cr",
                "--openalex-base",
                f"http://127.0.0.1:{port}/oa",
                "--delay", "0", "--out", str(out))
            self.assertEqual(proc.returncode, 0,
                             proc.stdout + proc.stderr)
            report = json.loads(
                out.read_text(encoding="utf-8"))
            verdicts = {r["citation"].get("doi"): r["verdict"]
                        for r in report["results"]}
            self.assertEqual(
                verdicts["10.2218/ijdc.v3i1.48"], "verified")
            self.assertEqual(
                verdicts["10.1234/fabricated.999999"],
                "not_found")
            self.assertEqual(
                report["summary"]["verified"], 1)
            self.assertEqual(
                report["summary"]["not_found"], 1)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
