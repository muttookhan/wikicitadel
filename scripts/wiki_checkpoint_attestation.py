#!/usr/bin/env python3
"""in-toto attestation for checkpoints — PILOT (Marathon R8,
Tier A; in-toto pattern, Apache-2.0 — PATTERN only, no
dependency, nothing imported from in-toto).

*** PILOT — additive only. *** This module does NOT change
the checkpoint format (evaluation/checkpoints.jsonl, scripts/
wiki_checkpoint.py) and does NOT invalidate, supersede or
re-interpret any existing checkpoint. It pilots the in-toto
shape BESIDE the checkpoint path: before a checkpoint is
taken over a build, the steps that produced its inputs can
carry an attestation chain a reviewer can verify.

The in-toto pattern, restated in this wiki's terms:

  LAYOUT  one JSON object naming, per step, WHICH agent may
          perform it (authorised_by), what the step consumes
          and produces by role (materials / products), and an
          expiry. The layout is signed by the layout signer:
          signature = HMAC-SHA256 over the canonical layout
          bytes. PILOT NOTE: HMAC with a shared pilot key is a
          stand-in for the checkpoint path's SSH signing — it
          proves the machinery's shape, it is NOT an identity
          guarantee, and the layout says so on its face.
  LINK    one JSON object per performed step: the agent that
          performed it, the sha256 of every material file and
          every product file (the chain from SOURCE hashes to
          COMPILED-PAGE hashes), and prev_link_hash — the
          sha256 of the previous link's canonical bytes — so
          the chain cannot be silently re-ordered or spliced.

  verify  recomputes everything: the layout signature, each
          link's step exists in the layout, the performing
          agent is authorised for that step, the link chain
          hashes link up, and every recorded material/product
          hash recomputes from the file on disk (under --root).

Usage:
  python3 scripts/wiki_checkpoint_attestation.py layout \
      --step ingest:agent-a,agent-b --step compile:agent-a \
      --expires YYYY-MM-DD --signer NAME --key-file F --out L.json
  python3 scripts/wiki_checkpoint_attestation.py link \
      --layout L.json --step compile --by agent-a \
      --material raw/sources/x.md --product wiki/concepts/x.md \
      [--prev-link LINK.json] [--root .] --out LINK.json
  python3 scripts/wiki_checkpoint_attestation.py verify \
      --layout L.json --key-file F --link LINK.json [...] [--root .]

Exit codes: verify 0 = chain verifies, 1 = a break,
2 = usage error. Stdlib only, no network.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path

PILOT_LABEL = "PILOT — in-toto pattern attestation; additive beside " \
              "the checkpoint register; not a checkpoint"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path) -> str:
    return sha256_hex(Path(path).read_bytes())


def build_layout(steps, signer, expires=""):
    """steps: {step_name: [authorised agent, ...]}. The layout
    body (unsigned); sign_layout adds the signature entry."""
    return {
        "kind": "intoto-layout",
        "pilot": PILOT_LABEL,
        "signature_scheme": "hmac-sha256 (pilot stand-in for the "
                            "checkpoint SSH key — shape, not identity)",
        "signer": signer,
        "expires": expires,
        "steps": [
            {"name": name,
             "authorised_by": sorted(agents),
             "expected_materials": [],
             "expected_products": []}
            for name, agents in sorted(steps.items())
        ],
    }


def sign_layout(layout, key: bytes):
    """A copy of `layout` carrying its HMAC signature entry."""
    out = {k: v for k, v in layout.items() if k != "signatures"}
    sig = hmac.new(key, canonical(out), hashlib.sha256).hexdigest()
    out["signatures"] = [{"signer": layout.get("signer", ""),
                          "scheme": "hmac-sha256",
                          "signature": sig}]
    return out


def verify_layout_signature(layout, key: bytes):
    sigs = layout.get("signatures") or []
    if not sigs:
        return ["layout carries no signature"]
    body = {k: v for k, v in layout.items() if k != "signatures"}
    want = hmac.new(key, canonical(body), hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(s.get("signature", ""), want)
               for s in sigs):
        return ["layout signature does not verify"]
    return []


def make_link(layout, step, by_agent, materials, products,
              prev_link=None, root="."):
    """One link for a performed step. materials / products are
    repo-relative paths hashed from disk under `root`; the
    link chains to prev_link (a link dict) by hash."""
    names = {s["name"]: s for s in layout.get("steps", [])}
    if step not in names:
        raise ValueError(f"step {step!r} is not in the layout")
    if by_agent not in names[step]["authorised_by"]:
        raise ValueError(
            f"agent {by_agent!r} is not authorised for step {step!r} "
            f"(authorised: {names[step]['authorised_by']})")
    root = Path(root)
    link = {
        "kind": "intoto-link",
        "pilot": PILOT_LABEL,
        "step": step,
        "by": by_agent,
        "materials": {p: file_hash(root / p) for p in materials},
        "products": {p: file_hash(root / p) for p in products},
        "prev_link_hash": sha256_hex(canonical(prev_link))
        if prev_link else None,
    }
    return link


def verify_chain(layout, links, root=".", key=None):
    """All problems with a layout + ordered link list ([] =
    the pilot chain verifies)."""
    problems = []
    if key is not None:
        problems += verify_layout_signature(layout, key)
    elif not (layout.get("signatures")):
        problems.append("layout carries no signature (and no key "
                        "was given to verify one against)")
    names = {s["name"]: s for s in layout.get("steps", [])}
    root = Path(root)
    prev = None
    for i, link in enumerate(links):
        step = link.get("step")
        if step not in names:
            problems.append(f"link {i}: step {step!r} not in the layout")
            continue
        if link.get("by") not in names[step]["authorised_by"]:
            problems.append(
                f"link {i} ({step}): performed by {link.get('by')!r}, "
                f"not authorised for this step")
        want_prev = sha256_hex(canonical(prev)) if prev else None
        if link.get("prev_link_hash") != want_prev:
            problems.append(f"link {i} ({step}): prev_link_hash does "
                            f"not chain to the previous link")
        for role in ("materials", "products"):
            for rel, want in (link.get(role) or {}).items():
                target = root / rel
                if not target.exists():
                    problems.append(f"link {i} ({step}): {role} file "
                                    f"missing: {rel}")
                elif file_hash(target) != want:
                    problems.append(f"link {i} ({step}): {role} hash "
                                    f"mismatch: {rel}")
        prev = link
    return problems


def _parse_step(spec):
    name, _, agents = spec.partition(":")
    return name.strip(), [a.strip() for a in agents.split(",") if a.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lay = sub.add_parser("layout")
    lay.add_argument("--step", action="append", required=True,
                     help="name:agent[,agent...] (repeatable)")
    lay.add_argument("--signer", required=True)
    lay.add_argument("--expires", default="")
    lay.add_argument("--key-file", required=True)
    lay.add_argument("--out", required=True)
    lnk = sub.add_parser("link")
    lnk.add_argument("--layout", required=True)
    lnk.add_argument("--step", required=True)
    lnk.add_argument("--by", required=True)
    lnk.add_argument("--material", action="append", default=[])
    lnk.add_argument("--product", action="append", default=[])
    lnk.add_argument("--prev-link", default=None)
    lnk.add_argument("--root", default=".")
    lnk.add_argument("--out", required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--layout", required=True)
    ver.add_argument("--key-file", default=None)
    ver.add_argument("--link", action="append", required=True)
    ver.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    if args.cmd == "layout":
        steps = {}
        for spec in args.step:
            name, agents = _parse_step(spec)
            steps[name] = agents
        key = Path(args.key_file).read_bytes()
        layout = sign_layout(
            build_layout(steps, args.signer, args.expires), key)
        Path(args.out).write_text(
            json.dumps(layout, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"pilot layout written: {args.out} "
              f"({len(steps)} step(s), signer {args.signer})")
        return 0
    if args.cmd == "link":
        layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
        prev = json.loads(Path(args.prev_link).read_text(
            encoding="utf-8")) if args.prev_link else None
        try:
            link = make_link(layout, args.step, args.by, args.material,
                             args.product, prev_link=prev, root=args.root)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        Path(args.out).write_text(
            json.dumps(link, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"pilot link written: {args.out} (step {args.step}, "
              f"by {args.by})")
        return 0
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    links = [json.loads(Path(p).read_text(encoding="utf-8"))
             for p in args.link]
    key = Path(args.key_file).read_bytes() if args.key_file else None
    problems = verify_chain(layout, links, root=args.root, key=key)
    print(json.dumps({"pilot": True, "ok": not problems,
                      "problems": problems}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
