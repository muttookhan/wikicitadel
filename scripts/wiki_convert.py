#!/usr/bin/env python3
"""wiki_convert.py — convert a document to Markdown for ingest.

The ingest helper of WikiCitadel v1: the wiki is fed
documents, and until now DOCX/PPTX/XLSX/HTML/PDF files had no
mechanical path into raw/-ready Markdown. Pattern after
Microsoft's markitdown (MIT) — a single small converter with
per-format extractors — but the implementation here is original,
written against the Python standard library only (plus pypdf for
PDFs when importable; it is present in the report venv at
.venv-report). No new dependencies are introduced.

    python3 scripts/wiki_convert.py FILE [-o OUT.md]

Formats: .md/.txt (passthrough), .html/.htm, .docx, .pptx, .xlsx,
.pdf (needs pypdf), .json (fenced). Anything else is refused with
the supported list. The converter is deliberately conservative:
it preserves text, headings, lists, links and tables, and drops
formatting it cannot represent rather than inventing structure.
"""
import argparse
import html as html_mod
import json
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED = ".md .txt .html .htm .docx .pptx .xlsx .pdf .json"


class ConvertError(Exception):
    pass


# ------------------------------------------------------------------ html

class _HTML2MD(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "header", "footer", "li",
             "tr", "blockquote", "pre", "table"}
    SKIP = {"script", "style", "head", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.skip_depth = 0
        self.href = None
        self.in_pre = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        attrs = dict(attrs)
        if re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.out.append("\n\n")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "blockquote":
            self.out.append("\n\n> ")
        elif tag == "pre":
            self.in_pre = True
            self.out.append("\n\n```\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self.in_pre:
            self.out.append("`")
        elif tag == "a":
            self.href = attrs.get("href")
            self.out.append("[")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "pre":
            self.in_pre = False
            self.out.append("\n```\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self.in_pre:
            self.out.append("`")
        elif tag == "a":
            self.out.append(f"]({self.href})" if self.href else "]")
            self.href = None
        elif tag in self.BLOCK or re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n")
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.skip_depth:
            return
        self.out.append(data if self.in_pre else re.sub(r"\s+", " ", data))

    def markdown(self):
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def html_to_md(text):
    p = _HTML2MD()
    p.feed(text)
    return p.markdown()


# ------------------------------------------------------- office (OOXML)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _zip_xml(zf, name):
    return ET.fromstring(zf.read(name))


def docx_to_md(data_path):
    with zipfile.ZipFile(data_path) as zf:
        doc = _zip_xml(zf, "word/document.xml")
    lines = []

    def para_text(p):
        return "".join(t.text or "" for t in p.iter(W + "t"))

    def walk(elem):
        for child in elem:
            if child.tag == W + "p":
                style = ""
                ppr = child.find(W + "pPr")
                if ppr is not None:
                    ps = ppr.find(W + "pStyle")
                    if ps is not None:
                        style = ps.get(W + "val", "")
                text = para_text(child).strip()
                if not text:
                    continue
                m = re.search(r"[Hh]eading\s*([1-6])", style)
                lines.append(("#" * int(m.group(1)) + " " + text) if m else text)
            elif child.tag == W + "tbl":
                rows = []
                for tr in child.iter(W + "tr"):
                    cells = [" ".join((tc.findtext(".//" + W + "t", "") or "").split())
                             for tc in tr.findall(W + "tc")]
                    rows.append(cells)
                if rows:
                    width = max(len(r) for r in rows)
                    rows = [r + [""] * (width - len(r)) for r in rows]
                    lines.append("| " + " | ".join(rows[0]) + " |")
                    lines.append("|" + " --- |" * width)
                    for r in rows[1:]:
                        lines.append("| " + " | ".join(r) + " |")
            else:
                walk(child)

    walk(doc.find(W + "body"))
    return "\n\n".join(lines) + "\n"


def pptx_to_md(data_path):
    with zipfile.ZipFile(data_path) as zf:
        names = [n for n in zf.namelist()
                 if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        out = []
        for i, name in enumerate(names, start=1):
            root = _zip_xml(zf, name)
            paras = []
            for p in root.iter(A + "p"):
                text = "".join(t.text or "" for t in p.iter(A + "t")).strip()
                if text:
                    paras.append(text)
            out.append(f"## Slide {i}\n\n" + "\n\n".join(paras))
    return "\n\n".join(out) + "\n"


def xlsx_to_md(data_path):
    with zipfile.ZipFile(data_path) as zf:
        names = set(zf.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            sroot = _zip_xml(zf, "xl/sharedStrings.xml")
            shared = ["".join(t.text or "" for t in si.iter(S + "t"))
                      for si in sroot.findall(S + "si")]
        wb = _zip_xml(zf, "xl/workbook.xml")
        rels = _zip_xml(zf, "xl/_rels/workbook.xml.rels")
        rel_map = {rel.get("Id"): rel.get("Target") for rel in rels}
        out = []
        for sheet in wb.iter(S + "sheet"):
            title = sheet.get("name", "Sheet")
            target = rel_map.get(sheet.get(R + "id"), "")
            sname = "xl/" + target.lstrip("/") if not target.startswith("xl/") \
                else target
            if sname not in names:
                continue
            sroot = _zip_xml(zf, sname)
            rows = []
            for row in sroot.iter(S + "row"):
                cells = []
                for c in row.findall(S + "c"):
                    v = c.find(S + "v")
                    if c.get("t") == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(S + "t"))
                    elif v is None:
                        val = ""
                    elif c.get("t") == "s":
                        try:
                            val = shared[int(v.text)]
                        except (ValueError, IndexError):
                            val = ""
                    else:
                        val = v.text or ""
                    cells.append(" ".join(str(val).split()))
                if any(cells):
                    rows.append(cells)
            out.append(f"## {title}\n")
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("|" + " --- |" * width)
                for r in rows[1:]:
                    out.append("| " + " | ".join(r) + " |")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------------- pdf

def pdf_to_md(data_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ConvertError(
            "PDF conversion needs pypdf, which this interpreter lacks. "
            "It is installed in the .venv-report virtualenv — run: "
            ".venv-report/bin/python scripts/wiki_convert.py FILE")
    reader = PdfReader(str(data_path))
    parts = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        parts.append(f"## Page {i}\n\n{text}")
    return "\n\n".join(parts).rstrip() + "\n"


# -------------------------------------------------- injection defence
# Prompt-injection defence on the ingest path (WikiCitadel v1;
# pattern: NicoBleh/secure-llm-wiki, MIT): converted output
# is SANITISED before it can enter the wiki — invisible codepoints
# stripped, hidden HTML dropped, base64-smuggled instructions
# neutralised — and the source's trust tier is classified and
# recorded. The gateway modules are loaded by path (the validator's
# profile.py pattern) so this script stays stdlib-only and the
# defence has exactly one implementation.

def _load_gateway_module(name):
    import importlib.util
    mod_path = (Path(__file__).resolve().parent.parent
                / "tools" / "gateway" / "gateway" / f"{name}.py")
    if not mod_path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"gw_{name}", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_SANITIZE = _load_gateway_module("sanitize")
_TRUST = _load_gateway_module("trust")


# ------------------------------------------ sensitivity at ingest
# Sensitivity classes (WikiCitadel v1; PNAAM via the
# survey): material is classified AT INGEST, in the fixed
# vocabulary of evaluation/sensitivity.json (the human statement
# is wiki/rules/schema-profile.md). The class is stamped into
# the ingest sidecar beside the trust tier. A conversion whose
# output enters raw/ IS an ingest and refuses to proceed without
# a class: unclassified never reads as public, so an unstamped
# ingest would enter the corpus in a state nothing may rely on.
# Conversions written elsewhere (scratch, fixtures) are not
# ingests and may omit the stamp — the sidecar then records
# sensitivity: null, which every reader treats as unclassified.

_SENSITIVITY_FALLBACK = ("public", "internal", "personal",
                         "family-sensitive", "credential-adjacent",
                         "export-only")


def _sensitivity_vocabulary():
    """The class ids from evaluation/sensitivity.json when the
    register is readable; the built-in list otherwise, so the
    converter still refuses unknown classes in a bare checkout."""
    reg = (Path(__file__).resolve().parent.parent
           / "evaluation" / "sensitivity.json")
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
        ids = [c["id"] for c in data.get("classes") or []]
        return ids or list(_SENSITIVITY_FALLBACK)
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return list(_SENSITIVITY_FALLBACK)


def _check_sensitivity(sensitivity):
    if sensitivity is not None \
            and sensitivity not in _sensitivity_vocabulary():
        raise ConvertError(
            f"unknown sensitivity class {sensitivity!r}; the "
            f"vocabulary is {_sensitivity_vocabulary()} "
            f"(evaluation/sensitivity.json)")


# ------------------------------------------ format identification
# Format-risk watch (the survey, lane A, finds 12–13): at
# ingest a source's format is IDENTIFIED — by signature where a
# signature exists (the DROID/Siegfried discipline: never trust
# the extension alone) — and recorded in the ingest sidecar with
# its PRONOM PUID, so the format identity survives renames and
# extension changes, and an extension that lies about its
# content is flagged (extension_mismatch) instead of trusted.
#
# PUID discipline: the find names the fmt/… scheme but
# states NO per-format PUID values, and no concrete PUID appears
# anywhere in the local record — so no PUID is hardcoded here
# from memory. Every identified format records puid
# "unverified" until a value is stated in the local record, at
# which point it is entered in _FORMAT_PUID below. A format the
# local record states PRONOM does not cover would record
# "none"; no current format carries that statement, so no entry
# uses it yet. evaluation/format-risk.json is the watch list
# these identifications feed (scripts/wiki_format_watch.py).

_FORMAT_PUID = {
    # format name -> PUID as stated in the local record.
    # Empty by evidence: the finds state no values.
}

# Canonical format names by the extension that conventionally
# carries them — the expectation the signature is checked
# against. .md/.txt are one text family (no mismatch between
# them).
_EXT_FORMAT = {".md": "Markdown", ".txt": "Plain Text",
               ".text": "Plain Text", ".html": "HTML",
               ".htm": "HTML", ".docx": "DOCX", ".pptx": "PPTX",
               ".xlsx": "XLSX", ".pdf": "PDF", ".json": "JSON",
               ".zip": "ZIP Archive"}
_TEXT_FAMILY = {"Markdown", "Plain Text"}


def _puid_for(name):
    return _FORMAT_PUID.get(name, "unverified")


def identify_format(path):
    """Identify a file's format by signature first, extension
    last. Returns {"format", "puid", "basis",
    "extension_mismatch"}: basis is "signature" (magic bytes /
    container contents), "text" (content sniffed as text), or
    "extension" (nothing better available — the format is the
    extension taken on faith, find 13's caveat made visible)."""
    p = Path(path)
    suffix = p.suffix.lower()
    expected = _EXT_FORMAT.get(suffix)
    name = basis = None
    try:
        head = p.read_bytes()[:8192]
    except OSError:
        head = b""
    if head.startswith(b"%PDF-"):
        name, basis = "PDF", "signature"
    elif head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        name, basis = "ZIP Archive", "signature"
        try:
            with zipfile.ZipFile(p) as zf:
                names = set(zf.namelist())
            if "word/document.xml" in names:
                name = "DOCX"
            elif "xl/workbook.xml" in names:
                name = "XLSX"
            elif "ppt/presentation.xml" in names:
                name = "PPTX"
        except (zipfile.BadZipFile, OSError):
            pass  # stays a ZIP by signature; the converter refuses it later
    if name is None and head:
        text = head.decode("utf-8", errors="replace")
        stripped = text.lstrip("\ufeff \t\r\n")
        if stripped[:1] in ("{", "["):
            try:
                json.loads(p.read_text(encoding="utf-8"))
                name, basis = "JSON", "text"
            except (ValueError, OSError, UnicodeDecodeError):
                pass
        if name is None and ("<!doctype html" in text[:2048].lower()
                             or "<html" in text[:2048].lower()):
            name, basis = "HTML", "text"
    if name is None:
        name, basis = expected or "Unknown", "extension"
    mismatch = False
    if expected and basis in ("signature", "text"):
        if not (name == expected
                or (name in _TEXT_FAMILY and expected in _TEXT_FAMILY)):
            mismatch = True
    return {"format": name, "puid": _puid_for(name), "basis": basis,
            "extension_mismatch": mismatch}


def _converter_identity(path):
    """This converter's identity, recorded in every ingest
    sidecar so the citation lockfile can later tell WHICH
    converter produced a converted source (survey,
    KNOX's parser-fingerprint mechanic): the script's own
    content hash, the gateway sanitiser's hash (the sanitiser
    mutates text, so it is part of the converter set), and the
    source format converted. A change to any of them
    re-identifies the converter, and the lockfile re-flags
    citations over sources the old identity produced."""
    import hashlib
    here = Path(__file__).resolve()
    sanitiser = (here.parent.parent / "tools" / "gateway"
                 / "gateway" / "sanitize.py")
    return {
        "tool": "wiki_convert.py",
        "script_sha256": hashlib.sha256(here.read_bytes()).hexdigest(),
        "sanitizer_sha256": (hashlib.sha256(
            sanitiser.read_bytes()).hexdigest()
            if sanitiser.is_file() else None),
        "format": Path(path).suffix.lstrip(".").lower() or None,
    }


# ------------------------------------------ extraction provenance
# OCR verification queue (WikiCitadel v1; pattern:
# ABBYY FineReader Verification, survey): extracted text
# carries its state — the sidecar records HOW the text was got
# out of the source, the confidence the extractor reported, and
# whether the result is machine text nobody has verified. The
# states: "machine-unverified" for the guessing kinds — OCR
# and a PDF's embedded text layer, where a process reads
# characters/layout and can silently misread (pypdf reports no
# confidence at all: "unknown", never an invented number) —
# "machine-extracted" for deterministic structural extraction
# (OOXML/HTML/JSON text nodes read verbatim), "not-applicable"
# for native text passed through untouched. A machine-
# unverified ingest registers its extraction with
# scripts/wiki_ocr_queue.py (enqueue --from-sidecar) and the
# compiled layer may not rest a cited claim on it until a human
# verifies it there. Additive key: the sidecar's existing
# readers (cite lock, format watch) read named keys and are
# unaffected.

_EXTRACTION_UNKNOWN = {
    "method": "unknown", "tool": None,
    "detail": "extraction path unrecorded — treated as "
              "machine-unverified rather than passed over in "
              "silence",
    "confidence": "unknown", "state": "machine-unverified",
}

_EXTRACTION_BY_SUFFIX = {
    ".md": {"method": "none", "tool": None,
            "detail": "native text passthrough — the file's "
                      "own bytes are the text; no extraction "
                      "step",
            "confidence": "not-applicable",
            "state": "not-applicable"},
    ".txt": {"method": "none", "tool": None,
             "detail": "native text passthrough — the file's "
                       "own bytes are the text; no extraction "
                       "step",
             "confidence": "not-applicable",
             "state": "not-applicable"},
    ".text": {"method": "none", "tool": None,
              "detail": "native text passthrough — the file's "
                        "own bytes are the text; no extraction "
                        "step",
              "confidence": "not-applicable",
              "state": "not-applicable"},
    ".html": {"method": "html-text", "tool": "wiki_convert.py",
              "detail": "text read from the HTML source by the "
                        "converter's parser",
              "confidence": "not-applicable",
              "state": "machine-extracted"},
    ".htm": {"method": "html-text", "tool": "wiki_convert.py",
             "detail": "text read from the HTML source by the "
                       "converter's parser",
             "confidence": "not-applicable",
             "state": "machine-extracted"},
    ".docx": {"method": "ooxml-text", "tool": "wiki_convert.py",
              "detail": "text nodes read verbatim from the "
                        "package XML",
              "confidence": "not-applicable",
              "state": "machine-extracted"},
    ".pptx": {"method": "ooxml-text", "tool": "wiki_convert.py",
              "detail": "text nodes read verbatim from the "
                        "package XML",
              "confidence": "not-applicable",
              "state": "machine-extracted"},
    ".xlsx": {"method": "ooxml-text", "tool": "wiki_convert.py",
              "detail": "text nodes read verbatim from the "
                        "package XML",
              "confidence": "not-applicable",
              "state": "machine-extracted"},
    ".pdf": {"method": "embedded-text", "tool": "pypdf",
             "detail": "text read from the PDF's embedded text "
                       "layer (page.extract_text); pypdf "
                       "reports no confidence, and this "
                       "converter does no OCR — a scanned page "
                       "yields no text here, never a guess",
             "confidence": "unknown",
             "state": "machine-unverified"},
    ".json": {"method": "json-text", "tool": "wiki_convert.py",
              "detail": "the JSON document re-serialised "
                        "verbatim",
              "confidence": "not-applicable",
              "state": "machine-extracted"},
}


def _extraction_for(path):
    return dict(_EXTRACTION_BY_SUFFIX.get(
        Path(path).suffix.lower(), _EXTRACTION_UNKNOWN))


def _report_for(path, scan, sensitivity=None, extraction=None):
    import hashlib
    ident = identify_format(path)
    return {
        "source": str(path),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "format": ident["format"],
        "puid": ident["puid"],
        "format_basis": ident["basis"],
        "extension_mismatch": ident["extension_mismatch"],
        "trust_tier": _TRUST.classify(str(path)) if _TRUST else None,
        "sensitivity": sensitivity,
        "extraction": extraction or _extraction_for(path),
        "sanitiser": scan,
        "converter": _converter_identity(path),
    }


def _merge_scans(a, b):
    findings = list((a or {}).get("findings") or []) \
        + list((b or {}).get("findings") or [])
    if _SANITIZE is None:
        return {"verdict": "unavailable", "findings": findings}
    return {"verdict": _SANITIZE.verdict_of(findings), "findings": findings}


def _ingest_defence(path, md, sensitivity=None, extraction=None):
    """Apply the sanitiser + trust classification to converted
    markdown. Returns (clean_md, report). When the gateway modules
    are unavailable the text passes through and the report says so
    — a degraded run must be visible, never silent."""
    if _SANITIZE is None:
        return md, _report_for(path, {"verdict": "unavailable",
                                      "findings": []}, sensitivity,
                               extraction)
    cleaned, scan = _SANITIZE.clean_text(md)
    return cleaned, _report_for(path, scan, sensitivity, extraction)


# -------------------------------------------------------------- dispatch

def convert_with_report(path, sensitivity=None):
    _check_sensitivity(sensitivity)
    p = Path(path)
    if not p.is_file():
        raise ConvertError(f"no such file: {p}")
    suffix = p.suffix.lower()
    if suffix in (".md", ".txt", ".text"):
        return _ingest_defence(p, p.read_text(encoding="utf-8", errors="replace"),
                               sensitivity)
    if suffix in (".html", ".htm"):
        raw_html = p.read_text(encoding="utf-8", errors="replace")
        if _SANITIZE is None:
            return _ingest_defence(p, html_to_md(raw_html), sensitivity)
        # Sanitise the SOURCE first: hidden elements and comments
        # must be dropped before conversion flattens them into
        # innocent-looking markdown text. Then clean the output as
        # well and merge both scans into the ingest record.
        cleaned_src, src_scan = _SANITIZE.clean_text(raw_html)
        md, out_scan = _SANITIZE.clean_text(html_to_md(cleaned_src))
        return md, _report_for(p, _merge_scans(src_scan, out_scan),
                               sensitivity)
    if suffix == ".docx":
        return _ingest_defence(p, docx_to_md(p), sensitivity)
    if suffix == ".pptx":
        return _ingest_defence(p, pptx_to_md(p), sensitivity)
    if suffix == ".xlsx":
        return _ingest_defence(p, xlsx_to_md(p), sensitivity)
    if suffix == ".pdf":
        return _ingest_defence(p, pdf_to_md(p), sensitivity)
    if suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        md = "```json\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```\n"
        return _ingest_defence(p, md, sensitivity)
    raise ConvertError(f"unsupported format {suffix!r}; supported: {SUPPORTED}")


def convert(path):
    md, _report = convert_with_report(path)
    return md


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("-o", "--out", default=None,
                    help="write here instead of stdout")
    ap.add_argument("--sensitivity", default=None, metavar="CLASS",
                    help="sensitivity class for this ingest, from "
                    "the vocabulary in evaluation/sensitivity.json "
                    "(public, internal, personal, family-sensitive, "
                    "credential-adjacent, export-only). REQUIRED "
                    "when --out enters raw/: an ingest without a "
                    "class is refused, because unclassified never "
                    "reads as public")
    args = ap.parse_args(argv)
    try:
        _check_sensitivity(args.sensitivity)
    except ConvertError as exc:
        print(f"wiki_convert: {exc}", file=sys.stderr)
        return 2
    if args.out and "raw" in Path(args.out).parts \
            and not args.sensitivity:
        print("wiki_convert: refusing to ingest into raw/ without "
              "a --sensitivity class (evaluation/sensitivity.json; "
              "the human statement is wiki/rules/schema-profile.md). "
              "Classify the material at the door: unclassified "
              "never reads as public.", file=sys.stderr)
        return 2
    try:
        md, report = convert_with_report(args.file, args.sensitivity)
    except (ConvertError, zipfile.BadZipFile, ET.ParseError,
            json.JSONDecodeError) as exc:
        print(f"wiki_convert: {exc}", file=sys.stderr)
        return 2
    scan = report["sanitiser"] or {}
    print(f"wiki_convert: trust-tier {report['trust_tier']}; sanitiser "
          f"verdict {scan.get('verdict')} "
          f"({len(scan.get('findings') or [])} finding(s))",
          file=sys.stderr)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        sidecar = Path(args.out).with_suffix(
            Path(args.out).suffix + ".ingest.json")
        sidecar.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
        print(f"wrote {args.out} ({len(md)} chars) + {sidecar.name} "
              "(ingest record: trust tier + sanitiser report "
              "+ converter identity + sensitivity + extraction)")
        if report["extraction"]["state"] == "machine-unverified":
            print("wiki_convert: this extraction is machine-"
                  "unverified — register it with "
                  "scripts/wiki_ocr_queue.py enqueue "
                  "--from-sidecar " + str(sidecar),
                  file=sys.stderr)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
