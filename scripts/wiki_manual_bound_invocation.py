#!/usr/bin/env python3
"""Invocation tokens bound to the manual's hash (CyberClaw pattern, TA6).

A token is issued for an agent under a specific manual (AGENTS.md).
Token: ta6.<agent>.<issued-epoch>.<manual-sha256[:16]>.<hmac[:32]>
The HMAC (stdlib hmac/hashlib, key from --secret or env
WIKI_TOKEN_SECRET) covers agent|issued|manual-hash, so a token stops
verifying the moment the manual changes. LOCAL TEST ARTEFACTS ONLY:
no real credentials; the secret is a throwaway test value.
Commands: issue --agent A | verify --token T [--max-age-days N]
"""
from __future__ import annotations
import argparse, hashlib, hmac, os, sys, time
from pathlib import Path
def manual_hash(root: Path): return hashlib.sha256((root/"AGENTS.md").read_bytes()).hexdigest()
def _secret(ns): 
    s=ns.secret or os.environ.get("WIKI_TOKEN_SECRET")
    if not s: raise SystemExit("secret required (--secret or WIKI_TOKEN_SECRET); use a throwaway test value only")
    return s.encode()
def issue(root, agent, secret: bytes, now=None):
    issued=int(now if now is not None else time.time()); mh=manual_hash(root)
    msg=f"{agent}|{issued}|{mh}".encode(); sig=hmac.new(secret,msg,hashlib.sha256).hexdigest()[:32]
    return f"ta6.{agent}.{issued}.{mh[:16]}.{sig}"
def verify(root, token, secret: bytes, max_age_days=None, now=None):
    try: pre,agent,issued,mh,sig=token.split(".")
    except ValueError: return False,"malformed"
    if pre!="ta6": return False,"bad-prefix"
    cur=manual_hash(root)
    if mh!=cur[:16]: return False,"manual-changed"
    exp=hmac.new(secret,f"{agent}|{issued}|{cur}".encode(),hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(exp,sig): return False,"bad-signature"
    if max_age_days is not None:
        now=int(now if now is not None else time.time())
        if now-int(issued) > max_age_days*86400: return False,"expired"
    return True,"ok"
def main(argv=None):
    a=argparse.ArgumentParser(); sub=a.add_subparsers(dest="cmd",required=True)
    for n in ("issue","verify"):
        p=sub.add_parser(n); p.add_argument("--root",default="."); p.add_argument("--secret")
        if n=="issue": p.add_argument("--agent",required=True)
        else: p.add_argument("--token",required=True); p.add_argument("--max-age-days",type=int)
    ns=a.parse_args(argv); sec=_secret(ns)
    if ns.cmd=="issue": print(issue(Path(ns.root),ns.agent,sec)); return 0
    ok,why=verify(Path(ns.root),ns.token,sec,ns.max_age_days); print(why); return 0 if ok else 1
if __name__=="__main__": sys.exit(main())
