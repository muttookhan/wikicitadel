#!/usr/bin/env python3
"""wiki_structured_ingest.py — Docling-pattern structured ingest.

Marathon Round 3, lane TB7, row 5. Pattern: Docling's structured
document model (Docling, MIT — re-implemented from the idea):
beside the flat markdown, a conversion also emits a TYPED BLOCK
STREAM — headings (with level), paragraphs, tables (headers +
rows), lists (ordered/unordered, with items), code blocks (with
language), blockquotes — as JSON, so structure a source carries
is not flattened away at ingest.

This is deliberately a NEW module that POST-PROCESSES the
converter's output rather than an edit to wiki_convert.py: any
source the existing converter turns into markdown (or a markdown
file directly) gains its block stream here, and the converter
itself is untouched.

    python3 scripts/wiki_structured_ingest.py FILE \\
        [-o OUT.md] [--blocks-out OUT.blocks.json]

Defaults: OUT.md beside the source as <stem>.md, blocks at
OUT.md + ".blocks.json" (i.e. <stem>.md.blocks.json). The blocks
JSON: {"kind": "structured-document", "source": ..., "blocks":
[...], "counts": {type: n}}. Exit 2 on a conversion failure.
Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|(\d+)[.)]\s+)(.*)$")
FENCE_RE = re.compile(r"^```\s*([A-Za-z0-9_-]*)\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _split_row(line):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [c.strip() for c in text.split("|")]


def parse_blocks(md):
    """Markdown -> the typed block stream (see module docstring).
    Deterministic, line-based, no guessing: a construct is typed
    only when its markdown shape is unambiguous."""
    lines = (md or "").splitlines()
    blocks = []
    para = []

    def flush_para():
        if para:
            text = " ".join(x.strip() for x in para).strip()
            if text:
                blocks.append({"type": "paragraph", "text": text})
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        fence = FENCE_RE.match(line.strip())
        if fence:
            flush_para()
            code = []
            i += 1
            while i < len(lines) and not FENCE_RE.match(lines[i].strip()):
                code.append(lines[i])
                i += 1
            i += 1  # closing fence (or EOF)
            blocks.append({"type": "code",
                           "language": fence.group(1) or None,
                           "text": "\n".join(code)})
            continue
        heading = HEADING_RE.match(line)
        if heading:
            flush_para()
            blocks.append({"type": "heading",
                           "level": len(heading.group(1)),
                           "text": heading.group(2).strip()})
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) \
                and TABLE_SEP_RE.match(lines[i + 1]) \
                and "-" in lines[i + 1]:
            flush_para()
            headers = _split_row(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append({"type": "table", "headers": headers,
                           "rows": rows})
            continue
        item = LIST_RE.match(line)
        if item:
            flush_para()
            ordered = item.group(1) is not None
            items = [item.group(2).strip()]
            i += 1
            while i < len(lines):
                nxt = LIST_RE.match(lines[i])
                if not nxt or (nxt.group(1) is not None) != ordered:
                    break
                items.append(nxt.group(2).strip())
                i += 1
            blocks.append({"type": "list", "ordered": ordered,
                           "items": items})
            continue
        if line.strip().startswith(">"):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append({"type": "blockquote",
                           "text": " ".join(quote).strip()})
            continue
        if not line.strip():
            flush_para()
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para()
    return blocks


def structured_document(source, md):
    blocks = parse_blocks(md)
    counts = {}
    for b in blocks:
        counts[b["type"]] = counts.get(b["type"], 0) + 1
    return {"kind": "structured-document", "source": str(source),
            "blocks": blocks, "counts": counts}


def _convert(path):
    """Markdown for a source: passthrough for .md/.txt, else the
    existing converter (loaded by path; its ingest sidecar rules
    are the converter's own, this tool writes no sidecar)."""
    p = Path(path)
    if p.suffix.lower() in (".md", ".txt", ".text"):
        return p.read_text(encoding="utf-8", errors="replace")
    conv_path = Path(__file__).with_name("wiki_convert.py")
    spec = importlib.util.spec_from_file_location("wiki_convert", conv_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.convert(str(p))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--blocks-out", default=None)
    args = ap.parse_args(argv)
    src = Path(args.file)
    if not src.is_file():
        print(f"wiki_structured_ingest: no such file: {src}",
              file=sys.stderr)
        return 2
    try:
        md = _convert(src)
    except Exception as exc:
        print(f"wiki_structured_ingest: conversion failed: {exc}",
              file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else src.with_suffix(".md")
    blocks_out = (Path(args.blocks_out) if args.blocks_out
                  else Path(str(out) + ".blocks.json"))
    out.write_text(md, encoding="utf-8")
    doc = structured_document(src, md)
    blocks_out.write_text(json.dumps(doc, indent=2, ensure_ascii=False)
                          + "\n", encoding="utf-8")
    print(f"structured ingest: {len(doc['blocks'])} blocks "
          f"{doc['counts']} -> {out} + {blocks_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
