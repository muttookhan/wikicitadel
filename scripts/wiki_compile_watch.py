#!/usr/bin/env python3
"""wiki_compile_watch.py — threshold-triggered compile PROPOSALS.

Marathon Round 3, Lane TA5 (Tier A). Pattern: KR-R1's
threshold-triggered knowledge compilation, re-implemented
from the idea (no code copied): a raw source that sits
UNCOMPILED past a stated threshold — old enough, or large
enough — should not wait for someone to notice it. When a
source crosses a threshold, this watch files a compile
PROPOSAL automatically. Filing a proposal is all it does:
compiling remains a directed, reviewed act.

Definitions (stated, deterministic):
  uncompiled  the source's repo-relative path appears in NO
              compiled page's frontmatter `sources:`;
  age         (now - file mtime) in whole days — `now` is
              injectable (--now) so runs are testable and
              reproducible;
  crossing    age_days >= --age-days OR bytes >= --size-bytes.
              Thresholds are configurable per run via flags,
              or via a JSON config file (--config) with keys
              age_days / size_bytes; flags override config.

Outputs, per run:
  * one proposal filing per crossing source under
    wiki/filings/: compile-<stem>-<date>.md / .json;
  * the REGISTER: wiki/filings/compile-proposals-register.jsonl
    gains one JSON line per NEW proposal, in this format:
      {"date": ..., "source": <raw rel path>,
       "age_days": N, "bytes": N, "reasons": [...],
       "proposal": <filing rel path>, "status": "proposed"}
    A source already on the register with status "proposed"
    is not re-filed (idempotent reruns); a register line
    whose status a reviewer has moved on is left alone.

Exit codes: 0 clean pass (crossings or none) · 2 usage error.

    python3 scripts/wiki_compile_watch.py [--root DIR]
        [--age-days N] [--size-bytes N] [--config FILE]
        [--now ISO] [--date YYYY-MM-DD] [--dry-run]

Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_AGE_DAYS = 14
DEFAULT_SIZE_BYTES = 20000
REGISTER_REL = "wiki/filings/compile-proposals-register.jsonl"

_spec = importlib.util.spec_from_file_location(
    "wiki_validate", Path(__file__).resolve().parent / "wiki_validate.py")
_wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wv)
parse_frontmatter, as_list = _wv.parse_frontmatter, _wv.as_list


def load_config(path: Path | None) -> dict:
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"config {path} is not a JSON object")
    return data


def resolve_thresholds(config: dict, age_days=None,
                       size_bytes=None) -> dict:
    """Flags override config override defaults."""
    return {
        "age_days": (age_days if age_days is not None
                     else config.get("age_days", DEFAULT_AGE_DAYS)),
        "size_bytes": (size_bytes if size_bytes is not None
                       else config.get("size_bytes",
                                       DEFAULT_SIZE_BYTES)),
    }


def compiled_sources(root: Path) -> set[str]:
    out = set()
    wiki = Path(root) / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            fields, _ = parse_frontmatter(
                p.read_text(encoding="utf-8", errors="ignore"))
            for s in as_list((fields or {}).get("sources")):
                out.add(str(s))
    return out


def scan_crossings(root: Path, thresholds: dict,
                   now: datetime) -> list[dict]:
    """Uncompiled raw sources crossing a threshold, sorted
    by path: [{source, age_days, bytes, reasons}]."""
    root = Path(root)
    compiled = compiled_sources(root)
    out = []
    raw = root / "raw"
    if not raw.is_dir():
        return out
    for p in sorted(raw.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if rel in compiled:
            continue
        st = p.stat()
        age_days = int((now.timestamp() - st.st_mtime) // 86400)
        reasons = []
        if age_days >= thresholds["age_days"]:
            reasons.append(f"age {age_days}d >= "
                           f"{thresholds['age_days']}d threshold")
        if st.st_size >= thresholds["size_bytes"]:
            reasons.append(f"size {st.st_size}B >= "
                           f"{thresholds['size_bytes']}B threshold")
        if reasons:
            out.append({"source": rel, "age_days": age_days,
                        "bytes": st.st_size, "reasons": reasons})
    return out


def load_register(root: Path) -> list[dict]:
    path = Path(root) / REGISTER_REL
    entries = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def analyse(root: Path, thresholds: dict, now: datetime,
            today: date | None = None) -> dict:
    """Crossings minus sources already holding an open
    ('proposed') register entry — the NEW proposals."""
    today = today or now.date()
    already = {e.get("source") for e in load_register(root)
               if e.get("status") == "proposed"}
    new = []
    for c in scan_crossings(root, thresholds, now):
        if c["source"] in already:
            continue
        stem = Path(c["source"]).stem
        entry = {
            "date": today.isoformat(),
            "source": c["source"],
            "age_days": c["age_days"],
            "bytes": c["bytes"],
            "reasons": c["reasons"],
            "proposal": f"wiki/filings/compile-{stem}-{today.isoformat()}.md",
            "status": "proposed",
        }
        new.append({"crossing": c, "register_entry": entry})
    return {
        "tool": "scripts/wiki_compile_watch.py",
        "kind": "compile-proposals",
        "pattern": "KR-R1 threshold-triggered compile "
                   "proposals — filing only; compiling is a "
                   "separate directed act",
        "generated_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "date": today.isoformat(),
        "thresholds": thresholds,
        "stats": {"new_proposals": len(new)},
        "proposals": new,
    }


def render_filing(manifest: dict, proposal: dict) -> str:
    d = manifest["date"]
    c = proposal["crossing"]
    th = manifest["thresholds"]
    return "\n".join([
        "---",
        f"title: Compile proposal — {c['source']}",
        "type: query",
        f"created: {d}",
        f"updated: {d}",
        "sources: []",
        "tags: [compile, proposal, filings]",
        "status: draft",
        "stage: seedling",
        f"planted: {d}",
        f"tended: {d}",
        "work_type: record",
        "---",
        "",
        f"# Compile proposal — `{c['source']}`",
        "",
        "> [!warning] PROPOSAL ONLY — nothing has been compiled",
        "> Filed automatically by the threshold watch "
        "(`scripts/wiki_compile_watch.py`, Marathon R3 TA5; "
        "KR-R1 pattern) because this raw source crossed a "
        "stated threshold while uncompiled. Compiling it is "
        "a separate, directed act.",
        "",
        f"Source: `{c['source']}` · age {c['age_days']} day(s) · "
        f"{c['bytes']} bytes",
        f"Thresholds this run: age >= {th['age_days']}d, "
        f"size >= {th['size_bytes']}B",
        "",
        "Crossing reasons:",
        "",
        *[f"- {r}" for r in c["reasons"]],
        "",
        "Register entry: `" + json.dumps(proposal["register_entry"],
                                         sort_keys=True) + "`",
        "",
    ])


def write_filings(root: Path, manifest: dict) -> list[Path]:
    root = Path(root)
    written = []
    for proposal in manifest["proposals"]:
        rel = proposal["register_entry"]["proposal"]
        md_path = root / rel
        json_path = md_path.with_suffix(".json")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_filing(manifest, proposal),
                           encoding="utf-8")
        json_path.write_text(json.dumps(
            {"tool": manifest["tool"], "kind": manifest["kind"],
             "date": manifest["date"],
             "register_entry": proposal["register_entry"],
             "crossing": proposal["crossing"]},
            indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written += [md_path, json_path]
    if manifest["proposals"]:
        reg = root / REGISTER_REL
        reg.parent.mkdir(parents=True, exist_ok=True)
        with reg.open("a", encoding="utf-8") as fh:
            for proposal in manifest["proposals"]:
                fh.write(json.dumps(proposal["register_entry"],
                                    sort_keys=True) + "\n")
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--age-days", type=int, default=None)
    ap.add_argument("--size-bytes", type=int, default=None)
    ap.add_argument("--config", default=None,
                    help="JSON config with age_days / size_bytes")
    ap.add_argument("--now", default=None,
                    help="ISO datetime treated as now (testing/"
                         "reproducibility); default: current UTC")
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the manifest JSON; write nothing")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        config = load_config(Path(args.config) if args.config else None)
        thresholds = resolve_thresholds(config, args.age_days,
                                        args.size_bytes)
    except (ValueError, OSError) as exc:
        print(f"compile watch: bad config: {exc}", file=sys.stderr)
        return 2
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = date.fromisoformat(args.date) if args.date else now.date()
    manifest = analyse(root, thresholds, now, today=today)
    if args.dry_run:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    write_filings(root, manifest)
    print(f"compile watch: thresholds age>={thresholds['age_days']}d "
          f"size>={thresholds['size_bytes']}B -> "
          f"{manifest['stats']['new_proposals']} new proposal(s)")
    for p in manifest["proposals"]:
        print(f"  {p['register_entry']['source']}: "
              f"{'; '.join(p['crossing']['reasons'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
