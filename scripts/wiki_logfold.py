#!/usr/bin/env python3
"""wiki_logfold.py — deterministic fold for wiki/log.md.

WikiCitadel v1 (pattern: zerg-su/llm-obsidian, MIT —
deterministic log fold). The log grows forever; a fold is the
principled compaction that never edits or deletes history:

  - every `## [...]` block in wiki/log.md has a deterministic ID:
    the SHA-256 of its canonical text;
  - a FOLD is a record declaring the entry IDs it covers — the
    union of all fold declarations IS the processed ledger (there
    is no mutable counter file to corrupt);
  - folds are taken in batches of exactly 2^k oldest unprocessed
    entries (default k=6 -> 64); partial batches are forbidden —
    if fewer remain, the fold waits;
  - a fold's own ID embeds its boundary entries (first + last
    covered ID), so re-running the fold is structurally
    idempotent: the same batch always produces the same fold;
  - deleting a fold record is the defined undo: its entries
    become eligible again. Folds are never children of folds.

Fold records live in evaluation/log-folds/ as Markdown — the
evaluation layer holds this wiki's other machine records, which
keeps the page layer (validator, Lens, benchmark corpus) free of
bookkeeping pages. The fold is ADDITIVE: log.md itself is never
rewritten by this tool.

    python3 scripts/wiki_logfold.py status
    python3 scripts/wiki_logfold.py fold            (dry-run)
    python3 scripts/wiki_logfold.py fold --write
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "wiki" / "log.md"
FOLD_DIR = ROOT / "evaluation" / "log-folds"
BLOCK_START = re.compile(r"^## \[", re.M)


def canonical(block: str) -> str:
    return block.replace("\r\n", "\n").rstrip() + "\n"


def entry_id(block: str) -> str:
    return hashlib.sha256(canonical(block).encode("utf-8")).hexdigest()


def parse_entries(log_text: str) -> list[dict]:
    starts = [m.start() for m in BLOCK_START.finditer(log_text)]
    entries = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(log_text)
        block = log_text[s:e]
        first = block.splitlines()[0] if block.splitlines() else ""
        entries.append({"id": entry_id(block), "heading": first,
                        "block": block})
    return entries


def load_fold_coverage(fold_dir: Path = FOLD_DIR) -> dict:
    """fold_id -> [covered entry ids], read from fold records."""
    coverage = {}
    if not fold_dir.exists():
        return coverage
    for p in sorted(fold_dir.glob("fold-*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^fold_id:\s*(\S+)", text, re.M)
        ids = re.findall(r"^-\s+([0-9a-f]{64})\s*$", text, re.M)
        if m:
            coverage[m.group(1)] = ids
    return coverage


def status(root_log: str, fold_dir: Path = FOLD_DIR) -> dict:
    entries = parse_entries(root_log)
    coverage = load_fold_coverage(fold_dir)
    covered = set()
    for ids in coverage.values():
        covered.update(ids)
    unprocessed = [e for e in entries if e["id"] not in covered]
    return {"total": len(entries), "folds": len(coverage),
            "covered": len(entries) - len(unprocessed),
            "unprocessed": unprocessed}


def next_batch(unprocessed: list[dict], k: int = 6) -> list[dict] | None:
    size = 2 ** k
    if len(unprocessed) < size:
        return None
    return unprocessed[:size]


def fold_id_for(batch: list[dict]) -> str:
    material = f"{batch[0]['id']}:{batch[-1]['id']}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def render_fold(batch: list[dict], fid: str) -> str:
    lines = [f"# Log fold {fid}",
             "",
             f"fold_id: {fid}",
             f"created: {date.today()}",
             f"covers_count: {len(batch)}",
             f"first_entry: {batch[0]['id']}",
             f"last_entry: {batch[-1]['id']}",
             "",
             "Entries covered by this fold (SHA-256 of canonical "
             "block text in wiki/log.md):",
             ""]
    lines += [f"- {e['id']}" for e in batch]
    lines += ["", "First and last headings:",
              f"- first: {batch[0]['heading']}",
              f"- last: {batch[-1]['heading']}",
              "",
              "This record is additive bookkeeping: wiki/log.md is "
              "unchanged. Deleting this file is the undo — its "
              "entries become eligible for a future fold again.",
              ""]
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    f = sub.add_parser("fold")
    f.add_argument("--k", type=int, default=6)
    f.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    log_text = LOG_PATH.read_text(encoding="utf-8")
    st = status(log_text)
    if args.cmd == "status":
        print(f"log entries: {st['total']}  folded: {st['covered']} "
              f"({st['folds']} fold(s))  unprocessed: "
              f"{len(st['unprocessed'])}")
        return 0
    batch = next_batch(st["unprocessed"], args.k)
    if batch is None:
        print(f"no fold: {len(st['unprocessed'])} unprocessed entries "
              f"< batch size {2 ** args.k} (partial batches are "
              "forbidden; the fold waits)")
        return 0
    fid = fold_id_for(batch)
    record = render_fold(batch, fid)
    if args.write:
        FOLD_DIR.mkdir(parents=True, exist_ok=True)
        target = FOLD_DIR / f"fold-{fid}.md"
        if target.exists():
            print(f"fold {fid} already exists (idempotent) — nothing done")
            return 0
        target.write_text(record, encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)} covering "
              f"{len(batch)} entries")
    else:
        print(record)
        print("# dry-run: nothing written (use --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
