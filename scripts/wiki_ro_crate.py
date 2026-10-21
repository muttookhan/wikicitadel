#!/usr/bin/env python3
"""wiki_ro_crate.py — an RO-Crate sidecar on export bundles
(Marathon Round 5, lane BA, item 3).

Pattern: ResearchObject/ro-crate-py (Apache-2.0) and the
RO-Crate 1.1 specification — a research object travels with a
machine-readable manifest that says what the bundle IS and
what it CONTAINS, in JSON-LD a stranger's tooling can read
without any of the producer's own scripts. Re-implemented
here in our own code, stdlib only; no code copied.

Why: this wiki's exports already prove their own integrity —
a BagIt bag (scripts/wiki_bag.py) verifies its bytes with
nothing but the bag and a sha256 tool. What a bag does not do
is DESCRIBE itself to outside tooling: what the bundle is,
when it was published, which files it has and what format
each one is. The RO-Crate sidecar is that description:
`ro-crate-metadata.json` at the bundle's root, written in
the RO-Crate 1.1 context, with the bundle as the root
Dataset entity and every file in the bundle as a File entity
(name, contentSize, encodingFormat, sha256).

GENERATED, NEVER HAND-WRITTEN. The sidecar is a pure function
of the bundle's contents plus the caller's stated name /
description / datePublished: paths are walked in sorted
order, JSON is serialised in one fixed shape, and no clock,
hostname, or filesystem ordering leaks into the output — two
runs over the same bundle give byte-identical sidecars. A
hand edit is therefore detectable by construction: `check`
recomputes the expected crate from the bundle on disk (the
descriptive fields are read back out of the existing
sidecar, so check verifies CONTENT, not the caller's memory
of the flags) and names every divergence.

Exclusions mirror the bag's: the sidecar itself, and
bytecode caches (__pycache__/, *.pyc) — derived artefacts
that would make crates differ between machines for no
content reason. The sidecar sits BESIDE a bag's payload, at
the bundle root: it is not a payload file, and a bag that
gains a sidecar still validates (asserted in the tests).

Commands:
  build <bundle-dir> [--name N] [--description D]
        [--date YYYY-MM-DD] [--license URL] [--out FILE]
        write ro-crate-metadata.json into the bundle (or to
        --out); prints the file count and bytes described
  check <bundle-dir>
        recompute and compare; exit 1 naming every problem

Exit codes: 0 ok, 1 check found problems, 2 usage error.
Stdlib only.
"""
import argparse
import hashlib
import json
import mimetypes
import sys
from pathlib import Path

SIDECAR_NAME = "ro-crate-metadata.json"
CRATE_CONTEXT = "https://w3id.org/ro/crate/1.1/context"
CRATE_SPEC = "https://w3id.org/ro/crate/1.1"
DEFAULT_DESCRIPTION = "Wiki export bundle (self-described by a "\
                      "generated RO-Crate sidecar)"


def _excluded(rel: Path) -> bool:
    return rel.as_posix() == SIDECAR_NAME \
        or "__pycache__" in rel.parts or rel.suffix == ".pyc"


def _sha256_file(path: Path):
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def collect_files(bundle: Path):
    """[(bundle-relative posix path, absolute path)],
    deterministically ordered, sidecar and caches excluded."""
    out = []
    for p in sorted(bundle.rglob("*")):
        if p.is_file():
            rel = p.relative_to(bundle)
            if not _excluded(rel):
                out.append((rel.as_posix(), p))
    out.sort(key=lambda t: t[0])
    return out


def build_crate(bundle: Path, name=None, description=None,
                date_published=None, license_url=None):
    """The crate dict for a bundle directory. Deterministic:
    the same bundle contents and the same arguments always
    produce the same dict."""
    bundle = Path(bundle)
    files = collect_files(bundle)
    graph = [{
        "@id": SIDECAR_NAME,
        "@type": "CreativeWork",
        "conformsTo": {"@id": CRATE_SPEC},
        "about": {"@id": "./"},
    }]
    root = {
        "@id": "./",
        "@type": "Dataset",
        "name": name or bundle.name,
        "description": description or DEFAULT_DESCRIPTION,
        "hasPart": [{"@id": rel} for rel, _p in files],
    }
    if date_published:
        root["datePublished"] = date_published
    if license_url:
        root["license"] = {"@id": license_url}
    graph.append(root)
    for rel, path in files:
        size, digest = _sha256_file(path)
        graph.append({
            "@id": rel,
            "@type": "File",
            "name": path.name,
            "contentSize": str(size),
            "encodingFormat": mimetypes.guess_type(path.name)[0]
                              or "application/octet-stream",
            "sha256": digest,
        })
    return {"@context": CRATE_CONTEXT, "@graph": graph}


def crate_text(crate):
    """The sidecar's canonical serialisation: one fixed shape
    (2-space indent, key order as built, trailing newline)."""
    return json.dumps(crate, indent=2, ensure_ascii=False) + "\n"


def write_crate(bundle: Path, name=None, description=None,
                date_published=None, license_url=None, out=None):
    """Generate and write the sidecar. Returns a stats dict."""
    bundle = Path(bundle)
    if not bundle.is_dir():
        raise ValueError(f"{bundle} is not a directory")
    crate = build_crate(bundle, name=name, description=description,
                        date_published=date_published,
                        license_url=license_url)
    dest = Path(out) if out else bundle / SIDECAR_NAME
    dest.write_text(crate_text(crate), encoding="utf-8")
    files = collect_files(bundle)
    return {"sidecar": str(dest), "files": len(files),
            "bytes": sum(p.stat().st_size for _r, p in files)}


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def check_crate(bundle: Path):
    """Recompute the expected crate from the bundle on disk
    and compare with the sidecar that is there. The
    descriptive fields (name, description, datePublished,
    license) are taken from the existing sidecar's root
    entity — check verifies the sidecar against the bundle,
    so any argument drift is the bundle's own record.
    Returns a list of problem strings."""
    bundle = Path(bundle)
    sidecar = bundle / SIDECAR_NAME
    if not sidecar.is_file():
        return [f"{SIDECAR_NAME} missing — the bundle carries "
                f"no RO-Crate sidecar"]
    try:
        actual = json.loads(sidecar.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"{SIDECAR_NAME} is not valid JSON: {exc}"]
    problems = []
    if actual.get("@context") != CRATE_CONTEXT:
        problems.append(f"@context is {actual.get('@context')!r}, "
                        f"expected the RO-Crate 1.1 context")
    graph = actual.get("@graph") or []
    by_id = {e.get("@id"): e for e in graph if isinstance(e, dict)}
    descriptor = by_id.get(SIDECAR_NAME)
    if not descriptor or descriptor.get("about") != {"@id": "./"}:
        problems.append("metadata descriptor entity missing or "
                        "its 'about' does not point at ./")
    root = by_id.get("./")
    if not root or root.get("@type") != "Dataset":
        problems.append("root Dataset entity (./) missing")
        return problems
    lic = root.get("license") or {}
    expected = build_crate(
        bundle, name=root.get("name"),
        description=root.get("description"),
        date_published=root.get("datePublished"),
        license_url=lic.get("@id") if isinstance(lic, dict) else None)
    if _canonical(expected) != _canonical(actual):
        exp_by_id = {e["@id"]: e for e in expected["@graph"]}
        for eid in sorted(set(exp_by_id) - set(by_id)):
            problems.append(f"file in bundle not described: {eid}")
        for eid in sorted(set(by_id) - set(exp_by_id)):
            problems.append(f"described but not in bundle: {eid}")
        for eid in sorted(set(by_id) & set(exp_by_id)):
            if _canonical(by_id[eid]) != _canonical(exp_by_id[eid]):
                if eid in ("./", SIDECAR_NAME):
                    problems.append(f"entity {eid} differs from "
                                    f"the bundle's recomputed "
                                    f"crate (descriptive fields "
                                    f"or hasPart)")
                else:
                    problems.append(f"file entity differs from "
                                    f"disk (size, format or "
                                    f"sha256): {eid}")
        if not problems:
            problems.append("sidecar differs from the recomputed "
                            "crate in @context or graph shape")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="generate the sidecar")
    b.add_argument("bundle")
    b.add_argument("--name", default=None)
    b.add_argument("--description", default=None)
    b.add_argument("--date", default=None,
                   help="datePublished (YYYY-MM-DD); omitted "
                        "from the crate when not given")
    b.add_argument("--license", default=None,
                   help="license URL for the bundle")
    b.add_argument("--out", default=None)
    c = sub.add_parser("check", help="verify the sidecar "
                                     "against the bundle")
    c.add_argument("bundle")
    ns = ap.parse_args(argv)
    if ns.cmd == "build":
        try:
            stats = write_crate(Path(ns.bundle), name=ns.name,
                                description=ns.description,
                                date_published=ns.date,
                                license_url=ns.license, out=ns.out)
        except ValueError as exc:
            print(f"wiki_ro_crate: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {stats['sidecar']}")
        print(f"  described: {stats['files']} files, "
              f"{stats['bytes']} bytes")
        return 0
    problems = check_crate(Path(ns.bundle))
    if problems:
        print(f"Result: INVALID ({len(problems)} problem(s))")
        for prob in problems:
            print(f"  - {prob}")
        return 1
    print("Result: VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
