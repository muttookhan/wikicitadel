#!/usr/bin/env python3
"""wiki_preocr.py — pre-ingest OCR wiring (Marathon R3, Tier B
bundle "Graph, portal and capture forms", row 7).

Pattern: OCRmyPDF's pre-ingest OCR step (MPL-2.0 — ideas only;
re-implemented seam, no code copied). The ingest path gains a
pre-OCR step seam: a binary/scanned source is routed through an OCR
stage BEFORE conversion, and the extraction confidence is recorded
to the OCR queue for the verification queue to pick up. A text-native
source passes straight through untouched.

Stage interface: a callable `stage(path) -> (text, confidence)`
returning the OCR'd text layer and a confidence in 0..1. The
default stage looks for a local `ocrmypdf` or `tesseract` binary;
when neither is present it raises OcrUnavailable, and the seam
reports a CLEAN REFUSAL (status "refused", with instructions) —
never a silent pass-through of an unreadable scan.

Classification: extensions .png/.jpg/.jpeg/.tif/.tiff are scanned
images; a .pdf is "scanned" when its extractable-text ratio is low
(no text-layer probe available in stdlib, so a PDF is routed to the
stage, which reports its own confidence; PDFs with a real text layer
come back at confidence 1.0 from a conforming stage). Text files
(.md/.txt/.html) are text-native.

The OCR queue is a JSONL file (default
`wiki/filings/ocr-queue.jsonl` under --root): one record per routed
source {source, status, confidence, queued_at}. Low confidence
(< --threshold, default 0.8) records status "needs-verification";
a refusal records "refused".

Exit 0 on a completed routing (refusal is a result), 2 on missing
input. Tests inject a fake stage — no real OCR binary is invoked.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
TEXT_EXTS = {".md", ".txt", ".html", ".htm", ".rst", ".csv", ".json"}
PDF_EXTS = {".pdf"}

REFUSAL = ("no local OCR engine found (looked for: ocrmypdf, "
           "tesseract). Install one locally, or configure a stage, "
           "then re-run; the source was NOT passed through silently.")


class OcrUnavailable(Exception):
    pass


def default_stage(path):
    """Stdlib-only default: presence check + honest refusal.

    A real deployment wires a conforming stage that shells to the
    local binary; the seam's contract is what is built and tested
    here, and absent a binary the correct behaviour is refusal.
    """
    if shutil.which("ocrmypdf") or shutil.which("tesseract"):
        raise OcrUnavailable(
            "an OCR binary is present but no stage is configured in "
            "this seam build; wire the stage callable to use it")
    raise OcrUnavailable(REFUSAL)


def classify(path):
    ext = Path(path).suffix.lower()
    if ext in TEXT_EXTS:
        return "text"
    if ext in IMAGE_EXTS:
        return "scanned"
    if ext in PDF_EXTS:
        return "scanned"
    return "binary"


def route(path, stage=None, threshold=0.8):
    """Route one source; returns the queue record dict."""
    kind = classify(path)
    rec = {"source": str(path), "kind": kind}
    if kind == "text":
        rec.update(status="text-native", confidence=1.0)
        return rec
    if kind == "binary":
        rec.update(status="unsupported", confidence=0.0,
                   note="unrecognised binary type; not routed to OCR")
        return rec
    stage = stage or default_stage
    try:
        _text, confidence = stage(Path(path))
    except OcrUnavailable as e:
        rec.update(status="refused", confidence=0.0, note=str(e))
        return rec
    rec.update(confidence=round(float(confidence), 3),
               status="ocr-done" if confidence >= threshold
               else "needs-verification")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--queue", default=None)
    ap.add_argument("--queued-at", default="")
    ns = ap.parse_args(argv)
    for f in ns.files:
        if not Path(f).exists():
            print(f"missing: {f}", file=sys.stderr)
            return 2
    records = []
    for f in ns.files:
        rec = route(f, threshold=ns.threshold)
        rec["queued_at"] = ns.queued_at
        records.append(rec)
    queue = Path(ns.queue) if ns.queue else \
        Path(ns.root) / "wiki" / "filings" / "ocr-queue.jsonl"
    queue.parent.mkdir(parents=True, exist_ok=True)
    with queue.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(json.dumps({"queue": str(queue), "records": records}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
