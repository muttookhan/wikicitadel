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


# -- Weighted damage (Brunelle et al., JCDL 2014; Marathon R8) -----
# A snapshot bundle whose embedded resources are partly missing is
# not damaged in proportion to the COUNT of missing files: losing
# the primary document is worse than losing a decorative image.
# Each resource is classed and weighted; a bundle record carries
# missing_weight beside missing_count. REPORT-ONLY for existing
# bundles: damage_report() computes the field read-only and no
# existing manifest is ever rewritten; bundle() stamps the field
# on NEW manifests at capture time.
RESOURCE_WEIGHTS = {
    "document": 5.0,    # the primary page / document itself
    "script": 3.0,
    "stylesheet": 3.0,
    "image": 2.0,
    "font": 2.0,
    "media": 2.0,
    "other": 1.0,
}
_EXT_CLASS = {
    ".html": "document", ".htm": "document", ".pdf": "document",
    ".js": "script", ".mjs": "script",
    ".css": "stylesheet",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".svg": "image", ".webp": "image",
    ".woff": "font", ".woff2": "font", ".ttf": "font",
    ".mp4": "media", ".mp3": "media", ".webm": "media",
}
_CT_CLASS = {
    "text/html": "document", "application/pdf": "document",
    "text/javascript": "script", "application/javascript": "script",
    "text/css": "stylesheet", "font/woff2": "font", "font/woff": "font",
}


def classify_resource(name, content_type=""):
    """Resource class for a captured file / URL leaf, from its
    content type first, then its extension, else 'other'."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _CT_CLASS:
        return _CT_CLASS[ct]
    if ct.startswith("image/"):
        return "image"
    if ct.startswith(("audio/", "video/")):
        return "media"
    leaf = str(name).split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1]
    dot = leaf.rfind(".")
    if dot >= 0:
        return _EXT_CLASS.get(leaf[dot:].lower(), "other")
    return "other"


def weighted_damage(resources):
    """resources: [{name, resource_class?, content_type?,
    present: bool}] -> the damage field: missing_count beside
    missing_weight, over total_weight, as a ratio in [0, 1]."""
    total = missing_w = 0.0
    missing = 0
    rows = []
    for res in resources:
        cls = res.get("resource_class") or classify_resource(
            res.get("name", ""), res.get("content_type", ""))
        weight = float(RESOURCE_WEIGHTS[cls])
        total += weight
        present = bool(res.get("present", True))
        if not present:
            missing += 1
            missing_w += weight
        rows.append({"name": res.get("name", ""), "resource_class": cls,
                     "weight": weight, "present": present})
    return {
        "missing_count": missing,
        "missing_weight": missing_w,
        "total_weight": total,
        "weighted_damage": (missing_w / total) if total else 0.0,
        "resources": rows,
    }


def damage_report(bundle_dir):
    """The weighted-damage field for an EXISTING bundle, computed
    read-only from its manifest (its recorded resources when the
    manifest carries them, else the files the manifest lists).
    Nothing is written back."""
    dest = Path(bundle_dir)
    manifest = json.loads((dest / "manifest.json").read_text(
        encoding="utf-8"))
    recorded = manifest.get("damage", {}).get("resources")
    if recorded:
        resources = [{"name": r["name"],
                      "resource_class": r.get("resource_class"),
                      "present": (dest / r["name"]).exists()
                      if r["name"] else r.get("present", True)}
                     for r in recorded]
    else:
        resources = [{"name": name,
                      "content_type": manifest.get("content_type", "")
                      if name == "original.bin" else "",
                      "present": (dest / name).exists()}
                     for name in manifest.get("files", {})]
    return weighted_damage(resources)


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
    # Tracking-parameter stripping at capture (Marathon R7 lane BA):
    # the bundle is fetched and recorded under the NORMALISED url;
    # the original is preserved verbatim in the manifest below as
    # original_url - provenance is stated, never falsified.
    import wiki_url_normalise as _wun
    _normalised, _original, _url_changes = _wun.normalise_url(url)
    url = _normalised
    data, headers = fetcher(url)
    dest = Path(out_dir) / slugify(url)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "original.bin").write_bytes(data)
    (dest / "headers.json").write_text(
        json.dumps(headers, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    _resources = [{
        "name": "original.bin",
        "resource_class": classify_resource(
            url, headers.get("Content-Type")
            or headers.get("content-type") or ""),
        "present": True,
    }]
    manifest = {
        "damage": weighted_damage(_resources),
        "url": url,
        "original_url": _original,
        "url_normalisation": _url_changes,
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
    d = sub.add_parser("damage")
    d.add_argument("bundle_dir")
    ns = ap.parse_args(argv)
    if ns.cmd == "bundle":
        out = Path(ns.out_dir) if ns.out_dir \
            else Path(ns.root) / "raw" / "snapshots"
        dest, manifest = bundle(ns.url, out, urllib_fetcher,
                                ns.fetched_at)
        print(json.dumps({"bundle": str(dest), "manifest": manifest},
                         indent=2))
        return 0
    if ns.cmd == "damage":
        print(json.dumps({"bundle": ns.bundle_dir,
                          "damage": damage_report(ns.bundle_dir)},
                         indent=2))
        return 0
    problems = verify(ns.bundle_dir)
    print(json.dumps({"bundle": ns.bundle_dir, "ok": not problems,
                      "problems": problems}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
