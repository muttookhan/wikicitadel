"""MCP gateway server — JSON-RPC 2.0 over stdio (newline-delimited).

Transport note: stdio is the core-build transport. The production
transport (HTTP shape, hosting) is an owner gate decision (design
§10); the tool/scope/ledger semantics here are transport-independent.

Implements design §4.6:
- identity is resolved from the bearer token on EVERY request and
  revocation/scope are re-checked per request (step 4);
- default-deny for unclassified/sensitive material;
- contributions arrive as staging proposals, never canonical writes;
- every action — allowed, denied, or errored — appends a Black Box
  entry; denied reads are indistinguishable from missing objects to
  the caller (existence is never leaked);
- search entries record result page IDs, a query length and a query
  hash — never the query text (design §5.3).

Auth carriage: clients send the bearer token in
params._meta.authorization ("Bearer <token>") per request, or once
in initialize params._meta.authorization (session token). Per-request
tokens take precedence and are re-validated every time.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from . import scopes
from .config import Config
from .ledger import Ledger, read_entries, utcnow
from .registry import Registry
from .store import GatewayStore, NotFoundOrDenied, StoreError

TOOLS = [
    {"name": "wiki_whoami", "description": "Return the caller's server-resolved identity and scopes.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "wiki_search",
     "description": "Search the wiki BEFORE starting work; cite only pages you have actually read (consultation is measured).",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]}},
    {"name": "wiki_read_page", "description": "Read one wiki page by repo-relative path.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "wiki_read_source", "description": "Read one raw source (scope-checked).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "wiki_graph_neighbors", "description": "Wikilink neighbours (inbound/outbound) of a page.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "wiki_list_decisions", "description": "List the decisions register.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "wiki_get_decision", "description": "Read one decision by id.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "wiki_stage_proposal",
     "description": "Stage a proposal (the ONLY write available to agents). Never cite a page you have not read in this session.",
     "inputSchema": {"type": "object", "properties": {
         "target_path": {"type": "string"}, "content": {"type": "string"},
         "cites": {"type": "array", "items": {"type": "string"}}},
         "required": ["target_path", "content"]}},
    {"name": "wiki_get_proposal_status", "description": "Status of a staged proposal.",
     "inputSchema": {"type": "object", "properties": {"proposal_id": {"type": "string"}}, "required": ["proposal_id"]}},
    {"name": "wiki_list_proposals",
     "description": "The staging listing: proposals (your own, unless you hold publish/admin), optionally filtered by state. Rejected proposals carry their rejection reasons.",
     "inputSchema": {"type": "object", "properties": {"state": {"type": "string"}}}},
    {"name": "wiki_reject_proposal",
     "description": "Reject a staged proposal (publish scope). A reason is mandatory: it is stored and fed into the next proposal for the same target.",
     "inputSchema": {"type": "object", "properties": {
         "proposal_id": {"type": "string"}, "reason": {"type": "string"}},
         "required": ["proposal_id", "reason"]}},
    {"name": "wiki_handoff_create", "description": "Create a handoff record in staging.",
     "inputSchema": {"type": "object", "properties": {
         "summary": {"type": "string"},
         "context_pages": {"type": "array", "items": {"type": "string"}}}, "required": ["summary"]}},
    {"name": "wiki_promote_proposal",
     "description": "Promote a staged proposal. Enforced in the write path: requires publish scope, a matching review manifest, and an owner authorisation record. When the eval gate is armed (an extended-eval baseline exists), the latest eval report must also show no regression beyond epsilon, or promotion blocks; the only way past a block is a recorded owner eval override (CLI: gateway eval-override). Optional expected_target_etag: the etag returned when the target was read — the write proceeds only if the target is unchanged (pass null to require the target still be absent).",
     "inputSchema": {"type": "object", "properties": {
         "proposal_id": {"type": "string"},
         "expected_target_etag": {"type": ["string", "null"]}}, "required": ["proposal_id"]}},
    {"name": "wiki_blackbox_my_activity", "description": "Your own Black Box entries (admin/owner may query any actor).",
     "inputSchema": {"type": "object", "properties": {"actor": {"type": "string"}, "limit": {"type": "integer", "default": 50}}}},
    {"name": "wiki_lint_run", "description": "Read-only lint report (page count, broken wikilinks).",
     "inputSchema": {"type": "object", "properties": {}}},
]


class Gateway:
    def __init__(self, config: Config):
        self.cfg = config
        config.ensure_state_dirs()
        self.registry = Registry(config.registry_path)
        self.store = GatewayStore(config)
        ledger_file = config.ledger_dir / f"black-box-{utcnow()[:4]}.jsonl"
        self.ledger = Ledger(ledger_file, id_prefix="bb", wiki_root=config.wiki_root)
        if self.ledger.seq < 0:
            from . import LEDGER_SCHEMA

            self.ledger.append_genesis(LEDGER_SCHEMA, str(config.wiki_root))
        self.session_token: str | None = None
        self.session_id: str | None = None
        self.client_name = "unknown"

    # -- helpers -------------------------------------------------------
    def _log(self, *, actor, action, tool, session_id, task_ref, direction,
             files_read=None, files_written=None, result="allow", commit_shas=None, extra=None):
        fields = {
            "actor": actor,
            "auth_method": "bearer-token",
            "client": self.client_name,
            "session_id": session_id or self.session_id or "no-session",
            "task_ref": task_ref,
            "direction_source": direction or {"kind": "approved-workflow", "ref": None},
            "action": action,
            "tool": tool,
            "files_read": files_read or [],
            "files_written": files_written or [],
            "result": result,
            "commit_shas": commit_shas or [],
        }
        if extra:
            fields.update(extra)
        return self.ledger.append(fields)

    @staticmethod
    def _result(payload, is_error=False):
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}],
                "isError": is_error}

    def _authenticate(self, meta: dict):
        token = None
        auth = (meta or {}).get("authorization")
        if isinstance(auth, str) and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        elif isinstance(auth, str) and auth:
            token = auth
        if token is None:
            token = self.session_token
        entry = self.registry.authenticate(token)
        return entry, token

    # -- JSON-RPC handling ----------------------------------------------
    def handle(self, request: dict):
        method = request.get("method")
        rid = request.get("id")
        params = request.get("params") or {}
        meta = params.get("_meta") or {}
        if method == "initialize":
            self.client_name = (params.get("clientInfo") or {}).get("name", "unknown")
            entry, token = self._authenticate(meta)
            if entry is not None:
                self.session_token = token
                self.session_id = meta.get("session_id") or f"sess-{entry['identity']}-init"
                self._log(actor=entry["identity"], action="session_start", tool=None,
                          session_id=self.session_id, task_ref=meta.get("task_ref"),
                          direction=meta.get("direction_source"))
            return self._rpc(rid, {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "wikicitadel-gateway", "version": "0.1"},
            })
        if method == "ping":
            return self._rpc(rid, {})
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return self._rpc(rid, {"tools": TOOLS})
        if method == "tools/call":
            return self._rpc(rid, self._call_tool(params, meta))
        return self._rpc(rid, None, error={"code": -32601, "message": "method not found"})

    @staticmethod
    def _rpc(rid, result, error=None):
        if rid is None:
            return None
        msg = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        return msg

    # -- tool dispatch ---------------------------------------------------
    def _call_tool(self, params: dict, meta: dict):
        name = params.get("name")
        args = params.get("arguments") or {}
        session_id = meta.get("session_id") or self.session_id or "no-session"
        task_ref = meta.get("task_ref")
        direction = meta.get("direction_source")
        entry, _ = self._authenticate(meta)
        if entry is None:
            extra = None
            if getattr(self.registry, "load_error", None):
                # Audit L3: a denial caused by a corrupt registry is
                # recorded as such — loudly, in the ledger itself.
                extra = {"registry_error": self.registry.load_error}
            self._log(actor="unknown", action="auth_denied", tool=name, session_id=session_id,
                      task_ref=task_ref, direction=direction, result="deny", extra=extra)
            return self._result({"error": "authentication required or token invalid"}, is_error=True)
        actor = entry["identity"]
        self.session_id = session_id

        def deny(action, files_read=None):
            self._log(actor=actor, action=action, tool=name, session_id=session_id,
                      task_ref=task_ref, direction=direction, files_read=files_read or [], result="deny")
            return self._result({"error": "not found or not available"}, is_error=True)

        try:
            if name == "wiki_whoami":
                self._log(actor=actor, action="whoami", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction)
                return self._result({"identity": actor, "scopes": entry.get("scopes", []),
                                     "status": entry.get("status")})

            if name == "wiki_search":
                query = str(args.get("query", ""))
                results = self.store.search(
                    query, limit=int(args.get("limit", 10)),
                    readable=lambda rel: scopes.can_read(entry, rel))
                self._log(actor=actor, action="search", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          files_read=[r["page_id"] for r in results],
                          extra={"query_hash": hashlib.sha256(query.encode()).hexdigest(),
                                 "query_length": len(query)})
                return self._result({"results": results})

            if name in ("wiki_read_page", "wiki_read_source"):
                rel = scopes.normalise(str(args.get("path", "")))
                action = "read_page" if name == "wiki_read_page" else "read_source"
                if rel is None or not scopes.can_read(entry, rel):
                    return deny(action, files_read=[str(args.get("path", ""))])
                try:
                    text = (self.store.read_page(rel) if name == "wiki_read_page"
                            else self.store.read_source(rel))
                except NotFoundOrDenied:
                    return deny(action, files_read=[rel])
                self._log(actor=actor, action=action, tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction, files_read=[rel])
                # Etag (harvest item 11): SHA-256 of the exact bytes
                # served — the optimistic-concurrency token a later
                # promotion can pin with expected_target_etag.
                etag = hashlib.sha256(text.encode("utf-8")).hexdigest()
                return self._result({"path": rel, "text": text, "etag": etag})

            if name == "wiki_graph_neighbors":
                rel = scopes.normalise(str(args.get("path", "")))
                if rel is None or not scopes.can_read(entry, rel):
                    return deny("graph_neighbors", files_read=[str(args.get("path", ""))])
                try:
                    out = self.store.graph_neighbors(rel)
                except NotFoundOrDenied:
                    return deny("graph_neighbors", files_read=[rel])
                self._log(actor=actor, action="graph_neighbors", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction, files_read=[rel])
                return self._result(out)

            if name == "wiki_list_decisions":
                decisions = [d for d in self.store.list_decisions()
                             if scopes.can_read(entry, d["page_id"])]
                self._log(actor=actor, action="read_decision", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          files_read=[d["page_id"] for d in decisions])
                return self._result({"decisions": decisions})

            if name == "wiki_get_decision":
                try:
                    out = self.store.get_decision(str(args.get("id", "")))
                except NotFoundOrDenied:
                    return deny("read_decision")
                if not scopes.can_read(entry, out["meta"]["page_id"]):
                    return deny("read_decision")
                self._log(actor=actor, action="read_decision", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction, files_read=[out["meta"]["page_id"]])
                return self._result(out)

            if name == "wiki_stage_proposal":
                if not scopes.can_propose(entry):
                    return deny("stage_proposal")
                meta_rec = self.store.stage_proposal(
                    actor=actor, session_id=session_id,
                    target_path=str(args.get("target_path", "")),
                    content=str(args.get("content", "")),
                    cites=list(args.get("cites") or []),
                    direction_source=direction or {"kind": "approved-workflow", "ref": None},
                    task_ref=task_ref)
                # Memory Defense block (2026-10-19): a proposal the
                # secret/PII scan stopped is ledgered as a denial
                # with the pattern CLASSES only — the ledger never
                # stores secrets (ledger.py rule), so the matched
                # value appears nowhere in this entry — and the
                # caller gets a clear error naming the class, never
                # the value. The quarantined record itself stays
                # visible via wiki_get_proposal_status.
                defense = meta_rec.get("defense") or {}
                defense_blocked = defense.get("verdict") == "blocked"
                secret_classes = sorted(
                    {f["pattern"] for f in defense.get("findings", [])})
                area = ("quarantine" if meta_rec["state"] == "quarantined"
                        else "proposed")
                self._log(actor=actor, action="stage_proposal", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          files_written=[f"staging/{area}/{meta_rec['proposal_id']}.md"],
                          result="deny" if defense_blocked else "allow",
                          extra=({"secret_scan": "blocked",
                                  "secret_classes": secret_classes}
                                 if defense_blocked else None))
                if defense_blocked:
                    return self._result(
                        {"error": "proposal blocked by secret/PII scan "
                                  f"(pattern class: {', '.join(secret_classes)}); "
                                  "the proposal was quarantined and cannot "
                                  "be promoted",
                         "proposal_id": meta_rec["proposal_id"],
                         "state": meta_rec["state"]}, is_error=True)
                return self._result({"proposal_id": meta_rec["proposal_id"], "state": meta_rec["state"],
                                     "sha256": meta_rec["sha256"]})

            if name == "wiki_get_proposal_status":
                try:
                    meta_rec = self.store.get_proposal(str(args.get("proposal_id", "")))
                except NotFoundOrDenied:
                    return deny("stage_proposal")
                if meta_rec["submitted_by"] != actor and not scopes.can_publish(entry) \
                        and "wiki:admin" not in entry.get("scopes", []):
                    return deny("stage_proposal")
                self._log(actor=actor, action="read_proposal_status", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction)
                return self._result(meta_rec)

            if name == "wiki_list_proposals":
                metas = self.store.list_proposals(
                    state=(str(args["state"]) if args.get("state") else None))
                if not scopes.can_publish(entry) and "wiki:admin" not in entry.get("scopes", []):
                    metas = [m for m in metas if m["submitted_by"] == actor]
                self._log(actor=actor, action="list_proposals", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          extra={"returned": len(metas)})
                return self._result({"proposals": metas})

            if name == "wiki_reject_proposal":
                if not scopes.can_publish(entry):
                    return deny("reject_proposal")
                meta_rec = self.store.reject_proposal(
                    str(args.get("proposal_id", "")), actor,
                    str(args.get("reason", "")))
                self._log(actor=actor, action="reject_proposal", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          files_written=[f"staging/proposed/{meta_rec['proposal_id']}.json"],
                          extra={"rejection_reason": meta_rec["rejection"]["reason"]})
                return self._result(meta_rec)

            if name == "wiki_handoff_create":
                if not scopes.can_propose(entry):
                    return deny("handoff_create")
                rec = self.store.create_handoff(
                    actor=actor, session_id=session_id, summary=str(args.get("summary", "")),
                    context_pages=list(args.get("context_pages") or []),
                    direction_source=direction or {"kind": "approved-workflow", "ref": None})
                self._log(actor=actor, action="handoff_create", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          files_written=[f"staging/handoffs/{rec['handoff_id']}.json"])
                return self._result(rec)

            if name == "wiki_promote_proposal":
                if not scopes.can_publish(entry):
                    return deny("promote")
                if "expected_target_etag" in args:
                    out = self.store.promote(str(args.get("proposal_id", "")), entry,
                                             expected_target_etag=args["expected_target_etag"])
                else:
                    out = self.store.promote(str(args.get("proposal_id", "")), entry)
                commit_shas = [out["commit_sha"]] if out.get("commit_sha") else []
                gate_extra = {}
                gate_info = out["proposal"].get("eval_gate") or {}
                if gate_info.get("status") == "override":
                    ov = gate_info.get("override") or {}
                    gate_extra = {"eval_gate_override": {
                        "by": ov.get("overridden_by"), "reason": ov.get("reason")}}
                self._log(actor=actor, action="promote", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          files_written=[out["proposal"]["target_path"]], commit_shas=commit_shas,
                          extra=gate_extra or None)
                return self._result({"proposal_id": out["proposal"]["proposal_id"],
                                     "state": "promoted", "commit_sha": out.get("commit_sha"),
                                     "target_path": out["proposal"]["target_path"]})

            if name == "wiki_blackbox_my_activity":
                target_actor = actor
                requested = args.get("actor")
                if requested and requested != actor:
                    if "wiki:admin" not in entry.get("scopes", []) and actor != "owner":
                        return deny("blackbox_activity")
                    target_actor = requested
                entries = [e for e in read_entries(self.ledger.path) if e.get("actor") == target_actor]
                entries = entries[-int(args.get("limit", 50)):]
                # Audit L3: reading the Black Box is itself an
                # auditable event. It is logged AFTER the snapshot
                # is taken, so the read never includes itself; the
                # entry records who looked, whose activity they saw,
                # and how much of it.
                self._log(actor=actor, action="blackbox_read", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction,
                          extra={"queried_actor": target_actor,
                                 "entries_returned": len(entries)})
                return self._result({"actor": target_actor, "entries": entries})

            if name == "wiki_lint_run":
                report = self.store.lint_run()
                self._log(actor=actor, action="lint_run", tool=name, session_id=session_id,
                          task_ref=task_ref, direction=direction)
                return self._result(report)

            return self._result({"error": f"unknown tool: {name}"}, is_error=True)
        except StoreError as exc:
            self._log(actor=actor, action="promote" if name == "wiki_promote_proposal" else (name or "tool"),
                      tool=name, session_id=session_id, task_ref=task_ref, direction=direction,
                      result="error", extra={"error": str(exc)})
            # Audit L2: a promotion refusal returns ONE uniform
            # message. Which gate failed (review, authorisation,
            # hash, target class) is internal state — it lives in
            # the ledger entry above, never in the caller's answer.
            caller_msg = ("promotion refused"
                          if name == "wiki_promote_proposal" else str(exc))
            return self._result({"error": caller_msg}, is_error=True)


def serve(config: Config) -> int:
    gateway = Gateway(config)
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = gateway.handle(request)
        if response is not None:
            out.write(json.dumps(response) + "\n")
            out.flush()
    return 0
