#!/usr/bin/env python3
"""Cross-agent handoff contract + fake-closure audit
(implementation wave 2026-10-22, wave 6; build-list item 67).

Pattern: the Round 7 deep-dive handoff contract, extending
the I-PASS handover shape this wiki already adopted as
governing rule 5 (wiki/rules/governing-rules.md — "Handover
completed by the receiver": Illness severity/state, Patient
summary, Action list, Situation awareness/contingency,
Synthesis by receiver). Clean re-implementation: the code
is ours; the only upstream named by the build list
(remembra-ai/remembra) contributed the idea, no code.

THE CONTRACT. A handoff is a record in the append-only
register evaluation/handoffs.jsonl, built FROM THE ARTEFACT,
not from the departing agent:

  {"kind": "handoff", "id": "ho-000001",
   "task": "...", "scope": "...",
   "from": "<sender>", "to": "<receiver>",
   "sender_claim": "done" | "partial" | "not-done",
   "sender_summary": "...",
   "artefacts": [{"path": "scripts/x.py",
                  "sha256": "<digest at define time>"}],
   "evidence": [{"rung": "repeatable-test",
                 "ref": "scripts/tests/test_x.py",
                 "note": "..."}],
   "gaps": ["..."],
   "declared_by": "sender" | "receiver" | "third-party",
   "receiver_synthesis": null |
     {"by": "...", "text": "...",
      "verdict": "accepted" | "accepted-with-findings"
                 | "rejected"}}

- `sender_claim` + `sender_summary` are CLAIMS to be
  checked, never facts. When the artefacts disagree with
  them, `check` labels the record `contradicted`.
- Evidence sits on the house ladder (copied verbatim from
  scripts/wiki_checkpoint_predicates.py; the two move
  together): agent-assertion < generated-summary
  < command-output < repeatable-test < independent-ci
  < independent-review < artifact-digest.
- Closure is DERIVED at check time, never stored: a
  handoff is closed only when the receiver's own synthesis
  is recorded (rule 5) and the artefact checks pass. A
  record carrying an asserted "status": "closed" field is
  flagged `closure-asserted-not-derived`.
- A handoff declared by its own sender (declared_by ==
  "sender") is PERMANENTLY labelled `self-declared` +
  `unchecked`: the labels record provenance — how the
  handoff entered the system — and no later verification
  removes them. The derived state is reported separately.

`define` validates a record's shape and computes artefact
digests from disk itself (a record that pre-claims a digest
must match, or define refuses — the claim is checked at
the door). `check` re-verifies every record against the
tree as it stands: completeness, rungs, artefact presence
and digests, claim-vs-fact contradictions, and the list of
handoffs still open (no receiver synthesis yet).

THE FAKE-CLOSURE AUDIT (`audit`) is report-only. It takes
the completion claims this system already keeps and
re-verifies each against the artefacts on disk, paths-only
style (governing rule 2). Claim sources:

  checkpoints            evaluation/checkpoints.jsonl —
                         each checkpoint's bindings: signed
                         message file present, git_head
                         resolves, git_tree equals that
                         commit's tree, provenance manifest
                         present with matching digest,
                         black-box file present.
  checkpoint-predicates  evaluation/checkpoint-predicates
                         .jsonl — ABSENT in this tree
                         tonight: reported as a named gap
                         with 0 claims, never as a pass.
  build-record           wiki/syntheses/implementation-
                         wave-2026-10-22.md — per item
                         section: the **Built:** bullet's
                         repo-relative paths exist, the
                         **Tests** bullet's test files
                         exist, the **Commits:** bullet's
                         private-tree hashes resolve in git.
                         (Public-tree claims are counted
                         out-of-scope, not checked here.)
  filings-ledgers        wiki/filings/*-filings.md —
                         frontmatter `sources:` paths and
                         body path references exist.
  close-history          evaluation/close-history.jsonl —
                         each close's filing exists, and
                         no register it snapshotted has
                         since SHRUNK below the snapshot
                         (registers are append-only; a
                         shrink is rewritten history).
  handoffs               this register — records closed
                         by a receiver synthesis (or
                         asserting closure) get their
                         artefacts re-verified.

The audit judges RECORDS, never intentions, and fixes
nothing. Output is deterministic: same tree + records ->
identical bytes (stable sort everywhere; the only state
anchor is the git HEAD the audit ran against).

Usage:
  python3 scripts/wiki_handoff.py template
  python3 scripts/wiki_handoff.py define RECORD.json [--json]
  python3 scripts/wiki_handoff.py check [--json]
  python3 scripts/wiki_handoff.py audit [--json]
                                        [--out PATH]

Exit codes: define/check/audit 0 = no findings,
1 = findings, 2 = usage error. Stdlib only; no network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/handoffs.jsonl"
AUDIT_REL = "evaluation/handoff-audit.json"
BUILD_RECORD_REL = "wiki/syntheses/implementation-wave-2026-10-22.md"

# The house evidence ladder, copied verbatim from
# scripts/wiki_checkpoint_predicates.py (the two move
# together).
LADDER = ["agent-assertion", "generated-summary", "command-output",
          "repeatable-test", "independent-ci", "independent-review",
          "artifact-digest"]

SENDER_CLAIMS = ["done", "partial", "not-done"]
DECLARED_BY = ["sender", "receiver", "third-party"]
VERDICTS = ["accepted", "accepted-with-findings", "rejected"]


def rung(name):
    return LADDER.index(name) if name in LADDER else -1


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path):
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            out.append(json.loads(ln))
    return out


def git(root: Path, *args):
    """(ok, stdout) — ok False when git or the object is
    unavailable; callers distinguish 'git missing' (None
    state) from 'object missing' via git_available()."""
    try:
        p = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return p.returncode == 0, p.stdout.strip()


def git_available(root: Path) -> bool:
    ok, _ = git(root, "rev-parse", "--git-dir")
    return bool(ok)


def tree_head(root: Path) -> str:
    ok, out = git(root, "rev-parse", "HEAD")
    return out if ok else "unknown"


# ----------------------------------------------------------------
# Contract shape validation (shared by define and check)

def shape_problems(rec: dict) -> list:
    """Structural problems with one handoff record (no disk
    access): missing/ill-formed fields, rungs off the
    ladder, verdicts off the closed set."""
    probs = []
    for field in ("task", "scope", "from", "to",
                  "sender_summary"):
        if not isinstance(rec.get(field), str) \
                or not rec[field].strip():
            probs.append(f"missing-field:{field}")
    if rec.get("sender_claim") not in SENDER_CLAIMS:
        probs.append("bad-value:sender_claim")
    if rec.get("declared_by") not in DECLARED_BY:
        probs.append("bad-value:declared_by")
    arts = rec.get("artefacts")
    if not isinstance(arts, list) or not arts:
        probs.append("missing-field:artefacts")
    else:
        for a in arts:
            p = a.get("path", "") if isinstance(a, dict) else ""
            if not p or p.startswith("/") or ".." in \
                    Path(p).parts:
                probs.append(f"bad-artefact-path:{p!r}")
    ev = rec.get("evidence")
    if not isinstance(ev, list):
        probs.append("missing-field:evidence")
    else:
        for e in ev:
            if not isinstance(e, dict) \
                    or rung(e.get("rung", "")) < 0:
                probs.append(
                    f"bad-rung:{(e or {}).get('rung')!r}")
            elif not (e.get("ref") or "").strip():
                probs.append("missing-field:evidence.ref")
    if not isinstance(rec.get("gaps"), list):
        probs.append("missing-field:gaps")
    syn = rec.get("receiver_synthesis")
    if syn is not None:
        if not isinstance(syn, dict) \
                or not (syn.get("text") or "").strip() \
                or not (syn.get("by") or "").strip():
            probs.append("missing-field:receiver_synthesis")
        elif syn.get("verdict") not in VERDICTS:
            probs.append("bad-value:synthesis.verdict")
    return probs


def provenance_labels(rec: dict) -> list:
    """Permanent provenance labels. `self-declared` +
    `unchecked` attach when the sender declared its own
    handoff, and are never removed by later verification —
    they record how the handoff entered the system."""
    labels = []
    if rec.get("declared_by") == "sender":
        labels += ["self-declared", "unchecked"]
    return labels


def check_record(root: Path, rec: dict) -> dict:
    """Full verification of one record against the tree:
    shape, artefact presence + digests, derived state."""
    findings = []
    for prob in shape_problems(rec):
        kind = prob.split(":", 1)[0]
        findings.append({"kind": kind, "detail": prob})
    art_results = []
    for a in rec.get("artefacts") or []:
        if not isinstance(a, dict):
            continue
        rel = a.get("path", "")
        p = root / rel
        if not p.is_file():
            findings.append({"kind": "artefact-missing",
                             "path": rel,
                             "detail": "claimed artefact "
                                       "not on disk"})
            art_results.append((rel, False))
            continue
        got = sha256_file(p)
        want = a.get("sha256")
        if want and got != want:
            findings.append({
                "kind": "hash-drifted", "path": rel,
                "detail": f"recorded {want[:16]}…, "
                          f"on disk {got[:16]}…"})
            art_results.append((rel, False))
        else:
            art_results.append((rel, True))
    syn = rec.get("receiver_synthesis")
    if rec.get("status") == "closed" and not syn:
        findings.append({
            "kind": "closure-asserted-not-derived",
            "detail": "record asserts status=closed with no "
                      "receiver synthesis; closure is "
                      "derived, never asserted"})
    facts_ok = all(ok for _, ok in art_results) \
        and not any(f["kind"] in ("artefact-missing",
                                  "hash-drifted")
                    for f in findings)
    contradicted = rec.get("sender_claim") == "done" and (
        not facts_ok
        or (isinstance(syn, dict)
            and syn.get("verdict") == "rejected"))
    if contradicted:
        findings.append({
            "kind": "claim-contradicted",
            "detail": "sender claimed 'done' but the "
                      "artefacts or the receiver's verdict "
                      "disagree"})
    if not syn:
        state = "open"
    elif contradicted:
        state = "contradicted"
    elif facts_ok:
        state = "closed"
    else:
        state = "closed-with-findings"
    return {"id": rec.get("id"),
            "labels": provenance_labels(rec),
            "derived_state": state,
            "findings": findings}


# ----------------------------------------------------------------
# define / check over the contract register

def load_register(root: Path):
    lines = load_jsonl(root / REGISTER_REL)
    header = None
    records = []
    for ln in lines:
        if ln.get("kind") == "header":
            header = ln
        elif ln.get("kind") == "handoff":
            records.append(ln)
    return header, records


def cmd_define(root: Path, record_path: Path) -> dict:
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    if rec.get("kind") not in (None, "handoff"):
        return {"ok": False,
                "error": "record kind must be 'handoff'"}
    rec["kind"] = "handoff"
    probs = shape_problems(rec)
    if probs:
        return {"ok": False, "problems": probs}
    # Digests are computed from disk by the tool — the
    # artefact speaks, not the agent. A pre-claimed digest
    # that disagrees refuses the record at the door.
    for a in rec["artefacts"]:
        p = root / a["path"]
        if not p.is_file():
            return {"ok": False,
                    "problems": [f"artefact-missing:{a['path']}"]}
        got = sha256_file(p)
        if a.get("sha256") and a["sha256"] != got:
            return {"ok": False,
                    "problems": [f"digest-claim-mismatch:"
                                 f"{a['path']}"]}
        a["sha256"] = got
    reg_path = root / REGISTER_REL
    header, records = load_register(root)
    if not reg_path.is_file():
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        header_line = {
            "kind": "header", "register": "handoffs",
            "version": 1,
            "purpose": "Cross-agent handoff contracts "
                       "(scripts/wiki_handoff.py): records "
                       "built from the artefact; closure is "
                       "derived by the checker, never "
                       "asserted. Append-only.",
            "ladder": LADDER}
        with reg_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(header_line) + "\n")
        header = header_line
    if not rec.get("id"):
        rec["id"] = f"ho-{len(records) + 1:06d}"
    with reg_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return {"ok": True, "id": rec["id"],
            "labels": provenance_labels(rec)}


def run_check(root: Path) -> dict:
    header, records = load_register(root)
    results = [check_record(root, r) for r in records]
    findings = []
    for res in results:
        for f in res["findings"]:
            findings.append(dict(f, record=res["id"]))
    return {"register": REGISTER_REL,
            "records": len(records),
            "open": [r["id"] for r in results
                     if r["derived_state"] == "open"],
            "states": {r["id"]: r["derived_state"]
                       for r in results},
            "labels": {r["id"]: r["labels"]
                       for r in results if r["labels"]},
            "findings": findings}


# ----------------------------------------------------------------
# Fake-closure audit — claim extraction per source.
# Every extractor returns (claims, findings, note):
# a claim is one verifiable assertion; a finding names the
# claim, the kind, and the evidence.

def F(source, claim, kind, detail, path=None):
    f = {"source": source, "claim": claim, "kind": kind,
         "detail": detail}
    if path:
        f["path"] = path
    return f


def audit_checkpoints(root: Path):
    claims = 0
    findings = []
    lines = [ln for ln in load_jsonl(root / "evaluation/checkpoints.jsonl")
             if ln.get("kind") == "checkpoint"]
    have_git = git_available(root)
    for cp in lines:
        cid = cp.get("id", "?")
        sig = (cp.get("signature") or {}).get("message_file")
        if sig:
            claims += 1
            if not (root / sig).is_file():
                findings.append(F(
                    "checkpoints", cid, "artefact-missing",
                    "signed message file not on disk", sig))
        head = cp.get("git_head")
        if head and have_git:
            claims += 1
            ok, _ = git(root, "cat-file", "-e",
                        f"{head}^{{commit}}")
            if not ok:
                findings.append(F(
                    "checkpoints", cid, "commit-unresolvable",
                    f"git_head {head[:12]}… not in the repo"))
            else:
                claims += 1
                ok2, tree = git(root, "show", "-s",
                                "--format=%T", head)
                if ok2 and cp.get("git_tree") \
                        and tree != cp["git_tree"]:
                    findings.append(F(
                        "checkpoints", cid, "hash-drifted",
                        f"recorded tree {cp['git_tree'][:12]}…, "
                        f"commit's tree {tree[:12]}…"))
        prov = cp.get("provenance") or {}
        man = prov.get("manifest")
        if man:
            claims += 1
            mp = root / man
            if not mp.is_file():
                findings.append(F(
                    "checkpoints", cid, "artefact-missing",
                    "provenance manifest not on disk", man))
            elif prov.get("manifest_sha256"):
                claims += 1
                got = sha256_file(mp)
                if got != prov["manifest_sha256"]:
                    findings.append(F(
                        "checkpoints", cid, "hash-drifted",
                        f"manifest digest recorded "
                        f"{prov['manifest_sha256'][:16]}…, on "
                        f"disk {got[:16]}… (the manifest is "
                        f"append-only, so growth moves this "
                        f"binding; stated, not smoothed)", man))
        bb = (cp.get("black_box") or {}).get("file")
        if bb:
            claims += 1
            if not (root / bb).is_file():
                findings.append(F(
                    "checkpoints", cid, "artefact-missing",
                    "black-box ledger file not on disk", bb))
    note = ("signed checkpoint register bindings re-verified "
            "against git and disk")
    if not have_git:
        note += "; git unavailable — commit claims skipped"
    return claims, findings, note


def audit_predicates(root: Path):
    reg = root / "evaluation/checkpoint-predicates.jsonl"
    if not reg.is_file():
        return 0, [], ("register evaluation/checkpoint-"
                       "predicates.jsonl does not exist in "
                       "this tree: the predicates tool is "
                       "present but no completion predicate "
                       "has ever been defined — 0 claims, "
                       "recorded as a gap, not a pass")
    lines = [ln for ln in load_jsonl(reg)
             if ln.get("kind") in (None, "predicate")]
    return len(lines), [], ("predicates register present; "
                            "condition-level evaluation is "
                            "wiki_checkpoint_predicates.py's "
                            "own check — counted here, not "
                            "duplicated")


BT = re.compile(r"`([^`]+)`")
PATH_TOKEN = re.compile(
    r"^(scripts|evaluation|tools|wiki|raw|templates|exports)/"
    r"[^\s]+$")


def _section_bullets(text: str):
    """Yield (section_title, {label: bullet_text})."""
    sections = re.split(r"^### ", text, flags=re.M)[1:]
    for sec in sections:
        title = sec.splitlines()[0].strip()
        bullets = {}
        cur = None
        for ln in sec.splitlines()[1:]:
            m = re.match(r"^- \*\*(.+?):\*\*\s*(.*)$", ln)
            if m:
                cur = m.group(1)
                bullets[cur] = m.group(2)
            elif cur and ln.startswith(("  ", "\t")):
                bullets[cur] += " " + ln.strip()
            elif ln.startswith("- "):
                cur = None
        yield title, bullets


def _find_test_file(root: Path, token: str):
    name = token if token.endswith(".py") else token + ".py"
    hits = sorted(p.relative_to(root).as_posix()
                  for p in root.rglob(name)
                  if ".git" not in p.parts)
    return hits[0] if hits else None


def audit_build_record(root: Path):
    claims = 0
    findings = []
    out_of_scope = 0
    path = root / BUILD_RECORD_REL
    if not path.is_file():
        return 0, [], "build record absent"
    text = path.read_text(encoding="utf-8")
    have_git = git_available(root)
    for title, bullets in _section_bullets(text):
        for label, body in bullets.items():
            tokens = BT.findall(body)
            if label == "Built":
                for tok in tokens:
                    if PATH_TOKEN.match(tok):
                        claims += 1
                        if not (root / tok).exists():
                            findings.append(F(
                                "build-record", title,
                                "artefact-missing",
                                "Built: path not on disk",
                                tok))
            elif label.startswith("Tests"):
                for tok in tokens:
                    if "/" in tok and tok.endswith(".py"):
                        claims += 1
                        if not (root / tok).is_file():
                            findings.append(F(
                                "build-record", title,
                                "test-artefact-absent",
                                "test file named in Tests: "
                                "not on disk", tok))
                    elif re.fullmatch(
                            r"test_[a-z0-9_]+(\.py)?", tok):
                        claims += 1
                        if not _find_test_file(root, tok):
                            findings.append(F(
                                "build-record", title,
                                "test-artefact-absent",
                                "test module named in Tests: "
                                "not found in the tree", tok))
            elif label == "Commits":
                for m in re.finditer(
                        r"private\s+`([0-9a-f]{7,40})`", body):
                    claims += 1
                    if have_git:
                        ok, _ = git(root, "cat-file", "-e",
                                    f"{m.group(1)}^{{commit}}")
                        if not ok:
                            findings.append(F(
                                "build-record", title,
                                "commit-unresolvable",
                                f"private commit "
                                f"{m.group(1)} not in the "
                                f"repo"))
                out_of_scope += len(re.findall(
                    r"WikiCitadel[^`]*`[0-9a-f]{7,40}`", body))
    note = ("per-item Built:/Tests:/Commits: claims "
            "re-verified paths-only against this tree")
    if out_of_scope:
        note += (f"; {out_of_scope} public-tree commit "
                 f"claim(s) counted out-of-scope (checked in "
                 f"the public tree's own record, not here)")
    return claims, findings, note


def audit_filings_ledgers(root: Path):
    claims = 0
    findings = []
    ledgers = sorted((root / "wiki" / "filings").glob(
        "*-filings.md"))
    for led in ledgers:
        name = led.relative_to(root).as_posix()
        text = led.read_text(encoding="utf-8")
        seen = set()
        fm = text.split("---", 2)[1] if text.startswith(
            "---") else ""
        for m in re.finditer(r"^\s+-\s+(raw/\S+)\s*$", fm,
                             flags=re.M):
            seen.add(m.group(1))
        for tok in BT.findall(text):
            if (tok.startswith(("raw/", "wiki/"))
                    and " " not in tok):
                seen.add(tok)
        for rel in sorted(seen):
            claims += 1
            if not (root / rel).exists():
                findings.append(F(
                    "filings-ledgers", name,
                    "artefact-missing",
                    "ledger names a path not on disk", rel))
    return claims, findings, ("filings ledgers' recorded "
                               "landing paths re-verified "
                               "against disk")


def audit_close_history(root: Path):
    claims = 0
    findings = []
    lines = [ln for ln in load_jsonl(
        root / "evaluation/close-history.jsonl")
        if ln.get("kind") == "close"]
    for i, ln in enumerate(lines):
        cid = f"{ln.get('date', '?')}#{i}"
        filing = ln.get("filing")
        if filing:
            claims += 1
            if not (root / filing).is_file():
                findings.append(F(
                    "close-history", cid, "artefact-missing",
                    "close filing not on disk", filing))
        for reg_name, snap in sorted(
                (ln.get("register_lines") or {}).items()):
            claims += 1
            rp = root / "evaluation" / reg_name
            now = 0
            if rp.is_file():
                now = sum(1 for x in rp.read_text(
                    encoding="utf-8").splitlines() if x.strip())
            if now < snap:
                findings.append(F(
                    "close-history", cid, "register-shrank",
                    f"register held {snap} lines at the "
                    f"close, holds {now} now — append-only "
                    f"history does not shrink",
                    f"evaluation/{reg_name}"))
    return claims, findings, ("periodic-close snapshots "
                               "re-verified: filings present, "
                               "no snapshotted register shrunk")


def audit_handoffs(root: Path):
    claims = 0
    findings = []
    _, records = load_register(root)
    for rec in records:
        syn = rec.get("receiver_synthesis")
        closed = isinstance(syn, dict) and syn.get(
            "verdict") in ("accepted",
                           "accepted-with-findings")
        if rec.get("status") == "closed" and not syn:
            claims += 1
            findings.append(F(
                "handoffs", rec.get("id", "?"),
                "closed-without-receiver-synthesis",
                "record asserts closure with no receiver "
                "synthesis (governing rule 5)"))
        if not closed:
            continue
        res = check_record(root, rec)
        for f in res["findings"]:
            if f["kind"] in ("artefact-missing",
                             "hash-drifted",
                             "claim-contradicted"):
                claims += 1
                findings.append(F(
                    "handoffs", rec.get("id", "?"), f["kind"],
                    f["detail"], f.get("path")))
    return claims, findings, ("handoff records closed by a "
                               "receiver synthesis re-verified "
                               "against their artefacts")


AUDIT_SOURCES = [
    ("checkpoints", audit_checkpoints),
    ("checkpoint-predicates", audit_predicates),
    ("build-record", audit_build_record),
    ("filings-ledgers", audit_filings_ledgers),
    ("close-history", audit_close_history),
    ("handoffs", audit_handoffs),
]


def run_audit(root: Path) -> dict:
    sources = {}
    findings = []
    total = 0
    for name, fn in AUDIT_SOURCES:
        claims, fnds, note = fn(root)
        sources[name] = {"claims": claims,
                         "findings": len(fnds), "note": note}
        total += claims
        findings.extend(fnds)
    findings.sort(key=lambda f: (f["source"], f["claim"],
                                 f["kind"],
                                 f.get("path", "")))
    by_kind = {}
    for f in findings:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    return {"kind": "handoff-audit", "version": 1,
            "tree_head": tree_head(root),
            "sources": sources,
            "claims_checked": total,
            "findings": findings,
            "summary": {"findings": len(findings),
                        "by_kind": by_kind}}


TEMPLATE = {
    "kind": "handoff",
    "task": "<the task as given>",
    "scope": "<the scope as given>",
    "from": "<sender>", "to": "<receiver>",
    "sender_claim": "done",
    "sender_summary": "<the departing agent's summary — a "
                      "claim to be checked, not a fact>",
    "artefacts": [{"path": "scripts/<artefact>.py"}],
    "evidence": [{"rung": "repeatable-test",
                  "ref": "scripts/tests/test_<artefact>.py",
                  "note": "<what the evidence shows>"}],
    "gaps": [],
    "declared_by": "sender",
    "receiver_synthesis": None,
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cross-agent handoff contract + "
                    "fake-closure audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("template")
    d = sub.add_parser("define")
    d.add_argument("record")
    d.add_argument("--json", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    a = sub.add_parser("audit")
    a.add_argument("--json", action="store_true")
    a.add_argument("--out", default=None,
                   help="write the report JSON here "
                        f"(default {AUDIT_REL}; '-' = stdout "
                        "only)")
    args = ap.parse_args(argv)

    if args.cmd == "template":
        print(json.dumps(TEMPLATE, indent=1))
        return 0
    if args.cmd == "define":
        res = cmd_define(ROOT, Path(args.record))
        print(json.dumps(res, indent=1) if args.json else
              ("defined " + res["id"] if res.get("ok")
               else "REFUSED: " + json.dumps(res)))
        return 0 if res.get("ok") else 1
    if args.cmd == "check":
        rep = run_check(ROOT)
        if args.json:
            print(json.dumps(rep, indent=1, sort_keys=True))
        else:
            print(f"handoffs: {rep['records']} record(s), "
                  f"open: {', '.join(rep['open']) or 'none'}")
            for rid, st in sorted(rep["states"].items()):
                lab = rep["labels"].get(rid, [])
                print(f"  {rid}: {st}"
                      + (f" [{', '.join(lab)}]" if lab
                         else ""))
            for f in rep["findings"]:
                print(f"  FINDING {f['record']} "
                      f"{f['kind']}: {f['detail']}")
            if not rep["findings"]:
                print("  no findings")
        return 1 if rep["findings"] else 0
    if args.cmd == "audit":
        rep = run_audit(ROOT)
        out = args.out if args.out is not None else AUDIT_REL
        if out != "-":
            op = ROOT / out
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(json.dumps(rep, indent=1,
                                     sort_keys=True) + "\n",
                          encoding="utf-8")
        if args.json:
            print(json.dumps(rep, indent=1, sort_keys=True))
        else:
            print(f"claims checked: {rep['claims_checked']}")
            for name, s in rep["sources"].items():
                print(f"  {name}: {s['claims']} claim(s), "
                      f"{s['findings']} finding(s) — "
                      f"{s['note']}")
            for f in rep["findings"]:
                print(f"  FINDING [{f['source']}] "
                      f"{f['claim']} {f['kind']}: "
                      f"{f['detail']}")
            print(f"findings: {rep['summary']['findings']} "
                  f"{rep['summary']['by_kind']}")
        return 1 if rep["findings"] else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
