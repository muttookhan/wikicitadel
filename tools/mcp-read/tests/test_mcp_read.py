#!/usr/bin/env python3
"""Tests for tools/mcp-read/server.py (the MCP read door;
15-gap programme, gap 1: a standard MCP read door beside the
governed gateway).

The suite speaks real JSON-RPC over stdio to the repo's
server.py, pointed (--root) at a FIXTURE wiki in a temp dir
built exactly the way scripts/tests/test_wiki_traverse.py
builds its fixture (the door's own dependencies copied in:
wiki_traverse.py, wiki_validate.py, wiki_search.py,
tools/lens/lenslib.py). The fixture carries, on purpose:

  - a claim-severed page (gamma): its severed claim must be
    cut by wiki_search when the query hunts it, and the page
    must stay findable by a query that does not;
  - a page-severed page (dead): excluded from every search;
  - a credential-adjacent raw source (secret-note): refused
    by wiki_read_source WITH the reason stated, and never
    surfaced by wiki_search even at scope=all;
  - a personal raw (diary) and an unclassified raw (plain):
    the door's stance (the owner's agent, never the owner)
    serves the first and serves the second STAMPED.

It also pins the protocol handshake, the tools/list shape
(exactly the five read tools — the read/write split is the
point), and the no-write proof: sha256 of every fixture
content file identical before and after a call battery.

Run:  python3 -m unittest discover -s tests   (from tools/mcp-read/)
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MCP_READ = HERE.parent
REPO = MCP_READ.parents[1]
SERVER = MCP_READ / "server.py"
SCRIPTS = REPO / "scripts"

ALPHA = """---
title: Alpha
type: entity
sources:
  - raw/sources/open-note.md
---

# Alpha

## Evidence

The case rests on [[beta]]. Alpha keeps a quixotic lantern
by the door.
"""

BETA = """---
title: Beta
type: entity
---

# Beta

Beta body text about traversal graphs and lantern light.
"""

GAMMA = """---
title: Gamma
type: entity
---

# Gamma

Gamma keeps the vault archive papers on the top shelf.
The vault code is 4451, set at founding and never changed.
"""

DEAD = """---
title: Dead
type: entity
---

# Dead

The zanzibar statement stands here, wholly superseded.
"""

SENSITIVITY = {
    "classes": [{"id": c} for c in
                ("public", "internal", "personal",
                 "family-sensitive", "export-only",
                 "credential-adjacent")],
    "assignments": [
        {"path": "raw/sources/open-note.md", "class": "internal"},
        {"path": "raw/sources/secret-note.md",
         "class": "credential-adjacent"},
        {"path": "raw/sources/diary/", "class": "personal"},
    ],
}

SEVERANCE = {
    "kind": "retrieval-severance", "version": 1,
    "purpose": "fixture severance list",
    "generated_from": "fixture registers",
    "entries": [
        {"id": "sev-9001", "kind": "treatment",
         "page": "wiki/entities/gamma.md",
         "claim": "The vault code is 4451.",
         "source": "raw/sources/open-note.md",
         "cues": {"phrases": [["vault", "code", "is", "4451"]],
                  "terms": ["vault", "code", "4451"]}},
        {"id": "sev-9002", "kind": "page",
         "page": "wiki/entities/dead.md",
         "claim": "The zanzibar statement.",
         "source": "raw/sources/open-note.md",
         "cues": {"phrases": [], "terms": []}},
    ],
}


def tree_checksums(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[p.relative_to(root).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class McpReadFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp-read-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self._mk("scripts")
        for name in ("wiki_traverse.py", "wiki_validate.py",
                     "wiki_search.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        lens = self._mk("tools", "lens")
        shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                    lens / "lenslib.py")
        ent = self._mk("wiki", "entities")
        (ent / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (ent / "beta.md").write_text(BETA, encoding="utf-8")
        (ent / "gamma.md").write_text(GAMMA, encoding="utf-8")
        (ent / "dead.md").write_text(DEAD, encoding="utf-8")
        src = self._mk("raw", "sources")
        (src / "open-note.md").write_text(
            "open note body about lantern light\n",
            encoding="utf-8")
        (src / "secret-note.md").write_text(
            "the hummingbird cipher key is kept here\n",
            encoding="utf-8")
        (src / "plain.md").write_text("unclassified body\n",
                                      encoding="utf-8")
        diary = self._mk("raw", "sources", "diary")
        (diary / "entry.md").write_text("personal entry\n",
                                        encoding="utf-8")
        ev = self._mk("evaluation")
        (ev / "sensitivity.json").write_text(
            json.dumps(SENSITIVITY), encoding="utf-8")
        (ev / "retrieval-severance.json").write_text(
            json.dumps(SEVERANCE), encoding="utf-8")

    def _mk(self, *parts):
        d = self.tmp.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- a minimal JSON-RPC-over-stdio client -------------------
    def rpc(self, *requests):
        inp = "".join(json.dumps(r) + "\n" for r in requests)
        proc = subprocess.run(
            [sys.executable, str(SERVER), "--root", str(self.tmp)],
            input=inp, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = {}
        for line in proc.stdout.splitlines():
            if line.strip():
                msg = json.loads(line)
                if "id" in msg:
                    out[msg["id"]] = msg
        return out

    def call(self, name, arguments=None):
        out = self.rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": name, "arguments": arguments or {}}})
        result = out[2]["result"]
        payload = json.loads(result["content"][0]["text"])
        return result.get("isError", False), payload


class TestProtocol(McpReadFixture):
    def test_handshake(self):
        out = self.rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        init = out[1]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertEqual(init["serverInfo"]["name"],
                         "wikicitadel-mcp-read")
        self.assertEqual(out[2]["result"], {})

    def test_tools_list_shape(self):
        out = self.rpc({"jsonrpc": "2.0", "id": 1,
                        "method": "tools/list"})
        tools = out[1]["result"]["tools"]
        self.assertEqual(
            {t["name"] for t in tools},
            {"wiki_search", "wiki_read_page", "wiki_read_source",
             "wiki_neighbors", "wiki_census"})
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("description", t)
        search = next(t for t in tools
                      if t["name"] == "wiki_search")
        self.assertEqual(search["inputSchema"]["required"],
                         ["query"])

    def test_unknown_tool_and_method(self):
        is_err, payload = self.call("wiki_write_page", {})
        self.assertTrue(is_err)
        self.assertIn("unknown tool", payload["error"])
        out = self.rpc({"jsonrpc": "2.0", "id": 9,
                        "method": "resources/list"})
        self.assertEqual(out[9]["error"]["code"], -32601)


class TestSearch(McpReadFixture):
    def test_search_finds_page(self):
        is_err, payload = self.call(
            "wiki_search", {"query": "quixotic lantern"})
        self.assertFalse(is_err, payload)
        ids = [r["page_id"] for r in payload["results"]]
        self.assertIn("wiki/entities/alpha.md", ids)

    def test_search_severed_claim_cut_when_hunted(self):
        is_err, payload = self.call(
            "wiki_search", {"query": "vault code is 4451"})
        self.assertFalse(is_err, payload)
        ids = [r["page_id"] for r in payload["results"]]
        self.assertNotIn("wiki/entities/gamma.md", ids)
        self.assertTrue(payload["severance"]["applied"])
        excluded = {e["path"]: e["entries"]
                    for e in payload["severance"]["excluded"]}
        self.assertEqual(excluded.get("wiki/entities/gamma.md"),
                         ["sev-9001"])

    def test_search_severed_record_findable_by_other_query(self):
        is_err, payload = self.call(
            "wiki_search", {"query": "vault archive papers"})
        self.assertFalse(is_err, payload)
        ids = [r["page_id"] for r in payload["results"]]
        self.assertIn("wiki/entities/gamma.md", ids)

    def test_search_page_severed_wholesale(self):
        is_err, payload = self.call(
            "wiki_search", {"query": "zanzibar statement"})
        self.assertFalse(is_err, payload)
        ids = [r["page_id"] for r in payload["results"]]
        self.assertNotIn("wiki/entities/dead.md", ids)
        excluded = {e["path"] for e in
                    payload["severance"]["excluded"]}
        self.assertIn("wiki/entities/dead.md", excluded)

    def test_search_raw_scope_withholds_gated_source(self):
        is_err, payload = self.call(
            "wiki_search", {"query": "hummingbird cipher",
                            "scope": "all"})
        self.assertFalse(is_err, payload)
        ids = [r["page_id"] for r in payload["results"]]
        self.assertNotIn("raw/sources/secret-note.md", ids)
        self.assertGreaterEqual(payload["withheld_count"], 1)
        for r in payload["results"]:
            self.assertNotIn("cipher key is kept", r["snippet"])

    def test_search_raw_scope_serves_open_source(self):
        is_err, payload = self.call(
            "wiki_search", {"query": "open note lantern",
                            "scope": "all"})
        self.assertFalse(is_err, payload)
        ids = [r["page_id"] for r in payload["results"]]
        self.assertIn("raw/sources/open-note.md", ids)


class TestReads(McpReadFixture):
    def test_read_page_by_stem_title_and_path(self):
        for name in ("alpha", "Alpha", "wiki/entities/alpha.md"):
            is_err, payload = self.call(
                "wiki_read_page", {"page": name})
            self.assertFalse(is_err, payload)
            self.assertEqual(payload["page"],
                             "wiki/entities/alpha.md")
            self.assertEqual(payload["frontmatter"]["title"],
                             "Alpha")
            self.assertIn("quixotic lantern", payload["text"])

    def test_read_page_missing_is_error(self):
        is_err, payload = self.call(
            "wiki_read_page", {"page": "no-such-page"})
        self.assertTrue(is_err)
        self.assertIn("refused", payload["error"])

    def test_read_source_internal(self):
        is_err, payload = self.call(
            "wiki_read_source",
            {"path": "raw/sources/open-note.md"})
        self.assertFalse(is_err, payload)
        self.assertEqual(payload["sensitivity"], "internal")
        self.assertIn("open note body", payload["text"])

    def test_read_source_credential_adjacent_refused(self):
        is_err, payload = self.call(
            "wiki_read_source",
            {"path": "raw/sources/secret-note.md"})
        self.assertTrue(is_err)
        self.assertIn("credential-adjacent", payload["error"])
        self.assertNotIn("hummingbird", json.dumps(payload))

    def test_read_source_personal_served_under_door_stance(self):
        is_err, payload = self.call(
            "wiki_read_source",
            {"path": "raw/sources/diary/entry.md"})
        self.assertFalse(is_err, payload)
        self.assertEqual(payload["sensitivity"], "personal")
        self.assertIn("personal entry", payload["text"])

    def test_read_source_unclassified_stamped(self):
        is_err, payload = self.call(
            "wiki_read_source", {"path": "raw/sources/plain.md"})
        self.assertFalse(is_err, payload)
        self.assertEqual(payload["sensitivity"], "unclassified")
        self.assertIn("UNCLASSIFIED", payload["stamp"])
        self.assertIn("unclassified body", payload["text"])


class TestGraph(McpReadFixture):
    def test_neighbors_typed_edges(self):
        is_err, payload = self.call(
            "wiki_neighbors", {"page": "alpha", "direction": "out"})
        self.assertFalse(is_err, payload)
        edges = payload["neighbours"]
        self.assertTrue(any(
            e["dst"] == "wiki/entities/beta.md"
            and e["relation"] == "grounds" for e in edges),
            edges)

    def test_census(self):
        is_err, payload = self.call("wiki_census", {})
        self.assertFalse(is_err, payload)
        self.assertEqual(payload["pages"], 4)
        self.assertGreaterEqual(payload["edges"], 1)
        self.assertEqual(payload["orphan_count"],
                         len(payload["orphans"]))


class TestNoWrite(McpReadFixture):
    def test_battery_leaves_fixture_byte_identical(self):
        before = tree_checksums(self.tmp)
        self.call("wiki_search", {"query": "quixotic lantern"})
        self.call("wiki_search", {"query": "vault code is 4451"})
        self.call("wiki_read_page", {"page": "alpha"})
        self.call("wiki_read_source",
                  {"path": "raw/sources/open-note.md"})
        self.call("wiki_neighbors", {"page": "alpha"})
        self.call("wiki_census", {})
        self.assertEqual(tree_checksums(self.tmp), before)

    def test_server_source_names_no_write_api(self):
        # Reads of the corpus happen inside the imported
        # traversal door and the search subprocess; THIS file
        # must not name a file-writing API of its own (writing
        # to stdout is the transport, not a corpus write).
        text = SERVER.read_text(encoding="utf-8")
        for verb in ("write_text", "write_bytes", "os.remove",
                     "os.rename", "shutil"):
            self.assertNotIn(verb, text)


if __name__ == "__main__":
    unittest.main()
