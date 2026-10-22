#!/usr/bin/env python3
"""wiki_convert_engines.py — optional heavyweight document engines
behind the wiki_convert.py seam (W4 document-engine trials).

The built-in converter (scripts/wiki_convert.py) is stdlib-only and
deliberately conservative: it preserves text and simple structure
and drops what it cannot represent. Heavyweight engines — Docling,
MarkItDown, Marker, Unstructured — promise more (layout analysis,
reading order, table structure, OCR), at the cost of large model
dependencies. This module is the seam they plug into:

  * a REGISTRY: each engine is a record (probe module names,
    adapter, formats, licence judged at source, route taken);
  * a PROBE: availability is established by import, never assumed
    — an engine that is not installed reports its blocker verbatim
    and selecting it is a named door in the ingest sidecar, never
    a silent fallback;
  * a SELECTION: explicit (--engine NAME) or complexity-scored
    auto-selection (--engine auto) that routes each document to
    the lightest adequate engine: a document-complexity score is
    computed from deterministic local signals, and the lightest
    AVAILABLE engine whose tier covers the score wins; when no
    heavy engine is available the route falls back to the built-in
    converter WITH the recommendation recorded — the fallback is
    visible in the sidecar, never silent;
  * a TRUST CHECK: every engine output carries an invented-content
    measurement (the Unstructured "tokens added" caution from the
    wave-4 survey, made mechanical): tokens in the output that no
    source-extraction token explains are counted and listed, so an
    engine that pads or hallucinates text is measured before it is
    trusted. The check runs on ANY engine's output, including the
    built-in converter's, whenever the caller supplies the source
    text to compare against.

Licence routes, judged at source 2026-10-22 (repo pages / LICENSE
files read directly):
  docling      MIT (docling-project/docling) — adapt-with-credit;
               the adapter here is our own code against its
               public API, no source carried.
  markitdown   MIT (microsoft/markitdown) — adapt-with-credit;
               adapter is our own code, no source carried. (The
               built-in converter's shape already follows
               MarkItDown's pattern, credited in wiki_convert.py.)
  unstructured Apache-2.0 (Unstructured-IO/unstructured) —
               adapt-with-credit; adapter is our own code.
  marker       INTERFACE ONLY. The codebase licence is in flux on
               the record: GPL-3.0 in the LICENSE file history,
               while the current README claims Apache-2.0 for the
               code with the model weights under a modified AI
               Pubs Open Rail-M licence (revenue-capped). Until
               the conflict settles, no Marker code is adapted and
               no weights are fetched; the adapter speaks to its
               public API only if the package is already present.

Local-only: no engine's paid/hosted API tier is ever called.
"""
import importlib
import re
import time
import zipfile
from pathlib import Path


# ------------------------------------------------------------------
# registry

class EngineUnavailable(Exception):
    """The selected engine cannot run in this environment. Carries
    the engine's probe record so the caller can door the request
    with the blocker named."""

    def __init__(self, engine):
        self.engine = engine
        super().__init__(
            f"engine {engine['name']!r} unavailable: "
            f"{engine['probe']['blocker']}")


def _probe(module_names, binary_note=None):
    """Try to import an engine's modules. Returns
    {"available", "version", "blocker"} — the blocker is the
    import error verbatim, never paraphrased into a guess."""
    last = None
    for name in module_names:
        try:
            mod = importlib.import_module(name)
            return {"available": True,
                    "version": getattr(mod, "__version__", None),
                    "blocker": None}
        except Exception as exc:  # ImportError and friends
            last = f"{type(exc).__name__}: {exc}"
    return {"available": False, "version": None,
            "blocker": last or "no importable module"}


# --- adapters: each returns markdown text only. They run ONLY when
# the probe passed. Written against the engines' public APIs.

def _adapt_docling(path):
    from docling.document_converter import DocumentConverter
    result = DocumentConverter().convert(str(path))
    return result.document.export_to_markdown()


def _adapt_markitdown(path):
    from markitdown import MarkItDown
    result = MarkItDown().convert(str(path))
    return getattr(result, "markdown", None) \
        or getattr(result, "text_content")


def _adapt_marker(path):
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = converter(str(path))
    return rendered.markdown


def _adapt_unstructured(path):
    from unstructured.partition.auto import partition
    elements = partition(filename=str(path))
    lines = []
    for el in elements:
        category = getattr(el, "category", "")
        text = str(el).strip()
        if not text:
            continue
        if category == "Title":
            lines.append("## " + text)
        elif category == "ListItem":
            lines.append("- " + text)
        else:
            lines.append(text)
    return "\n\n".join(lines) + "\n"


ENGINES = {
    "docling": {
        "name": "docling",
        "label": "Docling (docling-project/docling)",
        "modules": ["docling"],
        "formats": {".pdf", ".docx", ".pptx", ".xlsx", ".html",
                    ".htm", ".epub", ".md", ".txt"},
        "tier": 2,
        "licence": "MIT",
        "licence_route": "adapt-with-credit",
        "deterministic": "unmeasured",
        "adapter": _adapt_docling,
        "notes": "layout / reading-order / table-structure "
                 "understanding to a unified document model; "
                 "pulls torch + model weights (hundreds of MB); "
                 "local execution incl. air-gapped use",
    },
    "markitdown": {
        "name": "markitdown",
        "label": "MarkItDown (microsoft/markitdown)",
        "modules": ["markitdown"],
        "formats": {".pdf", ".docx", ".pptx", ".xlsx", ".html",
                    ".htm", ".epub", ".msg", ".json", ".zip"},
        "tier": 1,
        "licence": "MIT",
        "licence_route": "adapt-with-credit",
        "deterministic": "unmeasured",
        "adapter": _adapt_markitdown,
        "notes": "light converter in the same shape as the "
                 "built-in one; its PDF route is basic text "
                 "extraction without layout analysis; optional "
                 "plugins (OCR via an LLM client, Azure Document "
                 "Intelligence) are out of scope — local-only",
    },
    "unstructured": {
        "name": "unstructured",
        "label": "Unstructured (Unstructured-IO/unstructured)",
        "modules": ["unstructured"],
        "formats": {".pdf", ".docx", ".pptx", ".xlsx", ".html",
                    ".htm", ".epub", ".msg", ".md", ".txt"},
        "tier": 2,
        "licence": "Apache-2.0",
        "licence_route": "adapt-with-credit",
        "deterministic": "unmeasured",
        "adapter": _adapt_unstructured,
        "notes": "element partitioner (Title / NarrativeText / "
                 "Table / ...); the survey recorded a 'tokens "
                 "added' invented-content caution — the seam's "
                 "invented-content check exists to measure exactly "
                 "that before any trust; hi-res strategies pull "
                 "layout models + poppler/tesseract system deps",
    },
    "marker": {
        "name": "marker",
        "label": "Marker (datalab-to/marker)",
        "modules": ["marker"],
        "formats": {".pdf"},
        "tier": 3,
        "licence": "code licence in flux on the record: GPL-3.0 "
                   "(LICENSE history) vs Apache-2.0 (current "
                   "README); model weights under a modified AI "
                   "Pubs Open Rail-M licence",
        "licence_route": "interface-only",
        "deterministic": "unmeasured",
        "adapter": _adapt_marker,
        "notes": "PDF-only; neural layout + OCR pipeline (Surya); "
                 "some bundled models carry CC BY-NC terms; "
                 "interface only until the licence conflict "
                 "settles — no code adapted, no weights fetched",
    },
}

# tier 0 is the built-in converter itself.
BUILTIN = {
    "name": "builtin",
    "label": "built-in converter (wiki_convert.py, stdlib)",
    "formats": {".md", ".txt", ".text", ".html", ".htm", ".docx",
                ".pptx", ".xlsx", ".pdf", ".json", ".epub",
                ".zip", ".msg", ".url"},
    "tier": 0,
    "licence": "this project's own code",
    "licence_route": "native",
    "deterministic": "yes — same input, same bytes (measured in "
                     "the W4 trial record)",
}


def probe_engine(name):
    """The registry record for NAME with a live probe attached."""
    spec = ENGINES[name]
    record = {k: v for k, v in spec.items() if k != "adapter"}
    record["formats"] = sorted(spec["formats"])
    record["probe"] = _probe(spec["modules"])
    return record


def probe_all():
    return {name: probe_engine(name) for name in ENGINES}


# ------------------------------------------------------- complexity
# Complexity-scored routing (idea: BukeLy/rag-api's parser
# auto-selection — re-implemented from the idea): score the
# DOCUMENT from deterministic local signals, then route to the
# lightest engine whose tier covers the score. Signals are all
# readable without any engine: size, format family, and — for
# OOXML — the package's own table/image counts; for PDF — page
# count and whether an embedded text layer exists at all (via
# pypdf when importable; otherwise the score says the signal is
# unknown rather than guessing).

def document_complexity(path):
    """Returns {"score" (0.0-1.0), "band", "signals"} — every
    signal named with the value observed, unknowns stated."""
    p = Path(path)
    suffix = p.suffix.lower()
    size = p.stat().st_size if p.is_file() else 0
    signals = {"suffix": suffix, "bytes": size}
    score = 0.0
    if size > 1_000_000:
        score += 0.15
        signals["size"] = "large (>1MB)"
    elif size > 100_000:
        score += 0.05
        signals["size"] = "medium (>100KB)"
    else:
        signals["size"] = "small"
    if suffix in (".md", ".txt", ".text", ".json"):
        signals["family"] = "native text"
        return {"score": round(score, 3), "band": "simple",
                "signals": signals}
    if suffix in (".docx", ".pptx", ".xlsx"):
        signals["family"] = "OOXML package"
        try:
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                signals["members"] = len(names)
                images = sum(1 for n in names
                             if "/media/" in n or n.endswith(
                                 (".png", ".jpg", ".jpeg", ".emf",
                                  ".wmf")))
                signals["images"] = images
                score += min(0.2, 0.05 * images)
                main = [n for n in names if n.endswith(
                    ("document.xml", "sheet1.xml")) or "/slides/"
                    in n]
                tables = 0
                for n in main[:8]:
                    try:
                        tables += zf.read(n).count(b"<w:tbl>") \
                            + zf.read(n).count(b"<a:tbl>")
                    except KeyError:
                        pass
                signals["tables"] = tables
                score += min(0.3, 0.1 * tables)
        except zipfile.BadZipFile:
            signals["package"] = "unreadable as zip"
            score += 0.2
    elif suffix == ".pdf":
        signals["family"] = "PDF"
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            signals["pages"] = len(reader.pages)
            score += min(0.2, 0.02 * len(reader.pages))
            text_chars = sum(len(pg.extract_text() or "")
                             for pg in reader.pages[:5])
            signals["text_layer_chars_first5"] = text_chars
            if text_chars == 0:
                signals["text_layer"] = ("absent (scanned or "
                                         "image-only)")
                score += 0.5
            elif text_chars < 200:
                signals["text_layer"] = "sparse"
                score += 0.25
            else:
                signals["text_layer"] = "present"
            raw = p.read_bytes()
            signals["images"] = raw.count(b"/Subtype /Image")
            score += min(0.15, 0.05 * signals["images"])
            # aligned text runs that look like table rows
            rows = len(re.findall(rb"\S+\s{3,}\S+\s{3,}\S+", raw))
            signals["table_like_runs"] = rows
            score += min(0.2, 0.02 * rows)
        except Exception as exc:
            # pypdf missing, or the file unreadable as a PDF: the
            # signals are unknown — recorded verbatim, not guessed.
            signals["pdf_probe"] = (f"{type(exc).__name__}: {exc} "
                                     "— page/text-layer signals "
                                     "unknown, not guessed")
            score += 0.2
    elif suffix in (".html", ".htm"):
        signals["family"] = "HTML"
        text = p.read_text(encoding="utf-8", errors="replace")
        signals["tables"] = text.lower().count("<table")
        signals["images"] = text.lower().count("<img")
        score += min(0.3, 0.1 * signals["tables"])
    elif suffix in (".epub", ".zip", ".msg", ".url"):
        signals["family"] = "container/capture"
        score += 0.1
    score = max(0.0, min(1.0, score))
    band = ("simple" if score < 0.25 else
            "moderate" if score < 0.55 else "complex")
    return {"score": round(score, 3), "band": band,
            "signals": signals}


# tier needed to cover a complexity band
_BAND_TIER = {"simple": 0, "moderate": 1, "complex": 2}


def select_engine(path, requested="auto"):
    """Resolve a route for PATH. Returns
    {"engine", "mode", "complexity", "recommendation"} where
    engine is the registry name that will actually run ("builtin"
    when nothing heavier is available or needed) and
    recommendation names the lightest engine that WOULD cover
    the document — the gap between the two is the record, so a
    fallback is never silent."""
    complexity = document_complexity(path)
    needed = _BAND_TIER[complexity["band"]]
    suffix = Path(path).suffix.lower()
    if requested != "auto":
        return {"engine": requested, "mode": "explicit",
                "complexity": complexity,
                "recommendation": requested}
    if needed == 0:
        # the built-in converter covers a simple document; the
        # honest recommendation is the built-in itself
        return {"engine": "builtin", "mode": "auto",
                "complexity": complexity,
                "recommendation": "builtin"}
    candidates = []
    for name, spec in ENGINES.items():
        if suffix not in spec["formats"]:
            continue
        if spec["tier"] < needed:
            continue
        candidates.append((spec["tier"], name))
    candidates.sort()
    recommendation = candidates[0][1] if candidates else "builtin"
    chosen = "builtin"
    for _tier, name in candidates:
        if _probe(ENGINES[name]["modules"])["available"]:
            chosen = name
            break
    return {"engine": chosen, "mode": "auto",
            "complexity": complexity,
            "recommendation": recommendation}


# ------------------------------------------------- trust measurement

_TOKEN = re.compile(r"[a-z0-9]+(?:[.'/-][a-z0-9]+)*")


def _tokens(text):
    return _TOKEN.findall((text or "").lower())


def invented_content_check(source_text, md):
    """The 'tokens added' caution, measured: word tokens in the
    converted output that appear nowhere in the source text.
    Markdown furniture (heading marks, table pipes, link targets)
    is stripped before counting; numbers and words the source
    itself carries can never count as invented. Returns
    {"output_tokens", "invented_tokens", "invented_ratio",
    "invented_sample"} — a measurement, not a verdict: formatting
    words an extractor legitimately adds (e.g. 'Page 1' furniture)
    show up here and are read as such."""
    source_vocab = set(_tokens(source_text))
    body = re.sub(r"\[[^\]]*\]\([^)]*\)", "", md or "")  # link urls
    body = re.sub(r"[#>|*_`]", " ", body)
    out = _tokens(body)
    invented = [t for t in out if t not in source_vocab]
    return {"output_tokens": len(out),
            "invented_tokens": len(invented),
            "invented_ratio": round(len(invented) / len(out), 4)
            if out else 0.0,
            "invented_sample": sorted(set(invented))[:20]}


# ---------------------------------------------------------------- run

def run_engine(name, path):
    """Convert PATH with engine NAME. Returns (markdown, meta)
    where meta records the engine identity and wall time. Raises
    EngineUnavailable with the probe record when the engine
    cannot run here — the caller doors it, never falls back in
    silence."""
    spec = ENGINES[name]
    record = probe_engine(name)
    if not record["probe"]["available"]:
        raise EngineUnavailable(record)
    started = time.monotonic()
    md = spec["adapter"](Path(path))
    meta = {"engine": name, "label": spec["label"],
            "version": record["probe"]["version"],
            "licence": spec["licence"],
            "licence_route": spec["licence_route"],
            "wall_seconds": round(time.monotonic() - started, 3)}
    return md, meta


# ------------------------------------------------- sidecar services
# Services that are NOT markdown converters and therefore do
# NOT belong in ENGINES: they run BESIDE a conversion and add
# a block to the ingest sidecar. Registered here so the
# converter's registry names every external tool an ingest
# can engage, each with its licence judged at source and its
# configuration route. The probe for a service is
# endpoint-based (a service has no importable module): no
# endpoint configured is itself the honest probe result.

SIDECAR_SERVICES = {
    "grobid": {
        "name": "grobid",
        "label": "GROBID (grobidOrg/grobid)",
        "kind": "bibliographic-extraction sidecar (HTTP "
                "service; not a document converter)",
        "formats": {".pdf"},
        "licence": "Apache-2.0",
        "licence_route": "adapt-with-credit",
        "config": "endpoint from the GROBID_URL environment "
                  "variable or an explicit --grobid-url on "
                  "the converter; never hardcoded; the "
                  "service's default port is 8070",
        "client": "scripts/wiki_grobid.py (stdlib client + "
                  "TEI parser; the service is never vendored)",
        "notes": "header metadata + parsed references + "
                 "citation contexts for scholarly PDFs, "
                 "recorded in the ingest sidecar as "
                 "machine-unverified engine output feeding "
                 "the staged verification in "
                 "wiki_scholar_check.py — never as verified "
                 "fact. GROBID is a Java service; the Round "
                 "10 trial door-failed on this VM (no Java "
                 "runtime), recorded in "
                 "evaluation/grobid-trial-evidence.json",
    },
}


def probe_sidecar_service(name, endpoint=None):
    """The registry record for a sidecar service with a live
    probe attached. With no endpoint, the probe states the
    configuration door; with one, the service's own client
    (loaded lazily from this directory) probes it."""
    spec = SIDECAR_SERVICES[name]
    record = {k: v for k, v in spec.items()}
    record["formats"] = sorted(spec["formats"])
    if not endpoint:
        record["probe"] = {
            "available": False, "version": None,
            "blocker": "no endpoint configured (GROBID_URL "
                       "unset and no endpoint passed)"}
        return record
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location(
        "wiki_grobid",
        Path(__file__).with_name("wiki_grobid.py"))
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)
    record["probe"] = mod.probe(endpoint)
    return record
