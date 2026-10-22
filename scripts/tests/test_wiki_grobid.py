#!/usr/bin/env python3
"""Tests for scripts/wiki_grobid.py — the GROBID
bibliographic-extraction sidecar (W4 item 40) — plus its
registry entry in wiki_convert_engines.py and its wiring in
wiki_convert.py.

The discriminations that matter:
  * no endpoint configured is the named door
    "grobid-not-configured", stated in the sidecar block —
    never a silent skip and never a guessed localhost;
  * a configured but unreachable endpoint is the named
    failure "grobid-unreachable" with the transport error
    carried verbatim;
  * against a LOCAL FIXTURE server speaking the GROBID API
    shape (this suite's stub — GROBID itself cannot run on
    this VM: no Java runtime, the Round 10 door recorded in
    evaluation/grobid-trial-evidence.json), extraction works
    end to end: header metadata, parsed references and
    citation contexts land in the block, all stamped
    machine-unverified;
  * partial TEI is partial: missing header fields are NAMED
    in missing_fields, never filled in;
  * malformed TEI is the named door "grobid-malformed-tei";
    a service HTTP error is "grobid-service-error" with its
    stage named;
  * GROBID output NEVER verifies itself: fed into
    wiki_scholar_check.verify_citation, a header whose DOI
    Crossref resolves to a DIFFERENT paper lands as
    field-mismatch, not verified — the 2026-10-22 DOI-defect
    pattern, pinned;
  * with no --grobid, the converter's report carries no
    "grobid" key at all (the pre-change default); a non-PDF
    with --grobid converts normally and records the
    "grobid-format-unsupported" door additively.

Run:  python3 -m unittest discover -s scripts/tests -v
(the PDF-conversion tests need pypdf and skip without it;
they run under ~/workspace/.venv-report/bin/python.)
"""
import http.server
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Test isolation (coordinator repair, 2026-10-22): this suite's
# module-level loads must not leak into other suites sharing the
# process. wiki_convert resolves its sibling modules
# (wiki_convert_engines, wiki_grobid) through sys.modules at call
# time, and the convert-engines suite registers its stub engine
# in ITS OWN copy of the engines registry — if this suite's fresh
# copies were left standing in sys.modules, a combined run would
# hand the engines suite a registry without its stub ("unknown
# engine 'stubengine'"). So: snapshot the prior occupants, load
# this suite's copies (kept in the locals below), then restore
# sys.modules exactly as found. This suite's own calls go
# through its locals; a by-path reload inside wiki_convert's
# singleton loaders is stateless and unaffected.
_PRIOR_MODULES = {name: sys.modules.get(name) for name in (
    "wiki_grobid", "wiki_convert_engines", "wiki_convert",
    "wiki_scholar_check")}

grobid = _load("wiki_grobid")
engines = _load("wiki_convert_engines")
wc = _load("wiki_convert")
scholar = _load("wiki_scholar_check")

for _name, _prior in _PRIOR_MODULES.items():
    if _prior is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _prior
del _name, _prior, _PRIOR_MODULES

try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


# ------------------------------------------------------------- TEI fixtures
# GROBID-shaped TEI (TEI P5 namespace), modelled on the real
# service's output for Murre & Dros 2015 (the corpus's own
# citation; DOI 10.1371/journal.pone.0120644).

HEADER_TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title level="a" type="main">Replication and Analysis of Ebbinghaus' Forgetting Curve</title>
      </titleStmt>
      <publicationStmt>
        <publisher>PLOS</publisher>
        <date type="published" when="2015-07-06">July 6, 2015</date>
        <idno type="DOI">10.1371/journal.pone.0120644</idno>
      </publicationStmt>
      <sourceDesc>
        <biblStruct>
          <analytic>
            <title level="a" type="main">Replication and Analysis of Ebbinghaus' Forgetting Curve</title>
            <author>
              <persName><forename type="first">Jaap</forename><forename type="middle">M.</forename><forename type="middle">J.</forename><surname>Murre</surname></persName>
            </author>
            <author>
              <persName><forename type="first">Joeri</forename><surname>Dros</surname></persName>
            </author>
            <idno type="DOI">10.1371/journal.pone.0120644</idno>
          </analytic>
          <monogr>
            <title level="m">PLOS ONE</title>
            <imprint>
              <date type="published" when="2015"><date/></date>
              <biblScope unit="volume">10</biblScope>
              <biblScope unit="issue">7</biblScope>
            </imprint>
          </monogr>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <text><body><div><p>body</p></div></body></text>
</TEI>
"""

HEADER_TEI_PARTIAL = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title level="a" type="main">A Partially Extracted Paper</title>
      </titleStmt>
      <sourceDesc>
        <biblStruct>
          <analytic>
            <title level="a" type="main">A Partially Extracted Paper</title>
          </analytic>
          <monogr>
            <imprint/>
          </monogr>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <text><body/></text>
</TEI>
"""

REFERENCES_TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <back>
      <div type="references">
        <listBibl>
          <biblStruct xml:id="b0">
            <analytic>
              <title level="a" type="main">Memory: A Contribution to Experimental Psychology</title>
              <author>
                <persName><forename type="first">Hermann</forename><surname>Ebbinghaus</surname></persName>
              </author>
            </analytic>
            <monogr>
              <title level="m">Memory: A Contribution to Experimental Psychology</title>
              <imprint>
                <date type="published" when="1885"/>
              </imprint>
            </monogr>
            <note type="raw_reference">Ebbinghaus, H. (1885). Memory: A Contribution to Experimental Psychology.</note>
          </biblStruct>
          <biblStruct xml:id="b1">
            <analytic>
              <title level="a" type="main">The DCC Curation Lifecycle Model</title>
              <author>
                <persName><forename type="first">Sarah</forename><surname>Higgins</surname></persName>
              </author>
              <idno type="DOI">10.2218/ijdc.v3i1.48</idno>
            </analytic>
            <monogr>
              <title level="m">International Journal of Digital Curation</title>
              <imprint>
                <date type="published" when="2008"/>
              </imprint>
            </monogr>
          </biblStruct>
        </listBibl>
      </div>
    </back>
  </text>
</TEI>
"""

FULLTEXT_TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <div>
        <head>Introduction</head>
        <p>Forgetting follows a curve <ref type="bibr" target="#b0">[1]</ref> that has been replicated <ref type="bibr" target="#b1">[2]</ref> many times since.</p>
        <p>Later work <ref type="bibr" target="#b1">[2]</ref> confirms the shape of the curve.</p>
      </div>
    </body>
  </text>
</TEI>
"""

MALFORMED_TEI = "<TEI xmlns=\"http://www.tei-c.org/ns/1.0\">" \
                "<teiHeader><fileDesc><titleStmt>"

# Crossref's true record for the fixture DOI (trimmed to the
# fields the scholar checker reads) — the control — and a
# record for a DIFFERENT paper carrying the same DOI — the
# contradiction (the 2026-10-22 DOI-defect pattern).
CROSSREF_TRUE_RECORD = {
    "DOI": "10.1371/journal.pone.0120644",
    "title": ["Replication and Analysis of Ebbinghaus'"
              " Forgetting Curve"],
    "author": [{"given": "Jaap M. J.", "family": "Murre"},
               {"given": "Joeri", "family": "Dros"}],
    "issued": {"date-parts": [[2015]]},
    "container-title": ["PLOS ONE"],
    "type": "journal-article",
    "URL": "https://doi.org/10.1371/journal.pone.0120644",
}

CROSSREF_WRONG_RECORD = {
    "DOI": "10.1371/journal.pone.0120644",
    "title": ["An Unrelated Study of Nematode Feeding"
              " Behaviour"],
    "author": [{"given": "Jo", "family": "Someone"}],
    "issued": {"date-parts": [[2025]]},
    "container-title": ["PLOS Biology"],
    "type": "journal-article",
    "URL": "https://doi.org/10.1371/journal.pone.0120644",
}


def minimal_pdf():
    text = "Replication and Analysis of Ebbinghaus Forgetting Curve"
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >>"
        b" >> >>",
        b"<< /Length " + str(len(stream)).encode()
        + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>"
            f"\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


# ------------------------------------------------------------ fixture server

class _GrobidHandler(http.server.BaseHTTPRequestHandler):
    """A stub that speaks the GROBID API shape. The header
    response is chosen by the uploaded filename: 'partial'
    -> partial TEI, 'malformed' -> unparseable body, 'boom'
    -> HTTP 500, anything else -> the full header TEI."""

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/xml"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/isalive":
            self._send(200, "true", "text/plain")
        elif self.path == "/api/version":
            self._send(200, "0.9.1-fixture", "text/plain")
        else:
            self._send(404, "no such route", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        m = re.search(rb'filename="([^"]+)"', body)
        filename = m.group(1).decode() if m else ""
        if self.path == "/api/processHeaderDocument":
            if "boom" in filename:
                self._send(500, "internal error", "text/plain")
            elif "malformed" in filename:
                self._send(200, MALFORMED_TEI)
            elif "partial" in filename:
                self._send(200, HEADER_TEI_PARTIAL)
            else:
                self._send(200, HEADER_TEI)
        elif self.path == "/api/processReferences":
            self._send(200, REFERENCES_TEI)
        elif self.path == "/api/processFulltextDocument":
            self._send(200, FULLTEXT_TEI)
        else:
            self._send(404, "no such route", "text/plain")


class GrobidServerMixin:
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _GrobidHandler)
        cls.port = cls.server.server_address[1]
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()


# --------------------------------------------------------------------- tests

class TeiParsingTests(unittest.TestCase):

    def test_header_fields(self):
        h = grobid.parse_header_tei(HEADER_TEI)
        self.assertEqual(
            h["title"],
            "Replication and Analysis of Ebbinghaus'"
            " Forgetting Curve")
        self.assertEqual([a["display"] for a in h["authors"]],
                         ["Jaap M. J. Murre", "Joeri Dros"])
        self.assertEqual(h["venue"], "PLOS ONE")
        self.assertEqual(h["date"], "2015")
        self.assertEqual(h["year"], 2015)
        self.assertEqual(h["doi"],
                         "10.1371/journal.pone.0120644")
        self.assertEqual(h["missing_fields"], [])

    def test_header_partial_names_missing_fields(self):
        h = grobid.parse_header_tei(HEADER_TEI_PARTIAL)
        self.assertEqual(h["title"],
                         "A Partially Extracted Paper")
        for field in ("authors", "venue", "date", "doi"):
            self.assertIn(field, h["missing_fields"])

    def test_malformed_tei_raises_named_door(self):
        with self.assertRaises(grobid.GrobidDoor) as cm:
            grobid.parse_header_tei(MALFORMED_TEI)
        self.assertEqual(cm.exception.door["name"],
                         "grobid-malformed-tei")
        self.assertEqual(cm.exception.door["stage"],
                         "processHeaderDocument")

    def test_references_fields(self):
        refs = grobid.parse_references_tei(REFERENCES_TEI)
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["id"], "b0")
        self.assertEqual(refs[0]["authors"][0]["display"],
                         "Hermann Ebbinghaus")
        self.assertEqual(refs[0]["year"], 1885)
        self.assertIn("doi", refs[0]["missing_fields"])
        self.assertIn("Ebbinghaus, H. (1885).",
                      refs[0]["raw"])
        self.assertEqual(refs[1]["doi"],
                         "10.2218/ijdc.v3i1.48")
        self.assertEqual(refs[1]["missing_fields"], [])

    def test_citation_contexts(self):
        ctx = grobid.parse_citation_contexts_tei(FULLTEXT_TEI)
        self.assertEqual(len(ctx), 3)
        self.assertEqual(ctx[0]["marker"], "[1]")
        self.assertEqual(ctx[0]["target"], "b0")
        self.assertEqual(ctx[1]["target"], "b1")
        self.assertIn("Forgetting follows a curve",
                      ctx[0]["context"])
        self.assertEqual(ctx[2]["target"], "b1")


class DoorTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdf = self.tmp / "paper.pdf"
        self.pdf.write_bytes(minimal_pdf())

    def test_no_config_is_a_named_door(self):
        block = grobid.extract(self.pdf, env={})
        self.assertEqual(block["state"], "door")
        self.assertEqual(block["door"]["name"],
                         "grobid-not-configured")
        self.assertIn("GROBID_URL", block["door"]["reason"])
        self.assertIsNone(block["header"])
        # the door never pretends extraction happened
        self.assertEqual(block["references"], [])

    def test_configured_unreachable_is_a_named_failure(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        block = grobid.extract(
            self.pdf,
            endpoint=f"http://127.0.0.1:{dead_port}", env={})
        self.assertEqual(block["state"], "failed")
        self.assertEqual(block["failure"]["name"],
                         "grobid-unreachable")
        self.assertTrue(block["failure"]["reason"])
        self.assertIn("URLError", block["failure"]["reason"])
        self.assertFalse(block["probe"]["available"])
        self.assertIsNone(block["header"])

    def test_env_var_configures_the_endpoint(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        block = grobid.extract(
            self.pdf,
            env={"GROBID_URL": f"http://127.0.0.1:{dead_port}"})
        self.assertEqual(block["endpoint"],
                         f"http://127.0.0.1:{dead_port}")
        self.assertEqual(block["failure"]["name"],
                         "grobid-unreachable")


class FixtureServerTests(GrobidServerMixin, unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _pdf(self, name):
        p = self.tmp / name
        p.write_bytes(minimal_pdf())
        return p

    def test_end_to_end_extraction(self):
        block = grobid.extract(self._pdf("paper.pdf"),
                               endpoint=self.url, env={})
        self.assertEqual(block["state"], "machine-unverified")
        self.assertTrue(block["probe"]["available"])
        self.assertEqual(block["probe"]["version"],
                         "0.9.1-fixture")
        self.assertIn("unverified", block["verification"])
        h = block["header"]
        self.assertEqual(h["doi"],
                         "10.1371/journal.pone.0120644")
        self.assertEqual(h["venue"], "PLOS ONE")
        self.assertEqual(block["missing_fields"], [])
        self.assertFalse(block["partial"])
        self.assertEqual(len(block["references"]), 2)
        self.assertEqual(len(block["citation_contexts"]), 3)
        self.assertEqual(block["stage_failures"], [])
        self.assertIsNone(block["door"])
        self.assertIsNone(block["failure"])

    def test_partial_tei_records_partial_with_fields_named(self):
        block = grobid.extract(self._pdf("partial.pdf"),
                               endpoint=self.url, env={})
        self.assertEqual(block["state"], "machine-unverified")
        self.assertTrue(block["partial"])
        for field in ("authors", "venue", "date", "doi"):
            self.assertIn(field, block["missing_fields"])
        self.assertEqual(block["header"]["title"],
                         "A Partially Extracted Paper")

    def test_malformed_tei_is_a_named_door(self):
        block = grobid.extract(self._pdf("malformed.pdf"),
                               endpoint=self.url, env={})
        self.assertEqual(block["state"], "door")
        self.assertEqual(block["door"]["name"],
                         "grobid-malformed-tei")
        self.assertIsNone(block["header"])

    def test_service_error_is_a_named_failure(self):
        block = grobid.extract(self._pdf("boom.pdf"),
                               endpoint=self.url, env={})
        self.assertEqual(block["state"], "failed")
        self.assertEqual(block["failure"]["name"],
                         "grobid-service-error")
        self.assertEqual(block["failure"]["stage"],
                         "processHeaderDocument")
        self.assertIn("HTTP 500", block["failure"]["reason"])


class ScholarFeedTests(GrobidServerMixin, unittest.TestCase):
    """GROBID output feeds staged verification; it never
    verifies itself."""

    class Fetcher:
        def __init__(self, crossref_record):
            self.record = crossref_record

        def crossref_work(self, doi):
            return self.record

        def openalex_work(self, doi):
            raise scholar.RegistryMiss("fixture: no record")

        def crossref_search(self, cit):
            raise AssertionError("DOI path must not search")

        def openalex_search(self, cit):
            raise AssertionError("DOI path must not search")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdf = self.tmp / "paper.pdf"
        self.pdf.write_bytes(minimal_pdf())
        self.block = grobid.extract(self.pdf, endpoint=self.url,
                                    env={})
        self.assertEqual(self.block["state"],
                         "machine-unverified")
        self.cit = grobid.header_as_citation(
            self.block["header"])

    def test_header_maps_to_citation_shape(self):
        self.assertEqual(self.cit["doi"],
                         "10.1371/journal.pone.0120644")
        self.assertEqual(self.cit["authors"],
                         ["Jaap M. J. Murre", "Joeri Dros"])
        self.assertEqual(self.cit["year"], 2015)
        self.assertEqual(self.cit["venue"], "PLOS ONE")

    def test_agreeing_registry_record_verifies(self):
        entry = scholar.verify_citation(
            dict(self.cit), self.Fetcher(CROSSREF_TRUE_RECORD))
        self.assertEqual(entry["verdict"], "verified")

    def test_contradicted_doi_is_field_mismatch_not_verified(
            self):
        entry = scholar.verify_citation(
            dict(self.cit),
            self.Fetcher(CROSSREF_WRONG_RECORD))
        self.assertNotEqual(entry["verdict"], "verified")
        self.assertEqual(entry["verdict"], "field-mismatch")
        for field in ("title", "authors", "year"):
            self.assertEqual(
                entry["fields"][field]["result"], "disagree",
                field)


class ConvertWiringTests(GrobidServerMixin, unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_default_conversion_has_no_grobid_key(self):
        p = self.tmp / "note.txt"
        p.write_text("A plain note.\n", encoding="utf-8")
        md, report = wc.convert_with_report(p)
        self.assertNotIn("grobid", report)
        md2, report2 = wc.convert_with_report(p, grobid=None)
        self.assertEqual(md, md2)
        self.assertEqual(
            json.dumps(report, sort_keys=True),
            json.dumps(report2, sort_keys=True))

    def test_non_pdf_with_grobid_records_format_door(self):
        p = self.tmp / "note.md"
        p.write_text("# A note\n\nBody.\n", encoding="utf-8")
        md, report = wc.convert_with_report(p, grobid=True)
        self.assertIn("# A note", md)
        self.assertEqual(report["grobid"]["state"], "door")
        self.assertEqual(report["grobid"]["door"]["name"],
                         "grobid-format-unsupported")

    @unittest.skipUnless(HAS_PYPDF, "needs pypdf (report venv)")
    def test_pdf_end_to_end_sidecar_block(self):
        p = self.tmp / "paper.pdf"
        p.write_bytes(minimal_pdf())
        md, report = wc.convert_with_report(
            p, grobid=self.url)
        self.assertIn("## Page 1", md)
        block = report["grobid"]
        self.assertEqual(block["state"], "machine-unverified")
        self.assertEqual(block["header"]["doi"],
                         "10.1371/journal.pone.0120644")
        self.assertEqual(len(block["references"]), 2)

    @unittest.skipUnless(HAS_PYPDF, "needs pypdf (report venv)")
    def test_pdf_no_config_door_in_sidecar(self):
        p = self.tmp / "paper.pdf"
        p.write_bytes(minimal_pdf())
        env = {k: v for k, v in os.environ.items()
               if k != "GROBID_URL"}
        old = os.environ.get("GROBID_URL")
        os.environ.pop("GROBID_URL", None)
        try:
            md, report = wc.convert_with_report(p, grobid=True)
        finally:
            if old is not None:
                os.environ["GROBID_URL"] = old
        self.assertIn("## Page 1", md)
        self.assertEqual(report["grobid"]["state"], "door")
        self.assertEqual(report["grobid"]["door"]["name"],
                         "grobid-not-configured")


class RegistryTests(GrobidServerMixin, unittest.TestCase):

    def test_grobid_registered_as_sidecar_service(self):
        spec = engines.SIDECAR_SERVICES["grobid"]
        self.assertEqual(spec["licence"], "Apache-2.0")
        self.assertEqual(spec["licence_route"],
                         "adapt-with-credit")
        self.assertEqual(sorted(spec["formats"]), [".pdf"])
        # not a converter engine: the engine registry is for
        # markdown producers and GROBID is not one
        self.assertNotIn("grobid", engines.ENGINES)

    def test_probe_without_endpoint_states_the_door(self):
        record = engines.probe_sidecar_service("grobid")
        self.assertFalse(record["probe"]["available"])
        self.assertIn("GROBID_URL", record["probe"]["blocker"])
        self.assertEqual(record["formats"], [".pdf"])

    def test_probe_with_fixture_endpoint(self):
        record = engines.probe_sidecar_service(
            "grobid", endpoint=self.url)
        self.assertTrue(record["probe"]["available"])
        self.assertEqual(record["probe"]["version"],
                         "0.9.1-fixture")


class CliTests(unittest.TestCase):

    def test_probe_cli_without_config_exits_4_with_door(self):
        env = {k: v for k, v in os.environ.items()
               if k != "GROBID_URL"}
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "wiki_grobid.py"),
             "probe"],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 4)
        record = json.loads(proc.stdout)
        self.assertFalse(record["available"])
        self.assertIn("GROBID_URL", record["blocker"])


if __name__ == "__main__":
    unittest.main()
