#!/usr/bin/env python3
"""SHA-256 provenance manifest for ALL of raw/ (WikiCitadel v1).

A mirror sub-manifest (for example
raw/sources/mirror-a-manifest.json) proves the
pattern for one subtree: every mirrored file recorded with bytes +
sha256, so any later drift is detectable. This tool generalises it
to the whole raw layer — the wiki's source of truth — and is the
mechanical half of the rule "a manifest mismatch is an integrity
event, never an automatic raw rewrite" (merged design §3.1).

Usage:
  python3 scripts/wiki_provenance.py            # generate / refresh
  python3 scripts/wiki_provenance.py --verify   # re-hash & compare
  python3 scripts/wiki_provenance.py --merkle-generate
  python3 scripts/wiki_provenance.py --merkle   # verify Merkle roots

Generate writes raw/sources/provenance-manifest.json (a NEW raw
file; nothing else in raw/ is touched). The manifest excludes
itself. --verify exits 1 when any file was added, changed, or went
missing since the manifest was generated; it writes nothing.

Merkle layer (WikiCitadel v1, provenance hardening; pattern: the
SHA-256 Merkle tree per ingested source of CiteIndex, MIT —
re-implemented): every file under raw/sources/ is additionally
hashed in fixed-size chunks and reduced to a Merkle root,
recorded per source in evaluation/merkle-manifest.jsonl (one
JSON record per file: whole-file sha256, chunk size, the chunk
leaf hashes, and the root). --merkle-generate (re)builds that
manifest; --merkle verifies it: a file whose root changed is
re-walked chunk by chunk so the report names exactly which
chunk(s) — and which byte range — diverge. The whole-file
manifest above says *that* a source changed; the Merkle layer
says *where*. The provenance manifest itself (a generated
artefact living inside raw/sources/) is excluded, exactly as
it excludes itself from its own listing.

Deliberately NOT built here: WARC archiving of web ingests and
Ed25519 signing of ingest records (the Gnosis pattern, MIT).
Python's stdlib has no Ed25519 and no WARC writer, and a
signature that cannot be verified with the tools on hand would
be theatre. Both are the documented next step once a vetted
dependency is admitted; the hash chains built today are the
substrate they would sign.

Overlap handling: two older sub-manifests already cover raw
subtrees — one mirror manifest in dict shape and another in
list shape. Files they cover get an
"also_in" marker naming the sub-manifest, and if a sub-manifest's
recorded hash disagrees with the bytes on disk that drift is
reported (disk is truth; the sub-manifest is a record about it).
The remaining *-manifest.json files in raw/sources describe
external GitHub trees, not raw/ subtrees, so they are listed as
descriptive manifests with no per-file overlap.

Stdlib only.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
MANIFEST_PATH = RAW / "sources" / "provenance-manifest.json"
SELF_REL = MANIFEST_PATH.relative_to(ROOT).as_posix()

# Mirror sub-manifests: (covered subtree, manifest file, shape).
# "dict"  -> {"files": {subtree-relative path: {"sha256": ...}}}
# "list"  -> [{"path": subtree-relative path, "sha256": ...}, ...]
MIRRORS = [
    ("raw/sources/mirror-a",
     "raw/sources/mirror-a-manifest.json", "dict"),
    ("raw/sources/mirror-b",
     "raw/sources/mirror-b-manifest.json", "list"),
]


def hash_file(path: Path):
    """Return (bytes, sha256) reading in chunks."""
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def iter_raw_files():
    """Every file under raw/, repo-relative posix paths, sorted."""
    out = []
    for p in sorted(RAW.rglob("*")):
        if p.is_file():
            rel = p.relative_to(ROOT).as_posix()
            if rel != SELF_REL:
                out.append((rel, p))
    return out


def load_mirror_maps():
    """Return (maps, meta): maps[subtree] = {subtree-rel path: sha256}.

    meta is the manifest-file metadata for the output manifest:
    which sub-manifests exist, what they cover, how many entries.
    Missing/unparseable sub-manifests are noted, never fatal.
    """
    maps = {}
    meta = []
    for subtree, mrel, shape in MIRRORS:
        mpath = ROOT / mrel
        entry = {"path": mrel, "kind": "mirror sub-manifest",
                 "covers": subtree, "entries": 0}
        if not mpath.exists():
            entry["note"] = "not present on disk"
            meta.append(entry)
            continue
        try:
            data = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception as exc:  # malformed JSON: record, don't die
            entry["note"] = f"unparseable: {exc}"
            meta.append(entry)
            continue
        m = {}
        if shape == "dict":
            for rel, rec in (data.get("files") or {}).items():
                if isinstance(rec, dict) and rec.get("sha256"):
                    m[Path(rel).as_posix()] = rec["sha256"]
        else:  # list
            for rec in data if isinstance(data, list) else []:
                if isinstance(rec, dict) and rec.get("path") and rec.get("sha256"):
                    m[Path(rec["path"]).as_posix()] = rec["sha256"]
        maps[subtree] = m
        entry["entries"] = len(m)
        meta.append(entry)
    # Descriptive manifests: any other *-manifest.json in raw/sources.
    covered = {m for _s, m, _sh in MIRRORS}
    for p in sorted((RAW / "sources").glob("*manifest*.json")):
        rel = p.relative_to(ROOT).as_posix()
        if rel != SELF_REL and rel not in covered:
            meta.append({"path": rel, "kind": "descriptive manifest",
                         "covers": None,
                         "note": "describes an external tree, not a raw/ subtree"})
    return maps, meta


def scan(maps):
    """Hash all of raw/. Return (files dict, drift list, total bytes).

    drift entries: (repo-rel path, sub-manifest path) where the
    sub-manifest's recorded hash disagrees with the bytes on disk.
    """
    files = {}
    drift = []
    total = 0
    for rel, p in iter_raw_files():
        n, digest = hash_file(p)
        total += n
        rec = {"bytes": n, "sha256": digest}
        for subtree, mmap in maps.items():
            if rel.startswith(subtree + "/"):
                sub_rel = rel[len(subtree) + 1:]
                if sub_rel in mmap:
                    rec["also_in"] = [m for s, m, _ in MIRRORS if s == subtree]
                    if mmap[sub_rel] != digest:
                        drift.append((rel, rec["also_in"][0]))
        files[rel] = rec
    return files, drift, total


def cmd_generate():
    maps, meta = load_mirror_maps()
    files, drift, total = scan(maps)
    drift_by_manifest = {}
    for rel, mrel in drift:
        drift_by_manifest.setdefault(mrel, []).append(rel)
    for entry in meta:
        if entry["path"] in drift_by_manifest:
            entry["drift"] = len(drift_by_manifest[entry["path"]])
    manifest = {
        "manifest": "WikiCitadel raw/ provenance manifest (all of raw/)",
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": "raw",
        "excludes": [SELF_REL + " (the manifest never lists itself)"],
        "file_count": len(files),
        "total_bytes": total,
        "sub_manifests": meta,
        "sub_manifest_drift": [
            {"path": rel, "sub_manifest": mrel} for rel, mrel in drift],
        "files": files,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"Wrote {SELF_REL}")
    print(f"  files hashed : {len(files)}")
    print(f"  total bytes  : {total}")
    overlaps = sum(1 for r in files.values() if "also_in" in r)
    print(f"  also_in a mirror sub-manifest: {overlaps}")
    if drift:
        print(f"  SUB-MANIFEST DRIFT: {len(drift)} file(s) whose recorded"
              " sub-manifest hash disagrees with disk:")
        for rel, mrel in drift:
            print(f"    - {rel}  (per {mrel})")
    else:
        print("  sub-manifest drift: none")
    return 0


def cmd_verify():
    if not MANIFEST_PATH.exists():
        print(f"No manifest at {SELF_REL} — run without --verify first.")
        return 2
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Manifest is unparseable: {exc}")
        return 2
    recorded = manifest.get("files") or {}
    maps, _meta = load_mirror_maps()
    current, drift, _total = scan(maps)

    added = sorted(set(current) - set(recorded))
    missing = sorted(set(recorded) - set(current))
    changed = sorted(
        rel for rel in set(current) & set(recorded)
        if current[rel]["sha256"] != recorded[rel].get("sha256")
        or current[rel]["bytes"] != recorded[rel].get("bytes"))

    print(f"== Provenance verify ==  manifest generated_at:"
          f" {manifest.get('generated_at')}")
    print(f"  recorded files: {len(recorded)}   on disk now: {len(current)}")
    print(f"  added: {len(added)}   changed: {len(changed)}"
          f"   missing: {len(missing)}")
    for rel in added:
        print(f"    ADDED    {rel}")
    for rel in changed:
        print(f"    CHANGED  {rel}  (manifest {recorded[rel].get('bytes')} B"
              f" -> disk {current[rel]['bytes']} B)")
    for rel in missing:
        print(f"    MISSING  {rel}")
    if drift:
        print(f"  sub-manifest drift (recorded mirror hash != disk): {len(drift)}")
        for rel, mrel in drift:
            print(f"    DRIFT    {rel}  (per {mrel})")
    bad = bool(added or changed or missing)
    print("Result:", "MISMATCH" if bad else "CLEAN — raw/ matches the manifest")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# Merkle layer (WikiCitadel v1): per-source chunk trees over raw/sources/.
# ---------------------------------------------------------------------------

MERKLE_MANIFEST_PATH = ROOT / "evaluation" / "merkle-manifest.jsonl"
MERKLE_REL = MERKLE_MANIFEST_PATH.relative_to(ROOT).as_posix()
CHUNK_SIZE = 65536  # 64 KiB leaves; one config point for the tree shape


def chunk_hashes(path: Path):
    """Return (total_bytes, [sha256 hex per CHUNK_SIZE chunk]).

    An empty file has zero leaves; its whole-file sha256 (of the
    empty byte string) still anchors it in the manifest record.
    """
    leaves = []
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            leaves.append(hashlib.sha256(chunk).hexdigest())
            n += len(chunk)
    return n, leaves


def merkle_root(leaves):
    """Reduce leaf hashes to one root.

    Pairwise SHA-256 over the raw hash bytes; an odd trailing
    node is duplicated (the Bitcoin convention), so the tree
    shape depends only on the leaf list. Zero leaves -> the
    SHA-256 of the empty string; one leaf -> the leaf itself.
    """
    if not leaves:
        return hashlib.sha256(b"").hexdigest()
    level = list(leaves)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(hashlib.sha256(
                bytes.fromhex(left) + bytes.fromhex(right)).hexdigest())
        level = nxt
    return level[0]


def iter_source_files():
    """Every file under raw/sources/, repo-relative, sorted.

    Excludes the provenance manifest itself: it is a generated
    artefact whose own tool already excludes it, and hashing a
    file whose content changes on every provenance refresh
    would make every Merkle verify fail by construction.
    """
    out = []
    src = RAW / "sources"
    if not src.exists():
        return out
    for p in sorted(src.rglob("*")):
        if p.is_file():
            rel = p.relative_to(ROOT).as_posix()
            if rel != SELF_REL:
                out.append((rel, p))
    return out


def scan_merkle():
    """Build the current record set for raw/sources/."""
    records = {}
    for rel, p in iter_source_files():
        n, leaves = chunk_hashes(p)
        # Whole-file hash computed streaming, not by re-reading:
        # chunk hashes cannot be combined into a whole-file hash,
        # so hash the file a second time via hash_file().
        _n2, whole = hash_file(p)
        records[rel] = {
            "path": rel,
            "bytes": n,
            "sha256": whole,
            "chunk_size": CHUNK_SIZE,
            "chunks": len(leaves),
            "leaves": leaves,
            "merkle_root": merkle_root(leaves),
        }
    return records


def load_merkle_manifest():
    """Return {path: record} from the Merkle manifest, or None."""
    if not MERKLE_MANIFEST_PATH.exists():
        return None
    records = {}
    with MERKLE_MANIFEST_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                records[rec["path"]] = rec
    return records


def cmd_merkle_generate():
    records = scan_merkle()
    MERKLE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MERKLE_MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        for rel in sorted(records):
            fh.write(json.dumps(records[rel], ensure_ascii=False) + "\n")
    total = sum(r["bytes"] for r in records.values())
    chunks = sum(r["chunks"] for r in records.values())
    print(f"Wrote {MERKLE_REL}")
    print(f"  sources hashed : {len(records)}")
    print(f"  total bytes    : {total}")
    print(f"  chunk leaves   : {chunks} (chunk size {CHUNK_SIZE})")
    return 0


def cmd_merkle_verify():
    try:
        recorded = load_merkle_manifest()
    except Exception as exc:
        print(f"Merkle manifest is unparseable: {exc}")
        return 2
    if recorded is None:
        print(f"No Merkle manifest at {MERKLE_REL} — "
              "run with --merkle-generate first.")
        return 2
    current = scan_merkle()
    added = sorted(set(current) - set(recorded))
    missing = sorted(set(recorded) - set(current))
    changed = []
    for rel in sorted(set(current) & set(recorded)):
        if current[rel]["merkle_root"] != recorded[rel].get("merkle_root"):
            changed.append(rel)

    print(f"== Merkle verify ==  manifest: {MERKLE_REL}")
    print(f"  recorded sources: {len(recorded)}   on disk now: {len(current)}")
    print(f"  added: {len(added)}   changed: {len(changed)}"
          f"   missing: {len(missing)}")
    for rel in added:
        print(f"    ADDED    {rel}")
    for rel in missing:
        print(f"    MISSING  {rel}")
    for rel in changed:
        old, new = recorded[rel], current[rel]
        print(f"    CHANGED  {rel}  (manifest {old.get('bytes')} B"
              f" -> disk {new['bytes']} B)")
        old_leaves = old.get("leaves") or []
        new_leaves = new["leaves"]
        diff = [i for i in range(max(len(old_leaves), len(new_leaves)))
                if (old_leaves[i] if i < len(old_leaves) else None)
                != (new_leaves[i] if i < len(new_leaves) else None)]
        cs = new["chunk_size"]
        for i in diff:
            print(f"      chunk {i} differs"
                  f" (bytes {i * cs}..{min((i + 1) * cs, new['bytes']) - 1})")
        print(f"      {len(diff)} of {max(len(old_leaves), len(new_leaves))}"
              " chunks diverge")
    bad = bool(added or changed or missing)
    print("Result:", "MISMATCH" if bad else
          "CLEAN — every raw/sources Merkle root matches")
    return 1 if bad else 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Generate or verify the all-of-raw/ provenance manifest.")
    ap.add_argument("--verify", action="store_true",
                    help="re-hash raw/ and compare against the manifest "
                         "(writes nothing; exit 1 on any mismatch)")
    ap.add_argument("--merkle-generate", action="store_true",
                    help="(re)build evaluation/merkle-manifest.jsonl: "
                         "per-source chunk hashes + Merkle roots over "
                         "raw/sources/")
    ap.add_argument("--merkle", action="store_true",
                    help="verify raw/sources/ against the Merkle "
                         "manifest, localising any change to its chunk "
                         "(writes nothing; exit 1 on mismatch, 2 when "
                         "the manifest is missing/unparseable)")
    args = ap.parse_args(argv[1:])
    if args.merkle_generate:
        return cmd_merkle_generate()
    if args.merkle:
        return cmd_merkle_verify()
    return cmd_verify() if args.verify else cmd_generate()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
