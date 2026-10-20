#!/usr/bin/env python3
"""MCP read door — JSON-RPC 2.0 over stdio (newline-delimited).

The standard, lightweight read door beside the governed gateway
(tools/gateway/). The split is the point:

  * THIS door reads. Any MCP client (Claude Code, Codex, ...)
    points at it over stdio and gets read-only access to the
    compiled corpus and the gated raw layer — no tokens, no
    registry, no ledger, no write verb anywhere in the surface.
  * The GATEWAY governs writes: scoped bearer tokens,
    staging proposals, review, promotion, the Black Box. If a
    client needs to change the wiki, it goes there, not here.

Read rules are NOT re-invented here. This server imports
scripts/wiki_traverse.py — the traversal door (item 66) — and
applies its read rule verbatim:

  * the compiled layer (wiki/) is readable;
  * the raw layer is gated by the Phase-6 sensitivity register
    (evaluation/sensitivity.json), class by class, through
    traverse.classify_raw + traverse.raw_read_permitted;
  * search delegates to scripts/wiki_search.py (subprocess,
    --pack), so ranking AND retrieval severance (item 20) are
    the engine's own, never a re-implementation; results the
    sensitivity gate bars are then withheld (see _search).

Tools (eight, all reads): wiki_search, wiki_read_page,
wiki_read_source, wiki_neighbors, wiki_path, wiki_census,
wiki_claim, wiki_cite. The last three are thin wrappers over
the traversal door's path / claim / cite commands, imported
the same way — never re-implemented here.

The door's identity stance (a design decision, stated here
because it decides what the gate does): the door runs as the
owner's local agent — identity "agent", the traversal door's
FULL_RAW agent seat — and never as "owner". Consequences, by
the traverse rule table: personal and family-sensitive raw is
served (the owner's agent already holds it under the
memory-transparency rule); credential-adjacent and export-only
raw is REFUSED, with the reason stated — those classes are
owner-only-ever, and an agent door does not become the side
channel around that rule. There is deliberately no flag or
environment variable that widens the stance.

Transport/protocol shape follows tools/gateway/gateway/
server.py (the proven in-repo MCP server): newline-delimited
JSON-RPC, initialize -> protocolVersion 2025-06-18, tool
results as a single JSON text content block.

Wiki root: --root <path>, else $LLM_WIKI_ROOT, else the repo
this file lives in (tools/mcp-read/ -> repo root).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

# The door's fixed identity stance (see module docstring).
DOOR_IDENTITY = "agent"

TOOLS = [
    {"name": "wiki_search",
     "description": "Search the compiled corpus (hybrid BM25 + graph ranking, retrieval severance applied by the engine itself). Scope 'raw'/'all' also searches raw sources; hits the sensitivity gate bars are withheld and counted. Cite only pages you have actually read.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "limit": {"type": "integer", "default": 10},
         "scope": {"type": "string", "enum": ["wiki", "raw", "all"],
                   "default": "wiki"}}, "required": ["query"]}},
    {"name": "wiki_read_page",
     "description": "Read one compiled wiki page by page id, path, stem or title.",
     "inputSchema": {"type": "object", "properties": {
         "page": {"type": "string"}}, "required": ["page"]}},
    {"name": "wiki_read_source",
     "description": "Read one raw source by repo-relative path, subject to the sensitivity gate (credential-adjacent and export-only are refused, with the reason stated; unclassified is served stamped).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}}, "required": ["path"]}},
    {"name": "wiki_neighbors",
     "description": "Wikilink neighbours (typed edges: inbound/outbound) of a page.",
     "inputSchema": {"type": "object", "properties": {
         "page": {"type": "string"},
         "type": {"type": "string"},
         "direction": {"type": "string",
                       "enum": ["out", "in", "both"],
                       "default": "both"}}, "required": ["page"]}},
    {"name": "wiki_path",
     "description": "Shortest directed wikilink path between two pages, with the relation of each step; reports when no directed path exists (and whether an undirected connection does).",
     "inputSchema": {"type": "object", "properties": {
         "from_page": {"type": "string"},
         "to_page": {"type": "string"},
         "max_depth": {"type": "integer", "default": 6}},
         "required": ["from_page", "to_page"]}},
    {"name": "wiki_census",
     "description": "Corpus census: page and edge counts by relation/kind, and the orphan pages.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "wiki_claim",
     "description": "Claim pages and their lifecycle status (candidate / rule / retired, with outcome counts), optionally filtered by a substring of the claim text or page path.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "default": ""}}}},
    {"name": "wiki_cite",
     "description": "Verbatim cited passages from the citation lockfile, for a page or for one citation by id; a passage whose source class the sensitivity gate bars for this door's fixed identity is withheld, with the reason stated.",
     "inputSchema": {"type": "object", "properties": {
         "page": {"type": "string"},
         "cite_id": {"type": "string"}}}},
]


class DoorError(Exception):
    """A tool failure to report to the caller as an error result."""


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ReadDoor:
    def __init__(self, root: Path):
        # Resolved once, here: the traversal door computes page
        # paths relative to the root, and a relative root (a plain
        # `--root .` start) crashes its claim/cite verbs against
        # the absolute paths its page walk yields.
        self.root = Path(root).resolve()
        traverse_path = self.root / "scripts" / "wiki_traverse.py"
        if not traverse_path.is_file():
            raise DoorError(
                f"no traversal door at {traverse_path} — the read "
                f"door serves a wiki repo root (got {root})")
        # The read rule itself, imported — never re-implemented.
        self.traverse = _load_module("wiki_traverse", traverse_path)

    # -- tools ---------------------------------------------------------
    def _search(self, query: str, limit: int = 10,
                scope: str = "wiki") -> dict:
        """Delegate to scripts/wiki_search.py --pack (the same
        delegation the traversal door's search command uses), so
        the ranking — and its retrieval-severance stage — is the
        engine's own. Hits into the raw layer are then passed
        through the sensitivity gate: a hit the gate bars is
        withheld (existence not leaked beyond a count), because
        ranked snippets cannot be class-filtered by the engine,
        which knows nothing of identities."""
        if scope not in ("wiki", "raw", "all"):
            raise DoorError(f"unknown scope: {scope!r}")
        limit = max(1, min(int(limit), 100))
        cmd = [sys.executable,
               str(self.root / "scripts" / "wiki_search.py"),
               query, "--top", str(limit), "--scope", scope,
               "--pack"]
        proc = subprocess.run(cmd, cwd=self.root,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stdout.strip().splitlines()
                    or proc.stderr.strip().splitlines() or [""])
            raise DoorError(f"wiki_search.py failed: {tail[-1]}")
        try:
            pack = json.loads(proc.stdout)
        except ValueError:
            raise DoorError("wiki_search.py returned no JSON pack")
        withheld = 0

        def gate(entries):
            nonlocal withheld
            kept = []
            for e in entries:
                rel = e.get("path", "")
                if rel.startswith("raw/"):
                    cls = self.traverse.classify_raw(self.root, rel)
                    if not self.traverse.raw_read_permitted(
                            DOOR_IDENTITY, cls):
                        withheld += 1
                        continue
                kept.append(e)
            return kept

        results = []
        for e in gate(pack.get("included", [])):
            entry = {"page_id": e["path"], "score": e["score"],
                     "snippet": e["snippet"]}
            if "freshness" in e:
                entry["freshness"] = e["freshness"]
            results.append(entry)
        gate(pack.get("omitted", []))  # counted, never surfaced
        return {"query": pack.get("query", query), "scope": scope,
                "results": results,
                "total_ranked": pack.get("total_ranked", len(results)),
                "corpus_docs": pack.get("corpus_docs"),
                "severance": pack.get("severance"),
                "withheld_count": withheld}

    def _read_page(self, name: str) -> dict:
        pages, keys = self.traverse.page_index(self.root)
        rel = self.traverse.resolve_page(keys, name)
        fields, _body, text = pages[rel]
        return {"page": rel, "frontmatter": fields, "text": text}

    def _read_source(self, raw_path: str) -> dict:
        # traverse.cmd_source IS the gate: classify + permit +
        # refuse-with-reason (its Refusal propagates to dispatch).
        out = self.traverse.cmd_source(
            self.root, DOOR_IDENTITY, raw_path, True)
        result = {"path": out["source"],
                  "sensitivity": out["sensitivity"],
                  "text": out["text"]}
        if out["sensitivity"] == "unclassified":
            result["stamp"] = ("UNCLASSIFIED — no class on the "
                               "register; not thereby public")
        return result

    def _neighbors(self, name: str, etype, direction: str) -> dict:
        return self.traverse.cmd_neighbours(
            self.root, DOOR_IDENTITY, name, etype, direction, True)

    def _path(self, a: str, b: str, max_depth: int = 6) -> dict:
        return self.traverse.cmd_path(
            self.root, DOOR_IDENTITY, a, b, int(max_depth), True)

    def _census(self) -> dict:
        out = self.traverse.cmd_census(self.root, DOOR_IDENTITY,
                                       True)
        out["orphan_count"] = len(out.get("orphans", []))
        return out

    def _claim(self, query: str = "") -> dict:
        return self.traverse.cmd_claim(
            self.root, DOOR_IDENTITY, query, True)

    def _cite(self, page=None, cite_id=None) -> dict:
        return self.traverse.cmd_cite(
            self.root, DOOR_IDENTITY, page or None,
            cite_id or None, True)

    # -- JSON-RPC handling (gateway server.py's shape) -----------------
    @staticmethod
    def _result(payload, is_error=False):
        return {"content": [{"type": "text",
                             "text": json.dumps(payload, indent=2,
                                                sort_keys=True)}],
                "isError": is_error}

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

    def handle(self, request: dict):
        method = request.get("method")
        rid = request.get("id")
        params = request.get("params") or {}
        if method == "initialize":
            return self._rpc(rid, {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "wikicitadel-mcp-read",
                               "version": "0.1"},
            })
        if method == "ping":
            return self._rpc(rid, {})
        if isinstance(method, str) and method.startswith(
                "notifications/"):
            return None
        if method == "tools/list":
            return self._rpc(rid, {"tools": TOOLS})
        if method == "tools/call":
            return self._rpc(rid, self._call_tool(params))
        return self._rpc(rid, None, error={
            "code": -32601, "message": "method not found"})

    def _call_tool(self, params: dict):
        name = params.get("name")
        args = params.get("arguments") or {}
        Refusal = self.traverse.Refusal
        try:
            if name == "wiki_search":
                return self._result(self._search(
                    str(args.get("query", "")),
                    args.get("limit", 10),
                    str(args.get("scope", "wiki"))))
            if name == "wiki_read_page":
                return self._result(self._read_page(
                    str(args.get("page") or args.get("path") or "")))
            if name == "wiki_read_source":
                return self._result(self._read_source(
                    str(args.get("path", ""))))
            if name == "wiki_neighbors":
                direction = str(args.get("direction", "both"))
                if direction not in ("out", "in", "both"):
                    raise DoorError(
                        f"unknown direction: {direction!r}")
                return self._result(self._neighbors(
                    str(args.get("page") or args.get("path") or ""),
                    args.get("type"), direction))
            if name == "wiki_path":
                return self._result(self._path(
                    str(args.get("from_page") or ""),
                    str(args.get("to_page") or ""),
                    args.get("max_depth", 6)))
            if name == "wiki_census":
                return self._result(self._census())
            if name == "wiki_claim":
                return self._result(self._claim(
                    str(args.get("query") or "")))
            if name == "wiki_cite":
                return self._result(self._cite(
                    args.get("page"), args.get("cite_id")))
            return self._result(
                {"error": f"unknown tool: {name}"}, is_error=True)
        except Refusal as exc:
            return self._result({"error": f"refused: {exc}"},
                                is_error=True)
        except DoorError as exc:
            return self._result({"error": str(exc)}, is_error=True)
        except Exception as exc:  # one bad call must not kill the door
            return self._result(
                {"error": f"{type(exc).__name__}: {exc}"},
                is_error=True)


def serve(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="The MCP read door: read-only tools over "
                    "stdio. Writes live in the gateway.")
    ap.add_argument("--root", type=Path, default=None,
                    help="wiki repo root (default: $LLM_WIKI_ROOT "
                         "or the repo this file lives in)")
    args = ap.parse_args(argv)
    root = args.root or (
        Path(os.environ["LLM_WIKI_ROOT"])
        if os.environ.get("LLM_WIKI_ROOT")
        else Path(__file__).resolve().parents[2])
    try:
        door = ReadDoor(root)
    except DoorError as exc:
        print(f"mcp-read: {exc}", file=sys.stderr)
        return 2
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = door.handle(request)
        if response is not None:
            out.write(json.dumps(response) + "\n")
            out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
