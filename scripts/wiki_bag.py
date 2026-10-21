#!/usr/bin/env python3
"""BagIt (RFC 8493) packaging for the wiki's preservation exports.

Pattern: RFC 8493, the BagIt File Packaging Format (IETF,
Informational, 2018) — re-implemented here from the spec, stdlib
only; no code copied. Survey record: find 6 of
docs/research-notes.md.

Why: the wiki's other integrity machinery proves things about
the REPO (the Merkle provenance proves the repo's own
history; the citation lockfile proves cited bytes). A bag proves
an EXPORT COPY in someone else's hands: anyone holding the bag
can prove it is complete and untampered with nothing but the
bag itself and a sha256 tool — no wiki scripts required. That
is the copy that leaves the building (the take-home export),
so it is the copy that must be self-verifying.

A bag is a directory:

    <bag>/
      bagit.txt             the declaration (version + encoding)
      bag-info.txt          metadata: source, date, Payload-Oxum
      manifest-sha256.txt   every payload file -> its sha256
      tagmanifest-sha256.txt  sha256 of the tag files themselves
      data/                 the payload, repo-relative paths kept

Snapshot sets (the payload is a NAMED set, so a bag always says
what it is a bag OF):

  compiled (default)  wiki/ + evaluation/ + AGENTS.md — the
      compiled layer, the registers, and the schema that makes
      them interpretable.
  full (--full)       raw/ as well — the whole corpus.

Bytecode caches (__pycache__/, *.pyc) are excluded from every
set: they are derived artefacts, and including them would make
bags differ between machines for no content reason. Nothing
else is excluded; ordering is deterministic everywhere (paths
sorted byte-wise), so two packs of the same tree differ only
in bag-info.txt's Bagging-Date.

`validate` performs the RFC's two checks — completeness (every
manifest entry present; no unmanifested payload file) and
fixity (every checksum verifies, payload and tag files alike) —
plus a cross-check of bag-info.txt's Payload-Oxum against the
manifest. It reports VALID, or INVALID with every reason named.

Pack-time secret-pattern scan (added 2026-10-21, Marathon
Round 3): `pack` first runs scripts/wiki_pack_scan.py over
the payload, reusing the leak lint's pattern classes. A hit
REFUSES the pack before anything is copied, unless the
caller passes --allow-pack-findings (pack proceeds, hits
reported as warnings, scan result in the stats). The scan
can be skipped only explicitly, with --no-pack-scan, and
the stats record that it was skipped.

Usage:
  python3 scripts/wiki_bag.py pack <dest-dir> [--full]
      Assemble a bag at <dest-dir> (must not exist, or be
      empty). The bag is an export artefact: keep it OUTSIDE
      the repo.
  python3 scripts/wiki_bag.py validate <bag-dir>
      Exit 0 = VALID, 1 = INVALID, 2 = usage error / not a bag.

Stdlib only.
"""
import argparse
import hashlib
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL_ID = "wiki_bag.py 1.0 (WikiCitadel)"
DEFAULT_SOURCE_ORG = "WikiCitadel"

SETS = {
    "compiled": ["wiki", "evaluation", "AGENTS.md"],
    "full": ["raw", "wiki", "evaluation", "AGENTS.md"],
}

TAG_FILES = ("bag-info.txt", "bagit.txt", "manifest-sha256.txt")


def _excluded(rel: Path) -> bool:
    return "__pycache__" in rel.parts or rel.suffix == ".pyc"


def collect_payload(root: Path, set_name: str):
    """[(repo-relative posix path, absolute path)] for a set,
    deterministically ordered."""
    out = []
    for entry in SETS[set_name]:
        base = root / entry
        if base.is_file():
            rel = Path(entry)
            if not _excluded(rel):
                out.append((rel.as_posix(), base))
        elif base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(root)
                    if not _excluded(rel):
                        out.append((rel.as_posix(), p))
    out.sort(key=lambda t: t[0])
    return out


def _sha256_file(path: Path):
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def _pack_scan(payload):
    """Run the pack-time secret-pattern scan (scripts/
    wiki_pack_scan.py, imported in-process) over a payload
    list of (rel, abspath) pairs."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "wiki_pack_scan",
        Path(__file__).resolve().parent / "wiki_pack_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scan_payload_files(payload)


def pack(root: Path, dest: Path, set_name: str,
         source_org: str = DEFAULT_SOURCE_ORG,
         bagging_date: str = None,
         scan: bool = True, allow_pack_findings: bool = False):
    """Assemble a bag. Returns a stats dict. Raises ValueError
    on a bad destination (exists and non-empty, or inside the
    payload it would copy), and — unless allow_pack_findings
    — when the pack-time secret-pattern scan finds a hit."""
    root = root.resolve()
    dest = dest.resolve() if dest.exists() else dest.absolute()
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"destination {dest} exists and is not empty")
    try:
        dest.relative_to(root)
        inside = dest != root
    except ValueError:
        inside = False
    if inside:
        raise ValueError("destination is inside the repository — "
                         "a bag is an export artefact and must live "
                         "outside the tree it copies")

    payload = collect_payload(root, set_name)
    pack_scan = None
    if scan:
        pack_scan = _pack_scan(payload)
        if pack_scan["findings"] and not allow_pack_findings:
            hits = "; ".join(
                f"{f['file']}: {f['pattern']} x{f['count']}"
                for f in pack_scan["findings"][:10])
            raise ValueError(
                "pack refused: the pack-time secret-pattern scan "
                f"found {pack_scan['findings_total']} hit(s) — "
                f"{hits}. Nothing was copied. Rule on the hits, "
                "or re-run with --allow-pack-findings to pack "
                "anyway (the hits are then reported as warnings).")
    data_dir = dest / "data"
    manifest_lines = []
    total_bytes = 0
    for rel, src in payload:
        target = data_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        n, digest = _sha256_file(target)
        total_bytes += n
        manifest_lines.append(f"{digest}  data/{rel}")

    (dest / "bagit.txt").write_text(
        "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n",
        encoding="utf-8")
    (dest / "manifest-sha256.txt").write_text(
        "\n".join(manifest_lines) + "\n", encoding="utf-8")
    info = [
        f"Source-Organization: {source_org}",
        f"Bagging-Date: {bagging_date or date.today().isoformat()}",
        f"Payload-Oxum: {total_bytes}.{len(payload)}",
        f"Bag-Software-Agent: {TOOL_ID}",
        f"External-Description: WikiCitadel preservation export,"
        f" snapshot set '{set_name}'"
        f" ({', '.join(SETS[set_name])})",
    ]
    (dest / "bag-info.txt").write_text(
        "\n".join(info) + "\n", encoding="utf-8")
    tag_lines = []
    for name in TAG_FILES:
        _n, digest = _sha256_file(dest / name)
        tag_lines.append(f"{digest}  {name}")
    (dest / "tagmanifest-sha256.txt").write_text(
        "\n".join(tag_lines) + "\n", encoding="utf-8")
    return {"set": set_name, "files": len(payload),
            "bytes": total_bytes, "dest": str(dest),
            "pack_scan": (pack_scan if pack_scan is not None
                          else {"verdict": "skipped",
                                "findings_total": None,
                                "findings": []})}


def _parse_manifest(path: Path):
    """{bag-relative path: sha256} from a manifest/tagmanifest."""
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            entries[parts[1].strip().lstrip("*")] = parts[0].lower()
    return entries


def _parse_bag_info(path: Path):
    info = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip().lower()] = v.strip()
    return info


def validate(bag: Path):
    """(valid, problems, stats). The RFC's completeness +
    fixity checks, plus the Payload-Oxum cross-check."""
    problems = []
    stats = {"payload_files": 0, "payload_bytes": 0}
    if not bag.is_dir():
        return False, [f"{bag} is not a directory"], stats
    decl = bag / "bagit.txt"
    if not decl.is_file():
        return False, ["bagit.txt missing — not a bag"], stats
    decl_text = decl.read_text(encoding="utf-8", errors="replace")
    version = None
    for line in decl_text.splitlines():
        if line.lower().startswith("bagit-version:"):
            version = line.split(":", 1)[1].strip()
    if version not in ("1.0", "0.97"):
        problems.append(f"bagit.txt declares BagIt-Version "
                        f"{version!r}, expected 1.0")
    manifest_path = bag / "manifest-sha256.txt"
    if not manifest_path.is_file():
        problems.append("manifest-sha256.txt missing")
        return False, problems, stats
    manifest = _parse_manifest(manifest_path)

    # Completeness + fixity over the payload.
    on_disk = set()
    data_dir = bag / "data"
    if data_dir.is_dir():
        for p in sorted(data_dir.rglob("*")):
            if p.is_file():
                on_disk.add("data/" + p.relative_to(data_dir)
                            .as_posix())
    for rel in sorted(set(manifest) - on_disk):
        problems.append(f"incomplete: manifest entry missing on"
                        f" disk: {rel}")
    for rel in sorted(on_disk - set(manifest)):
        problems.append(f"unmanifested payload file: {rel}")
    for rel in sorted(set(manifest) & on_disk):
        n, digest = _sha256_file(bag / rel)
        stats["payload_files"] += 1
        stats["payload_bytes"] += n
        if digest != manifest[rel]:
            problems.append(f"fixity: sha256 mismatch: {rel}")

    # Tag files: verify the tagmanifest where one is present.
    tagmanifest_path = bag / "tagmanifest-sha256.txt"
    if tagmanifest_path.is_file():
        for rel, want in sorted(
                _parse_manifest(tagmanifest_path).items()):
            target = bag / rel
            if not target.is_file():
                problems.append(f"tag file missing: {rel}")
            else:
                _n, digest = _sha256_file(target)
                if digest != want:
                    problems.append(f"fixity: tag file sha256"
                                    f" mismatch: {rel}")

    # Payload-Oxum cross-check (bag-info vs the manifest totals).
    info_path = bag / "bag-info.txt"
    if info_path.is_file():
        oxum = _parse_bag_info(info_path).get("payload-oxum")
        if oxum:
            try:
                want_bytes, want_count = oxum.split(".")
                if int(want_bytes) != stats["payload_bytes"] \
                        or int(want_count) != stats["payload_files"]:
                    problems.append(
                        f"Payload-Oxum mismatch: bag-info says"
                        f" {oxum}, manifest payload totals"
                        f" {stats['payload_bytes']}."
                        f"{stats['payload_files']}")
            except ValueError:
                problems.append(f"Payload-Oxum unparseable: {oxum!r}")
    return not problems, problems, stats


def main(argv):
    ap = argparse.ArgumentParser(
        description="BagIt (RFC 8493) packaging for the wiki's "
                    "preservation exports.")
    ap.add_argument("--root", default=None,
                    help="repository root (default: this script's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_pack = sub.add_parser("pack", help="assemble a bag")
    p_pack.add_argument("dest", help="destination directory for the bag")
    p_pack.add_argument("--full", action="store_true",
                        help="snapshot set 'full' (adds raw/); "
                             "default set is 'compiled'")
    p_pack.add_argument("--no-pack-scan", action="store_true",
                        help="skip the pack-time secret-pattern "
                             "scan (recorded in the pack stats)")
    p_pack.add_argument("--allow-pack-findings", action="store_true",
                        help="pack even when the pack-time scan "
                             "finds hits (reported as warnings)")
    p_pack.add_argument("--source-org", default=DEFAULT_SOURCE_ORG)
    p_val = sub.add_parser("validate", help="verify a bag")
    p_val.add_argument("bag", help="the bag directory")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT

    if args.cmd == "pack":
        set_name = "full" if args.full else "compiled"
        try:
            stats = pack(root, Path(args.dest), set_name,
                         source_org=args.source_org,
                         scan=not args.no_pack_scan,
                         allow_pack_findings=args.allow_pack_findings)
        except ValueError as exc:
            print(f"wiki_bag: {exc}", file=sys.stderr)
            return 2
        print(f"packed {stats['set']} set -> {stats['dest']}")
        print(f"  payload: {stats['files']} files,"
              f" {stats['bytes']} bytes"
              f" (Payload-Oxum {stats['bytes']}.{stats['files']})")
        scan_stats = stats.get("pack_scan") or {}
        if scan_stats.get("verdict") == "skipped":
            print("  pack scan: SKIPPED (--no-pack-scan)")
        elif scan_stats.get("findings"):
            print(f"  pack scan: {scan_stats['findings_total']} "
                  f"hit(s) — packed under --allow-pack-findings:")
            for f in scan_stats["findings"]:
                print(f"    warning: {f['file']}: {f['pattern']}"
                      f" x{f['count']}")
        else:
            print("  pack scan: clean")
        return 0
    ok, problems, stats = validate(Path(args.bag))
    if not (Path(args.bag) / "bagit.txt").is_file():
        print(f"wiki_bag: {problems[0]}", file=sys.stderr)
        return 2
    print(f"bag: {args.bag}")
    print(f"  payload verified: {stats['payload_files']} files,"
          f" {stats['payload_bytes']} bytes")
    if ok:
        print("Result: VALID")
        return 0
    print(f"Result: INVALID ({len(problems)} problem(s))")
    for prob in problems:
        print(f"  - {prob}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
