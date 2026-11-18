#!/usr/bin/env python3
"""the build core acceptance tests (design §5.5 + §7 the build checks,
scoped to the gateway/Black Box core).

Proves, against fixture wikis and fixture tokens only:
- default-deny (no token, bad token, revoked, rotated, Reserved-seat);
- scoped reads with no existence leak;
- propose -> review -> owner-authorise -> promote through the
  write path, incl. tamper quarantine and git-trailer linkage;
- the Black Box chain verifies, detects tampering at the right
  entry, and anchors its head;
- searches never write query text to the ledger;
- the watcher captures create/modify/delete as unattributed-local,
  emits a restart gap marker, and chains verifiably;
- consultation metrics (§6) compute and flag violations.

Run:  python3 -m unittest discover -s tests -v   (from tools/gateway)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
GW_DIR = HERE.parents[1]
sys.path.insert(0, str(GW_DIR))

from fixtures.make_fixtures import build_fixture  # noqa: E402
from gateway import ledger as ledger_mod  # noqa: E402
from gateway.config import Config  # noqa: E402
from gateway.metrics import compute_metrics, load_proposals  # noqa: E402
from gateway.registry import Registry, RegistryError  # noqa: E402
from gateway.server import Gateway  # noqa: E402

ALPHA = "wiki/concepts/alpha.md"
BETA = "wiki/entities/beta.md"


def meta(token, session):
    return {
        "authorization": f"Bearer {token}",
        "session_id": session,
        "direction_source": {"kind": "owner", "ref": "fixture-test"},
        "task_ref": "fixture-task",
    }


class ServerProcess:
    def __init__(self, fixture):
        env = {**os.environ, **fixture["env"]}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gateway", "serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1, env=env, cwd=str(GW_DIR),
        )
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        return json.loads(line)

    def call(self, name, arguments, token, session):
        resp = self.send("tools/call", {"name": name, "arguments": arguments,
                                        "_meta": meta(token, session)})
        result = resp["result"]
        return result, json.loads(result["content"][0]["text"])

    def init(self, token, session):
        return self.send("initialize", {
            "clientInfo": {"name": "fixture-client"},
            "_meta": meta(token, session),
        })

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = build_fixture(Path(self.tmp.name))
        self.tokens = self.fx["tokens"]
        self.root = self.fx["root"]
        self.state = self.fx["state_dir"]

    def tearDown(self):
        self.tmp.cleanup()

    def ledger_file(self) -> Path:
        files = sorted((self.state / "ledger").glob("black-box-*.jsonl"))
        self.assertEqual(len(files), 1)
        return files[0]

    def cli(self, *argv):
        env = {**os.environ, **self.fx["env"]}
        out = subprocess.run([sys.executable, "-m", "gateway", *argv],
                             capture_output=True, text=True, env=env, cwd=str(GW_DIR))
        return out


class TestDefaultDeny(FixtureCase):
    def test_no_token_and_bad_token_denied(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "s0")
            result, payload = srv.call("wiki_read_page", {"path": ALPHA}, token="", session="sx")
            self.assertTrue(result["isError"])
            self.assertIn("authentication", payload["error"])
            result, payload = srv.call("wiki_read_page", {"path": ALPHA},
                                       token="wct1.collaborator-a.deadbeef", session="sx")
            self.assertTrue(result["isError"])
            entries = ledger_mod.read_entries(self.ledger_file())
            denials = [e for e in entries if e["action"] == "auth_denied"]
            self.assertGreaterEqual(len(denials), 2)
        finally:
            srv.close()

    def test_reserved_seat_fails_closed(self):
        reg = Registry(self.state / "registry.json")
        with self.assertRaises(RegistryError):
            reg.issue("reserved-agent", ["wiki:read"])
        self.assertIsNone(reg.authenticate("wct1.reserved-agent." + "ab" * 24))

    def test_revocation_and_rotation_apply_next_request(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "s1")
            _, payload = srv.call("wiki_read_page", {"path": ALPHA}, self.tokens["collaborator-a"], "s1")
            self.assertIn("Alpha", payload["text"])
            Registry(self.state / "registry.json").revoke("collaborator-a")
            result, _ = srv.call("wiki_read_page", {"path": ALPHA}, self.tokens["collaborator-a"], "s1")
            self.assertTrue(result["isError"])
            new_token = Registry(self.state / "registry.json").issue(
                "collaborator-a", ["wiki:read", "wiki:propose"],
                read_prefixes=["wiki/concepts", "wiki/entities", "wiki/syntheses", "wiki/index.md"],
                source_prefixes=["raw/sources/field-notes.md"])
            _, payload = srv.call("wiki_read_page", {"path": ALPHA}, new_token, "s1")
            self.assertIn("Alpha", payload["text"])
            result, _ = srv.call("wiki_read_page", {"path": ALPHA}, self.tokens["collaborator-a"], "s1")
            self.assertTrue(result["isError"])  # rotated-out token stays dead
        finally:
            srv.close()


class TestScopedReads(FixtureCase):
    def test_scoped_reads_and_no_existence_leak(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "s2")
            _, payload = srv.call("wiki_read_page", {"path": ALPHA}, self.tokens["collaborator-a"], "s2")
            self.assertIn("Alpha Concept", payload["text"])
            _, payload = srv.call("wiki_read_source", {"path": "raw/sources/field-notes.md"},
                                  self.tokens["collaborator-a"], "s2")
            self.assertIn("field notes", payload["text"])
            # Out-of-scope existing object, in-scope missing object, and
            # out-of-scope raw object: identical response (no leak).
            _, leak1 = srv.call("wiki_read_source", {"path": "raw/sources/restricted/mufti-only.md"},
                                self.tokens["collaborator-a"], "s2")
            _, leak2 = srv.call("wiki_read_page", {"path": "wiki/concepts/does-not-exist.md"},
                                self.tokens["collaborator-a"], "s2")
            _, leak3 = srv.call("wiki_read_page", {"path": "wiki/decisions/decision-fixture.md"},
                                self.tokens["collaborator-a"], "s2")  # decisions outside collaborator-a prefixes
            self.assertEqual(leak1, leak2)
            self.assertEqual(leak2, leak3)
            self.assertEqual(leak1["error"], "not found or not available")
        finally:
            srv.close()

    def test_search_scoped_and_ledger_has_no_query_text(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "s3")
            _, payload = srv.call("wiki_search", {"query": "zqxjv alphaseed"},
                                  self.tokens["collaborator-a"], "s3")
            self.assertEqual([r["page_id"] for r in payload["results"]], [ALPHA])
            raw = self.ledger_file().read_bytes()
            self.assertNotIn(b"zqxjv", raw)
            self.assertNotIn(b"alphaseed", raw)
            entries = ledger_mod.read_entries(self.ledger_file())
            search_entries = [e for e in entries if e["action"] == "search"]
            self.assertEqual(len(search_entries), 1)
            self.assertIn("query_hash", search_entries[0])
            self.assertEqual(search_entries[0]["files_read"], [ALPHA])
        finally:
            srv.close()

    def test_decisions_and_graph_for_full_reader(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["agent"], "s4")
            _, payload = srv.call("wiki_list_decisions", {}, self.tokens["agent"], "s4")
            self.assertEqual([d["id"] for d in payload["decisions"]], ["decision-fixture"])
            _, payload = srv.call("wiki_get_decision", {"id": "decision-fixture"},
                                  self.tokens["agent"], "s4")
            self.assertIn("fixture decision", payload["text"])
            _, payload = srv.call("wiki_graph_neighbors", {"path": ALPHA},
                                  self.tokens["agent"], "s4")
            self.assertIn(BETA, payload["outbound"])
        finally:
            srv.close()


class TestProposePromote(FixtureCase):
    def _stage(self, srv, token, session, target, content, cites):
        _, payload = srv.call("wiki_stage_proposal",
                              {"target_path": target, "content": content, "cites": cites},
                              token, session)
        return payload

    def test_full_flow_with_git_linkage(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "flow")
            staged = self._stage(srv, self.tokens["collaborator-a"], "flow",
                                 "wiki/syntheses/from-collaborator-a.md",
                                 "# From Collaborator-a\n\nStaged content.\n", [ALPHA])
            pid = staged["proposal_id"]
            self.assertFalse((self.root / "wiki/syntheses/from-collaborator-a.md").exists())

            # Collaborator-a cannot promote (no publish scope).
            result, _ = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                 self.tokens["collaborator-a"], "flow")
            self.assertTrue(result["isError"])

            # Agent cannot promote yet: write-path gates (no review, no owner act).
            srv.init(self.tokens["agent"], "flow-m")
            result, payload = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                       self.tokens["agent"], "flow-m")
            self.assertTrue(result["isError"])
            # Audit L2: the caller sees ONE uniform refusal; which
            # gate failed is recorded in the ledger only.
            self.assertEqual(payload["error"], "promotion refused")
            err_entries = [e for e in ledger_mod.read_entries(self.ledger_file())
                           if e["action"] == "promote" and e["result"] == "error"]
            self.assertTrue(any("review manifest" in e.get("error", "")
                                for e in err_entries))

            out = self.cli("review", pid, "--reviewer", "agent")
            self.assertEqual(out.returncode, 0, out.stderr)
            result, payload = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                       self.tokens["agent"], "flow-m")
            self.assertTrue(result["isError"])
            self.assertEqual(payload["error"], "promotion refused")
            err_entries = [e for e in ledger_mod.read_entries(self.ledger_file())
                           if e["action"] == "promote" and e["result"] == "error"]
            self.assertTrue(any("owner authorisation" in e.get("error", "")
                                for e in err_entries))

            out = self.cli("authorise", pid, "--by", "owner")
            self.assertEqual(out.returncode, 0, out.stderr)
            result, payload = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                       self.tokens["agent"], "flow-m")
            self.assertFalse(result["isError"], payload)
            self.assertEqual(payload["state"], "promoted")
            target = self.root / "wiki/syntheses/from-collaborator-a.md"
            self.assertTrue(target.exists())
            self.assertIn("Staged content", target.read_text())

            head = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            self.assertEqual(payload["commit_sha"], head)
            body = subprocess.run(["git", "-C", str(self.root), "log", "-1", "--format=%B"],
                                  capture_output=True, text=True).stdout
            self.assertIn("Agent: collaborator-a", body)
            self.assertIn("Session: flow", body)
            self.assertIn(f"Sources: {ALPHA}", body)
            self.assertIn(f"Operation: promote {pid}", body)

            entries = ledger_mod.read_entries(self.ledger_file())
            promotes = [e for e in entries if e["action"] == "promote" and e["result"] == "allow"]
            self.assertEqual(len(promotes), 1)
            self.assertEqual(promotes[0]["commit_shas"], [head])
            self.assertEqual(promotes[0]["actor"], "agent")
        finally:
            srv.close()

    def test_tampered_staged_file_is_quarantined(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "tamp")
            staged = self._stage(srv, self.tokens["collaborator-a"], "tamp",
                                 "wiki/syntheses/tampered.md", "# Clean\n", [ALPHA])
            pid = staged["proposal_id"]
            self.assertEqual(self.cli("review", pid, "--reviewer", "agent").returncode, 0)
            staged_file = self.state / "staging" / "proposed" / f"{pid}.md"
            staged_file.write_text("# Clean\n\nSNEAKED EDIT\n")
            self.assertEqual(self.cli("authorise", pid, "--by", "owner").returncode, 0)
            srv.init(self.tokens["agent"], "tamp-m")
            result, payload = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                       self.tokens["agent"], "tamp-m")
            self.assertTrue(result["isError"])
            # Audit L2: uniform caller message; the reason (hash
            # mismatch) is in the ledger's promote-error entry.
            self.assertEqual(payload["error"], "promotion refused")
            err_entries = [e for e in ledger_mod.read_entries(self.ledger_file())
                           if e["action"] == "promote" and e["result"] == "error"]
            self.assertTrue(any("hash mismatch" in e.get("error", "")
                                for e in err_entries))
            self.assertFalse((self.root / "wiki/syntheses/tampered.md").exists())
            self.assertTrue((self.state / "staging" / "quarantine" / f"{pid}.md").exists())
            _, status = srv.call("wiki_get_proposal_status", {"proposal_id": pid},
                                 self.tokens["agent"], "tamp-m")
            self.assertEqual(status["state"], "quarantined")
        finally:
            srv.close()

    def test_stage_target_restrictions(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "tgt")
            for bad in ("raw/sources/evil.md", "../outside.md", "wiki/access/black-box.md"):
                result, _ = srv.call("wiki_stage_proposal",
                                     {"target_path": bad, "content": "x", "cites": []},
                                     self.tokens["collaborator-a"], "tgt")
                self.assertTrue(result["isError"], bad)
        finally:
            srv.close()


class TestPlanHashBinding(FixtureCase):
    """Harvest item 6: an owner authorisation binds the SHA-256 of
    the exact staged plan it approves (pattern from
    AgriciDaniel/claude-obsidian, MIT). An approval must never be
    spendable on a different plan."""

    def _stage(self, srv, token, session, target, content, cites):
        _, payload = srv.call("wiki_stage_proposal",
                              {"target_path": target, "content": content, "cites": cites},
                              token, session)
        return payload

    def _staged_sha(self, pid):
        import hashlib
        data = (self.state / "staging" / "proposed" / f"{pid}.md").read_bytes()
        return hashlib.sha256(data).hexdigest()

    def _auth_path(self, pid):
        return self.state / "authorisations" / f"{pid}.json"

    def test_authorisation_record_carries_plan_hash(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "phb")
            pid = self._stage(srv, self.tokens["collaborator-a"], "phb",
                              "wiki/syntheses/plan-bound.md", "# Plan\n", [ALPHA])["proposal_id"]
            out = self.cli("authorise", pid, "--by", "owner")
            self.assertEqual(out.returncode, 0, out.stderr)
            record = json.loads(self._auth_path(pid).read_text())
            self.assertEqual(record["plan_sha256"], self._staged_sha(pid))
        finally:
            srv.close()

    def test_authorise_with_wrong_shown_hash_writes_nothing(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "phb2")
            pid = self._stage(srv, self.tokens["collaborator-a"], "phb2",
                              "wiki/syntheses/plan-bound-2.md", "# Plan\n", [ALPHA])["proposal_id"]
            out = self.cli("authorise", pid, "--by", "owner",
                           "--plan-sha256", "0" * 64)
            self.assertEqual(out.returncode, 2)
            self.assertIn("plan hash does not match", out.stderr)
            self.assertFalse(self._auth_path(pid).exists())
        finally:
            srv.close()

    def test_promote_refused_when_plan_changes_after_authorisation(self):
        # Review is re-done after the change so ONLY the plan-hash
        # gate can refuse: the approval named the earlier bytes.
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "phb3")
            pid = self._stage(srv, self.tokens["collaborator-a"], "phb3",
                              "wiki/syntheses/plan-bound-3.md", "# Plan v1\n",
                              [ALPHA])["proposal_id"]
            self.assertEqual(self.cli("review", pid, "--reviewer", "agent").returncode, 0)
            self.assertEqual(self.cli("authorise", pid, "--by", "owner").returncode, 0)
            staged = self.state / "staging" / "proposed" / f"{pid}.md"
            staged.write_text("# Plan v2 — swapped after approval\n")
            self.assertEqual(self.cli("review", pid, "--reviewer", "agent").returncode, 0)
            srv.init(self.tokens["agent"], "phb3-m")
            result, payload = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                       self.tokens["agent"], "phb3-m")
            self.assertTrue(result["isError"])
            self.assertEqual(payload["error"], "promotion refused")
            err_entries = [e for e in ledger_mod.read_entries(self.ledger_file())
                           if e["action"] == "promote" and e["result"] == "error"]
            self.assertTrue(any("plan hash mismatch" in e.get("error", "")
                                for e in err_entries))
            self.assertFalse((self.root / "wiki/syntheses/plan-bound-3.md").exists())
        finally:
            srv.close()

    def test_legacy_authorisation_without_hash_fails_closed(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "phb4")
            pid = self._stage(srv, self.tokens["collaborator-a"], "phb4",
                              "wiki/syntheses/plan-bound-4.md", "# Plan\n",
                              [ALPHA])["proposal_id"]
            self.assertEqual(self.cli("review", pid, "--reviewer", "agent").returncode, 0)
            # A pre-binding record: same shape as before this build.
            self._auth_path(pid).write_text(json.dumps({
                "proposal_id": pid, "authorised_by": "owner",
                "decision_ref": None, "authorised_at": "2026-10-13T00:00:00Z"}))
            srv.init(self.tokens["agent"], "phb4-m")
            result, payload = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                       self.tokens["agent"], "phb4-m")
            self.assertTrue(result["isError"])
            self.assertEqual(payload["error"], "promotion refused")
            err_entries = [e for e in ledger_mod.read_entries(self.ledger_file())
                           if e["action"] == "promote" and e["result"] == "error"]
            self.assertTrue(any("no plan hash" in e.get("error", "")
                                for e in err_entries))
        finally:
            srv.close()


class TestLifecycleProfiles(FixtureCase):
    """Harvest item 7: lifecycle-profile machinery with the
    warn-legacy default (pattern: atomicstrata/llm-wiki-compiler,
    MIT). Violations are recorded, never refused — until an Owner
    decision flips a profile to enforce."""

    PROFILE = {
        "name": "fixture-profile",
        "page_types": {"concept": {"required_fields":
                                   ["title", "type", "created", "updated",
                                    "sources", "tags"]}},
        "status_transitions": {"draft": ["verified", "published"],
                               "verified": ["published"],
                               "published": ["archived"], "archived": []},
    }
    GOOD = ("---\ntitle: New Concept\ntype: concept\ncreated: 2026-10-13\n"
            "updated: 2026-10-13\nsources: []\ntags: [fixture]\n---\n\nBody.\n")
    NO_TAGS = ("---\ntitle: New Concept\ntype: concept\ncreated: 2026-10-13\n"
               "updated: 2026-10-13\nsources: []\n---\n\nBody.\n")

    def _store(self, profile):
        from gateway.config import Config
        from gateway.store import GatewayStore
        env = dict(self.fx["env"])
        if profile is not None:
            ppath = Path(self.tmp.name) / "profile.json"
            ppath.write_text(json.dumps(profile), encoding="utf-8")
            env["GATEWAY_PROFILE"] = str(ppath)
        else:
            env["GATEWAY_PROFILE"] = str(Path(self.tmp.name) / "absent.json")
        return GatewayStore(Config(env=env))

    def _stage(self, store, content, target="wiki/concepts/from-profile.md"):
        return store.stage_proposal(
            actor="collaborator-a", session_id="prof", target_path=target,
            content=content, cites=[], direction_source={"kind": "owner"},
            task_ref="fixture")

    def test_warn_legacy_records_and_stages_anyway(self):
        store = self._store({**self.PROFILE, "mode": "warn-legacy"})
        meta = self._stage(store, self.NO_TAGS)
        self.assertEqual(meta["state"], "draft")
        check = meta["profile_check"]
        self.assertEqual(check["mode"], "warn-legacy")
        self.assertTrue(any(v["rule"] == "required-field" and "tags" in v["detail"]
                            for v in check["violations"]))

    def test_enforce_refuses_on_the_write_path(self):
        from gateway.store import StoreError
        store = self._store({**self.PROFILE, "mode": "enforce"})
        with self.assertRaises(StoreError):
            self._stage(store, self.NO_TAGS)
        meta = self._stage(store, self.GOOD)
        self.assertEqual(meta["profile_check"]["violations"], [])

    def test_status_transition_judged_against_current_page(self):
        store = self._store({**self.PROFILE, "mode": "warn-legacy"})
        existing = self.root / "wiki" / "concepts" / "statused.md"
        existing.write_text("---\ntitle: Statused\ntype: concept\n"
                            "created: 2026-10-13\nupdated: 2026-10-13\n"
                            "sources: []\ntags: [fixture]\nstatus: draft\n"
                            "---\n\nBody.\n", encoding="utf-8")
        jumped = self.GOOD.replace("tags: [fixture]",
                                   "tags: [fixture]\nstatus: archived")
        meta = self._stage(store, jumped, target="wiki/concepts/statused.md")
        self.assertTrue(any(v["rule"] == "status-transition"
                            for v in meta["profile_check"]["violations"]))
        legal = self.GOOD.replace("tags: [fixture]",
                                  "tags: [fixture]\nstatus: verified")
        meta = self._stage(store, legal, target="wiki/concepts/statused.md")
        self.assertFalse(any(v["rule"] == "status-transition"
                             for v in meta["profile_check"]["violations"]))

    def test_absent_profile_leaves_machinery_inert(self):
        store = self._store(None)
        meta = self._stage(store, self.NO_TAGS)
        self.assertIsNone(meta["profile_check"])


class TestRejectionFeedback(FixtureCase):
    """Harvest item 8: rejection reasons are stored on the proposal,
    surfaced in the staging listing, and fed into the next proposal
    for the same target (pattern: kytmanov/synto, MIT)."""

    def _stage(self, srv, token, session, target, content, cites):
        _, payload = srv.call("wiki_stage_proposal",
                              {"target_path": target, "content": content, "cites": cites},
                              token, session)
        return payload

    def test_reject_records_reason_and_status_shows_it(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "rej")
            pid = self._stage(srv, self.tokens["collaborator-a"], "rej",
                              "wiki/syntheses/rejected.md", "# Weak\n", [ALPHA])["proposal_id"]
            out = self.cli("reject", pid, "--by", "agent",
                           "--reason", "cites do not support the claim")
            self.assertEqual(out.returncode, 0, out.stderr)
            _, status = srv.call("wiki_get_proposal_status", {"proposal_id": pid},
                                 self.tokens["collaborator-a"], "rej")
            self.assertEqual(status["state"], "rejected")
            self.assertEqual(status["rejection"]["reason"],
                             "cites do not support the claim")
            self.assertEqual(status["rejection"]["by"], "agent")
        finally:
            srv.close()

    def test_rejection_requires_a_reason(self):
        out = self.cli("reject", "prop-whatever", "--by", "agent", "--reason", "  ")
        self.assertEqual(out.returncode, 2)
        self.assertIn("requires a reason", out.stderr)

    def test_listing_visibility_and_feedback_into_next_proposal(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "rej2")
            pid = self._stage(srv, self.tokens["collaborator-a"], "rej2",
                              "wiki/syntheses/retry-me.md", "# v1\n", [ALPHA])["proposal_id"]
            # Collaborator-a (no publish scope) cannot reject.
            result, _ = srv.call("wiki_reject_proposal",
                                 {"proposal_id": pid, "reason": "nope"},
                                 self.tokens["collaborator-a"], "rej2")
            self.assertTrue(result["isError"])
            # Agent rejects via the tool; the reason is stored.
            srv.init(self.tokens["agent"], "rej2-m")
            result, payload = srv.call("wiki_reject_proposal",
                                       {"proposal_id": pid,
                                        "reason": "missing the Oct-07 state"},
                                       self.tokens["agent"], "rej2-m")
            self.assertFalse(result["isError"], payload)
            self.assertEqual(payload["state"], "rejected")
            # Listing: the rejected proposal shows for its author,
            # with the reason attached.
            _, listing = srv.call("wiki_list_proposals", {"state": "rejected"},
                                  self.tokens["collaborator-a"], "rej2")
            mine = [m for m in listing["proposals"] if m["proposal_id"] == pid]
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]["rejection"]["reason"], "missing the Oct-07 state")
            # Feedback: the NEXT proposal for the same target carries
            # the earlier rejection in its meta.
            pid2 = self._stage(srv, self.tokens["collaborator-a"], "rej2",
                               "wiki/syntheses/retry-me.md", "# v2\n", [ALPHA])["proposal_id"]
            _, status2 = srv.call("wiki_get_proposal_status", {"proposal_id": pid2},
                                  self.tokens["collaborator-a"], "rej2")
            self.assertEqual(len(status2["prior_rejections"]), 1)
            self.assertEqual(status2["prior_rejections"][0]["reason"],
                             "missing the Oct-07 state")
            self.assertEqual(status2["prior_rejections"][0]["proposal_id"], pid)
        finally:
            srv.close()


class TestGatewayHardening(FixtureCase):
    """Harvest item 11 (pattern: flsteven87/your-llm-wiki-fl, MIT):
    reads carry a SHA-256 etag; a promotion may pin the target's
    etag and is refused if the target moved underneath it; store
    writes are atomic (temp + fsync + rename, nothing left over)."""

    def _stage(self, srv, token, session, target, content, cites):
        _, payload = srv.call("wiki_stage_proposal",
                              {"target_path": target, "content": content, "cites": cites},
                              token, session)
        return payload

    def _arm(self, pid):
        self.assertEqual(self.cli("review", pid, "--reviewer", "agent").returncode, 0)
        self.assertEqual(self.cli("authorise", pid, "--by", "owner").returncode, 0)

    def test_read_page_returns_sha256_etag(self):
        import hashlib
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["agent"], "etag")
            _, payload = srv.call("wiki_read_page", {"path": ALPHA},
                                  self.tokens["agent"], "etag")
            expect = hashlib.sha256((self.root / ALPHA).read_bytes()).hexdigest()
            self.assertEqual(payload["etag"], expect)
        finally:
            srv.close()

    def test_promote_with_matching_etag_succeeds_stale_etag_refused(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["agent"], "etag2")
            _, before = srv.call("wiki_read_page", {"path": ALPHA},
                                 self.tokens["agent"], "etag2")
            # Stale etag: refused, target untouched.
            srv.init(self.tokens["collaborator-a"], "etag2-c")
            pid = self._stage(srv, self.tokens["collaborator-a"], "etag2-c", ALPHA,
                              "# Alpha v2\n\nRewritten.\n", [ALPHA])["proposal_id"]
            self._arm(pid)
            srv.init(self.tokens["agent"], "etag2-m")
            result, payload = srv.call(
                "wiki_promote_proposal",
                {"proposal_id": pid, "expected_target_etag": "0" * 64},
                self.tokens["agent"], "etag2-m")
            self.assertTrue(result["isError"])
            self.assertEqual(payload["error"], "promotion refused")
            err_entries = [e for e in ledger_mod.read_entries(self.ledger_file())
                           if e["action"] == "promote" and e["result"] == "error"]
            self.assertTrue(any("etag mismatch" in e.get("error", "")
                                for e in err_entries))
            self.assertNotIn("Rewritten", (self.root / ALPHA).read_text())
            # Matching etag: the same promotion now goes through.
            result, payload = srv.call(
                "wiki_promote_proposal",
                {"proposal_id": pid, "expected_target_etag": before["etag"]},
                self.tokens["agent"], "etag2-m")
            self.assertFalse(result["isError"], payload)
            self.assertIn("Rewritten", (self.root / ALPHA).read_text())
        finally:
            srv.close()

    def test_new_page_promotion_can_require_absence(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "etag3")
            pid = self._stage(srv, self.tokens["collaborator-a"], "etag3",
                              "wiki/syntheses/brand-new.md", "# New\n", [ALPHA])["proposal_id"]
            self._arm(pid)
            srv.init(self.tokens["agent"], "etag3-m")
            # A string etag for a target that does not exist: refuse.
            result, _ = srv.call("wiki_promote_proposal",
                                 {"proposal_id": pid, "expected_target_etag": "a" * 64},
                                 self.tokens["agent"], "etag3-m")
            self.assertTrue(result["isError"])
            # Null etag = "must still be absent": promote.
            result, payload = srv.call("wiki_promote_proposal",
                                       {"proposal_id": pid, "expected_target_etag": None},
                                       self.tokens["agent"], "etag3-m")
            self.assertFalse(result["isError"], payload)
        finally:
            srv.close()

    def test_atomic_writes_leave_no_temp_files(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["collaborator-a"], "etag4")
            pid = self._stage(srv, self.tokens["collaborator-a"], "etag4",
                              "wiki/syntheses/atomic.md", "# A\n", [ALPHA])["proposal_id"]
            self._arm(pid)
            srv.init(self.tokens["agent"], "etag4-m")
            result, payload = srv.call("wiki_promote_proposal", {"proposal_id": pid},
                                       self.tokens["agent"], "etag4-m")
            self.assertFalse(result["isError"], payload)
            leftovers = [str(p) for p in self.state.rglob("*.tmp")]
            leftovers += [str(p) for p in self.root.rglob("*.tmp")]
            self.assertEqual(leftovers, [])
        finally:
            srv.close()


class TestAuditHardening(FixtureCase):
    """Security-audit fixes (2026-10-13 audit: gateway L2, L3, L4)."""

    def _stage(self, srv, token, session, target, content, cites):
        _, payload = srv.call("wiki_stage_proposal",
                              {"target_path": target, "content": content,
                               "cites": cites}, token, session)
        return payload

    def test_corrupt_registry_denies_all_without_crashing(self):
        # Audit L3: a corrupt registry.json must deny-all and be
        # ledgered loudly — never crash the server.
        registry_path = self.state / "registry.json"
        self.assertTrue(registry_path.exists())
        registry_path.write_text("{ this is not json", encoding="utf-8")
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["agent"], "corrupt")
            result, payload = srv.call("wiki_whoami", {},
                                       self.tokens["agent"], "corrupt")
            self.assertTrue(result["isError"])
            self.assertIn("authentication required", payload["error"])
            # Still alive: a second call is answered the same way.
            result, payload = srv.call("wiki_whoami", {},
                                       self.tokens["agent"], "corrupt")
            self.assertTrue(result["isError"])
        finally:
            srv.close()
        entries = ledger_mod.read_entries(self.ledger_file())
        denials = [e for e in entries if e["action"] == "auth_denied"]
        self.assertTrue(denials)
        self.assertTrue(any("registry_error" in e for e in denials),
                        "corrupt-registry denials must name the cause")

    def test_blackbox_read_is_ledgered(self):
        # Audit L3: reading the Black Box is itself recorded — and
        # the read never includes itself.
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["agent"], "bbread")
            srv.call("wiki_search", {"query": "alpha"},
                     self.tokens["agent"], "bbread")
            _, payload = srv.call("wiki_blackbox_my_activity", {},
                                  self.tokens["agent"], "bbread")
            returned = payload["entries"]
            self.assertTrue(returned)
            self.assertTrue(all(e["action"] != "blackbox_read"
                                for e in returned))
        finally:
            srv.close()
        entries = ledger_mod.read_entries(self.ledger_file())
        reads = [e for e in entries if e["action"] == "blackbox_read"]
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0]["actor"], "agent")
        self.assertEqual(reads[0]["queried_actor"], "agent")
        self.assertEqual(reads[0]["entries_returned"], len(returned))

    def test_commit_message_fields_are_single_line(self):
        # Audit L4: newlines in client-supplied session ids and
        # citations must not forge extra commit trailers.
        srv = ServerProcess(self.fx)
        try:
            evil_session = "flow\nOperation: forged-op"
            srv.init(self.tokens["collaborator-a"], evil_session)
            staged = self._stage(
                srv, self.tokens["collaborator-a"], evil_session,
                "wiki/syntheses/trailer-test.md", "# Trailer test\n",
                [ALPHA + "\nAgent: mallory"])
            pid = staged["proposal_id"]
            self.assertEqual(
                self.cli("review", pid, "--reviewer", "agent").returncode, 0)
            self.assertEqual(
                self.cli("authorise", pid, "--by", "owner").returncode, 0)
            srv.init(self.tokens["agent"], "l4-m")
            result, payload = srv.call("wiki_promote_proposal",
                                       {"proposal_id": pid},
                                       self.tokens["agent"], "l4-m")
            self.assertFalse(result["isError"], payload)
        finally:
            srv.close()
        body = subprocess.run(
            ["git", "-C", str(self.root), "log", "-1", "--format=%B"],
            capture_output=True, text=True).stdout
        lines = [ln for ln in body.splitlines() if ln.strip()]
        self.assertIn(f"Operation: promote {pid}", lines)
        self.assertNotIn("Operation: forged-op", lines)
        self.assertNotIn("Agent: mallory", lines)
        self.assertEqual(
            sum(1 for ln in lines if ln.startswith("Agent: ")), 1)
        self.assertTrue(any(ln.startswith("Session: flow Operation:")
                            for ln in lines))


class TestLedger(FixtureCase):
    def _drive_traffic(self):
        srv = ServerProcess(self.fx)
        try:
            srv.init(self.tokens["agent"], "led")
            srv.call("wiki_search", {"query": "alpha"}, self.tokens["agent"], "led")
            srv.call("wiki_read_page", {"path": ALPHA}, self.tokens["agent"], "led")
            srv.call("wiki_lint_run", {}, self.tokens["agent"], "led")
        finally:
            srv.close()

    def test_chain_verifies_and_detects_tampering(self):
        self._drive_traffic()
        path = self.ledger_file()
        result = ledger_mod.verify_chain(path)
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(result["entries"], 4)
        entries = ledger_mod.read_entries(path)
        self.assertEqual(entries[0]["action"], "genesis")
        self.assertIn("schema_version", entries[0])

        lines = path.read_text(encoding="utf-8").splitlines()
        target_seq = 2
        tampered = list(lines)
        row = tampered[target_seq]
        tampered[target_seq] = row.replace('"actor":"agent"', '"actor":"mallory"')
        self.assertNotEqual(tampered[target_seq], row)
        copy_path = Path(self.tmp.name) / "tampered.jsonl"
        copy_path.write_text("\n".join(tampered) + "\n", encoding="utf-8")
        result = ledger_mod.verify_chain(copy_path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["bad_seq"], target_seq)

    def test_anchor_records_chain_head(self):
        self._drive_traffic()
        path = self.ledger_file()
        entries = ledger_mod.read_entries(path)
        out = Path(self.tmp.name) / "anchor.json"
        record = ledger_mod.anchor(path, out, self.root)
        self.assertEqual(record["entry_hash"], entries[-1]["entry_hash"])
        self.assertEqual(record["seq"], entries[-1]["seq"])
        self.assertIn(f"Blackbox-Head: {entries[-1]['entry_hash']}", record["git_trailers"])
        on_disk = json.loads(out.read_text())
        self.assertEqual(on_disk["entry_hash"], entries[-1]["entry_hash"])


class TestWatcher(unittest.TestCase):
    def test_watcher_captures_events_gap_and_chain(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            tree = base / "tree"
            wstate = base / "wstate"
            (tree / "sub").mkdir(parents=True)
            (tree / "a.md").write_text("one\n")
            (tree / "sub" / "b.md").write_text("two\n")
            watcher = GW_DIR / "watcher" / "watcher.py"

            def run_once():
                out = subprocess.run(
                    [sys.executable, str(watcher), "--root", str(tree),
                     "--state-dir", str(wstate), "--once"],
                    capture_output=True, text=True)
                self.assertEqual(out.returncode, 0, out.stderr)
                return json.loads(out.stdout)

            self.assertEqual(run_once()["events"], 0)  # baseline, silent
            (tree / "a.md").write_text("one\nmodified\n")
            (tree / "c.md").write_text("three\n")
            (tree / "sub" / "b.md").unlink()
            self.assertEqual(run_once()["events"], 3)

            files = sorted(wstate.glob("watcher-*.jsonl"))
            self.assertEqual(len(files), 1)
            entries = ledger_mod.read_entries(files[0])
            kinds = sorted(e["event_kind"] for e in entries if e["action"] == "watcher_event")
            self.assertEqual(kinds, ["create", "delete", "modify"])
            for e in entries:
                if e["action"] == "watcher_event":
                    self.assertEqual(e["attribution"], "unattributed-local")
                    self.assertEqual(e["observer"], "local-watcher")
            gaps = [e for e in entries if e["action"] == "watcher_gap"]
            self.assertGreaterEqual(len(gaps), 1)
            self.assertIn("last_heartbeat", gaps[0])
            result = ledger_mod.verify_chain(files[0])
            self.assertTrue(result["ok"], result)


class TestMetrics(FixtureCase):
    def test_consultation_metrics(self):
        cfg = Config(env={**self.fx["env"], "PATH": "/usr/bin:/bin"})
        cfg.wiki_root = self.root
        cfg.state_dir = self.state
        cfg.registry_path = self.state / "registry.json"
        cfg.ledger_dir = self.state / "ledger"
        cfg.staging_dir = self.state / "staging"
        cfg.reviews_dir = self.state / "reviews"
        cfg.authorisations_dir = self.state / "authorisations"
        cfg.anchors_dir = self.state / "anchors"
        gw = Gateway(cfg)

        def rpc(method, params):
            return gw.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

        def call(name, args, token, session):
            resp = rpc("tools/call", {"name": name, "arguments": args, "_meta": meta(token, session)})
            return json.loads(resp["result"]["content"][0]["text"])

        rpc("initialize", {"clientInfo": {"name": "metrics-fixture"},
                           "_meta": meta(self.tokens["collaborator-a"], "m1")})
        call("wiki_search", {"query": "zqxjv alphaseed"}, self.tokens["collaborator-a"], "m1")
        call("wiki_read_page", {"path": ALPHA}, self.tokens["collaborator-a"], "m1")
        staged = call("wiki_stage_proposal",
                      {"target_path": "wiki/syntheses/metric.md", "content": "# M\n",
                       "cites": [ALPHA, BETA]},
                      self.tokens["collaborator-a"], "m1")
        self.assertIn("proposal_id", staged)

        rpc("initialize", {"clientInfo": {"name": "metrics-fixture"},
                           "_meta": meta(self.tokens["collaborator-b"], "m2")})
        call("wiki_stage_proposal",
             {"target_path": "wiki/concepts/metric2.md", "content": "# M2\n", "cites": []},
             self.tokens["collaborator-b"], "m2")

        entries = ledger_mod.read_entries(gw.ledger.path)
        proposals = load_proposals(cfg.staging_dir)
        report = compute_metrics(entries, proposals)

        collaborator_a_tasks = {t["session_id"]: t for t in report["identities"]["collaborator-a"]["tasks"]}
        m1 = collaborator_a_tasks["m1"]
        self.assertTrue(m1["consulted"])
        self.assertTrue(m1["read_before_write"])
        self.assertEqual(m1["citation_coverage"], 0.5)
        self.assertEqual(m1["consultation_depth"], 0.5)
        collaborator_a_signals = {v["signal"] for v in report["identities"]["collaborator-a"]["violations"]}
        self.assertIn("citation_coverage", collaborator_a_signals)
        self.assertIn("consultation_depth", collaborator_a_signals)

        ag_signals = {v["signal"] for v in report["identities"]["collaborator-b"]["violations"]}
        self.assertIn("consulted", ag_signals)


if __name__ == "__main__":
    unittest.main()
