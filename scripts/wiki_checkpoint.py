#!/usr/bin/env python3
"""Checkpoints — signed, witnessed, timestamp-anchored heads
for the LLM Wiki (WikiCitadel v1).

Pattern: the signing pack, in its build order —
Git SSH signing with an in-repo allowed_signers file (find
13), a C2SP-style checkpoint over the ledger heads with one
PRIVATE witness (find 2), and two independent timestamp
anchors, OpenTimestamps (find 7) + RFC 3161 (find 8), which
are the dual-anchor rule. Re-implemented here in this
wiki's own style; no code copied. Public transparency logs
(Rekor/Sigstore class) are NOT used and must not be added:
they publish signer identity and timing permanently, and
this wiki is private (the survey's never-build list).

What a checkpoint binds, in one signed record:

  - the git HEAD commit and its tree hash;
  - the Black Box head (wiki/access/black-box-*.jsonl: the
    entry count and the last entry_hash) — the checkpoint
    attests the ledger AS IT STOOD; verify re-checks that
    the recorded head still appears in the living ledger,
    which is what makes a wholesale ledger rewrite
    detectable (the recorded head would be gone);
  - the provenance state: evaluation/merkle-manifest.jsonl
    as recorded — its sha256, its source count, and a corpus
    root (sha256 over the sorted "path:merkle_root" lines).

The register evaluation/checkpoints.jsonl is hash-chained
like the wiki's other registers: every line carries
prev_hash and line_hash = sha256(prev_hash || canonical
line without line_hash); canonical = UTF-8 JSON, sorted
keys, no insignificant whitespace. A checkpoint line's body
is signed with the wiki's dedicated SSH signing key
(~/.ssh/id_ed25519_wiki_signing — VM-resident, NO
passphrase: that is stated plainly wherever the key is
described; the private key never enters this repo). The
exact signed bytes live in evaluation/checkpoints.d/<id>.json
and the armored signature in <id>.json.sig; verification is
`ssh-keygen -Y verify` against wiki/access/allowed_signers
for identity agent@wikicitadel, namespace "git".

THE WITNESS: after every create/anchor, the register and
the signature artefacts are copied to a second location
OUTSIDE the repo (default ~/workspace/wikicitadel-checkpoints/).
The witness is a plain copy held in different storage, not
a service and not a public log: rewriting the repo's
history now also requires rewriting the witness's copy,
and `verify` reports when the two disagree (the witness
chain must be a prefix of, or equal to, the repo chain).

THE DUAL-ANCHOR RULE: a checkpoint should carry
TWO independent timestamp anchors over its line_hash — one
OpenTimestamps (Bitcoin-anchored, no trusted party, coarse
time) and one RFC 3161 (a TSA's signed token, precise time,
a trusted party) — because each covers the other's failure
mode. `anchor` attempts both and APPENDS an anchor line
recording each attempt's real outcome (receipt path or the
dated failure — a receipt is never faked). The anchor line
states the checkpoint's anchor_label: "dual-anchor" (both
receipts), "single-anchor" (exactly one), "unanchored"
(none, or no anchor attempted yet). A label is only ever
set by an anchor line recording the act that earned it —
it is never edited or silently upgraded afterwards.

The anchored digest file evaluation/anchors/<id>.digest
contains the checkpoint's line_hash hex; every anchor binds
that file (OTS stamps the file; the RFC 3161 imprint is
sha256 of the file), so an anchor proves: this checkpoint
record existed, in this chain position, by the anchor's
time.

Usage:
  python3 scripts/wiki_checkpoint.py create [--note TEXT]
  python3 scripts/wiki_checkpoint.py verify
  python3 scripts/wiki_checkpoint.py anchor [--id cp-000001]
  python3 scripts/wiki_checkpoint.py show

Exit codes: create/show 0 = ok, 2 = usage error. anchor 0
= the anchor line was written (individual anchor failures
are recorded IN the line, not hidden behind the exit code),
2 = usage error. verify 0 = every check passed, 1 = a
check failed, 2 = usage error (no register, bad key, ...).

Stdlib only (ssh-keygen / git / openssl / ots are external
tools, invoked, never imported).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/checkpoints.jsonl"
ARTEFACT_DIR_REL = "evaluation/checkpoints.d"
ANCHOR_DIR_REL = "evaluation/anchors"
SIGNERS_REL = "wiki/access/allowed_signers"
SIGNER_IDENTITY = "agent@wikicitadel"
SIGN_NAMESPACE = "git"
GENESIS_PREV = "0" * 64
DEFAULT_KEY = Path.home() / ".ssh" / "id_ed25519_wiki_signing"
DEFAULT_WITNESS = Path.home() / "workspace" / "wikicitadel-checkpoints"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=120, **kw)


# -- register -----------------------------------------------------------------

def load_register(path: Path):
    """All register lines ([] when absent); header excluded
    from chaining but returned for inspection."""
    if not path.exists():
        return [], []
    header, lines = [], []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        (header if obj.get("kind") == "header" else lines).append(obj)
    return header, lines


def line_digest(prev_hash: str, line_without_hash: dict) -> str:
    return sha256_hex(prev_hash.encode("utf-8")
                      + canonical(line_without_hash))


def append_line(register: Path, body: dict) -> dict:
    _header, lines = load_register(register)
    prev = lines[-1]["line_hash"] if lines else GENESIS_PREV
    line = dict(body)
    line["prev_hash"] = prev
    line["line_hash"] = line_digest(prev, line)
    register.parent.mkdir(parents=True, exist_ok=True)
    with register.open("a", encoding="utf-8") as fh:
        fh.write(canonical(line).decode("utf-8") + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return line


def ensure_header(register: Path, key_fingerprint: str):
    if register.exists():
        return
    header = {
        "kind": "header", "register": "checkpoints", "version": 1,
        "created": utcnow(),
        "purpose": "Signed, witnessed, timestamp-anchored "
                   "checkpoints over the wiki's heads (git HEAD, "
                   "Black Box head, provenance corpus root). "
                   "Maintained by scripts/wiki_checkpoint.py; see "
                   "wiki/rules/signing-and-anchoring.md.",
        "signer": {"identity": SIGNER_IDENTITY,
                   "key_fingerprint": key_fingerprint,
                   "allowed_signers": SIGNERS_REL},
    }
    register.parent.mkdir(parents=True, exist_ok=True)
    register.write_text(canonical(header).decode("utf-8") + "\n",
                        encoding="utf-8")


def verify_chain(lines):
    prev = GENESIS_PREV
    for i, line in enumerate(lines):
        if line.get("prev_hash") != prev:
            return False, i, "prev_hash mismatch"
        body = {k: v for k, v in line.items() if k != "line_hash"}
        if line_digest(prev, body) != line.get("line_hash"):
            return False, i, "line_hash mismatch (line altered)"
        prev = line["line_hash"]
    return True, None, None


# -- state collection -----------------------------------------------------------

def git_out(root: Path, *args) -> str:
    r = run(["git", "-C", str(root), *args])
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def black_box_state(root: Path):
    """(rel path, entry count, head hash) of the newest
    Black Box ledger under wiki/access/."""
    files = sorted((root / "wiki" / "access").glob("black-box-*.jsonl"))
    if not files:
        raise SystemExit("no Black Box ledger under wiki/access/")
    path = files[-1]
    entries = [json.loads(ln) for ln in
               path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not entries:
        raise SystemExit(f"Black Box ledger {path} is empty")
    return (path.relative_to(root).as_posix(), len(entries),
            entries[-1]["entry_hash"], {e["entry_hash"] for e in entries})


def provenance_state(root: Path):
    """(source count, corpus root, manifest sha256) from the
    RECORDED manifest — the checkpoint attests the recorded
    provenance state, not a fresh rescan."""
    manifest = root / "evaluation" / "merkle-manifest.jsonl"
    if not manifest.is_file():
        raise SystemExit("no evaluation/merkle-manifest.jsonl — "
                         "run scripts/wiki_provenance.py --merkle-generate")
    raw = manifest.read_bytes()
    pairs = []
    for ln in raw.decode("utf-8").splitlines():
        if ln.strip():
            d = json.loads(ln)
            pairs.append(f"{d['path']}:{d['merkle_root']}")
    pairs.sort()
    corpus_root = sha256_hex("\n".join(pairs).encode("utf-8"))
    return len(pairs), corpus_root, sha256_hex(raw)


def key_fingerprint(pub_path: Path) -> str:
    r = run(["ssh-keygen", "-lf", str(pub_path)])
    if r.returncode != 0:
        raise SystemExit(f"cannot read public key {pub_path}")
    return r.stdout.split()[1]  # "SHA256:..." field


# -- witness ---------------------------------------------------------------------

def copy_witness(root: Path, witness: Path):
    witness.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / REGISTER_REL, witness / "checkpoints.jsonl")
    src_dir = root / ARTEFACT_DIR_REL
    dst_dir = witness / "checkpoints.d"
    dst_dir.mkdir(exist_ok=True)
    for f in sorted(src_dir.iterdir()):
        if f.is_file():
            shutil.copy2(f, dst_dir / f.name)
    anchors = root / ANCHOR_DIR_REL
    if anchors.is_dir():
        dst_a = witness / "anchors"
        dst_a.mkdir(exist_ok=True)
        for f in sorted(anchors.rglob("*")):
            if f.is_file():
                rel = f.relative_to(anchors)
                (dst_a / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst_a / rel)


# -- create ------------------------------------------------------------------------

def cmd_create(root: Path, key: Path, witness: Path, note: str):
    if not key.is_file():
        print(f"signing key not found: {key}", file=sys.stderr)
        return 2
    register = root / REGISTER_REL
    fp = key_fingerprint(Path(str(key) + ".pub"))
    ensure_header(register, fp)
    _h, lines = load_register(register)
    n = sum(1 for ln in lines if ln.get("kind") == "checkpoint") + 1
    cp_id = f"cp-{n:06d}"
    bb_rel, bb_n, bb_head, _hashes = black_box_state(root)
    prov_n, prov_root, prov_sha = provenance_state(root)
    body = {
        "kind": "checkpoint", "id": cp_id, "created_utc": utcnow(),
        "git_head": git_out(root, "rev-parse", "HEAD"),
        "git_tree": git_out(root, "rev-parse", "HEAD^{tree}"),
        "black_box": {"file": bb_rel, "entries": bb_n,
                      "head_hash": bb_head},
        "provenance": {"manifest": "evaluation/merkle-manifest.jsonl",
                        "sources": prov_n, "corpus_root": prov_root,
                        "manifest_sha256": prov_sha},
        "signer": SIGNER_IDENTITY, "key_fingerprint": fp,
    }
    if note:
        body["note"] = note
    arte_dir = root / ARTEFACT_DIR_REL
    arte_dir.mkdir(parents=True, exist_ok=True)
    msg_path = arte_dir / f"{cp_id}.json"
    msg_path.write_bytes(canonical(body))
    r = run(["ssh-keygen", "-Y", "sign", "-f", str(key),
             "-n", SIGN_NAMESPACE, str(msg_path)])
    if r.returncode != 0:
        print(f"ssh-keygen -Y sign failed: {r.stderr.strip()}",
              file=sys.stderr)
        return 2
    body["signature"] = {
        "message_file": f"{ARTEFACT_DIR_REL}/{cp_id}.json",
        "signature_file": f"{ARTEFACT_DIR_REL}/{cp_id}.json.sig",
        "namespace": SIGN_NAMESPACE,
    }
    line = append_line(register, body)
    copy_witness(root, witness)
    print(f"created {cp_id}  line_hash {line['line_hash']}")
    print(f"  git {body['git_head'][:12]}  tree {body['git_tree'][:12]}")
    print(f"  black box {bb_rel}: {bb_n} entries, head {bb_head[:16]}…")
    print(f"  provenance: {prov_n} sources, corpus root {prov_root[:16]}…")
    print(f"  signed by {SIGNER_IDENTITY} ({fp}); witness copy at {witness}")
    return 0


# -- verify ------------------------------------------------------------------------

def cmd_verify(root: Path, witness: Path):
    register = root / REGISTER_REL
    if not register.is_file():
        print("no checkpoint register — run create first")
        return 2
    _header, lines = load_register(register)
    failures = []
    ok, bad, why = verify_chain(lines)
    print(f"register chain: {'OK' if ok else f'BROKEN at line {bad}: {why}'}"
          f" ({len(lines)} chained line(s))")
    if not ok:
        failures.append("chain")
    signers = root / SIGNERS_REL
    _bb_rel, _bb_n, _bb_head, bb_hashes = black_box_state(root)
    labels = {}
    for ln in lines:
        if ln.get("kind") == "anchor":
            labels[ln["checkpoint"]] = ln["anchor_label"]
    for ln in lines:
        if ln.get("kind") != "checkpoint":
            continue
        cp = ln["id"]
        body = {k: v for k, v in ln.items()
                if k not in ("prev_hash", "line_hash", "signature")}
        msg_path = root / ln["signature"]["message_file"]
        sig_path = root / ln["signature"]["signature_file"]
        problems = []
        if not msg_path.is_file() or msg_path.read_bytes() != canonical(body):
            problems.append("signed message bytes differ from the register line")
        else:
            with msg_path.open("rb") as fh:
                r = subprocess.run(
                    ["ssh-keygen", "-Y", "verify", "-f", str(signers),
                     "-I", SIGNER_IDENTITY, "-n", SIGN_NAMESPACE,
                     "-s", str(sig_path)],
                    stdin=fh, capture_output=True, text=True, timeout=60)
            if r.returncode != 0 or "Good" not in r.stderr + r.stdout:
                problems.append(f"signature does not verify: "
                                f"{(r.stderr or r.stdout).strip()}")
        tree = run(["git", "-C", str(root), "cat-file", "-t",
                    ln["git_head"]])
        if tree.returncode != 0:
            problems.append("recorded git HEAD commit not in this repo")
        else:
            actual_tree = git_out(root, "rev-parse",
                                  f"{ln['git_head']}^{{tree}}")
            if actual_tree != ln["git_tree"]:
                problems.append("recorded tree hash does not match the commit")
        if ln["black_box"]["head_hash"] not in bb_hashes:
            problems.append("recorded Black Box head NOT FOUND in the "
                            "living ledger — the ledger was rewritten")
        _pn, proot, psha = provenance_state(root)
        if psha != ln["provenance"]["manifest_sha256"]:
            print(f"  [{cp}] note: provenance manifest regenerated since "
                  f"this checkpoint (corpus-root recomputation skipped)")
        elif proot != ln["provenance"]["corpus_root"]:
            problems.append("provenance corpus root does not recompute")
        status = "OK" if not problems else "FAIL"
        if problems:
            failures.append(cp)
        print(f"  [{cp}] signature+state: {status}"
              f" · anchor label: {labels.get(cp, 'unanchored (no anchor attempted)')}")
        for p in problems:
            print(f"      - {p}")
    wreg = witness / "checkpoints.jsonl"
    if wreg.is_file():
        _wh, wlines = load_register(wreg)
        repo_hashes = [ln["line_hash"] for ln in lines]
        wit_hashes = [ln["line_hash"] for ln in wlines]
        if repo_hashes[:len(wit_hashes)] == wit_hashes:
            print(f"witness: OK — witness chain is a prefix of the repo "
                  f"chain ({len(wit_hashes)}/{len(repo_hashes)} lines)")
        else:
            print("witness: DIVERGED — witness chain is not a prefix of "
                  "the repo chain")
            failures.append("witness")
    else:
        print(f"witness: no witness copy at {wreg} (note, not a failure)")
    print(f"Result: {'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


# -- anchor ------------------------------------------------------------------------

def find_ots():
    for cand in (shutil.which("ots"),
                 str(Path.home() / ".venv-tools" / "bin" / "ots")):
        if cand and Path(cand).exists():
            return cand
    return None


TSAS = ["https://freetsa.org/tsr",
        "https://www.digistamp.com/TSA/"]


def ots_attempt(root: Path, cp_id: str, digest_path: Path):
    ots = find_ots()
    receipt_rel = f"{ANCHOR_DIR_REL}/{cp_id}.ots"
    if ots is None:
        return {"mechanism": "opentimestamps", "status": "failed",
                "detail": "ots client not available (checked PATH and "
                          "~/.venv-tools/bin/ots) — attempt "
                          "recorded, no receipt exists"}
    work = Path("/tmp") / f"{cp_id}.digest"
    shutil.copy2(digest_path, work)
    r = run([ots, "stamp", str(work)])
    produced = Path(str(work) + ".ots")
    if r.returncode == 0 and produced.is_file():
        shutil.copy2(produced, root / receipt_rel)
        detail = (r.stdout or r.stderr).strip().splitlines()
        return {"mechanism": "opentimestamps", "status": "receipt",
                "receipt": receipt_rel,
                "detail": detail[-1] if detail else "stamped"}
    return {"mechanism": "opentimestamps", "status": "failed",
            "detail": f"ots stamp failed: {(r.stderr or r.stdout).strip()[:300]}"}


def rfc3161_attempt(root: Path, cp_id: str, digest_path: Path):
    receipt_rel = f"{ANCHOR_DIR_REL}/{cp_id}.tsr"
    req = Path("/tmp") / f"{cp_id}.tsq"
    resp = Path("/tmp") / f"{cp_id}.tsr"
    r = run(["openssl", "ts", "-query", "-data", str(digest_path),
             "-sha256", "-cert", "-out", str(req)])
    if r.returncode != 0:
        return {"mechanism": "rfc3161", "status": "failed",
                "detail": f"openssl ts -query failed: {r.stderr.strip()[:200]}"}
    errors = []
    for tsa in TSAS:
        r = run(["curl", "-sS", "-m", "30", "-H",
                 "Content-Type: application/timestamp-query",
                 "--data-binary", f"@{req}", "-o", str(resp), tsa])
        if r.returncode != 0 or not resp.is_file() or resp.stat().st_size == 0:
            errors.append(f"{tsa}: curl: {r.stderr.strip()[:120]}")
            continue
        # sanity: the reply must parse as a timestamp response
        chk = run(["openssl", "ts", "-reply", "-in", str(resp), "-text"])
        if chk.returncode != 0 or "Time stamp" not in (chk.stdout + chk.stderr):
            errors.append(f"{tsa}: reply did not parse as an RFC 3161 "
                          f"timestamp response")
            continue
        verify = verify_tsr(root, cp_id, digest_path, resp, tsa)
        shutil.copy2(resp, root / receipt_rel)
        return {"mechanism": "rfc3161", "status": "receipt",
                "receipt": receipt_rel, "tsa": tsa,
                "detail": verify}
    return {"mechanism": "rfc3161", "status": "failed",
            "detail": "; ".join(errors)[:400]}


def verify_tsr(root: Path, cp_id: str, digest_path: Path,
               resp: Path, tsa: str) -> str:
    """Verify the token when the TSA's chain is fetchable
    (FreeTSA publishes its CA + TSA certs); otherwise record
    honestly that the token parses but chain verification
    was not performed."""
    if "freetsa" in tsa:
        chain_dir = root / ANCHOR_DIR_REL / "freetsa"
        chain_dir.mkdir(parents=True, exist_ok=True)
        ca = chain_dir / "cacert.pem"
        crt = chain_dir / "tsa.crt"
        for url, dst in (("https://freetsa.org/files/cacert.pem", ca),
                         ("https://freetsa.org/files/tsa.crt", crt)):
            if not dst.is_file():
                run(["curl", "-sS", "-m", "30", "-o", str(dst), url])
        if ca.is_file() and crt.is_file() and ca.stat().st_size > 0:
            r = run(["openssl", "ts", "-verify", "-data", str(digest_path),
                     "-in", str(resp), "-CAfile", str(ca),
                     "-untrusted", str(crt)])
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0 and "Verification: OK" in out:
                return ("token verified against the FreeTSA chain "
                        "(openssl ts -verify: OK); chain files kept at "
                        "evaluation/anchors/freetsa/")
            return f"openssl ts -verify against FreeTSA chain: {out[:200]}"
        return "FreeTSA chain files could not be fetched; token parses only"
    return "token parses as an RFC 3161 response; chain verification not performed for this TSA"


def cmd_anchor(root: Path, witness: Path, cp_id: str | None):
    register = root / REGISTER_REL
    if not register.is_file():
        print("no checkpoint register — run create first", file=sys.stderr)
        return 2
    _h, lines = load_register(register)
    cps = [ln for ln in lines if ln.get("kind") == "checkpoint"]
    if not cps:
        print("no checkpoints to anchor", file=sys.stderr)
        return 2
    target = (next((ln for ln in cps if ln["id"] == cp_id), None)
              if cp_id else cps[-1])
    if target is None:
        print(f"no such checkpoint: {cp_id}", file=sys.stderr)
        return 2
    anchor_dir = root / ANCHOR_DIR_REL
    anchor_dir.mkdir(parents=True, exist_ok=True)
    digest_path = anchor_dir / f"{target['id']}.digest"
    digest_path.write_text(target["line_hash"] + "\n", encoding="utf-8")
    attempts = [ots_attempt(root, target["id"], digest_path),
                rfc3161_attempt(root, target["id"], digest_path)]
    receipts = sum(1 for a in attempts if a["status"] == "receipt")
    label = {2: "dual-anchor", 1: "single-anchor",
             0: "unanchored"}[receipts]
    body = {"kind": "anchor", "checkpoint": target["id"],
            "attempted_utc": utcnow(),
            "anchored_line_hash": target["line_hash"],
            "anchors": attempts, "anchor_label": label}
    append_line(register, body)
    copy_witness(root, witness)
    for a in attempts:
        print(f"  {a['mechanism']}: {a['status']} — {a['detail']}")
    print(f"anchor line appended for {target['id']}: label {label}")
    return 0


# -- show ---------------------------------------------------------------------------

def cmd_show(root: Path):
    register = root / REGISTER_REL
    if not register.is_file():
        print("no checkpoint register")
        return 2
    _h, lines = load_register(register)
    labels = {}
    for ln in lines:
        if ln.get("kind") == "anchor":
            labels[ln["checkpoint"]] = ln["anchor_label"]
    for ln in lines:
        if ln.get("kind") == "checkpoint":
            print(f"{ln['id']}  {ln['created_utc']}  head "
                  f"{ln['git_head'][:12]}  black-box "
                  f"{ln['black_box']['entries']} entries  label: "
                  f"{labels.get(ln['id'], 'unanchored (no anchor attempted)')}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Signed, witnessed, timestamp-anchored "
                    "checkpoints for the LLM Wiki.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    ap.add_argument("--key", default=None,
                    help="signing key (default: ~/.ssh/id_ed25519_wiki_signing)")
    ap.add_argument("--witness-dir", default=None,
                    help="witness copy dir (default: ~/workspace/wikicitadel-checkpoints)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("create", help="write + sign a checkpoint")
    pc.add_argument("--note", default="")
    pa = sub.add_parser("anchor", help="attempt both timestamp anchors")
    pa.add_argument("--id", default=None)
    sub.add_parser("verify", help="verify chain, signatures, state, witness")
    sub.add_parser("show", help="list checkpoints + anchor labels")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    key = Path(args.key) if args.key else DEFAULT_KEY
    witness = Path(args.witness_dir) if args.witness_dir else DEFAULT_WITNESS
    if args.cmd == "create":
        return cmd_create(root, key, witness, args.note)
    if args.cmd == "anchor":
        return cmd_anchor(root, witness, args.id)
    if args.cmd == "verify":
        return cmd_verify(root, witness)
    return cmd_show(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
