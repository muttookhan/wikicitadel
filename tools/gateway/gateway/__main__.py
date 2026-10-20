"""Gateway CLI.

  python3 -m gateway serve                 MCP server on stdio
  python3 -m gateway issue <identity> --scopes wiki:read,wiki:propose
                                             Owner ceremony: issue/rotate a
                                             token (printed once; only the
                                             salted hash is stored, outside git)
  python3 -m gateway revoke <identity>       Revoke (next request fails)
  python3 -m gateway identities              List identities (no secrets)
  python3 -m gateway review <proposal_id> --reviewer agent [--decision-ref R]
                                             Write the review manifest
  python3 -m gateway reject <proposal_id> --by agent --reason "..."
                                             Reject a proposal; the reason is
                                             stored and fed into the next
                                             proposal for the same target
  python3 -m gateway authorise <proposal_id> --by owner [--decision-ref R]
                                             [--plan-sha256 H]
                                             The separate Owner act that arms
                                             a promotion (write-path gate);
                                             the record binds the SHA-256 of
                                             the staged plan it approves
  python3 -m gateway eval-override <proposal_id> --by owner --reason "..."
                                             The Owner act that overrides an
                                             eval-gate block for ONE proposal
                                             (the build). A reason is mandatory
                                             and is written to the eval-gate
                                             ledger; the override is single-use.
  python3 -m gateway verify [--ledger FILE]  Verify a Black Box chain
  python3 -m gateway anchor [--ledger FILE] [--out FILE]
                                             Record chain head for git commit
  python3 -m gateway metrics [--identity X]  Consultation report (§6)

issue/revoke are the Owner admin workflow (design §4.6).
In the reference deployment, activation proceeded under the owner's
directive: production issuance happens only under the production
environment (see wiki/access/identity-scopes.md); the agent
identity's token was the first production issuance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .ledger import anchor, read_entries, utcnow, verify_chain
from .metrics import compute_metrics, load_proposals
from .registry import Registry, RegistryError
from .server import serve
from .store import GatewayStore, StoreError


def _ledger_path(cfg: Config, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    return cfg.ledger_dir / f"black-box-{utcnow()[:4]}.jsonl"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gateway")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    p_issue = sub.add_parser("issue")
    p_issue.add_argument("identity")
    p_issue.add_argument("--scopes", default="wiki:read")
    p_issue.add_argument("--read-prefixes", default=None, help="comma-separated repo-relative prefixes")
    p_issue.add_argument("--source-prefixes", default=None, help="comma-separated raw/ prefixes")
    p_rev = sub.add_parser("revoke")
    p_rev.add_argument("identity")
    sub.add_parser("identities")
    p_review = sub.add_parser("review")
    p_review.add_argument("proposal_id")
    p_review.add_argument("--reviewer", required=True)
    p_review.add_argument("--decision-ref", default=None)
    p_rej = sub.add_parser("reject")
    p_rej.add_argument("proposal_id")
    p_rej.add_argument("--by", required=True)
    p_rej.add_argument("--reason", required=True)
    p_auth = sub.add_parser("authorise")
    p_auth.add_argument("proposal_id")
    p_auth.add_argument("--by", required=True)
    p_auth.add_argument("--decision-ref", default=None)
    p_auth.add_argument("--plan-sha256", default=None,
                        help="the plan hash the Owner was shown; refused if it "
                             "does not match the staged bytes")
    p_eo = sub.add_parser("eval-override")
    p_eo.add_argument("proposal_id")
    p_eo.add_argument("--by", required=True)
    p_eo.add_argument("--reason", required=True)
    p_ver = sub.add_parser("verify")
    p_ver.add_argument("--ledger", default=None)
    p_anc = sub.add_parser("anchor")
    p_anc.add_argument("--ledger", default=None)
    p_anc.add_argument("--out", default=None)
    p_met = sub.add_parser("metrics")
    p_met.add_argument("--identity", default=None)
    p_met.add_argument("--ledger", default=None)
    args = parser.parse_args(argv)

    cfg = Config()
    cfg.ensure_state_dirs()

    if args.cmd == "serve":
        return serve(cfg)
    if args.cmd == "issue":
        reg = Registry(cfg.registry_path)
        try:
            token = reg.issue(
                args.identity,
                [s.strip() for s in args.scopes.split(",") if s.strip()],
                read_prefixes=[s.strip() for s in args.read_prefixes.split(",")] if args.read_prefixes else None,
                source_prefixes=[s.strip() for s in args.source_prefixes.split(",")] if args.source_prefixes else None,
            )
        except RegistryError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps({"identity": args.identity, "token": token,
                          "warning": "shown once; only a salted hash is stored"}))
        return 0
    if args.cmd == "revoke":
        try:
            Registry(cfg.registry_path).revoke(args.identity)
        except RegistryError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps({"revoked": args.identity}))
        return 0
    if args.cmd == "identities":
        print(json.dumps(Registry(cfg.registry_path).list_identities(), indent=2))
        return 0
    if args.cmd == "review":
        store = GatewayStore(cfg)
        try:
            record = store.write_review(args.proposal_id, args.reviewer, args.decision_ref)
        except StoreError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(record, indent=2))
        return 0
    if args.cmd == "reject":
        store = GatewayStore(cfg)
        try:
            record = store.reject_proposal(args.proposal_id, args.by, args.reason)
        except StoreError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(record, indent=2))
        return 0
    if args.cmd == "authorise":
        store = GatewayStore(cfg)
        try:
            record = store.write_authorisation(
                args.proposal_id, args.by, args.decision_ref, args.plan_sha256)
        except StoreError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(record, indent=2))
        return 0
    if args.cmd == "eval-override":
        store = GatewayStore(cfg)
        try:
            record = store.write_eval_override(args.proposal_id, args.by, args.reason)
        except StoreError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(record, indent=2))
        return 0
    if args.cmd == "verify":
        result = verify_chain(_ledger_path(cfg, args.ledger))
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if args.cmd == "anchor":
        ledger_file = _ledger_path(cfg, args.ledger)
        out = Path(args.out) if args.out else cfg.anchors_dir / f"anchor-{ledger_file.stem}.json"
        try:
            record = anchor(ledger_file, out, cfg.wiki_root)
        except RuntimeError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps(record, indent=2))
        return 0
    if args.cmd == "metrics":
        entries = read_entries(_ledger_path(cfg, args.ledger))
        proposals = load_proposals(cfg.staging_dir)
        report = compute_metrics(entries, proposals)
        if args.identity:
            report = {"identities": {k: v for k, v in report["identities"].items() if k == args.identity}}
        print(json.dumps(report, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
