#!/usr/bin/env python3
"""Erasure certificates — a receipt for every forget.

Pattern: the signed, content-free erasure certificates of
DanceNitra/inspeximus (MIT) — re-implemented. Inspeximus
measured why receipts matter: a popular memory system
resurrected corrected values in 46.7% of trials, while a
supersede-with-receipt discipline held at 0%. This wiki's
forget flow (owner-ordered removals, de-ingest owner actions)
previously left no checkable proof that the bytes were gone.

A certificate records, for each erased path:
  - the repo-relative path,
  - the erased file's byte count and SHA-256 (a hash is not
    the content: the certificate is CONTENT-FREE — the erased
    bytes never appear in it, in any encoding),
  - the authorising record that ordered the erasure (kind +
    reference: an owner directive, a de-ingest plan hash, ...),
  - a free-text reason, the issuer, and the issue time.

Certificates live in evaluation/erasure-certificates.jsonl,
append-only, hash-chained exactly like the Black Box ledger:
cert_hash = SHA-256(prev_hash || canonical(certificate
without cert_hash)), canonical = UTF-8 JSON, sorted keys, no
insignificant whitespace. Tampering with any earlier
certificate breaks every later link.

"Signed-form", honestly: the chain makes certificates
tamper-evident, and each names its authorising record — but
stdlib Python has no Ed25519, so there is no cryptographic
signature yet. Signing the chain head (the Gnosis pattern) is
the documented next step, the same one noted in
scripts/wiki_provenance.py; nothing here pretends otherwise.

Verify (offline, deterministic):
  1. the register's hash chain recomputes cleanly;
  2. every erased path is absent from the working tree;
  3. the erased BYTES are absent from the working tree: every
     file under the root (outside .git/ and the register
     itself) is hashed, and any file whose SHA-256 equals an
     erased file's SHA-256 is a resurrection — the content
     came back under another name, which is exactly the
     failure Inspeximus measured.
  Verification covers the working tree, not git history:
  history is append-only in this wiki by rule, and rewriting
  it is the memory guard's separate concern
  (scripts/wiki_memory_guard.py).

Usage:
  python3 scripts/wiki_erasure.py issue --path raw/sources/x.md \
      --authorisation-kind owner-directive \
      --authorisation-ref "owner directive ..." \
      --reason "owner-ordered forget"
  python3 scripts/wiki_erasure.py verify
  python3 scripts/wiki_erasure.py list

Issue reads each file's bytes from disk when present, else
from git HEAD (so a certificate can still be issued just
after the deletion, from the last committed bytes). It never
deletes anything itself: erasure is the owner's act (or the
de-ingest cascade's, under its own authorisation); this tool
only issues and checks the receipt.

Exit codes: issue/list 0 = ok, 2 = usage error (a path that
exists nowhere, a bad register). verify 0 = clean, 1 = chain
broken / a path or its bytes are present, 2 = register
missing or unparseable.

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/erasure-certificates.jsonl"
GENESIS_PREV = "0" * 64
SCHEMA = "erasure-certificate/1"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def cert_digest(prev_hash: str, cert_without_hash: dict) -> str:
    return hashlib.sha256(
        prev_hash.encode("utf-8") + canonical(cert_without_hash)).hexdigest()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_bytes(data: bytes):
    return len(data), hashlib.sha256(data).hexdigest()


def hash_file(path: Path):
    """(bytes, sha256) of a file, read in chunks."""
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def file_bytes(root: Path, rel: str):
    """Bytes of rel from disk, else from git HEAD; None if neither."""
    p = root / rel
    if p.is_file():
        return p.read_bytes()
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{rel}"],
            capture_output=True, timeout=15)
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return None


def load_register(register: Path):
    """Return the list of certificates ([] when the file is absent)."""
    if not register.exists():
        return []
    certs = []
    with register.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                certs.append(json.loads(line))
    return certs


def verify_chain(certs):
    """Recompute the hash chain. Return (ok, bad_seq, reason)."""
    prev = GENESIS_PREV
    for i, cert in enumerate(certs):
        if cert.get("seq") != i:
            return False, cert.get("seq"), \
                f"seq discontinuity: expected {i}, found {cert.get('seq')}"
        if cert.get("prev_hash") != prev:
            return False, cert.get("seq"), \
                "prev_hash does not match previous cert_hash"
        body = {k: v for k, v in cert.items() if k != "cert_hash"}
        if cert_digest(prev, body) != cert.get("cert_hash"):
            return False, cert.get("seq"), \
                "cert_hash mismatch (certificate altered)"
        prev = cert["cert_hash"]
    return True, None, None


def issue(root: Path, register: Path, paths, auth_kind: str,
          auth_ref: str, reason: str, actor: str) -> dict:
    scope = []
    for rel in paths:
        rel = Path(rel).as_posix()
        data = file_bytes(root, rel)
        if data is None:
            raise SystemExit(
                f"erasure: cannot certify {rel}: not on disk and not "
                "in git HEAD — there is nothing to take a hash of")
        n, digest = hash_bytes(data)
        scope.append({"path": rel, "bytes": n, "sha256": digest})
    certs = load_register(register)
    prev = certs[-1]["cert_hash"] if certs else GENESIS_PREV
    seq = len(certs)
    cert = {
        "schema": SCHEMA,
        "cert_id": f"erase-{seq:06d}",
        "seq": seq,
        "issued_at": utcnow(),
        "issuer": actor,
        "scope": scope,
        "authorisation": {"kind": auth_kind, "ref": auth_ref},
        "reason": reason,
        "prev_hash": prev,
    }
    cert["cert_hash"] = cert_digest(prev, cert)
    register.parent.mkdir(parents=True, exist_ok=True)
    with register.open("ab") as fh:
        fh.write(canonical(cert) + b"\n")
        fh.flush()
        import os
        os.fsync(fh.fileno())
    return cert


def iter_tree_files(root: Path, register: Path):
    """Every file under root except .git/ and the register itself."""
    register_abs = register.resolve()
    for p in sorted(root.rglob("*")):
        if ".git" in p.parts:
            continue
        if p.is_file() and p.resolve() != register_abs:
            yield p


def verify(root: Path, register: Path) -> int:
    if not register.exists():
        print(f"No erasure register at "
              f"{register.relative_to(root).as_posix() if register.is_relative_to(root) else register}"
              " — nothing has been certified.")
        return 2
    try:
        certs = load_register(register)
    except Exception as exc:
        print(f"Erasure register is unparseable: {exc}")
        return 2
    ok, bad_seq, why = verify_chain(certs)
    print(f"== Erasure verify ==  certificates: {len(certs)}")
    if not ok:
        print(f"  CHAIN BROKEN at seq {bad_seq}: {why}")
        print("Result: FAIL")
        return 1
    print("  hash chain: OK")

    erased_hashes = {}
    present_paths = []
    for cert in certs:
        for entry in cert.get("scope") or []:
            erased_hashes[entry["sha256"]] = entry["path"]
            if (root / entry["path"]).exists():
                present_paths.append(entry["path"])
    for rel in present_paths:
        print(f"  PATH PRESENT  {rel} (certified erased, still on disk)")
    resurrected = []
    if erased_hashes:
        for p in iter_tree_files(root, register):
            try:
                _n, digest = hash_file(p)
            except Exception:
                continue
            if digest in erased_hashes:
                resurrected.append(
                    (p.relative_to(root).as_posix(), erased_hashes[digest]))
    for rel, orig in resurrected:
        print(f"  BYTES PRESENT {rel} holds the erased bytes of {orig}")
    if present_paths or resurrected:
        print("Result: FAIL — certified-erased content is present")
        return 1
    total = sum(len(c.get("scope") or []) for c in certs)
    print(f"  absence: OK ({total} erased path(s), "
          "no erased bytes anywhere in the tree)")
    print("Result: CLEAN")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Issue and verify content-free erasure certificates.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    ap.add_argument("--register", default=None,
                    help=f"register path (default: <root>/{REGISTER_REL})")
    sub = ap.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("issue", help="certify an erasure (receipt only; "
                                      "deletes nothing)")
    pi.add_argument("--path", action="append", required=True,
                    help="repo-relative erased path (repeatable)")
    pi.add_argument("--authorisation-kind", required=True,
                    help="e.g. owner-directive, deingest-plan")
    pi.add_argument("--authorisation-ref", required=True,
                    help="reference to the authorising record")
    pi.add_argument("--reason", required=True)
    pi.add_argument("--actor", default="agent")

    sub.add_parser("verify", help="check the chain and the absence of "
                                  "the erased bytes")
    sub.add_parser("list", help="list issued certificates")

    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    register = Path(args.register) if args.register else root / REGISTER_REL

    if args.command == "issue":
        cert = issue(root, register, args.path, args.authorisation_kind,
                     args.authorisation_ref, args.reason, args.actor)
        print(f"issued {cert['cert_id']}  cert_hash {cert['cert_hash']}")
        for entry in cert["scope"]:
            print(f"  {entry['path']}  {entry['bytes']} B  "
                  f"sha256 {entry['sha256']}")
        return 0
    if args.command == "verify":
        return verify(root, register)
    if args.command == "list":
        try:
            certs = load_register(register)
        except Exception as exc:
            print(f"Erasure register is unparseable: {exc}")
            return 2
        for cert in certs:
            paths = ", ".join(e["path"] for e in cert.get("scope") or [])
            print(f"{cert['cert_id']}  {cert.get('issued_at')}  "
                  f"{cert.get('authorisation', {}).get('kind')}: "
                  f"{paths}")
        print(f"{len(certs)} certificate(s)")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
