#!/usr/bin/env python3
"""Signed pipeline receipts (Marathon R3, Tier B row
TB3-7; in-toto pattern).

Pattern: in-toto — an owner-signed pipeline definition with
a signed receipt per step, each receipt binding the step's
artefacts by hash, so the filing -> scan -> review ->
promote path can be audited end to end (via the wave
survey's agent-systems lane). Re-implemented from the idea
in this wiki's register style; no code copied. Signing is
HMAC-SHA256 over the canonical receipt body with a LOCAL
key file — in this scoped build the key is a test artefact,
never a real credential: `init-key` writes a random key
marked TEST ONLY, and a production deployment would swap
the seam for the wiki's SSH signing key.

Receipt register: evaluation/pipeline-receipts.jsonl,
append-only, hash-chained like the other registers. A
receipt line:

    {"kind": "receipt", "run_id": "ingest-2026-10-21-a",
     "step": "compile", "artefacts": {"path": "sha256hex"},
     "prev_receipt": "<line_hash of previous receipt for
                      this run, or genesis>",
     "prev_hash": ..., "line_hash": ...,
     "hmac": "HMAC-SHA256(key, canonical(body without
             hmac/line_hash/prev_hash))"}

`verify` recomputes, for every receipt: each artefact's
sha256 against the file on disk, the per-run receipt chain
(prev_receipt links), the register hash chain, and the
HMAC. Any break is reported by line and kind; nothing is
repaired silently.

Usage:
  python3 scripts/wiki_receipts.py init-key KEYFILE
  python3 scripts/wiki_receipts.py sign --key K --run R \
      --step S ARTEFACT...
  python3 scripts/wiki_receipts.py verify --key K [--run R]

Exit codes: verify 0 = all receipts sound, 1 = a break,
2 = usage error. Stdlib only; no network.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac as hmac_mod
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/pipeline-receipts.jsonl"
GENESIS = "0" * 64


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_register(path: Path):
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def receipt_mac(key: bytes, body: dict) -> str:
    return hmac_mod.new(key, canonical(body), hashlib.sha256).hexdigest()


def cmd_init_key(path: Path):
    if path.exists():
        print(f"key file already exists: {path}", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(secrets.token_bytes(32))
    print(f"wrote TEST-ONLY HMAC key to {path} "
          f"(artefact for receipt signing tests; not a credential)")
    return 0


def cmd_sign(root: Path, key_path: Path, run_id: str, step: str,
             artefacts):
    if not key_path.is_file():
        print(f"no key file: {key_path}", file=sys.stderr)
        return 2
    key = key_path.read_bytes()
    hashes = {}
    for art in artefacts:
        p = root / art
        if not p.is_file():
            print(f"artefact not found: {art}", file=sys.stderr)
            return 2
        hashes[art] = sha256_hex(p.read_bytes())
    register = root / REGISTER_REL
    lines = [ln for ln in load_register(register)
             if ln.get("kind") != "header"]
    run_lines = [ln for ln in lines if ln.get("run_id") == run_id]
    body = {"kind": "receipt", "run_id": run_id, "step": step,
            "artefacts": hashes,
            "prev_receipt": (run_lines[-1]["line_hash"]
                             if run_lines else GENESIS)}
    body["hmac"] = receipt_mac(key, body)
    prev = lines[-1]["line_hash"] if lines else GENESIS
    line = dict(body, prev_hash=prev)
    line["line_hash"] = sha256_hex(prev.encode("utf-8") + canonical(line))
    register.parent.mkdir(parents=True, exist_ok=True)
    if not register.exists():
        header = {"kind": "header", "register": "pipeline-receipts",
                  "version": 1,
                  "purpose": "HMAC-signed per-step pipeline receipts "
                             "(in-toto pattern), maintained by "
                             "scripts/wiki_receipts.py."}
        register.write_text(json.dumps(header, sort_keys=True) + "\n",
                            encoding="utf-8")
    with register.open("a", encoding="utf-8") as fh:
        fh.write(canonical(line).decode("utf-8") + "\n")
    print(f"receipt signed: run {run_id} step {step} "
          f"({len(hashes)} artefact(s)) line_hash {line['line_hash'][:16]}…")
    return 0


def verify(root: Path, key: bytes, run_id=None):
    """(ok, problems list of strings)."""
    lines = [ln for ln in load_register(root / REGISTER_REL)
             if ln.get("kind") != "header"]
    problems = []
    prev = GENESIS
    last_for_run = {}
    for i, ln in enumerate(lines):
        if ln.get("prev_hash") != prev:
            problems.append(f"line {i}: register chain prev_hash break")
        body = {k: v for k, v in ln.items() if k != "line_hash"}
        if sha256_hex(prev.encode("utf-8") + canonical(body)) \
                != ln.get("line_hash"):
            problems.append(f"line {i}: register chain line_hash break")
        prev = ln.get("line_hash")
        if run_id and ln.get("run_id") != run_id:
            continue
        mac_body = {k: v for k, v in ln.items()
                    if k not in ("hmac", "line_hash", "prev_hash")}
        if not hmac_mod.compare_digest(receipt_mac(key, mac_body),
                                       ln.get("hmac", "")):
            problems.append(f"line {i}: HMAC does not verify "
                            f"(run {ln.get('run_id')}, step "
                            f"{ln.get('step')})")
        expected_prev = last_for_run.get(ln.get("run_id"), GENESIS)
        if ln.get("prev_receipt") != expected_prev:
            problems.append(f"line {i}: receipt chain break for run "
                            f"{ln.get('run_id')}")
        last_for_run[ln.get("run_id")] = ln.get("line_hash")
        for art, want in (ln.get("artefacts") or {}).items():
            p = root / art
            if not p.is_file():
                problems.append(f"line {i}: artefact missing: {art}")
            elif sha256_hex(p.read_bytes()) != want:
                problems.append(f"line {i}: artefact changed since "
                                f"receipt: {art}")
    return not problems, problems


def cmd_verify(root: Path, key_path: Path, run_id):
    if not key_path.is_file():
        print(f"no key file: {key_path}", file=sys.stderr)
        return 2
    ok, problems = verify(root, key_path.read_bytes(), run_id)
    print(json.dumps({"ok": ok, "problems": problems}, indent=2))
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pk = sub.add_parser("init-key", help="write a TEST-ONLY local key")
    pk.add_argument("keyfile")
    ps = sub.add_parser("sign", help="sign a step receipt")
    ps.add_argument("--key", required=True)
    ps.add_argument("--run", required=True)
    ps.add_argument("--step", required=True)
    ps.add_argument("artefacts", nargs="+")
    pv = sub.add_parser("verify", help="verify receipts + chains")
    pv.add_argument("--key", required=True)
    pv.add_argument("--run", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "init-key":
        return cmd_init_key(Path(args.keyfile))
    if args.cmd == "sign":
        return cmd_sign(root, Path(args.key), args.run, args.step,
                        args.artefacts)
    return cmd_verify(root, Path(args.key), args.run)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
