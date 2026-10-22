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
.pdf (needs pypdf), .json (fenced), .epub (spine text), .zip
(listing + convertible members, in memory only), .msg (Outlook
message — a built-in minimal CFB/MAPI reader, stdlib only), .url
(YouTube capture: oEmbed metadata + caption transcript, fetched
live). Anything else is a named door: a ConversionDoorError whose
ingest report records the format evaluation (the ezpzfile idea —
a local, offline assessment of every format's route) instead of
a silent skip. The converter is deliberately conservative:
it preserves text, headings, lists, links and tables, and drops
formatting it cannot represent rather than inventing structure.

Optional heavyweight document engines (Docling / MarkItDown /
Marker / Unstructured) plug in behind this same interface via
scripts/wiki_convert_engines.py — explicit --engine selection
only, never a changed default; see the engine-seam section below.
A GROBID bibliographic sidecar for scholarly PDFs rides the same
explicit-only discipline (--grobid / --grobid-url); its client is
scripts/wiki_grobid.py.
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

SUPPORTED = (".md .txt .html .htm .docx .pptx .xlsx .pdf .json "
             ".epub .zip .msg .url")


class ConvertError(Exception):
    pass


class ParseQualityError(ConvertError):
    """A conversion whose parse-quality score fell below the
    caller's gate threshold (KR-R2). Carries the converted
    markdown and the ingest report so the caller can quarantine
    them with a record instead of filing them."""

    def __init__(self, message, md, report):
        super().__init__(message)
        self.md = md
        self.report = report


class ConversionDoorError(ConvertError):
    """A conversion this environment has no local route for —
    an unsupported format, or a live capture that could not be
    reached. Carries the ingest report (which names the door in
    its "door" block and assesses the format in
    "format_evaluation") so the caller records the door in the
    sidecar instead of the format being skipped in silence."""

    def __init__(self, message, report, door):
        super().__init__(message)
        self.report = report
        self.door = door


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


# ------------------------------------------------------------------ epub
# EPUB breadth (W1.11; pattern: markitdown's one-converter-many-
# formats shape, MIT — implementation original, stdlib only):
# an EPUB is a ZIP whose META-INF/container.xml names an OPF
# package document; the spine gives the reading order. Content
# documents are XHTML and pass the injection gate at the SOURCE
# exactly like the .html route. Hrefs are resolved inside the
# archive namespace only — a spine member that escapes it
# ("../…") or is absent is skipped with a loss note, never read.

_OPF = "{http://www.idpf.org/2007/opf}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_EPUB_MEMBER_CAP = 20 * 1024 * 1024


def _epub_member(zf, name, loss):
    try:
        info = zf.getinfo(name)
    except KeyError:
        loss.append(f"EPUB member named in the package documents "
                    f"is absent from the archive: {name}")
        return None
    if info.file_size > _EPUB_MEMBER_CAP:
        loss.append(f"EPUB member skipped (over the "
                    f"{_EPUB_MEMBER_CAP}-byte extraction cap): {name}")
        return None
    return zf.read(name)


def epub_to_md(source):
    """EPUB (a path or a binary file object) -> (markdown,
    sanitiser findings, loss notes)."""
    import posixpath
    import urllib.parse
    findings, loss = [], []
    with zipfile.ZipFile(source) as zf:
        names = set(zf.namelist())
        if "META-INF/container.xml" not in names:
            raise ConvertError(
                "EPUB without META-INF/container.xml — not an "
                "EPUB package this converter can open")
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = None
        for rf in container.iter(_CONTAINER + "rootfile"):
            rootfile = rf.get("full-path")
            break
        if not rootfile:
            raise ConvertError(
                "EPUB container.xml names no rootfile (OPF) — "
                "the book's spine cannot be located")
        opf_raw = _epub_member(zf, rootfile, loss)
        if opf_raw is None:
            raise ConvertError(
                f"EPUB rootfile {rootfile!r} could not be read "
                f"(see conversion-loss notes)")
        opf = ET.fromstring(opf_raw)
        opf_dir = posixpath.dirname(rootfile)
        title = creator = None
        metadata = opf.find(_OPF + "metadata")
        if metadata is not None:
            t = metadata.find(_DC + "title")
            if t is not None and (t.text or "").strip():
                title = t.text.strip()
            c = metadata.find(_DC + "creator")
            if c is not None and (c.text or "").strip():
                creator = c.text.strip()
        manifest = {}
        images = 0
        for item in opf.iter(_OPF + "item"):
            manifest[item.get("id")] = (item.get("href", ""),
                                        item.get("media-type", ""))
            if (item.get("media-type") or "").startswith("image/"):
                images += 1
        parts = []
        head = []
        if title:
            head.append(f"# {title}")
        if creator:
            head.append(f"Author: {creator}")
        if head:
            parts.append("\n\n".join(head))
        spine = opf.find(_OPF + "spine")
        idrefs = [ir.get("idref")
                  for ir in spine.iter(_OPF + "itemref")] \
            if spine is not None else []
        skipped_types = 0
        for idref in idrefs:
            if idref not in manifest:
                continue
            href, mtype = manifest[idref]
            if mtype not in ("application/xhtml+xml", "text/html"):
                skipped_types += 1
                continue
            rel = urllib.parse.unquote(href).split("#")[0]
            member = posixpath.normpath(
                posixpath.join(opf_dir, rel)) if opf_dir \
                else posixpath.normpath(rel)
            if member.startswith("../") or member.startswith("/") \
                    or member not in names:
                loss.append(f"EPUB spine member not read (unsafe "
                            f"or missing path): {href}")
                continue
            raw = _epub_member(zf, member, loss)
            if raw is None:
                continue
            text = raw.decode("utf-8", errors="replace")
            if _SANITIZE is not None:
                text, scan = _SANITIZE.clean_text(text)
                findings.extend(scan.get("findings") or [])
            parts.append(html_to_md(text))
        if images:
            loss.append(f"{images} image(s) in the EPUB manifest "
                        f"were not extracted (text-only conversion)")
        if skipped_types:
            loss.append(f"{skipped_types} non-text spine item(s) "
                        f"(navigation/media) were not converted")
    md = "\n\n".join(p for p in parts if p.strip()).rstrip()
    return md + "\n", findings, loss


# ------------------------------------------------------------------- zip
# ZIP breadth (W1.11): listing FIRST, then text extraction of the
# members this converter can itself convert — in memory only.
# Nothing is ever written to disk by archive conversion, so a
# hostile member name ("../../evil.md", an absolute path, a
# drive path) is LISTED as unsafe and never extracted; caps on
# entry count, per-member bytes/chars and total chars bound the
# work a crafted archive can cause. Binary and macro members
# (vbaProject.bin and friends) are listed, never opened.

ZIP_MAX_ENTRIES = 200
ZIP_MAX_MEMBER_BYTES = 8 * 1024 * 1024
ZIP_MAX_MEMBER_CHARS = 1_000_000
ZIP_MAX_TOTAL_CHARS = 4_000_000
_ZIP_TEXT_SUFFIXES = {".md", ".txt", ".text", ".json"}
_ZIP_DOC_SUFFIXES = {".docx", ".pptx", ".xlsx", ".epub"}


def _zip_safe_name(name):
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return False
    return ".." not in n.split("/")


def _zip_member_md(suffix, data, findings, loss, name):
    import io
    if suffix in (".html", ".htm"):
        text = data.decode("utf-8", errors="replace")
        if _SANITIZE is not None:
            text, scan = _SANITIZE.clean_text(text)
            findings.extend(scan.get("findings") or [])
        return html_to_md(text)
    if suffix == ".docx":
        return docx_to_md(io.BytesIO(data))
    if suffix == ".pptx":
        return pptx_to_md(io.BytesIO(data))
    if suffix == ".xlsx":
        return xlsx_to_md(io.BytesIO(data))
    if suffix == ".epub":
        md, f2, l2 = epub_to_md(io.BytesIO(data))
        findings.extend(f2)
        loss.extend(f"member {name}: {note}" for note in l2)
        return md
    if suffix == ".json":
        try:
            parsed = json.loads(data.decode("utf-8"))
            return ("```json\n" + json.dumps(parsed, indent=2,
                                             ensure_ascii=False)
                    + "\n```\n")
        except (ValueError, UnicodeDecodeError):
            return data.decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def zip_to_md(path):
    """ZIP archive -> (markdown, sanitiser findings, loss
    notes): a listing table, then the converted text of each
    convertible member, in archive order."""
    findings, loss = [], []
    p = Path(path)
    with zipfile.ZipFile(p) as zf:
        infos = zf.infolist()
        rows, sections = [], []
        total_chars = 0
        n_binary = n_big = n_unsafe = n_cap = n_failed = 0
        if len(infos) > ZIP_MAX_ENTRIES:
            loss.append(
                f"ZIP listing truncated at {ZIP_MAX_ENTRIES} of "
                f"{len(infos)} entries; the rest were neither "
                f"listed nor extracted")
        for info in infos[:ZIP_MAX_ENTRIES]:
            name = info.filename
            if name.endswith("/"):
                rows.append((name, info.file_size, "directory",
                             "listed only"))
                continue
            suffix = Path(name).suffix.lower()
            if not _zip_safe_name(name):
                n_unsafe += 1
                rows.append((name, info.file_size, "unsafe path",
                             "NOT extracted — the path escapes "
                             "the archive root"))
                continue
            convertible = suffix in _ZIP_TEXT_SUFFIXES \
                or suffix in _ZIP_DOC_SUFFIXES \
                or suffix in (".html", ".htm")
            if not convertible:
                n_binary += 1
                rows.append((name, info.file_size,
                             suffix.lstrip(".") or "binary",
                             "listed only"))
                continue
            if info.file_size > ZIP_MAX_MEMBER_BYTES:
                n_big += 1
                rows.append((name, info.file_size, suffix,
                             "listed only — over the per-member "
                             "extraction cap"))
                continue
            if total_chars >= ZIP_MAX_TOTAL_CHARS:
                n_cap += 1
                rows.append((name, info.file_size, suffix,
                             "listed only — the total extraction "
                             "cap was reached"))
                continue
            data = zf.read(name)
            try:
                member_md = _zip_member_md(suffix, data, findings,
                                           loss, name)
            except (ConvertError, zipfile.BadZipFile,
                    ET.ParseError, ValueError, KeyError,
                    UnicodeDecodeError) as exc:
                n_failed += 1
                rows.append((name, info.file_size, suffix,
                             f"listed only — member conversion "
                             f"failed: {exc}"))
                continue
            if len(member_md) > ZIP_MAX_MEMBER_CHARS:
                member_md = member_md[:ZIP_MAX_MEMBER_CHARS]
                loss.append(f"ZIP member truncated at "
                            f"{ZIP_MAX_MEMBER_CHARS} chars: {name}")
            total_chars += len(member_md)
            sections.append(f"## Member: {name}\n\n"
                            f"{member_md.rstrip()}")
            rows.append((name, info.file_size, suffix, "converted"))
    if n_binary:
        loss.append(f"{n_binary} member(s) are not in a "
                    f"convertible format and were listed, not "
                    f"extracted (PDF members included — convert a "
                    f"PDF itself, not through an archive)")
    if n_big:
        loss.append(f"{n_big} member(s) exceeded the "
                    f"{ZIP_MAX_MEMBER_BYTES}-byte per-member cap "
                    f"and were listed, not extracted")
    if n_unsafe:
        loss.append(f"{n_unsafe} member(s) carry unsafe paths "
                    f"and were listed, not extracted")
    if n_cap:
        loss.append(f"{n_cap} convertible member(s) were listed, "
                    f"not extracted — the "
                    f"{ZIP_MAX_TOTAL_CHARS}-char total cap")
    if n_failed:
        loss.append(f"{n_failed} member(s) failed conversion and "
                    f"were listed with the reason")

    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    out = [f"# ZIP archive: {p.name}", "",
           f"{len(infos)} entries.", "",
           "| Member | Size (bytes) | Kind | Disposition |",
           "| --- | --- | --- | --- |"]
    out += [f"| {cell(n)} | {s} | {cell(k)} | {cell(d)} |"
            for n, s, k, d in rows]
    if sections:
        out += ["", "## Contents", ""]
        out += sections
    return "\n".join(out).rstrip() + "\n", findings, loss


# ------------------------------------------------------- outlook .msg
# Outlook .msg breadth (W1.11): a .msg is an OLE/CFB (Compound
# File Binary) container of MAPI property streams. olefile /
# extract_msg are NOT installed in this environment and no new
# packages may be added, so this is a clean-room minimal CFB
# reader written from the format's public specification
# ([MS-CFB] / [MS-OXMSG]): header, DIFAT/FAT chains, directory,
# mini stream, then the named property streams. It reads the
# core properties and the plain-text (or HTML) body; recipient
# and attachment storages are LISTED, never extracted, and a
# compressed-RTF body is a recorded loss, not a guess.

_CFB_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_CFB_FREE = 0xFFFFFFFF
_CFB_END = 0xFFFFFFFE
_CFB_NOSTREAM = 0xFFFFFFFF


class _Cfb:
    def __init__(self, data):
        if data[:8] != _CFB_SIGNATURE:
            raise ConvertError("not a CFB container (bad "
                               "signature) — not an Outlook .msg "
                               "this converter can read")
        if len(data) < 512:
            raise ConvertError("CFB header truncated")

        def u16(o):
            return int.from_bytes(data[o:o + 2], "little")

        def u32(o):
            return int.from_bytes(data[o:o + 4], "little")

        self.data = data
        self.sector_size = 1 << u16(30)
        self.mini_sector_size = 1 << u16(32)
        self.mini_cutoff = u32(56)
        difat = [u32(76 + 4 * i) for i in range(109)]
        nxt = u32(68)
        guard = 0
        while nxt not in (_CFB_END, _CFB_FREE) and guard < 4096:
            sec = self._sector(nxt)
            per = self.sector_size // 4
            entries = [int.from_bytes(sec[4 * i:4 * i + 4], "little")
                       for i in range(per)]
            difat.extend(entries[:-1])
            nxt = entries[-1]
            guard += 1
        self.fat = []
        for fat_sect in difat:
            if fat_sect >= 0xFFFFFFFA:
                continue
            sec = self._sector(fat_sect)
            self.fat.extend(
                int.from_bytes(sec[4 * i:4 * i + 4], "little")
                for i in range(self.sector_size // 4))
        dir_bytes = self._read_chain(u32(48), regular=True)
        self.entries = []
        for off in range(0, len(dir_bytes) - 127, 128):
            e = dir_bytes[off:off + 128]
            name_len = int.from_bytes(e[64:66], "little")
            name = e[:max(0, name_len - 2)].decode(
                "utf-16-le", errors="replace") if name_len >= 2 else ""
            self.entries.append({
                "name": name, "type": e[66],
                "left": int.from_bytes(e[68:72], "little"),
                "right": int.from_bytes(e[72:76], "little"),
                "child": int.from_bytes(e[76:80], "little"),
                "start": int.from_bytes(e[116:120], "little"),
                "size": int.from_bytes(e[120:128], "little")})
        if not self.entries:
            raise ConvertError("CFB directory is empty")
        root = self.entries[0]
        self._mini_stream = self._read_chain(
            root["start"], regular=True)[:root["size"]] \
            if root["size"] else b""
        self.minifat = []
        if u32(64) and u32(60) not in (_CFB_END, _CFB_FREE):
            mf = self._read_chain(u32(60), regular=True)
            self.minifat = [int.from_bytes(mf[4 * i:4 * i + 4],
                                           "little")
                            for i in range(len(mf) // 4)]

    def _sector(self, n):
        off = (n + 1) * self.sector_size
        sec = self.data[off:off + self.sector_size]
        if len(sec) < self.sector_size:
            raise ConvertError("CFB sector out of range")
        return sec

    def _read_chain(self, start, regular):
        table = self.fat if regular else self.minifat
        out = bytearray()
        cur = start
        guard = 0
        while cur not in (_CFB_END, _CFB_FREE) \
                and guard <= len(table) + 1:
            if cur >= len(table):
                raise ConvertError("CFB chain runs past its "
                                   "allocation table")
            if regular:
                out.extend(self._sector(cur))
            else:
                off = cur * self.mini_sector_size
                chunk = self._mini_stream[off:off + self.mini_sector_size]
                if len(chunk) < self.mini_sector_size:
                    raise ConvertError("CFB mini sector out of "
                                       "range")
                out.extend(chunk)
            cur = table[cur]
            guard += 1
        return bytes(out)

    def streams(self):
        """[(path tuple, stream name, bytes)] for every stream."""
        out = []
        seen = set()

        def data_for(e):
            if e["size"] < self.mini_cutoff and self.minifat:
                return self._read_chain(e["start"],
                                        regular=False)[:e["size"]]
            return self._read_chain(e["start"],
                                    regular=True)[:e["size"]]

        def visit(sid, prefix):
            if sid == _CFB_NOSTREAM or sid >= len(self.entries) \
                    or sid in seen:
                return
            seen.add(sid)
            e = self.entries[sid]
            visit(e["left"], prefix)
            if e["type"] == 2:
                out.append((prefix, e["name"], data_for(e)))
            if e["type"] in (1, 5) \
                    and e["child"] != _CFB_NOSTREAM:
                visit(e["child"],
                      prefix + (e["name"],) if e["type"] == 1
                      else prefix)
            visit(e["right"], prefix)

        if self.entries:
            visit(self.entries[0]["child"], ())
        return out


def _msg_decode(raw, type_tag):
    if type_tag == "001F":
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("cp1252", errors="replace")


def msg_to_md(path):
    """Outlook .msg -> (markdown, sanitiser findings, loss
    notes) via the built-in CFB reader."""
    data = Path(path).read_bytes()
    try:
        cfb = _Cfb(data)
        streams = cfb.streams()
    except ConvertError:
        raise
    except Exception as exc:
        raise ConvertError(f".msg (CFB) parse failed: {exc}")
    smap = {(prefix, name): raw for prefix, name, raw in streams}
    findings, loss = [], []

    def prop(pid, prefix=()):
        for type_tag in ("001F", "001E"):
            raw = smap.get((prefix,
                            f"__substg1.0_{pid:04X}{type_tag}"))
            if raw is not None:
                return _msg_decode(raw, type_tag) \
                    .strip("\x00").strip()
        return None

    def prop_bytes(pid, prefix=()):
        return smap.get((prefix, f"__substg1.0_{pid:04X}0102"))

    subject = prop(0x0037)
    sender = prop(0x0C1A)
    sender_email = prop(0x0C1F)
    display_to = prop(0x0E04)
    display_cc = prop(0x0E03)
    date = None
    props_raw = smap.get(((), "__properties_version1.0"))
    if props_raw:
        import datetime
        entries = props_raw[32:]  # the root properties header
        for off in range(0, len(entries) - 15, 16):
            tag = int.from_bytes(entries[off:off + 4], "little")
            if (tag >> 16) in (0x0E06, 0x0039) \
                    and (tag & 0xFFFF) == 0x0040:
                ft = int.from_bytes(entries[off + 8:off + 16],
                                    "little")
                moment = datetime.datetime(
                    1601, 1, 1, tzinfo=datetime.timezone.utc) \
                    + datetime.timedelta(microseconds=ft / 10)
                date = moment.strftime("%Y-%m-%d %H:%M UTC")
                break
    body = prop(0x1000)
    if body is None:
        raw_body = prop_bytes(0x1000)
        if raw_body:
            body = raw_body.decode(
                "utf-16-le" if b"\x00" in raw_body[1:6]
                else "utf-8", errors="replace").strip("\x00").strip()
    if not body:
        raw_html_body = prop_bytes(0x1013)
        if raw_html_body:
            text = raw_html_body.decode("utf-8", errors="replace")
            if _SANITIZE is not None:
                text, scan = _SANITIZE.clean_text(text)
                findings.extend(scan.get("findings") or [])
            body = html_to_md(text).strip()
    if not body and any(name.endswith("10090102")
                        for _pre, name in smap):
        loss.append("the message body is stored as compressed "
                    "RTF (property 0x1009), which this converter "
                    "does not decode")
    recipients = []
    for (prefix, name), raw in sorted(smap.items()):
        if len(prefix) == 1 \
                and prefix[0].startswith("__recip_version1.0_") \
                and name in ("__substg1.0_3001001F",
                             "__substg1.0_3001001E"):
            recipients.append(_msg_decode(
                raw, name[-4:]).strip("\x00").strip())
    attach_names = []
    stores = sorted({prefix[0] for (prefix, _n) in smap
                     if len(prefix) == 1 and prefix[0].startswith(
                         "__attach_version1.0_")})
    for store in stores:
        fname = prop(0x3707, (store,)) or prop(0x3704, (store,))
        attach_names.append(fname or store)
    if attach_names:
        loss.append(f"{len(attach_names)} attachment(s) listed, "
                    f"not extracted (this converter reads message "
                    f"text only)")
    lines = [f"# {subject or '(no subject)'}", ""]
    if sender or sender_email:
        lines.append(f"From: {sender or ''}"
                     f"{' <' + sender_email + '>' if sender_email else ''}")
    if display_to:
        lines.append(f"To: {display_to}")
    elif recipients:
        lines.append(f"To: {', '.join(recipients)}")
    if display_cc:
        lines.append(f"Cc: {display_cc}")
    if date:
        lines.append(f"Date: {date}")
    lines += ["", "## Body", "",
              body if body else "(no readable body — see the "
                                "conversion-loss notes)"]
    if attach_names:
        lines += ["", "## Attachments (listed, not extracted)", ""]
        lines += [f"- {n}" for n in attach_names]
    return "\n".join(lines).rstrip() + "\n", findings, loss


# ------------------------------------------------------- youtube (.url)
# YouTube-URL breadth (W1.11): a .url (Internet Shortcut) file
# pointing at a YouTube video is captured as metadata + caption
# transcript — the video itself is never downloaded. Fetching
# uses urllib only (oEmbed for metadata; the watch page's
# captionTracks for the transcript). Where nothing is reachable
# the conversion is a named door in the sidecar, never a silent
# empty file. _fetch_url is a module function so tests can stand
# in for the network.

_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
             "music.youtube.com", "youtu.be",
             "www.youtube-nocookie.com"}


def _fetch_url(url, timeout=12):
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "wiki-convert/1.0 "
                                   "(local ingest)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class _DoorSignal(Exception):
    def __init__(self, name, reason):
        super().__init__(reason)
        self.name = name
        self.reason = reason


def _youtube_video_id(url):
    import urllib.parse
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    if host == "youtu.be":
        return u.path.strip("/").split("/")[0] or None
    if host in _YT_HOSTS:
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/watch" and qs.get("v"):
            return qs["v"][0]
        for pre in ("/shorts/", "/embed/", "/live/", "/v/"):
            if u.path.startswith(pre):
                return u.path[len(pre):].split("/")[0] or None
    return None


def youtube_to_md(path):
    """A .url file for a YouTube video -> (markdown, loss
    notes). Raises _DoorSignal when nothing is reachable."""
    import urllib.parse
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    url = None
    for line in text.splitlines():
        if line.lower().startswith("url="):
            url = line[4:].strip()
            break
    if not url:
        m = re.search(r"https?://\S+", text)
        if m:
            url = m.group(0)
    if not url:
        raise ConvertError(".url file carries no URL")
    vid = _youtube_video_id(url)
    if not vid:
        raise ConvertError(
            f".url target is not a YouTube video URL this "
            f"converter captures: {url}")
    watch = f"https://www.youtube.com/watch?v={vid}"
    loss = []
    title = author = None
    try:
        meta = json.loads(_fetch_url(
            "https://www.youtube.com/oembed?url="
            + urllib.parse.quote(watch, safe="")
            + "&format=json").decode("utf-8", "replace"))
        title = meta.get("title")
        author = meta.get("author_name")
    except Exception:
        pass
    transcript = None
    try:
        page = _fetch_url(watch).decode("utf-8", "replace")
        tracks = None
        idx = page.find('"captionTracks"')
        if idx >= 0:
            rest = page[idx + len('"captionTracks"'):]
            rest = rest[rest.index("["):]
            tracks, _end = json.JSONDecoder().raw_decode(rest)
        if tracks:
            def rank(track):
                lang = track.get("languageCode", "")
                if lang.startswith("en") \
                        and track.get("kind") != "asr":
                    return 0
                return 1 if lang.startswith("en") else 2

            track = sorted(tracks, key=rank)[0]
            base = track["baseUrl"]
            tdata = json.loads(_fetch_url(
                base + ("&" if "?" in base else "?")
                + "fmt=json3").decode("utf-8", "replace"))
            spoken = []
            for event in tdata.get("events", []):
                line = "".join(seg.get("utf8", "")
                               for seg in event.get("segs")
                               or []).strip()
                if line:
                    spoken.append(line)
            transcript = "\n".join(spoken) or None
            if transcript:
                loss.append(
                    f"transcript captured from the "
                    f"'{track.get('languageCode', '?')}' caption "
                    f"track"
                    + (" (automatic captions)"
                       if track.get("kind") == "asr" else ""))
    except Exception:
        pass
    if title is None and transcript is None:
        raise _DoorSignal(
            "youtube-unreachable",
            f"neither the oEmbed metadata nor the watch page "
            f"for {watch} could be fetched from this "
            f"environment — no YouTube content was captured")
    parts = [f"# {title or ('YouTube video ' + vid)}", "",
             f"Source: {watch}"]
    if author:
        parts.append(f"Channel: {author}")
    if transcript:
        parts += ["", "## Transcript", "", transcript]
    else:
        parts += ["", "Transcript: not captured — no reachable "
                      "caption track (see the conversion-loss "
                      "notes)."]
        loss.append("no caption track could be fetched — "
                    "transcript not captured; metadata only")
    if title is None:
        loss.append("oEmbed metadata unreachable — the title "
                    "was not captured")
    return "\n".join(parts).rstrip() + "\n", loss


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
               ".zip": "ZIP Archive", ".epub": "EPUB",
               ".msg": "Outlook Message",
               ".url": "Internet Shortcut"}
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
    if head[:8] == _CFB_SIGNATURE:
        name, basis = "Outlook Message", "signature"
    elif head.startswith(b"%PDF-"):
        name, basis = "PDF", "signature"
    elif head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        name, basis = "ZIP Archive", "signature"
        try:
            with zipfile.ZipFile(p) as zf:
                names = set(zf.namelist())
                mimetype = None
                if "mimetype" in names:
                    mimetype = zf.read("mimetype")[:64] \
                        .decode("ascii", errors="replace").strip()
            if "word/document.xml" in names:
                name = "DOCX"
            elif "xl/workbook.xml" in names:
                name = "XLSX"
            elif "ppt/presentation.xml" in names:
                name = "PPTX"
            elif "META-INF/container.xml" in names \
                    or mimetype == "application/epub+zip":
                name = "EPUB"
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
    ".epub": {"method": "epub-text", "tool": "wiki_convert.py",
              "detail": "text read from the EPUB's spine "
                        "content documents (XHTML) in reading "
                        "order by the converter's parser",
              "confidence": "not-applicable",
              "state": "machine-extracted"},
    ".zip": {"method": "zip-members", "tool": "wiki_convert.py",
             "detail": "the archive listing plus text "
                       "extracted in memory from the members "
                       "in convertible formats — nothing is "
                       "written outside the conversion output",
             "confidence": "not-applicable",
             "state": "machine-extracted"},
    ".msg": {"method": "cfb-msg", "tool": "wiki_convert.py",
             "detail": "core MAPI properties and the message "
                       "body read from the CFB property streams "
                       "by the converter's built-in CFB reader",
             "confidence": "not-applicable",
             "state": "machine-extracted"},
    ".url": {"method": "url-capture", "tool": "wiki_convert.py",
             "detail": "YouTube metadata (oEmbed) and "
                       "caption-track text fetched live at "
                       "conversion time; remote and mutable, "
                       "so the capture is treated as "
                       "unverified",
             "confidence": "unknown",
             "state": "machine-unverified"},
}


def _extraction_for(path):
    return dict(_EXTRACTION_BY_SUFFIX.get(
        Path(path).suffix.lower(), _EXTRACTION_UNKNOWN))


# --------------------------------- conversion loss + evaluation
# Conversion-loss notes (W1.11): every format states, in its
# ingest sidecar, what the conversion does NOT carry — the
# per-format static notes below plus the dynamic notes a
# converter records while working (an EPUB's skipped images, a
# ZIP's listed-only members, a .msg's undecoded RTF body).
#
# The format evaluation is the ezpzfile idea (ezpzfile-mcp,
# Round 5 capture & ingest batch — idea only, re-implemented):
# a LOCAL, deterministic, offline assessment of the route this
# converter has for a format and what that route loses, recorded
# for EVERY conversion — and, for a format with no route, the
# whole content of the door record, so a rare format is assessed
# on the record instead of refused in silence.

_LOSS_NOTES = {
    ".pdf": ["page layout, columns, images and reading order "
             "beyond the embedded text layer are not preserved"],
    ".docx": ["tracked changes, comments, headers/footers and "
              "embedded objects are not converted"],
    ".pptx": ["speaker notes, animations and slide layout are "
              "not converted"],
    ".xlsx": ["formulas are converted as their cached values; "
              "charts and formatting are dropped"],
    ".html": ["scripts, styles and interactive elements are "
              "dropped; only readable structure is kept"],
    ".htm": ["scripts, styles and interactive elements are "
             "dropped; only readable structure is kept"],
    ".json": ["the document is re-serialised; the original "
              "key order and whitespace are not preserved"],
    ".epub": ["images, CSS styling and fixed-layout geometry "
              "are dropped; text follows the OPF spine order"],
    ".zip": ["only members in a supported text format are "
             "converted; every other member is listed, not "
             "extracted"],
    ".msg": ["attachments are listed, not extracted; "
             "compressed-RTF bodies and embedded messages are "
             "not decoded"],
    ".url": ["only YouTube metadata and caption text are "
             "captured; the audio/video themselves are never "
             "downloaded"],
}

_NATIVE_FORMATS = {"Markdown", "Plain Text", "HTML", "DOCX",
                   "PPTX", "XLSX", "JSON"}
_PARTIAL_FORMATS = {"PDF", "EPUB", "ZIP Archive",
                    "Outlook Message", "Internet Shortcut"}


def evaluate_format(path, ident=None):
    """Assess the local conversion route for a file's format.
    Returns {"format", "route" ("native" | "partial" | "door"),
    "expected_loss", "recommendation"} — deterministic, offline,
    no model, no network."""
    ident = ident or identify_format(path)
    fmt = ident["format"]
    suffix = Path(path).suffix.lower()
    expected_loss = list(_LOSS_NOTES.get(suffix, []))
    if fmt in _NATIVE_FORMATS:
        route = "native"
        recommendation = ("convert with wiki_convert.py; the "
                          "route is a full local extraction")
    elif fmt in _PARTIAL_FORMATS:
        route = "partial"
        recommendation = ("convert with wiki_convert.py; the "
                          "route is partial — weigh the recorded "
                          "conversion-loss notes before citing "
                          "the parse")
    else:
        route = "door"
        recommendation = ("no local conversion route — do not "
                          "ingest this format until a converter "
                          "lands behind the injection gate; the "
                          "file itself is preserved as-is")
    return {"format": fmt, "route": route,
            "expected_loss": expected_loss,
            "recommendation": recommendation}


def _report_for(path, scan, sensitivity=None, extraction=None,
                loss=None):
    import hashlib
    ident = identify_format(path)
    report = {
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
    report["conversion_loss"] = list(
        _LOSS_NOTES.get(Path(path).suffix.lower(), [])) \
        + list(loss or [])
    report["format_evaluation"] = evaluate_format(path, ident)
    return report


def _merge_scans(a, b):
    findings = list((a or {}).get("findings") or []) \
        + list((b or {}).get("findings") or [])
    if _SANITIZE is None:
        return {"verdict": "unavailable", "findings": findings}
    return {"verdict": _SANITIZE.verdict_of(findings), "findings": findings}


def _ingest_defence(path, md, sensitivity=None, extraction=None,
                    loss=None):
    """Apply the sanitiser + trust classification to converted
    markdown. Returns (clean_md, report). When the gateway modules
    are unavailable the text passes through and the report says so
    — a degraded run must be visible, never silent."""
    if _SANITIZE is None:
        return md, _report_for(path, {"verdict": "unavailable",
                                      "findings": []}, sensitivity,
                               extraction, loss)
    cleaned, scan = _SANITIZE.clean_text(md)
    return cleaned, _report_for(path, scan, sensitivity, extraction,
                                loss)


# ------------------------------------------ parse-quality gating
# KR-R2 (Marathon Round 3, lane TA4; pattern: parse-quality
# gating with a structural metric, Upstage Document Parse /
# DP-Bench via the Korea harvest — proprietary source, IDEA
# ONLY, re-implemented here from the idea): a conversion is
# scored for parse quality BEFORE it can be filed, and a caller
# that sets a threshold gets a gate: below-threshold parses
# raise ParseQualityError carrying the markdown + report, so
# the caller quarantines them with a record instead of filing
# a parse nobody should cite. The score is a deterministic
# stdlib heuristic bundle (no model, no network):
#   readable ratio  alphanumerics + ordinary punctuation as a
#                   share of non-space characters (garble —
#                   symbol soup, replacement chars, control
#                   chars — drags this down)
#   diversity       distinct word tokens / word tokens (a
#                   parse that repeats one token is a failed
#                   extraction, however clean its characters)
#   structure       headings / lists / tables / code fences /
#                   multiple paragraphs present at all
#   substance       word count up to a small floor (an empty
#                   or near-empty parse scores ~0)
# The components are recorded in the ingest report's
# "parse_quality" block beside the score, so a quarantined
# parse says WHY it scored low.

def parse_quality(md):
    """Score converted markdown 0.0–1.0. Returns
    {"score", "verdict" ("good" at >= 0.5), "components"}."""
    text = md or ""
    stripped = text.strip()
    if not stripped:
        return {"score": 0.0, "verdict": "poor",
                "components": {"words": 0, "readable_ratio": 0.0,
                               "diversity": 0.0, "structure": 0.0,
                               "substance": 0.0}}
    words = re.findall(r"[A-Za-z0-9']+", text)
    n_words = len(words)
    nonspace = [c for c in text if not c.isspace()]
    readable = sum(1 for c in nonspace
                   if c.isalnum() or c in ".,;:!?()'\"-—–#>|*_`~/\\[]{}=+")
    readable_ratio = readable / max(1, len(nonspace))
    garble = sum(1 for c in text if c == "�" or
                 (ord(c) < 32 and c not in "\n\t"))
    garble_ratio = garble / max(1, len(text))
    diversity = (len({w.lower() for w in words}) / n_words
                 if n_words else 0.0)
    structure_hits = 0
    if re.search(r"^#{1,6} ", text, re.M):
        structure_hits += 1
    if re.search(r"^\s*[-*] ", text, re.M):
        structure_hits += 1
    if re.search(r"^\|.*\|", text, re.M):
        structure_hits += 1
    if "```" in text:
        structure_hits += 1
    if len([p for p in text.split("\n\n") if p.strip()]) >= 2:
        structure_hits += 1
    structure = structure_hits / 5.0
    substance = min(1.0, n_words / 25.0)
    score = (0.45 * readable_ratio + 0.25 * diversity
             + 0.15 * structure + 0.15 * substance
             - 2.0 * garble_ratio)
    if n_words > 10 and diversity < 0.2:
        score -= 0.3  # one token repeated: a failed extraction
    score = max(0.0, min(1.0, round(score, 3)))
    return {"score": score,
            "verdict": "good" if score >= 0.5 else "poor",
            "components": {
                "words": n_words,
                "readable_ratio": round(readable_ratio, 3),
                "diversity": round(diversity, 3),
                "structure": round(structure, 3),
                "substance": round(substance, 3),
                "garble_ratio": round(garble_ratio, 4)}}


# ------------------------------------------------------- engine seam
# Optional heavyweight document engines behind this converter's
# interface (W4 document-engine trials). The registry, the
# availability probes, the complexity-scored auto-selection and
# the invented-content trust check live in
# scripts/wiki_convert_engines.py. Selection is EXPLICIT
# (--engine NAME, or --engine auto for the scored route); no
# engine is ever engaged by default — with no engine named, this
# module behaves exactly as it did before the seam. An engine's
# raw output passes through the SAME injection gate
# (_ingest_defence) as every built-in route, and the sidecar
# gains an "engine" block naming the engine, its identity, its
# licence route, the selection mode and — on an auto route — the
# complexity score and the recommendation, so a fallback to the
# built-in converter is recorded, never silent. Selecting an
# engine this environment cannot run is a named door
# ("engine-unavailable") in the sidecar, like every other door.
#
# The GROBID bibliographic sidecar (W4, item 40) rides the
# same explicit-only discipline: --grobid (endpoint from the
# GROBID_URL environment variable) or --grobid-url URL asks
# the GROBID service (registered in wiki_convert_engines.py
# as a SIDECAR SERVICE — it extracts bibliographic structure,
# it does not convert) for a PDF's header metadata, parsed
# references and citation contexts, recorded in the sidecar
# under "grobid" as machine-unverified engine output feeding
# wiki_scholar_check.py. With neither flag, no "grobid" key
# appears and behaviour is byte-identical to before. The
# client + TEI parser live in scripts/wiki_grobid.py.

_ENGINES_MODULE = None


def _load_engines():
    """The engines module is a per-process SINGLETON: if it is
    already loaded (a caller or a test registered an engine),
    that instance — and its registry — is the one used."""
    global _ENGINES_MODULE
    if _ENGINES_MODULE is None:
        import sys
        _ENGINES_MODULE = sys.modules.get("wiki_convert_engines")
        if _ENGINES_MODULE is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "wiki_convert_engines",
                Path(__file__).with_name("wiki_convert_engines.py"))
            mod = importlib.util.module_from_spec(spec)
            sys.modules["wiki_convert_engines"] = mod
            spec.loader.exec_module(mod)
            _ENGINES_MODULE = mod
    return _ENGINES_MODULE


def _convert_via_engine(path, sensitivity, engine):
    engines = _load_engines()
    p = Path(path)
    if engine == "auto":
        route = engines.select_engine(p, "auto")
        chosen = route["engine"]
    else:
        if engine not in engines.ENGINES:
            raise ConvertError(
                f"unknown engine {engine!r}; registered: "
                f"{', '.join(sorted(engines.ENGINES))} (plus "
                f"'auto'; no --engine means the built-in "
                f"converter)")
        route = {"engine": engine, "mode": "explicit",
                 "complexity": None, "recommendation": engine}
        chosen = engine
    if chosen == "builtin":
        md, report = _convert_with_report_impl(path, sensitivity)
        report["engine"] = {
            "requested": engine, "ran": "builtin",
            "mode": route["mode"],
            "complexity": route.get("complexity"),
            "recommendation": route.get("recommendation"),
            "note": "the built-in converter ran: the document "
                    "needed no heavier engine, or the recommended "
                    "engine is unavailable here — the gap is "
                    "recorded, not silent"}
        return md, report
    suffix = p.suffix.lower()
    if suffix not in engines.ENGINES[chosen]["formats"]:
        report = _report_for(p, {"verdict": "unavailable",
                                 "findings": []}, sensitivity)
        door = {"name": "engine-format-unsupported",
                "format": identify_format(p)["format"],
                "engine": chosen,
                "reason": f"engine {chosen!r} does not convert "
                          f"{suffix} files; its formats: "
                          f"{', '.join(sorted(engines.ENGINES[chosen]['formats']))}"}
        report["door"] = door
        raise ConversionDoorError(
            f"engine {chosen!r} does not convert {suffix!r} — "
            f"recorded as door 'engine-format-unsupported' in "
            f"the ingest sidecar", report, door)
    try:
        raw_md, meta = engines.run_engine(chosen, p)
    except engines.EngineUnavailable as unavail:
        report = _report_for(p, {"verdict": "unavailable",
                                 "findings": []}, sensitivity)
        report["engine"] = {"requested": engine, "ran": None,
                            "mode": route["mode"],
                            "probe": unavail.engine["probe"]}
        door = {"name": "engine-unavailable",
                "format": identify_format(p)["format"],
                "engine": chosen,
                "reason": unavail.engine["probe"]["blocker"]}
        report["door"] = door
        raise ConversionDoorError(
            f"document engine {chosen!r} unavailable: "
            f"{door['reason']} — recorded as door "
            f"'engine-unavailable' in the ingest sidecar",
            report, door)
    extraction = {
        "method": "document-engine", "tool": chosen,
        "detail": "text produced by the optional document "
                  f"engine {meta['label']} behind the converter "
                  "seam; its layout and table reconstruction is "
                  "inferred, not read verbatim, so the extraction "
                  "is machine-unverified until checked",
        "confidence": "unknown", "state": "machine-unverified"}
    loss = [f"conversion performed by the {chosen} engine; "
            f"anything it does not represent in its markdown "
            f"is not carried"]
    md, report = _ingest_defence(p, raw_md, sensitivity,
                                 extraction=extraction, loss=loss)
    report["engine"] = {
        "requested": engine, "ran": chosen, "mode": route["mode"],
        "complexity": route.get("complexity"),
        "recommendation": route.get("recommendation"),
        "identity": meta}
    return md, report


# --------------------------------------------------- GROBID sidecar

_GROBID_MODULE = None


def _load_grobid():
    """The grobid module is a per-process SINGLETON, loaded
    exactly as _load_engines loads the engines module."""
    global _GROBID_MODULE
    if _GROBID_MODULE is None:
        import sys
        _GROBID_MODULE = sys.modules.get("wiki_grobid")
        if _GROBID_MODULE is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "wiki_grobid",
                Path(__file__).with_name("wiki_grobid.py"))
            mod = importlib.util.module_from_spec(spec)
            sys.modules["wiki_grobid"] = mod
            spec.loader.exec_module(mod)
            _GROBID_MODULE = mod
    return _GROBID_MODULE


def _apply_grobid_sidecar(report, path, grobid):
    """Attach the GROBID block to a finished conversion
    report. `grobid` is True (endpoint from the GROBID_URL
    environment variable) or an explicit endpoint URL. The
    sidecar is additive: doors and failures are recorded in
    the block and never fail the conversion itself."""
    gb = _load_grobid()
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix != ".pdf":
        report["grobid"] = gb.format_door_block(suffix)
        return
    endpoint = grobid if isinstance(grobid, str) else None
    report["grobid"] = gb.extract(p, endpoint=endpoint)


# -------------------------------------------------------------- dispatch

def convert_with_report(path, sensitivity=None, quality_threshold=None,
                        engine=None, grobid=None):
    if engine is not None:
        md, report = _convert_via_engine(path, sensitivity, engine)
    else:
        md, report = _convert_with_report_impl(path, sensitivity)
    quality = parse_quality(md)
    report["parse_quality"] = quality
    if quality_threshold is not None \
            and quality["score"] < quality_threshold:
        raise ParseQualityError(
            "parse-quality gate: score %.3f is below the "
            "threshold %.3f (components: %s) — quarantine this "
            "parse instead of filing it"
            % (quality["score"], quality_threshold,
               quality["components"]), md, report)
    if grobid is not None:
        _apply_grobid_sidecar(report, path, grobid)
    return md, report


def _convert_with_report_impl(path, sensitivity=None):
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
    if suffix in (".epub", ".zip", ".msg"):
        extractor = {".epub": epub_to_md, ".zip": zip_to_md,
                     ".msg": msg_to_md}[suffix]
        raw_md, src_findings, loss = extractor(p)
        if _SANITIZE is None:
            return _ingest_defence(p, raw_md, sensitivity, loss=loss)
        # The extractors already sanitised embedded HTML at the
        # source; clean the assembled output as well and merge
        # both scans — the .html route's discipline, unchanged.
        md, out_scan = _SANITIZE.clean_text(raw_md)
        src_scan = {"verdict": _SANITIZE.verdict_of(src_findings),
                    "findings": src_findings}
        return md, _report_for(p, _merge_scans(src_scan, out_scan),
                               sensitivity, loss=loss)
    if suffix == ".url":
        try:
            md, loss = youtube_to_md(p)
        except _DoorSignal as door:
            report = _report_for(p, {"verdict": "unavailable",
                                     "findings": []}, sensitivity)
            report["door"] = {"name": door.name,
                              "format": "Internet Shortcut",
                              "reason": door.reason}
            raise ConversionDoorError(
                f"YouTube capture door {door.name!r}: "
                f"{door.reason} — recorded in the ingest "
                f"sidecar", report, report["door"])
        return _ingest_defence(p, md, sensitivity, loss=loss)
    ident = identify_format(p)
    report = _report_for(p, {"verdict": "unavailable",
                             "findings": []}, sensitivity)
    door = {"name": "no-local-converter",
            "format": ident["format"],
            "reason": f"no local conversion route for "
                      f"{ident['format']} ({suffix or 'no suffix'}); "
                      f"the format evaluation in this sidecar "
                      f"records the assessment"}
    report["door"] = door
    raise ConversionDoorError(
        f"unsupported format {suffix!r}; supported: {SUPPORTED} "
        f"— recorded as door 'no-local-converter' in the ingest "
        f"sidecar", report, door)


def convert(path):
    md, _report = convert_with_report(path)
    return md


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="?",
                    help="the document to convert (not needed "
                    "with --engines)")
    ap.add_argument("-o", "--out", default=None,
                    help="write here instead of stdout")
    ap.add_argument("--quality-threshold", type=float, default=None,
                    metavar="SCORE",
                    help="parse-quality gate (KR-R2): refuse to "
                    "file a conversion scoring below SCORE "
                    "(0.0-1.0); the parse is quarantined under "
                    "--quarantine-dir with its ingest report "
                    "instead, and the exit code is 3")
    ap.add_argument("--quarantine-dir", default="quarantine/parse-quality",
                    metavar="DIR",
                    help="where a gated parse is quarantined "
                    "(default: quarantine/parse-quality)")
    ap.add_argument("--sensitivity", default=None, metavar="CLASS",
                    help="sensitivity class for this ingest, from "
                    "the vocabulary in evaluation/sensitivity.json "
                    "(public, internal, personal, family-sensitive, "
                    "credential-adjacent, export-only). REQUIRED "
                    "when --out enters raw/: an ingest without a "
                    "class is refused, because unclassified never "
                    "reads as public")
    ap.add_argument("--engine", default=None, metavar="NAME",
                    help="optional heavyweight document engine "
                    "behind the converter seam (W4): a registered "
                    "name (docling, markitdown, unstructured, "
                    "marker) or 'auto' for complexity-scored "
                    "selection. Default: the built-in converter, "
                    "unchanged. An engine this environment cannot "
                    "run is a named door in the sidecar, never a "
                    "silent fallback")
    ap.add_argument("--engines", action="store_true",
                    help="list the registered engines with their "
                    "live availability probe and licence route, "
                    "then exit")
    ap.add_argument("--grobid", action="store_true",
                    help="also run the GROBID bibliographic "
                    "sidecar (W4) over a PDF conversion: header "
                    "metadata + parsed references + citation "
                    "contexts recorded in the ingest sidecar "
                    "under 'grobid' as machine-unverified engine "
                    "output feeding wiki_scholar_check.py. The "
                    "endpoint comes from the GROBID_URL "
                    "environment variable or --grobid-url; no "
                    "endpoint configured is a named door in the "
                    "sidecar, never a silent skip. Default: no "
                    "sidecar, behaviour unchanged")
    ap.add_argument("--grobid-url", default=None, metavar="URL",
                    help="GROBID endpoint base URL (implies "
                    "--grobid)")
    args = ap.parse_args(argv)
    if args.engines:
        engines = _load_engines()
        print(json.dumps(engines.probe_all(), indent=2,
                         sort_keys=True))
        return 0
    if not args.file:
        ap.error("a file to convert is required (or use "
                 "--engines to list the engine registry)")
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
        md, report = convert_with_report(
            args.file, args.sensitivity,
            quality_threshold=args.quality_threshold,
            engine=args.engine,
            grobid=(args.grobid_url if args.grobid_url
                    else (True if args.grobid else None)))
    except ParseQualityError as exc:
        qdir = Path(args.quarantine_dir)
        qdir.mkdir(parents=True, exist_ok=True)
        stem = Path(args.file).stem or "parse"
        qmd = qdir / (stem + ".quarantined.md")
        qjson = qdir / (stem + ".quarantined.ingest.json")
        qmd.write_text(exc.md, encoding="utf-8")
        qjson.write_text(json.dumps(exc.report, indent=2,
                                     sort_keys=True) + "\n",
                         encoding="utf-8")
        print(f"wiki_convert: {exc}", file=sys.stderr)
        print(f"wiki_convert: quarantined (NOT filed): {qmd} + "
              f"{qjson.name} — the report's parse_quality block "
              f"says why it scored low", file=sys.stderr)
        return 3
    except ConversionDoorError as exc:
        print(f"wiki_convert: {exc}", file=sys.stderr)
        if args.out:
            sidecar = Path(args.out).with_suffix(
                Path(args.out).suffix + ".ingest.json")
            sidecar.write_text(json.dumps(exc.report, indent=2,
                                          sort_keys=True) + "\n",
                               encoding="utf-8")
            print(f"wiki_convert: door recorded (NOT converted): "
                  f"{sidecar} — door {exc.door.get('name')!r}; "
                  f"no markdown was written", file=sys.stderr)
        return 4
    except (ConvertError, zipfile.BadZipFile, ET.ParseError,
            json.JSONDecodeError) as exc:
        print(f"wiki_convert: {exc}", file=sys.stderr)
        return 2
    scan = report["sanitiser"] or {}
    print(f"wiki_convert: trust-tier {report['trust_tier']}; sanitiser "
          f"verdict {scan.get('verdict')} "
          f"({len(scan.get('findings') or [])} finding(s)); "
          f"parse-quality {report['parse_quality']['score']} "
          f"({report['parse_quality']['verdict']})",
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
