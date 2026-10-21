#!/usr/bin/env python3
"""wiki_snapshot.py — per-source snapshot bundles (Marathon R3,
Tier B bundle "Graph, portal and capture forms", row 6).

Pattern: ArchiveBox's per-source snapshot bundle (MIT; re-implemented
from the idea, archive-upload defaults OFF — this tool never uploads
anywhere). Each web source can carry a snapshot bundle: the fetched
bytes exactly as received, the response headers, and a hash manifest
that lets anyone verify later that the bundle is the capture it
claims to be.

Bundle layout (one directory per source, under --out-dir):

    <slug>/
        original.bin    the fetched bytes, untouched
        headers.json    the response headers as a JSON object
        manifest.json   {url, fetched_at, content_type, size,
                         sha256, files: {name: sha256}}

The fetcher is INJECTABLE: `bundle(url, out_dir, fetcher)` takes a
callable url -> (bytes, headers dict). Tests pass a fake fetcher —
no live network in tests. The CLI's default fetcher uses urllib and
is the only network path; it is used only when the operator runs
`bundle` by hand.

Subcommands:
    bundle <url> [--out-dir D] [--fetched-at ISO]
    verify <bundle-dir>   recompute hashes; exit 1 on any mismatch.

CLI: --root defaults to the tree root. Exit 0 ok, 1 verify failure,
2 usage/missing input.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def slugify(url):
    s = re.sub(r"^https?://", "", url.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "source"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def urllib_fetcher(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "wiki-snapshot"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 — operator-run CLI
        return resp.read(), dict(resp.headers.items())


def bundle(url, out_dir, fetcher, fetched_at=""):
    data, headers = fetcher(url)
    dest = Path(out_dir) / slugify(url)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "original.bin").write_bytes(data)
    (dest / "headers.json").write_text(
        json.dumps(headers, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    manifest = {
        "url": url,
        "fetched_at": fetched_at,
        "content_type": headers.get("Content-Type")
        or headers.get("content-type") or "",
        "size": len(data),
        "sha256": sha256_bytes(data),
        "files": {
            "original.bin": sha256_bytes(data),
            "headers.json": sha256_bytes(
                (dest / "headers.json").read_bytes()),
        },
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return dest, manifest


def verify(bundle_dir):
    dest = Path(bundle_dir)
    problems = []
    mpath = dest / "manifest.json"
    if not mpath.exists():
        return [f"missing manifest: {mpath}"]
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    for name, want in manifest.get("files", {}).items():
        f = dest / name
        if not f.exists():
            problems.append(f"missing file: {name}")
        elif sha256_bytes(f.read_bytes()) != want:
            problems.append(f"hash mismatch: {name}")
    orig = dest / "original.bin"
    if orig.exists():
        if sha256_bytes(orig.read_bytes()) != manifest.get("sha256"):
            problems.append("original.bin does not match manifest sha256")
        if orig.stat().st_size != manifest.get("size"):
            problems.append("original.bin size differs from manifest")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("url")
    b.add_argument("--out-dir", default=None)
    b.add_argument("--fetched-at", default="")
    v = sub.add_parser("verify")
    v.add_argument("bundle_dir")
    ns = ap.parse_args(argv)
    if ns.cmd == "bundle":
        out = Path(ns.out_dir) if ns.out_dir \
            else Path(ns.root) / "raw" / "snapshots"
        dest, manifest = bundle(ns.url, out, urllib_fetcher,
                                ns.fetched_at)
        print(json.dumps({"bundle": str(dest), "manifest": manifest},
                         indent=2))
        return 0
    problems = verify(ns.bundle_dir)
    print(json.dumps({"bundle": ns.bundle_dir, "ok": not problems,
                      "problems": problems}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
