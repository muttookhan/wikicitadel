"""Tests for scripts/wiki_dedupe.py (build-list W1.9) and its
wiring into the three append doors: the shared design —
text-as-identity, comment-bearing copy wins,
backup-before-rewrite, every decision logged with its
survivor named; vocabulary-constrained filing on the
router's proposals; and the consolidation-exclusion
registry (declined while unchanged, re-opened by change).

The safety properties are the point and are proven here:
a comment-bearing duplicate survives over a bare one, and
nothing is lost when fingerprints collide. Run:
python3 -m unittest scripts.tests.test_wiki_dedupe
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_capture as wc  # noqa: E402
import wiki_dedupe as wd  # noqa: E402
import wiki_filing_router as wfr  # noqa: E402
import wiki_mailcapture as mc  # noqa: E402
import wiki_staging_inbox as wsi  # noqa: E402

OWNER = "owner@example.com"
NOW1 = datetime(2026, 10, 21, 8, 4, tzinfo=timezone.utc)
NOW2 = datetime(2026, 10, 22, 9, 15, tzinfo=timezone.utc)
REAL_TEMPLATES = SCRIPTS.parent / "templates" / "capture"


def make_root(prefix):
    root = Path(tempfile.mkdtemp(prefix=prefix))
    return root


class IdentityTests(unittest.TestCase):
    def test_blob_oid_matches_git(self):
        # The empty blob and the Pro Git "hello" blob: known
        # git OIDs, computed here without git.
        self.assertEqual(
            wd.blob_oid(b""),
            "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")
        self.assertEqual(
            wd.blob_oid(b"hello\n"),
            "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_fingerprint_ignores_case_space_and_when(self):
        a = "The Lens Report\n\nRead at 2026-10-21 08:04 UTC."
        b = "the lens   report\nread at 2026-10-22."
        self.assertEqual(wd.fingerprint(a), wd.fingerprint(b))

    def test_fingerprint_is_text_not_wording_free(self):
        self.assertNotEqual(wd.fingerprint("alpha body"),
                            wd.fingerprint("beta body"))

    def test_comment_is_not_identity_but_is_commentary(self):
        bare = "shared body text"
        noted = "shared body text\n<!-- check this -->"
        self.assertEqual(wd.fingerprint(bare),
                         wd.fingerprint(noted))
        self.assertFalse(wd.has_commentary(bare))
        self.assertTrue(wd.has_commentary(noted))
        self.assertTrue(wd.has_commentary("x ^[mark: raw/a#L1]"))

    def test_harness_comments_are_not_commentary(self):
        self.assertFalse(wd.has_commentary(
            "body\n<!-- write from here -->"))


class DecideTests(unittest.TestCase):
    def test_distinct(self):
        d = wd.decide("one body", "another body")
        self.assertEqual(d["outcome"], "distinct")
        self.assertIsNone(d["survivor"])

    def test_exact_duplicate(self):
        d = wd.decide("same body", "Same   Body")
        self.assertEqual(d["outcome"], "exact-duplicate")
        self.assertEqual(d["survivor"], "existing")

    def test_comment_bearing_incoming_wins(self):
        d = wd.decide("bare body", "bare body <!-- noted -->")
        self.assertEqual(d["outcome"], "incoming-wins")
        self.assertEqual(d["survivor"], "incoming")

    def test_comment_bearing_existing_wins(self):
        d = wd.decide("bare body <!-- noted -->", "bare body")
        self.assertEqual(d["outcome"], "existing-wins")
        self.assertEqual(d["survivor"], "existing")

    def test_two_different_annotations_collide(self):
        d = wd.decide("body <!-- first -->",
                      "body <!-- second -->")
        self.assertEqual(d["outcome"], "collision-keep-both")
        self.assertEqual(d["survivor"], "both")


class BackupAndLogTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root("dedupe-fix-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_backup_before_rewrite_is_literal(self):
        p = self.root / "staging" / "captures" / "d.md"
        p.parent.mkdir(parents=True)
        p.write_text("version one", encoding="utf-8")
        rel = wd.backup_before_rewrite(self.root, p,
                                       door="test")
        backup = self.root / rel
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(encoding="utf-8"),
                         "version one")
        p.write_text("version two", encoding="utf-8")
        rel2 = wd.backup_before_rewrite(self.root, p,
                                        door="test")
        self.assertNotEqual(rel, rel2)  # never overwritten

    def test_backup_refuses_a_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            wd.backup_before_rewrite(self.root, "nope.md",
                                     door="test")

    def test_log_names_the_survivor(self):
        wd.log_decision(self.root, {
            "door": "test", "outcome": "existing-wins",
            "survivor": "staging/captures/a.md",
            "fingerprint": "ab" * 32, "backup": None})
        lines = (self.root / wd.LOG_REL).read_text(
            encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        self.assertEqual(rec["survivor"],
                         "staging/captures/a.md")
        self.assertEqual(rec["kind"], "dedupe-decision")


class InboxDoorTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root("dedupe-inbox-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.staging = self.root / "staging"

    def _log(self):
        p = self.staging / "dedupe-log.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in
                p.read_text(encoding="utf-8").splitlines()]

    def test_exact_duplicate_creates_no_second_item(self):
        a = wsi.add_item(self.staging, "Note", "shared body")
        b = wsi.add_item(self.staging, "Note again",
                         "shared body")
        self.assertEqual(b["id"], a["id"])
        self.assertTrue(b["duplicate"])
        self.assertEqual(len(wsi.list_items(self.staging)), 1)
        self.assertEqual(self._log()[-1]["survivor"], a["id"])

    def test_comment_bearing_copy_survives_over_bare(self):
        a = wsi.add_item(self.staging, "Note", "shared body")
        path = self.staging / "items" / (a["id"] + ".md")
        out = wsi.add_item(self.staging, "Note",
                           "shared body\n<!-- verified -->")
        self.assertEqual(out["dedupe"], "incoming-wins")
        self.assertEqual(len(wsi.list_items(self.staging)), 1)
        # the surviving item file is the comment-bearing one
        self.assertIn("<!-- verified -->",
                      path.read_text(encoding="utf-8"))
        # ...and the bare copy survives as the backup
        backup = self.staging / out["backup"]
        self.assertTrue(backup.is_file())
        self.assertNotIn("<!-- verified -->",
                         backup.read_text(encoding="utf-8"))
        self.assertIn("shared body",
                      backup.read_text(encoding="utf-8"))
        self.assertEqual(self._log()[-1]["survivor"], a["id"])

    def test_fingerprint_collision_loses_nothing(self):
        a = wsi.add_item(self.staging, "Note",
                         "shared body\n<!-- first -->")
        b = wsi.add_item(self.staging, "Note",
                         "shared body\n<!-- second -->")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(b["dedupe"], "collision-keep-both")
        texts = [(self.staging / "items" / (i["id"] + ".md"))
                 .read_text(encoding="utf-8")
                 for i in wsi.list_items(self.staging)]
        self.assertTrue(any("<!-- first -->" in t
                            for t in texts))
        self.assertTrue(any("<!-- second -->" in t
                            for t in texts))
        self.assertEqual(self._log()[-1]["outcome"],
                         "collision-keep-both")


def _msg(mid, subject, body, received="2026-10-20T12:00:00Z"):
    return {"id": mid, "from": OWNER, "subject": subject,
            "body": body, "direction": "inbound",
            "received_at": received}


class MailDoorTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root("dedupe-mail-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def _scan(self, messages):
        f = self.root / "export.json"
        f.write_text(json.dumps({"messages": messages}),
                     encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = mc.main(["scan", str(f), "--root",
                          str(self.root)])
        self.assertEqual(rc, 0)
        return out.getvalue()

    def _draft(self):
        return next((self.root / "staging/captures").glob("*.md"))

    def _log(self):
        p = self.root / wd.LOG_REL
        if not p.exists():
            return []
        return [json.loads(l) for l in
                p.read_text(encoding="utf-8").splitlines()]

    def test_duplicate_append_under_a_new_id_is_not_appended(
            self):
        self._scan([_msg("msg_" + "1" * 32, "Lens idea @idea",
                         body="one")])
        report = self._scan([_msg(
            "msg_" + "2" * 32, "Lens idea +", body="one",
            received="2026-10-20T12:05:00Z")])
        self.assertIn("duplicate-append", report)
        text = self._draft().read_text(encoding="utf-8")
        self.assertNotIn("## Appended", text)
        # nothing lost: both messages stand raw
        self.assertEqual(
            len(list((self.root / "raw/captures/email")
                     .glob("*.md"))), 2)
        self.assertEqual(self._log()[-1]["outcome"],
                         "exact-duplicate")

    def test_comment_bearing_append_supersedes_bare(self):
        self._scan([_msg("msg_" + "3" * 32, "Lens idea @idea",
                         body="bare text")])
        report = self._scan([_msg(
            "msg_" + "4" * 32, "Lens idea +",
            body="bare text\n<!-- checked against the repo -->",
            received="2026-10-20T12:05:00Z")])
        self.assertIn("superseded", report)
        text = self._draft().read_text(encoding="utf-8")
        self.assertIn("<!-- checked against the repo -->", text)
        # the bare version survives as the named backup
        backups = list((self.root / "staging"
                        / "dedupe-backups").rglob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertNotIn("checked against the repo",
                         backups[0].read_text(encoding="utf-8"))
        rec = self._log()[-1]
        self.assertEqual(rec["outcome"], "incoming-wins")
        self.assertEqual(rec["backup"],
                         str(backups[0].relative_to(self.root)))

    def test_ordinary_append_still_happens_and_backs_up(self):
        self._scan([_msg("msg_" + "5" * 32, "Lens idea @idea",
                         body="one")])
        self._scan([_msg("msg_" + "6" * 32, "Lens idea +",
                         body="two",
                         received="2026-10-20T12:05:00Z")])
        text = self._draft().read_text(encoding="utf-8")
        self.assertEqual(text.count("## Appended"), 1)
        backups = list((self.root / "staging"
                        / "dedupe-backups").rglob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertNotIn("## Appended",
                         backups[0].read_text(encoding="utf-8"))


class CaptureDoorTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root("dedupe-capture-")
        self.addCleanup(shutil.rmtree, self.root, True)
        dest = self.root / "templates" / "capture"
        dest.mkdir(parents=True)
        for tpl in REAL_TEMPLATES.glob("*.md"):
            shutil.copy(tpl, dest / tpl.name)

    def test_same_text_another_day_is_refused_with_survivor(
            self):
        rel = wc.new_capture("note", "Dup check", now=NOW1,
                             root=self.root)
        with self.assertRaises(wc.CaptureError) as ctx:
            wc.new_capture("note", "Dup check", now=NOW2,
                           root=self.root)
        self.assertIn(rel, str(ctx.exception))
        drafts = list((self.root / "staging/captures")
                      .glob("*.md"))
        self.assertEqual(len(drafts), 1)
        lines = (self.root / wd.LOG_REL).read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[-1])["survivor"],
                         rel)


class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root("dedupe-vocab-")
        self.addCleanup(shutil.rmtree, self.root, True)
        reg = self.root / "evaluation" / "tag-registry.jsonl"
        reg.parent.mkdir(parents=True)
        reg.write_text("\n".join([
            json.dumps({"kind": "header"}),
            json.dumps({"kind": "concept",
                        "prefLabel": "lens",
                        "altLabels": ["portal"],
                        "status": "active"}),
            json.dumps({"kind": "concept",
                        "prefLabel": "old-tag",
                        "status": "deprecated",
                        "replacedBy": "lens"}),
        ]) + "\n", encoding="utf-8")

    def test_registered_and_altlabel_tags_pass(self):
        res = wd.vocabulary_check({"tags": "[lens, portal]"},
                                  self.root)
        self.assertTrue(res["ok"], res["violations"])

    def test_unregistered_tag_is_a_violation(self):
        res = wd.vocabulary_check({"tags": "[nope]"}, self.root)
        self.assertFalse(res["ok"])
        self.assertIn("unregistered tag", res["violations"][0])

    def test_deprecated_tag_is_a_violation(self):
        res = wd.vocabulary_check({"tags": "[old-tag]"},
                                  self.root)
        self.assertFalse(res["ok"])
        self.assertIn("deprecated tag", res["violations"][0])

    def test_adopted_relation_passes_undeclared_fails(self):
        ok = wd.vocabulary_check(
            {"supersedes": "wiki/a.md", "grounded_by": "wiki/b.md"},
            self.root)
        self.assertTrue(ok["ok"], ok["violations"])
        self.assertEqual(sorted(ok["relations"]),
                         ["grounded_by", "supersedes"])
        bad = wd.vocabulary_check({"based_on": "wiki/a.md"},
                                  self.root)
        self.assertFalse(bad["ok"])
        self.assertIn("undeclared relation field",
                      bad["violations"][0])

    def test_router_proposals_carry_the_check(self):
        p = self.root / "f.md"
        p.write_text("---\ntitle: X\ntype: filing\nby: grok\n"
                     "tags: [lens]\n---\n\nBody.\n",
                     encoding="utf-8")
        prop = wfr.route_item(p, root=str(self.root))
        self.assertIn("vocabulary", prop)
        self.assertTrue(prop["vocabulary"]["ok"])
        p.write_text("---\ntitle: X\ntype: filing\nby: grok\n"
                     "tags: [nope]\n---\n\nBody.\n",
                     encoding="utf-8")
        prop = wfr.route_item(p, root=str(self.root))
        self.assertFalse(prop["vocabulary"]["ok"])


class ExclusionTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root("dedupe-excl-")
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "a.md").write_text("page a\n",
                                       encoding="utf-8")
        (self.root / "b.md").write_text("page b\n",
                                       encoding="utf-8")

    def test_declined_pair_is_excluded_while_unchanged(self):
        self.assertEqual(
            wd.check_pair(self.root, "a.md", "b.md")["state"],
            "clear")
        rec = wd.record_decline(self.root, "b.md", "a.md",
                                 by="owner", reason="keep both",
                                 at="2026-10-22")
        self.assertEqual(rec["pair"], ["a.md", "b.md"])
        rep = wd.check_pair(self.root, "a.md", "b.md")
        self.assertEqual(rep["state"], "excluded")
        self.assertEqual(rep["decided_by"], "owner")

    def test_change_reopens_the_pair(self):
        wd.record_decline(self.root, "a.md", "b.md",
                          by="owner", reason="keep both",
                          at="2026-10-22")
        (self.root / "b.md").write_text("page b, revised\n",
                                        encoding="utf-8")
        rep = wd.check_pair(self.root, "a.md", "b.md")
        self.assertEqual(rep["state"], "changed")
        self.assertEqual(rep["changed_sides"], ["b.md"])

    def test_registry_is_append_only(self):
        wd.record_decline(self.root, "a.md", "b.md",
                          by="owner", reason="one",
                          at="2026-10-22")
        wd.record_decline(self.root, "a.md", "b.md",
                          by="owner", reason="two",
                          at="2026-10-22")
        lines = (self.root / wd.EXCLUSIONS_REL).read_text(
            encoding="utf-8").splitlines()
        kinds = [json.loads(l)["kind"] for l in lines]
        self.assertEqual(kinds, ["header",
                                 "consolidation-exclusion",
                                 "consolidation-exclusion"])
        self.assertEqual(
            len(wd.load_exclusions(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
