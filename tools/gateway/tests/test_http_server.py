#!/usr/bin/env python3
"""HTTP door tests (hosted-gateway-door build, 2026-11-08).

Proves, against fixture wikis and fixture tokens only, that the
thin HTTP shim in gateway/http_server.py:
- binds localhost only and refuses any non-loopback bind;
- authenticates per request against the same salted-token registry
  as stdio (no token / forged / revoked all denied + ledgered);
- serves the scoped read routes with the same no-existence-leak
  payloads as stdio, and records search entries with a query hash
  and length — never the query text;
- stages proposals only (no canonical-write route exists);
- promotes ONLY through the shared wiki_promote_proposal /
  store.promote() code path (refused without review manifest,
  refused without owner authorisation, succeeds with both; a
  staged file altered after review is quarantined, never promoted);
- appends a Black Box entry for EVERY request, and the chain
  still verifies afterwards.

Run:  python3 -m unittest discover -s tests -v   (from tools/gateway)
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve()
GW_DIR = HERE.parents[1]
sys.path.insert(0, str(GW_DIR))

from fixtures.make_fixtures import build_fixture  # noqa: E402
from gateway import ledger as ledger_mod  # noqa: E402
from gateway.config import Config  # noqa: E402
from gateway.http_server import (  # noqa: E402
    DEFAULT_HOST, LOOPBACK_HOSTS, _validate_host, make_server)
from gateway.registry import Registry  # noqa: E402

ALPHA = "wiki/concepts/alpha.md"
BETA = "wiki/entities/beta.md"


def _identities(tokens, state_dir):
    """Map fixture identity roles by scope, not by name: the two
    trees name their scoped agent and maintainer differently, so
    roles are derived from the fixture registry — maintainer is
    the identity with publish scope but no admin scope, scoped is
    the propose-only identity whose read prefixes include the
    syntheses area (the one the read/stage tests exercise)."""
    listed = Registry(Path(state_dir) / "registry.json").list_identities()
    by_name = {e["identity"]: e for e in listed}
    maintainer = next(
        name for name, e in by_name.items()
        if "wiki:publish" in e.get("scopes", [])
        and "wiki:admin" not in e.get("scopes", []))
    scoped = next(
        name for name, e in by_name.items()
        if "wiki:propose" in e.get("scopes", [])
        and "wiki:publish" not in e.get("scopes", [])
        and "wiki/syntheses" in (e.get("read_prefixes") or []))
    return {"owner": "owner", "maintainer": maintainer, "scoped": scoped}


class HttpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = build_fixture(Path(self.tmp.name))
        self.tokens = self.fx["tokens"]
        self.ids = _identities(self.tokens, self.fx["state_dir"])
        self.root = self.fx["root"]
        self.state = self.fx["state_dir"]
        cfg = Config(env={**self.fx["env"], "PATH": "/usr/bin:/bin"})
        self.httpd, self.door = make_server(cfg, host="127.0.0.1", port=0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=10)
        self.tmp.cleanup()

    # -- HTTP helpers -------------------------------------------------
    def req(self, method, path, token=None, body=None, raw_body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Connection": "close"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        payload = raw_body
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            parsed = json.loads(data.decode("utf-8"))
        except ValueError:
            parsed = None
        return resp.status, parsed

    def get(self, path, token):
        return self.req("GET", path, token=token)

    def post(self, path, token, body=None, raw_body=None):
        return self.req("POST", path, token=token, body=body, raw_body=raw_body)

    def ledger_file(self) -> Path:
        files = sorted((self.state / "ledger").glob("black-box-*.jsonl"))
        self.assertEqual(len(files), 1)
        return files[0]

    def entries(self):
        return ledger_mod.read_entries(self.ledger_file())

    def cli(self, *argv):
        env = {**os.environ, **self.fx["env"]}
        return subprocess.run([sys.executable, "-m", "gateway", *argv],
                              capture_output=True, text=True, env=env, cwd=str(GW_DIR))

    def stage(self, token, target, content="# Staged\n", cites=None):
        status, payload = self.post("/v1/proposals", token,
                                    {"target_path": target, "content": content,
                                     "cites": cites or [ALPHA]})
        self.assertEqual(status, 200, payload)
        return payload["proposal_id"]

    def arm(self, pid):
        self.assertEqual(
            self.cli("review", pid, "--reviewer", self.ids["maintainer"]).returncode, 0)
        self.assertEqual(
            self.cli("authorise", pid, "--by", "owner").returncode, 0)


class TestLocalhostBinding(unittest.TestCase):
    def test_default_host_is_loopback(self):
        self.assertEqual(DEFAULT_HOST, "127.0.0.1")
        self.assertIn("127.0.0.1", LOOPBACK_HOSTS)
        self.assertIn("::1", LOOPBACK_HOSTS)

    def test_validate_host_accepts_loopback_only(self):
        for good in ("127.0.0.1", "::1", "localhost", "127.0.0.2"):
            self.assertEqual(_validate_host(good), good)
        for bad in ("0.0.0.0", "::", "192.168.1.10", "10.0.0.1",
                    "8.8.8.8", "example.com", ""):
            with self.assertRaises(ValueError, msg=bad):
                _validate_host(bad)

    def test_make_server_binds_loopback_and_refuses_public(self):
        with tempfile.TemporaryDirectory() as td:
            fx = build_fixture(Path(td))
            cfg = Config(env={**fx["env"], "PATH": "/usr/bin:/bin"})
            httpd, _ = make_server(cfg, host="127.0.0.1", port=0)
            try:
                self.assertEqual(httpd.server_address[0], "127.0.0.1")
                self.assertGreater(httpd.server_address[1], 0)
            finally:
                httpd.server_close()
            for bad in ("0.0.0.0", "192.168.1.10", "example.com"):
                with self.assertRaises(ValueError, msg=bad):
                    make_server(cfg, host=bad, port=0)


class TestHttpAuth(HttpCase):
    def test_no_token_forged_and_revoked_denied_and_ledgered(self):
        scoped = self.tokens[self.ids["scoped"]]
        prefix = self.tokens["owner"].split(".")[0]
        before = len([e for e in self.entries() if e["action"] == "auth_denied"])
        status, payload = self.get("/v1/whoami", token=None)
        self.assertEqual(status, 401)
        self.assertIn("authentication", payload["error"])
        status, payload = self.get("/v1/whoami", token=f"{prefix}.{self.ids['scoped']}.deadbeef")
        self.assertEqual(status, 401)
        # A live request works, then revocation kills the next one.
        status, payload = self.get("/v1/whoami", token=scoped)
        self.assertEqual(status, 200)
        self.assertEqual(payload["identity"], self.ids["scoped"])
        Registry(self.state / "registry.json").revoke(self.ids["scoped"])
        status, _ = self.get("/v1/whoami", token=scoped)
        self.assertEqual(status, 401)
        denials = [e for e in self.entries() if e["action"] == "auth_denied"]
        self.assertGreaterEqual(len(denials) - before, 3)
        # Rotation: a freshly issued token works; the old one stays dead.
        new_token = Registry(self.state / "registry.json").issue(
            self.ids["scoped"], ["wiki:read", "wiki:propose"],
            read_prefixes=["wiki/concepts", "wiki/entities", "wiki/syntheses", "wiki/index.md"],
            source_prefixes=["raw/sources/field-notes.md"])
        status, payload = self.get("/v1/whoami", token=new_token)
        self.assertEqual(status, 200)
        status, _ = self.get("/v1/whoami", token=scoped)
        self.assertEqual(status, 401)


class TestHttpReads(HttpCase):
    def test_scoped_reads_and_no_existence_leak(self):
        scoped = self.tokens[self.ids["scoped"]]
        status, payload = self.get(f"/v1/pages?path={quote(ALPHA, safe='')}", scoped)
        self.assertEqual(status, 200)
        self.assertIn("Alpha Concept", payload["text"])
        self.assertIn("etag", payload)
        status, payload = self.get(
            "/v1/sources?path=" + quote("raw/sources/field-notes.md", safe=""), scoped)
        self.assertEqual(status, 200)
        self.assertIn("field notes", payload["text"])
        _, leak1 = self.get(
            "/v1/sources?path=" + quote("raw/sources/restricted/mufti-only.md", safe=""), scoped)
        _, leak2 = self.get(
            "/v1/pages?path=" + quote("wiki/concepts/does-not-exist.md", safe=""), scoped)
        _, leak3 = self.get(
            "/v1/pages?path=" + quote("wiki/decisions/decision-fixture.md", safe=""), scoped)
        self.assertEqual(leak1, leak2)
        self.assertEqual(leak2, leak3)
        self.assertEqual(leak1["error"], "not found or not available")

    def test_search_scoped_and_ledger_has_no_query_text(self):
        scoped = self.tokens[self.ids["scoped"]]
        status, payload = self.get("/v1/search?q=" + quote("zqxjv alphaseed"), scoped)
        self.assertEqual(status, 200)
        self.assertEqual([r["page_id"] for r in payload["results"]], [ALPHA])
        raw = self.ledger_file().read_bytes()
        self.assertNotIn(b"zqxjv", raw)
        self.assertNotIn(b"alphaseed", raw)
        search_entries = [e for e in self.entries() if e["action"] == "search"]
        self.assertEqual(len(search_entries), 1)
        self.assertIn("query_hash", search_entries[0])
        self.assertIn("query_length", search_entries[0])
        self.assertNotIn("query", search_entries[0])
        self.assertEqual(search_entries[0]["files_read"], [ALPHA])

    def test_decisions_graph_lint_and_activity(self):
        maintainer = self.tokens[self.ids["maintainer"]]
        status, payload = self.get("/v1/decisions", maintainer)
        self.assertEqual(status, 200)
        self.assertEqual([d["id"] for d in payload["decisions"]], ["decision-fixture"])
        status, payload = self.get("/v1/decisions/decision-fixture", maintainer)
        self.assertEqual(status, 200)
        self.assertIn("fixture decision", payload["text"])
        status, payload = self.get(f"/v1/graph?path={quote(ALPHA, safe='')}", maintainer)
        self.assertEqual(status, 200)
        self.assertIn(BETA, payload["outbound"])
        status, payload = self.get("/v1/lint", maintainer)
        self.assertEqual(status, 200)
        status, payload = self.get("/v1/activity", maintainer)
        self.assertEqual(status, 200)
        self.assertEqual(payload["actor"], self.ids["maintainer"])
        self.assertTrue(payload["entries"])
        # A scoped caller may not read another actor's activity.
        scoped = self.tokens[self.ids["scoped"]]
        status, _ = self.get("/v1/activity?actor=" + self.ids["maintainer"], scoped)
        self.assertEqual(status, 404)


class TestHttpWrites(HttpCase):
    def test_stage_only_no_canonical_write_route(self):
        scoped = self.tokens[self.ids["scoped"]]
        target = "wiki/syntheses/http-staged.md"
        pid = self.stage(scoped, target, "# From HTTP\n\nStaged only.\n")
        self.assertFalse((self.root / target).exists())
        status, payload = self.get(f"/v1/proposals/{pid}", scoped)
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "draft")
        # There is no canonical-write route: POST to a read route is
        # refused (405) and the target file is untouched.
        status, _ = self.post(f"/v1/pages?path={quote(ALPHA, safe='')}", scoped,
                              {"text": "overwrite attempt"})
        self.assertEqual(status, 405)
        self.assertNotIn("overwrite attempt", (self.root / ALPHA).read_text())
        status, _ = self.post("/v1/search", scoped, {"query": "alpha"})
        self.assertEqual(status, 405)

    def test_stage_without_propose_scope_denied(self):
        # The fixture owner token has publish; revoke propose by
        # issuing a read-only token for the scoped identity.
        read_only = Registry(self.state / "registry.json").issue(
            self.ids["scoped"], ["wiki:read"],
            read_prefixes=["wiki/concepts", "wiki/entities", "wiki/syntheses", "wiki/index.md"])
        status, _ = self.post("/v1/proposals", read_only,
                              {"target_path": "wiki/syntheses/nope.md", "content": "# x\n"})
        self.assertEqual(status, 404)


class TestHttpPromote(HttpCase):
    def test_promote_ladder_through_shared_code_path(self):
        scoped = self.tokens[self.ids["scoped"]]
        maintainer = self.tokens[self.ids["maintainer"]]
        target = "wiki/syntheses/http-promoted.md"
        pid = self.stage(scoped, target, "# From HTTP\n\nPromoted content.\n")
        # Scoped caller cannot promote (no publish scope): the stdio
        # deny path returns the uniform no-leak payload, not a
        # scope-specific refusal — HTTP keeps it (404).
        status, payload = self.post(f"/v1/proposals/{pid}/promote", scoped, {})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not found or not available")
        # Maintainer cannot promote without a review manifest.
        status, payload = self.post(f"/v1/proposals/{pid}/promote", maintainer, {})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "promotion refused")
        self.assertTrue(any("review manifest" in e.get("error", "")
                            for e in self.entries()
                            if e["action"] == "promote" and e["result"] == "error"))
        # Reviewed but not owner-authorised: still refused.
        self.assertEqual(
            self.cli("review", pid, "--reviewer", self.ids["maintainer"]).returncode, 0)
        status, _ = self.post(f"/v1/proposals/{pid}/promote", maintainer, {})
        self.assertEqual(status, 403)
        self.assertTrue(any("owner authorisation" in e.get("error", "")
                            for e in self.entries()
                            if e["action"] == "promote" and e["result"] == "error"))
        # Authorised: the same promote() path lands the file, with
        # the git linkage the stdio ladder proves.
        self.assertEqual(self.cli("authorise", pid, "--by", "owner").returncode, 0)
        status, payload = self.post(f"/v1/proposals/{pid}/promote", maintainer, {})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["state"], "promoted")
        self.assertTrue((self.root / target).exists())
        self.assertIn("Promoted content", (self.root / target).read_text())
        head = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(payload["commit_sha"], head)
        promotes = [e for e in self.entries()
                    if e["action"] == "promote" and e["result"] == "allow"]
        self.assertEqual(len(promotes), 1)
        self.assertEqual(promotes[0]["commit_shas"], [head])

    def test_tampered_staged_file_is_quarantined_not_promoted(self):
        scoped = self.tokens[self.ids["scoped"]]
        maintainer = self.tokens[self.ids["maintainer"]]
        target = "wiki/syntheses/http-tampered.md"
        pid = self.stage(scoped, target, "# Clean\n")
        self.assertEqual(
            self.cli("review", pid, "--reviewer", self.ids["maintainer"]).returncode, 0)
        staged_file = self.state / "staging" / "proposed" / f"{pid}.md"
        staged_file.write_text("# Clean\n\nSNEAKED EDIT\n")
        self.assertEqual(self.cli("authorise", pid, "--by", "owner").returncode, 0)
        status, payload = self.post(f"/v1/proposals/{pid}/promote", maintainer, {})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "promotion refused")
        self.assertTrue(any("hash mismatch" in e.get("error", "")
                            for e in self.entries()
                            if e["action"] == "promote" and e["result"] == "error"))
        self.assertFalse((self.root / target).exists())
        self.assertTrue((self.state / "staging" / "quarantine" / f"{pid}.md").exists())
        status, payload = self.get(f"/v1/proposals/{pid}", maintainer)
        self.assertEqual(payload["state"], "quarantined")


class TestHttpLedgerEveryRequest(HttpCase):
    def test_every_request_ledgers_and_chain_verifies(self):
        scoped = self.tokens[self.ids["scoped"]]
        before = len(self.entries())
        self.get("/v1/whoami", scoped)                       # allow
        self.get("/v1/whoami", token=None)                   # auth deny
        self.get("/v1/search?q=" + quote("zqxjv alphaseed"), scoped)  # allow
        self.get("/v1/no-such-route", scoped)                # unknown route
        self.post("/v1/proposals", scoped, raw_body=b"{not json")  # bad JSON
        self.get("/v1/pages", scoped)                        # missing param
        after = len(self.entries())
        self.assertEqual(after - before, 6)
        result = ledger_mod.verify_chain(self.ledger_file())
        self.assertTrue(result["ok"], result)
        actions = [e["action"] for e in self.entries()[before:]]
        self.assertIn("whoami", actions)
        self.assertIn("auth_denied", actions)
        self.assertIn("search", actions)
        self.assertIn("http_unknown_route", actions)
        self.assertIn("http_bad_request", actions)


if __name__ == "__main__":
    unittest.main()
