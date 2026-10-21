#!/usr/bin/env python3
"""wiki_verify_write.py — post-write verbatim check for raw/.

Pattern: the cmds-llm-wiki PostToolUse hook, via the feature
survey — after a raw file is written (mirrored, captured, or
handed over), prove the bytes on disk are the bytes the
provenance record says they are. This tool is the check half
only: it reads, hashes, compares, and reports. It never
rewrites the file or the manifest — a mismatch is an integrity
event for a human to disposition, not a cue to repair silently.

Given a raw/ file path, the tool re-hashes the file (sha256)
and compares it against its entry in the provenance manifest:

  default manifest   raw/sources/provenance-manifest.json
                     (the shape scripts/wiki_provenance.py
                     writes: {"files": {<rel path>: {"sha256":
                     ..., "bytes": ...}}})
  --manifest PATH    another manifest: the same JSON shape, a
                     JSON list of {"path", "sha256"} records,
                     or a JSONL file of such records (the
                     evaluation/source-manifest.jsonl shape)

Exit codes (the audit speaks exit codes):
  0  the file's hash matches its manifest entry
  1  mismatch — the hash (or byte count, when the entry
     carries one) differs, or the file is missing entirely
  2  no entry — the manifest carries no record for this path
     (also usage errors: unreadable manifest, path outside
     raw/)

Output is one line naming the path and the verdict; both
hashes are printed on a mismatch (hashes are integrity data,
not content — the manifest itself publishes them).

Usage:
  python3 scripts/wiki_verify_write.py raw/sources/<file>
  python3 scripts/wiki_verify_write.py <path> --manifest M \
      [--root ROOT]

Stdlib only.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = "raw/sources/provenance-manifest.json"


def hash_file(path):
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def load_entries(manifest_path):
    """-> {rel path: {"sha256": str, "bytes": int|None}} from
    any of the supported manifest shapes (see docstring)."""
    text = Path(manifest_path).read_text(encoding="utf-8")
    entries = {}

    def add(rel, sha, size=None):
        if rel and sha:
            entries[rel.replace("\\", "/")] = \
                {"sha256": sha, "bytes": size}

    stripped = text.lstrip()
    data = None
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None  # multi-record JSONL: parsed below
    if isinstance(data, dict):
        if "path" in data and "sha256" in data:
            # A one-line JSONL manifest parses as a single
            # record — treat it as that record.
            add(data.get("path"), data.get("sha256"),
                data.get("bytes", data.get("size")))
            return entries
        files = data.get("files")
        if isinstance(files, dict):
            for rel, rec in files.items():
                if isinstance(rec, dict):
                    add(rel, rec.get("sha256"), rec.get("bytes"))
            return entries
        # A bare {path: sha256} mapping.
        for rel, rec in data.items():
            if isinstance(rec, str):
                add(rel, rec)
            elif isinstance(rec, dict):
                add(rel, rec.get("sha256"), rec.get("bytes"))
        return entries
    if isinstance(data, list):
        for rec in data:
            if isinstance(rec, dict):
                add(rec.get("path"), rec.get("sha256"),
                    rec.get("bytes", rec.get("size")))
        return entries
    # JSONL: one {"path", "sha256", ...} record per line.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if isinstance(rec, dict):
            add(rec.get("path"), rec.get("sha256"),
                rec.get("bytes", rec.get("size")))
    return entries


def verify(root, rel, manifest_path):
    """-> (exit_code, message)."""
    entries = load_entries(manifest_path)
    entry = entries.get(rel)
    if entry is None:
        return 2, f"NO-ENTRY {rel}: no provenance-manifest entry"
    path = root / rel
    if not path.is_file():
        return 1, f"MISMATCH {rel}: file missing on disk"
    size, digest = hash_file(path)
    if digest != entry["sha256"]:
        return 1, (f"MISMATCH {rel}: sha256 {digest} "
                   f"!= manifest {entry['sha256']}")
    if entry["bytes"] is not None and size != entry["bytes"]:
        return 1, (f"MISMATCH {rel}: {size} bytes "
                   f"!= manifest {entry['bytes']} bytes")
    return 0, f"OK {rel}: sha256 matches the provenance manifest"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Verify a raw/ file's bytes against its "
                    "provenance-manifest entry (post-write "
                    "verbatim check).")
    ap.add_argument("path",
                    help="repo-relative raw/ path (a path "
                         "relative to raw/ is also accepted)")
    ap.add_argument("--manifest", default=None,
                    help=f"manifest file (default: "
                         f"{DEFAULT_MANIFEST})")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="repo root (default: this tool's repo)")
    args = ap.parse_args(argv[1:])
    root = args.root
    rel = args.path.replace("\\", "/").lstrip("/")
    if not rel.startswith("raw/"):
        if (root / "raw" / rel).is_file():
            rel = "raw/" + rel
        else:
            print(f"error: '{args.path}' is not a raw/ path",
                  file=sys.stderr)
            return 2
    manifest_path = Path(args.manifest) if args.manifest \
        else root / DEFAULT_MANIFEST
    if not manifest_path.is_file():
        print(f"error: no manifest at {manifest_path}",
              file=sys.stderr)
        return 2
    try:
        code, message = verify(root, rel, manifest_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: manifest unreadable: {exc}",
              file=sys.stderr)
        return 2
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
