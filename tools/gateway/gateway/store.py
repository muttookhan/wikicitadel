"""Wiki store: reads, search, graph, decisions, staging, promotion.

The write path is the enforcement point (Addendum 4: review/promotion
is enforced by the gateway's write path itself, never by prompts):

- Agents can only write into the staging area via stage_proposal.
  There is no tool that writes canonical content directly.
- promote() physically cannot move a staged file into the wiki tree
  unless ALL of the following exist and agree:
    1. the caller holds the wiki:publish scope (checked by server
       and re-checked here),
    2. a review manifest whose recorded SHA-256 matches the staged
       file's current bytes (a tampered staged file fails),
    3. an owner authorisation record for this proposal — promotion
       is a separate Owner act (design §4.3). G5 targets (decisions,
       AGENTS.md, purpose.md, wiki/access/) additionally require the
       authorisation to carry an explicit Owner decision reference.
    4. the eval gate (the build): when armed (a baseline exists at
       evaluation/extended-baseline.json), the latest extended eval
       report must show no gated metric regressed beyond epsilon.
       A block is recorded in the eval-gate ledger; the only way
       past it is an explicit owner override record carrying a
       reason (write_eval_override) — never a silent pass.
- Promotion is one git-visible operation: with git_commit enabled it
  commits with Agent:/Session:/Sources:/Operation: trailers
  (Addendum 1) and returns the commit SHA for the Black Box entry.

Staging metadata may record submission provenance (submitted_by,
derived_from) — staging is not evidence; promotion strips it
(ai-engineering-spec §5.2). Machine-queue items are provenance-only
(ai-eng §5.3); agent proposals carry their content in staging only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from . import defense as defense_mod
from . import evalgate
from . import profile as profile_mod
from . import sanitize as sanitize_mod
from . import scopes
from . import trust as trust_mod
from .ledger import Ledger, utcnow

TOKEN_RE = re.compile(r"[a-z0-9]+")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
K1, B = 1.5, 0.75
MAX_SOURCE_BYTES = 2_000_000


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write-then-rename (harvest item 11; hardening pattern from
    flsteven87/your-llm-wiki-fl, MIT): the bytes land in a temp
    file in the SAME directory, are fsynced, then os.replace
    swaps them in — a crash mid-write can never leave a torn file
    at the target path, and no temp file survives a failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def tokenize(text: str):
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def page_title(text: str, fallback: str) -> str:
    m = re.search(r"^title:\s*\"?([^\"\n]+)\"?\s*$", text, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


class StoreError(Exception):
    pass


class NotFoundOrDenied(StoreError):
    """Single error for missing and out-of-scope objects (no leak)."""


class GatewayStore:
    def __init__(self, config):
        self.cfg = config
        self.root = config.wiki_root
        self.wiki = self.root / "wiki"
        self.raw = self.root / "raw"
        self.staging = config.staging_dir
        self.proposed = self.staging / "proposed"
        self.quarantine = self.staging / "quarantine"
        self.handoffs = self.staging / "handoffs"
        for d in (self.proposed, self.quarantine, self.handoffs):
            d.mkdir(parents=True, exist_ok=True)
        self.profile = profile_mod.load_profile(config.profile_path)

    # -- path safety --------------------------------------------------
    def _resolve(self, rel: str) -> Path:
        norm = scopes.normalise(rel)
        if norm is None:
            raise NotFoundOrDenied("not found or not available")
        path = (self.root / norm).resolve()
        if self.root not in path.parents and path != self.root:
            raise NotFoundOrDenied("not found or not available")
        return path

    # -- reads --------------------------------------------------------
    def read_page(self, rel: str) -> str:
        path = self._resolve(rel)
        if not path.is_file() or path.suffix != ".md":
            raise NotFoundOrDenied("not found or not available")
        return path.read_text(encoding="utf-8", errors="ignore")

    def read_source(self, rel: str) -> str:
        path = self._resolve(rel)
        if not path.is_file():
            raise NotFoundOrDenied("not found or not available")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise StoreError("source too large for gateway read")
        return path.read_text(encoding="utf-8", errors="ignore")

    def list_pages(self) -> list[str]:
        if not self.wiki.exists():
            return []
        return sorted(
            str(p.relative_to(self.root)) for p in self.wiki.rglob("*.md") if p.is_file()
        )

    # -- search (BM25, same formulation as scripts/wiki_search.py) ----
    def search(self, query: str, limit: int = 10, readable=None) -> list[dict]:
        terms = tokenize(query)
        docs = []
        for rel in self.list_pages():
            if readable is not None and not readable(rel):
                continue
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            docs.append((rel, text))
        if not docs or not terms:
            return []
        tf = []
        df = Counter()
        lengths = []
        for rel, text in docs:
            counts = Counter(tokenize(text))
            tf.append(counts)
            lengths.append(sum(counts.values()))
            for t in set(counts):
                df[t] += 1
        n = len(docs)
        avgdl = (sum(lengths) / n) if n else 0.0
        results = []
        for i, (rel, text) in enumerate(docs):
            score = 0.0
            for t in terms:
                f = tf[i].get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                denom = f + K1 * (1 - B + B * (lengths[i] / avgdl if avgdl else 1))
                score += idf * (f * (K1 + 1)) / denom
            if score > 0:
                results.append(
                    {
                        "page_id": rel,
                        "title": page_title(text, Path(rel).stem),
                        "score": round(score, 4),
                        "snippet": self._snippet(text, terms),
                    }
                )
        results.sort(key=lambda r: -r["score"])
        return results[:limit]

    @staticmethod
    def _snippet(text: str, terms, width: int = 170) -> str:
        low = text.lower()
        best = None
        for t in terms:
            idx = low.find(t)
            if idx >= 0 and (best is None or idx < best):
                best = idx
        if best is None:
            return text[:width].replace("\n", " ").strip()
        start = max(0, best - 40)
        return text[start:start + width].replace("\n", " ").strip()

    # -- graph ----------------------------------------------------------
    def graph_neighbors(self, rel: str) -> dict:
        text = self.read_page(rel)
        by_stem: dict[str, list[str]] = {}
        for p in self.list_pages():
            by_stem.setdefault(Path(p).stem, []).append(p)
            by_stem.setdefault(p[:-3], []).append(p)  # path without .md
        outbound = []
        for target in LINK_RE.findall(text):
            cands = by_stem.get(target.strip()) or by_stem.get(Path(target.strip()).name)
            if cands:
                outbound.extend(cands)
        inbound = []
        stem = Path(rel).stem
        for p in self.list_pages():
            if p == rel:
                continue
            body = (self.root / p).read_text(encoding="utf-8", errors="ignore")
            for target in LINK_RE.findall(body):
                if Path(target.strip()).name == stem or target.strip() == rel[:-3]:
                    inbound.append(p)
                    break
        return {"page_id": rel, "outbound": sorted(set(outbound)), "inbound": sorted(set(inbound))}

    # -- decisions ------------------------------------------------------
    def _decision_meta(self, path: Path) -> dict:
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta = {"page_id": str(path.relative_to(self.root)), "title": page_title(text, path.stem)}
        fm = re.match(r"^---\n(.*?)\n---", text, re.S)
        if fm:
            for key in ("id", "status", "decided_by", "decided_at"):
                m = re.search(rf"^{key}:\s*(.+)$", fm.group(1), re.M)
                if m:
                    meta[key] = m.group(1).strip().strip('"')
        meta.setdefault("id", path.stem)
        return meta

    def list_decisions(self) -> list[dict]:
        d = self.wiki / "decisions"
        if not d.exists():
            return []
        return [self._decision_meta(p) for p in sorted(d.glob("*.md"))]

    def get_decision(self, decision_id: str) -> dict:
        for meta in self.list_decisions():
            if meta["id"] == decision_id or Path(meta["page_id"]).stem == decision_id:
                return {"meta": meta, "text": self.read_page(meta["page_id"])}
        raise NotFoundOrDenied("not found or not available")

    # -- lint (read-only report) ---------------------------------------
    def lint_run(self) -> dict:
        pages = self.list_pages()
        by_stem: dict[str, list[str]] = {}
        for p in pages:
            by_stem.setdefault(Path(p).stem, []).append(p)
            by_stem.setdefault(p[:-3], []).append(p)
        broken = []
        for p in pages:
            body = (self.root / p).read_text(encoding="utf-8", errors="ignore")
            body = re.sub(r"```.*?```", "", body, flags=re.S)
            body = re.sub(r"`[^`\n]*`", "", body)
            for target in LINK_RE.findall(body):
                t = target.strip()
                if not (by_stem.get(t) or by_stem.get(Path(t).name)):
                    broken.append({"page": p, "target": t})
        return {"pages": len(pages), "broken_links": broken, "broken_count": len(broken)}

    # -- staging --------------------------------------------------------
    def _proposal_paths(self, proposal_id: str) -> tuple[Path, Path]:
        return (
            self.proposed / f"{proposal_id}.md",
            self.proposed / f"{proposal_id}.json",
        )

    def stage_proposal(self, *, actor: str, session_id: str, target_path: str,
                       content: str, cites: list[str], direction_source: dict,
                       task_ref: str | None) -> dict:
        norm = scopes.normalise(target_path)
        allowed = (
            norm is not None
            and norm.endswith(".md")
            and (scopes.classify(norm) in ("wiki", "decision") or norm in ("AGENTS.md", "purpose.md"))
        )
        if not allowed:
            raise StoreError("proposal target must be a wiki page path (wiki/**/*.md) or a G5 schema file")
        # Rejection feedback (harvest item 8): earlier rejections
        # of proposals for THIS target ride into the new proposal's
        # meta, so whoever compiles the next attempt — and whoever
        # reviews it — sees why the last ones were refused.
        prior_rejections = [
            {"proposal_id": m["proposal_id"],
             "by": (m.get("rejection") or {}).get("by"),
             "reason": (m.get("rejection") or {}).get("reason"),
             "at": (m.get("rejection") or {}).get("at")}
            for m in self.list_proposals(state="rejected")
            if m.get("target_path") == norm
        ]
        # Lifecycle profile check (harvest item 7): the staged
        # content is checked against the profile, judged against
        # the page currently at the target. warn-legacy (default)
        # records violations in the proposal meta and stages
        # anyway; enforce refuses the write here, on the path.
        profile_check = None
        if self.profile is not None:
            fields = profile_mod.frontmatter_of(content)
            current_fields = None
            target_file = self.root / norm
            if target_file.is_file():
                current_fields = profile_mod.frontmatter_of(
                    target_file.read_text(encoding="utf-8", errors="ignore"))
            violations = profile_mod.violations_for(
                self.profile, fields, current_fields,
                assume_version=self.profile.get("schema_version"))
            profile_check = {
                "profile": self.profile.get("name"),
                "mode": self.profile.get("mode", "warn-legacy"),
                "violations": violations,
            }
            # Grandfathered (warn-severity) violations never refuse
            # a write, even in enforce mode — that is what
            # grandfathering means (Phase-2 item 5).
            hard = [v for v in violations if v.get("severity") != "warn"]
            if hard and profile_check["mode"] == "enforce":
                raise StoreError(
                    "proposal refused by lifecycle profile "
                    f"({self.profile.get('name')}): "
                    + "; ".join(v["detail"] for v in hard))
        # Prompt-injection defence (Phase-2 harvest item 1;
        # pattern: NicoBleh/secure-llm-wiki, MIT): the staged
        # content is scanned on the write path. Staged bytes are
        # NEVER altered (review hashes must keep their meaning),
        # but a blocked verdict — an instruction pattern, a hidden
        # instruction, a base64-smuggled payload — quarantines the
        # proposal on the spot: it is recorded, visible in the
        # listing, and can never be promoted. Trust tiers are
        # assessed from the citations with weakest-link
        # propagation and ride in the meta.
        #
        # Memory Defense (2026-10-19; pattern adapted from
        # Hindsight's Memory Defense, vectorize-io/hindsight,
        # MIT) runs at the same choke point: the staged content is
        # scanned for secrets and PII (defense.scan_secrets). The
        # sanitiser stops instructions-bearing data; this scan
        # stops credentials-bearing data. A hit blocks the same
        # way — quarantine, never silent redaction — and the meta
        # records pattern CLASSES and counts only: the matched
        # value is never copied anywhere (the ledger rule).
        sanitiser = sanitize_mod.scan_text(content)
        defense = defense_mod.scan_secrets(content)
        trust = trust_mod.assess(cites)
        proposal_id = "prop-" + secrets.token_hex(4)
        content_bytes = content.encode("utf-8")
        md_path, meta_path = self._proposal_paths(proposal_id)
        blocked = (sanitiser["verdict"] == "blocked"
                   or defense["verdict"] == "blocked")
        if blocked:
            md_path = self.quarantine / md_path.name
            meta_path = self.quarantine / meta_path.name
        atomic_write_bytes(md_path, content_bytes)
        meta = {
            "proposal_id": proposal_id,
            "state": "quarantined" if blocked else "draft",
            "submitted_by": actor,
            "session_id": session_id,
            "task_ref": task_ref,
            "direction_source": direction_source,
            "target_path": norm,
            "sha256": sha256_bytes(content_bytes),
            "bytes": len(content_bytes),
            "cites": list(cites or []),
            "submitted_at": utcnow(),
            "profile_check": profile_check,
            "prior_rejections": prior_rejections,
            "sanitiser": sanitiser,
            "defense": defense,
            "trust": trust,
        }
        if blocked:
            reasons = []
            if sanitiser["verdict"] == "blocked":
                kinds = sorted({f["kind"] for f in sanitiser["findings"]})
                reasons.append(
                    "sanitiser blocked the staged content "
                    f"({', '.join(kinds)}): untrusted content does not "
                    "enter the wiki as instructions-bearing data")
            if defense["verdict"] == "blocked":
                classes = sorted({f["pattern"] for f in defense["findings"]})
                reasons.append(
                    "secret scan blocked the staged content "
                    f"(pattern class: {', '.join(classes)}): secrets "
                    "and PII do not enter the wiki")
            meta["quarantine_reason"] = "; ".join(reasons)
        atomic_write_bytes(meta_path, (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return meta

    def get_proposal(self, proposal_id: str) -> dict:
        _, meta_path = self._proposal_paths(proposal_id)
        if not meta_path.exists():
            q = self.quarantine / f"{proposal_id}.json"
            if q.exists():
                return json.loads(q.read_text(encoding="utf-8"))
            raise NotFoundOrDenied("not found or not available")
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def list_proposals(self, state: str | None = None) -> list[dict]:
        """The staging listing: every proposal meta (proposed +
        quarantine), newest first, optionally filtered by state.
        Rejected proposals stay listed with their rejection record
        — the listing IS the feedback surface (harvest item 8)."""
        metas = []
        for d in (self.proposed, self.quarantine):
            for p in sorted(d.glob("*.json")):
                try:
                    metas.append(json.loads(p.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        metas.sort(key=lambda m: m.get("submitted_at", ""), reverse=True)
        if state is not None:
            metas = [m for m in metas if m.get("state") == state]
        return metas

    def reject_proposal(self, proposal_id: str, actor: str, reason: str) -> dict:
        """Record a rejection WITH its reason (harvest item 8;
        pattern from kytmanov/synto + obsidian-llm-wiki-local,
        MIT: rejection reasons are stored and fed into the next
        compile). The reason is mandatory — a bare 'no' teaches
        the next attempt nothing. The proposal's bytes stay in
        staging as the record of what was refused and why."""
        if not reason or not reason.strip():
            raise StoreError("rejection requires a reason")
        meta = self.get_proposal(proposal_id)
        if meta["state"] in ("promoted", "quarantined", "rejected"):
            raise StoreError(f"proposal is {meta['state']}; it cannot be rejected")
        meta["state"] = "rejected"
        meta["rejection"] = {"by": actor, "reason": reason.strip(),
                             "at": utcnow()}
        self._save_proposal(meta)
        return meta

    def _save_proposal(self, meta: dict) -> None:
        _, meta_path = self._proposal_paths(meta["proposal_id"])
        # A quarantined proposal's meta lives beside its bytes in
        # the quarantine dir (sanitiser blocks and tamper moves both
        # land there); never resurrect a copy into proposed/.
        q_meta = self.quarantine / meta_path.name
        q_md = self.quarantine / f"{meta['proposal_id']}.md"
        if q_meta.exists() or q_md.exists():
            meta_path = q_meta
        atomic_write_bytes(meta_path, (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    # -- review + owner authorisation (state dir, outside git) ---------
    def write_review(self, proposal_id: str, reviewer: str, decision_ref: str | None) -> dict:
        meta = self.get_proposal(proposal_id)
        # Review separation (Phase-2 harvest item 1; the 4-eyes
        # rule from NicoBleh/secure-llm-wiki, MIT): the reviewer
        # must be a different identity from the proposer. A
        # self-review is not a review. Enforced again at promotion
        # (below), so a manifest written by any path is checked.
        if reviewer and reviewer == meta.get("submitted_by"):
            raise StoreError(
                "review refused: reviewer must differ from the proposer "
                "(review separation)")
        md_path, _ = self._proposal_paths(proposal_id)
        manifest = {
            "proposal_id": proposal_id,
            "reviewer": reviewer,
            "decision_ref": decision_ref,
            "staged_sha256": sha256_bytes(md_path.read_bytes()),
            "target_path": meta["target_path"],
            "reviewed_at": utcnow(),
        }
        out = self.cfg.reviews_dir / f"{proposal_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(out, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        meta["state"] = "under_review"
        self._save_proposal(meta)
        return manifest

    def write_authorisation(self, proposal_id: str, authorised_by: str,
                            decision_ref: str | None,
                            plan_sha256: str | None = None) -> dict:
        """The Owner act that arms a promotion — now PLAN-HASH BOUND
        (harvest item 6; pattern from AgriciDaniel/claude-obsidian,
        MIT: a mutating command is applied only with the exact
        --approved-plan-sha256). The record carries the SHA-256 of
        the staged plan as it stands at authorisation time; if the
        caller supplies the hash they were shown, it must match the
        staged bytes or nothing is written. Promotion re-checks
        the binding, so an approval can never be spent on a plan
        other than the one that was approved."""
        md_path, _ = self._proposal_paths(proposal_id)
        if not md_path.exists():
            raise StoreError(
                f"authorisation refused: no staged plan for {proposal_id}")
        current = sha256_bytes(md_path.read_bytes())
        if plan_sha256 is not None and plan_sha256 != current:
            raise StoreError(
                "authorisation refused: plan hash does not match the "
                "staged proposal — the plan changed since it was shown")
        record = {
            "proposal_id": proposal_id,
            "authorised_by": authorised_by,
            "decision_ref": decision_ref,
            "plan_sha256": current,
            "authorised_at": utcnow(),
        }
        out = self.cfg.authorisations_dir / f"{proposal_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(out, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return record

    # -- eval gate (the build) -------------------------------------------
    def _gate_ledger(self) -> Ledger:
        if getattr(self, "_eval_ledger", None) is None:
            path = self.cfg.ledger_dir / f"eval-gate-{utcnow()[:4]}.jsonl"
            self._eval_ledger = Ledger(path, id_prefix="eg", wiki_root=self.root)
        return self._eval_ledger

    def _log_gate_event(self, fields: dict) -> None:
        """Gate events land in their own hash-chained ledger beside
        the Black Box: blocks and overrides must be auditable even
        when no promotion (and so no Black Box promote entry with
        a commit) follows from them."""
        try:
            self._gate_ledger().append(fields)
        except Exception:
            pass  # the gate's verdict never depends on its own log write

    def _read_eval_override(self, proposal_id: str) -> dict | None:
        path = self.cfg.eval_overrides_dir / f"{proposal_id}.json"
        if not path.exists():
            return None
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if rec.get("used_at"):
            return None  # an override is spent once; re-override explicitly
        if not (rec.get("reason") or "").strip():
            return None
        return rec

    def write_eval_override(self, proposal_id: str, overridden_by: str,
                            reason: str) -> dict:
        """The Owner act that overrides an eval-gate block for ONE
        proposal. A reason is mandatory — an override without one
        is exactly the silent pass this gate exists to prevent.
        The act is written twice: the record the gate reads (state
        dir, outside git) and an entry in the eval-gate ledger.
        Single-use: promotion marks it used, so a second blocked
        promotion needs a fresh, explicit override."""
        if not reason or not reason.strip():
            raise StoreError("eval override requires a reason")
        gate = evalgate.check(self.root, report_path=self.cfg.eval_report_path,
                              baseline_path=self.cfg.eval_baseline_path)
        record = {
            "proposal_id": proposal_id,
            "overridden_by": overridden_by,
            "reason": reason.strip(),
            "overridden_at": utcnow(),
            "gate_reasons_overridden": gate.get("reasons") or [],
            "gate_metrics": gate.get("metrics") or {},
            "gate_baseline": gate.get("baseline") or {},
            "used_at": None,
        }
        out = self.cfg.eval_overrides_dir / f"{proposal_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(out, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        self._log_gate_event({
            "actor": overridden_by, "action": "eval_gate_override",
            "proposal_id": proposal_id, "reason": record["reason"],
            "gate_reasons_overridden": record["gate_reasons_overridden"],
            "result": "recorded",
        })
        return record

    def _eval_gate_or_block(self, proposal_id: str, actor: str,
                            meta: dict) -> None:
        """The promotion precondition. Raises StoreError on a block
        with no live override; records pass/override into `meta`
        (saved with the proposal by promote()) and the gate ledger."""
        gate = evalgate.check(self.root, report_path=self.cfg.eval_report_path,
                              baseline_path=self.cfg.eval_baseline_path)
        if gate["status"] == "not_armed":
            return
        if gate["status"] == "pass":
            meta["eval_gate"] = {
                "status": "pass",
                "report_generated_at": gate.get("report_generated_at"),
                "metrics": gate.get("metrics"),
            }
            return
        override = self._read_eval_override(proposal_id)
        if override is None:
            self._log_gate_event({
                "actor": actor, "action": "eval_gate_block",
                "proposal_id": proposal_id,
                "reasons": gate["reasons"],
                "guidance": gate.get("guidance") or [],
                "metrics": gate.get("metrics"), "baseline": gate.get("baseline"),
                "result": "block",
            })
            coaching = gate.get("guidance") or []
            raise StoreError(
                "promotion refused: eval gate — "
                + "; ".join(gate["reasons"])
                + " (an owner eval override with a recorded reason is the only way past)"
                + ((" Coaching — what would change the verdict: "
                    + " ".join(coaching)) if coaching else ""))
        override["used_at"] = utcnow()
        out = self.cfg.eval_overrides_dir / f"{proposal_id}.json"
        atomic_write_bytes(out, (json.dumps(override, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        meta["eval_gate"] = {"status": "override", "override": override}
        self._log_gate_event({
            "actor": actor, "action": "eval_gate_override_used",
            "proposal_id": proposal_id,
            "overridden_by": override.get("overridden_by"),
            "reason": override.get("reason"),
            "gate_reasons_overridden": gate["reasons"],
            "result": "allow",
        })

    # -- promotion: the write path --------------------------------------
    def promote(self, proposal_id: str, actor_entry: dict,
                expected_target_etag=...) -> dict:
        """Promote a staged proposal. `expected_target_etag` is the
        etag optimistic-concurrency precondition (harvest item 11):
        the default Ellipsis means 'not supplied — no check'; a
        string requires the target to still hash to it; None
        requires the target to still be absent."""
        """Move a staged proposal into the wiki tree. Refuses unless
        scope, review-manifest hash agreement, and an owner
        authorisation record all check out — in code, not by prompt."""
        actor = actor_entry["identity"]
        if not scopes.can_publish(actor_entry):
            raise StoreError("promotion requires the wiki:publish scope")
        meta = self.get_proposal(proposal_id)
        if meta["state"] == "promoted":
            raise StoreError("proposal already promoted")
        if meta["state"] == "quarantined":
            raise StoreError("proposal is quarantined; promotion impossible")
        md_path, _ = self._proposal_paths(proposal_id)

        review_path = self.cfg.reviews_dir / f"{proposal_id}.json"
        if not review_path.exists():
            raise StoreError("promotion refused: no review manifest (write-path gate)")
        manifest = json.loads(review_path.read_text(encoding="utf-8"))
        # Review separation, re-checked on the write path itself:
        # whatever route a manifest took to disk, a promotion whose
        # reviewer IS the proposer does not proceed.
        if manifest.get("reviewer") and \
                manifest["reviewer"] == meta.get("submitted_by"):
            raise StoreError("promotion refused: reviewer is the proposer (review separation violated)")
        current_sha = sha256_bytes(md_path.read_bytes())
        if manifest.get("staged_sha256") != current_sha:
            meta["state"] = "quarantined"
            meta["quarantine_reason"] = "staged bytes changed after review; hash mismatch"
            self._save_proposal(meta)
            _, meta_path = self._proposal_paths(proposal_id)
            md_path.rename(self.quarantine / md_path.name)
            meta_path.rename(self.quarantine / meta_path.name)
            raise StoreError("promotion refused: staged file changed after review (hash mismatch); quarantined")

        auth_path = self.cfg.authorisations_dir / f"{proposal_id}.json"
        if not auth_path.exists():
            raise StoreError("promotion refused: no owner authorisation record (promotion is a separate Owner act)")
        authorisation = json.loads(auth_path.read_text(encoding="utf-8"))
        # Plan-hash binding (harvest item 6): the authorisation must
        # name the exact staged bytes it approved. A record without
        # a hash predates the binding and fails closed — the Owner
        # re-authorises the current plan.
        if not authorisation.get("plan_sha256"):
            raise StoreError("promotion refused: authorisation carries no plan hash (predates plan-hash binding); re-authorise the current plan")
        if authorisation["plan_sha256"] != current_sha:
            raise StoreError("promotion refused: staged plan changed after authorisation (plan hash mismatch)")
        if scopes.is_gate5_target(meta["target_path"]) and not authorisation.get("decision_ref"):
            raise StoreError("promotion refused: G5 target requires an Owner decision reference")

        # Eval gate (the build): the extended eval must not have
        # regressed past epsilon vs its recorded baseline. Checked
        # after every identity/record gate, before any bytes move.
        self._eval_gate_or_block(proposal_id, actor, meta)

        # Etag optimistic concurrency (harvest item 11): when the
        # promoter supplies the etag of the target as they read it,
        # the write proceeds only if the target is still exactly
        # those bytes (or still absent, etag null). A mismatch
        # means someone else wrote first — refuse rather than
        # silently overwrite their change.
        target = self._resolve(meta["target_path"])
        if expected_target_etag is not ...:
            current_etag = (sha256_bytes(target.read_bytes())
                            if target.is_file() else None)
            if current_etag != expected_target_etag:
                raise StoreError("promotion refused: target changed since it was read (etag mismatch)")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, md_path.read_bytes())

        commit_sha = None
        if self.cfg.git_commit:
            commit_sha = self._git_commit_promotion(meta, actor)

        meta["state"] = "promoted"
        meta["promoted_by"] = actor
        meta["promoted_at"] = utcnow()
        meta["review_manifest"] = manifest
        meta["authorisation"] = authorisation
        if commit_sha:
            meta["commit_sha"] = commit_sha
        self._save_proposal(meta)
        return {"proposal": meta, "commit_sha": commit_sha}

    def _git_commit_promotion(self, meta: dict, actor: str) -> str | None:
        root = str(self.root)
        rel = meta["target_path"]

        def one_line(value) -> str:
            # Audit L4: every client-supplied value composed into
            # this message is flattened to a single line — a newline
            # in session_id, a citation, or the target path could
            # otherwise forge extra commit trailers (fake Agent: or
            # Operation: lines) in an owner-trusted record.
            flat = " ".join(str(value).splitlines()).strip()
            return flat or "-"

        pid = one_line(meta["proposal_id"])
        sources = ", ".join(one_line(c) for c in (meta.get("cites") or [])) \
            or "none-declared"
        msg = (
            f"Promote {pid} -> {one_line(rel)}\n\n"
            f"Agent: {one_line(meta['submitted_by'])}\n"
            f"Session: {one_line(meta['session_id'])}\n"
            f"Sources: {sources}\n"
            f"Operation: promote {pid}\n"
        )
        env_name = f"Gateway Promotion ({actor})"
        cmds = [
            ["git", "-C", root, "add", "--", rel],
            ["git", "-C", root, "-c", f"user.name={env_name}",
             "-c", "user.email=gateway@localhost", "commit", "-q", "-m", msg, "--", rel],
            ["git", "-C", root, "rev-parse", "HEAD"],
        ]
        try:
            for cmd in cmds:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if out.returncode != 0:
                    return None
            return out.stdout.strip()
        except Exception:
            return None

    # -- handoffs ---------------------------------------------------------
    def create_handoff(self, *, actor: str, session_id: str, summary: str,
                       context_pages: list[str], direction_source: dict) -> dict:
        handoff_id = "handoff-" + secrets.token_hex(4)
        record = {
            "handoff_id": handoff_id,
            "created_by": actor,
            "session_id": session_id,
            "summary": summary,
            "context_pages": list(context_pages or []),
            "direction_source": direction_source,
            "created_at": utcnow(),
        }
        atomic_write_bytes(self.handoffs / f"{handoff_id}.json",
                           (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return record
