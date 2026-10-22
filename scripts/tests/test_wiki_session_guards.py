#!/usr/bin/env python3
"""Tests for scripts/wiki_session_guards.py (Wave-5 build).

Pins the three guards' contracts:
  precompact    — always reminds; halts only when artefacts
                  show unfiled substance; files nothing itself.
  session-clean — clean+pushed passes; dirty or unpushed
                  fires NAMING the paths/commits; a
                  session-start marker separates this
                  session's work from pre-existing state,
                  and without one the report says the
                  separation cannot be made.
  raw layer     — create/append pass; overwrite/delete of
                  an existing filed record blocked, with
                  the remedy stated; the two named sweep
                  exceptions (memory-mirror refresh,
                  provenance-manifest regeneration) pass;
                  legitimate paths (filings creates,
                  CONVERSATION-LOG.md appends, mirror
                  refresh) are tested as carefully as the
                  blocked ones.
Plus the wiring: the guards registered as data in a
fixture register run through scripts/wiki_hooks.py, and
a failing guard's explanation surfaces in the hook
detail (surface_output).

Git fixtures are hermetic: one repo per test class, built
once (setUpClass), with a local bare repo as its "azure"
remote; tests restore what they mutate in tearDown. No
network anywhere. Fixture construction is retried with
pacing: the build VM's file mediation intermittently
returns EPERM under parallel lane load (observed
2026-10-22 — tempfile's create-probe in particular), so
fixtures live under ~/workspace/.tmp-guards/fixtures via
plain mkdir, and a fixture that cannot be built is an
environment failure, not a test failure.

Prebuilt mode (GUARDS_FIXTURES=<dir>): when the
mediation denies python-driven git outright (observed
later the same night — git init could not write the HEAD
symref across ~7 minutes of retries, 0 tests run), the
fixtures are built ONCE by the shell instead — <dir>
holds golden/{repo,remote.git}, wiring/{repo,remote.git}
and gate/ — and each class copies its tree with cp -r
and repoints the azure remote at the copy. The tests and
assertions are identical in both modes; only fixture
construction differs.

Ready mode (GUARDS_FIXTURES_READY=<dir>, takes
precedence): when even the cp -r inside python is denied
mid-copy (also observed), the shell pre-builds one
complete tree PER CLASS — <dir>/gate plus
<dir>/<ClassName>/{repo,remote.git} with the remote
already pointing at its sibling — and the classes use
them in place with ZERO fixture operations in python.
Single-use scratch: the run consumes the trees.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import contextlib
import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURE_BASE = Path("~/workspace/.tmp-guards/fixtures").expanduser()
_counter = itertools.count()


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = load("wiki_session_guards", "wiki_session_guards.py")
H = load("wiki_hooks", "wiki_hooks.py")


def mkdtemp_retry(tag="fx"):
    """A fresh fixture directory via plain mkdir (retried):
    tempfile's create-probe is the operation the VM's file
    mediation denies most under load; mkdir lands."""
    last = None
    for _ in range(12):
        d = FIXTURE_BASE / f"{tag}-{os.getpid()}-{next(_counter)}"
        try:
            d.mkdir(parents=True, exist_ok=False)
            return str(d)
        except OSError as exc:
            last = exc
            time.sleep(1.5)
    raise last


def retry_op(fn, tries=8, delay=1.0):
    """One filesystem/subprocess operation, retried: the
    mediation denies operations in bursts under load, so
    the unit of retry is the single operation, paced."""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as exc:
            last = exc
            time.sleep(delay)
    raise last


def wtext(path, text):
    retry_op(lambda: path.write_text(text, encoding="utf-8"))


def mkdirp(path):
    retry_op(lambda: path.mkdir(parents=True, exist_ok=True))


def git(root, *args, check=True):
    def once():
        r = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            raise AssertionError(f"git {args}: {r.stderr}")
        return r
    if check:
        return retry_op(once, tries=5, delay=1.2)
    return once()


def make_repo(tmp):
    last = None
    for _ in range(6):
        try:
            return _make_repo_once(tmp)
        except Exception as exc:  # environment flake — retry
            last = exc
            time.sleep(3)
    raise last


def _make_repo_once(tmp):
    root = Path(tmp) / "repo"
    bare = Path(tmp) / "remote.git"

    def init_bare():
        r = subprocess.run(["git", "init", "--bare", "--template=",
                            str(bare)], capture_output=True,
                           text=True)
        if r.returncode != 0:
            raise AssertionError(f"git init --bare: {r.stderr}")

    def init_repo():
        r = subprocess.run(["git", "init", "--template=", "-b",
                            "master", str(root)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(f"git init: {r.stderr}")

    retry_op(init_bare, tries=5, delay=1.2)
    time.sleep(0.3)
    retry_op(init_repo, tries=5, delay=1.2)
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "remote", "add", "azure", str(bare))
    mkdirp(root / "raw" / "sources" / "claude-memory")
    mkdirp(root / "raw" / "filings" / "hark")
    wtext(root / "raw" / "sources" / "x.md",
          "line one\nline two\n")
    wtext(root / "raw" / "sources" / "claude-memory"
          / "2026-10-22.md", "mirror v1\n")
    wtext(root / "raw" / "sources" / "provenance-manifest.json",
          "{}\n")
    wtext(root / "CONVERSATION-LOG.md", "log\n")
    git(root, "add", "-A")
    git(root, "commit", "-m", "initial")
    time.sleep(0.3)
    git(root, "push", "-u", "azure", "master")
    return root


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(*a, **k)
    return code, buf.getvalue()


def restore_raw(root):
    """Undo any working-tree mutation under raw/ (and drop
    the audit test's one created filing)."""
    git(root, "checkout", "--", "raw/", check=False)
    extra = root / "raw" / "filings" / "hark" / "2026-10-22-new.md"
    if extra.exists():
        extra.unlink()


def copy_prebuilt(name, tag):
    """Copy a prebuilt fixture tree (shell-built) into a
    fresh per-class dir; returns the copy's root."""
    src = Path(os.environ["GUARDS_FIXTURES"]) / name
    dst = Path(mkdtemp_retry(tag)) / "fx"

    def cp():
        r = subprocess.run(["cp", "-r", str(src), str(dst)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(f"cp -r {src}: {r.stderr}")
    retry_op(cp, tries=6, delay=1.5)
    return dst


class TestRawGuardGate(unittest.TestCase):
    """The write-time gate — plain temp dir, no git needed."""

    @classmethod
    def setUpClass(cls):
        if os.environ.get("GUARDS_FIXTURES_READY"):
            cls.root = (Path(os.environ["GUARDS_FIXTURES_READY"])
                        / "gate")
            return
        if os.environ.get("GUARDS_FIXTURES"):
            cls.root = copy_prebuilt("gate", "gate")
            return
        cls.root = Path(mkdtemp_retry("gate"))
        mkdirp(cls.root / "raw" / "sources" / "claude-memory")
        wtext(cls.root / "raw" / "sources" / "x.md", "filed\n")
        wtext(cls.root / "raw" / "sources" / "claude-memory"
              / "2026-10-22.md", "m\n")
        wtext(cls.root / "raw" / "sources"
              / "provenance-manifest.json", "{}\n")
        wtext(cls.root / "CONVERSATION-LOG.md", "log\n")

    def verdict(self, rel, op):
        return G.classify_raw_write(self.root, rel, op)

    def test_create_new_raw_file_allowed(self):
        ok, why = self.verdict("raw/sources/new.md", "create")
        self.assertTrue(ok, why)

    def test_filings_verbatim_create_allowed(self):
        ok, why = self.verdict(
            "raw/filings/hark/2026-10-22-9653f67d.md", "create")
        self.assertTrue(ok, why)

    def test_create_onto_existing_judged_as_overwrite_blocked(self):
        ok, why = self.verdict("raw/sources/x.md", "create")
        self.assertFalse(ok)
        self.assertIn("judged as overwrite", why)

    def test_append_existing_raw_allowed(self):
        ok, why = self.verdict("raw/sources/x.md", "append")
        self.assertTrue(ok, why)
        self.assertIn("append", why)

    def test_overwrite_existing_raw_blocked_with_remedy(self):
        ok, why = self.verdict("raw/sources/x.md", "overwrite")
        self.assertFalse(ok)
        self.assertIn("NEW file", why)

    def test_delete_existing_raw_blocked(self):
        ok, why = self.verdict("raw/sources/x.md", "delete")
        self.assertFalse(ok)
        self.assertIn("never deleted", why)

    def test_mirror_overwrite_allowed_named_exception(self):
        ok, why = self.verdict(
            "raw/sources/claude-memory/2026-10-22.md", "overwrite")
        self.assertTrue(ok, why)
        self.assertIn("memory mirror", why)

    def test_mirror_delete_still_blocked(self):
        # The sweep re-copies the mirror; it never deletes it.
        ok, _why = self.verdict(
            "raw/sources/claude-memory/2026-10-22.md", "delete")
        self.assertFalse(ok)

    def test_provenance_manifest_overwrite_allowed(self):
        ok, why = self.verdict(
            "raw/sources/provenance-manifest.json", "overwrite")
        self.assertTrue(ok, why)
        self.assertIn("wiki_provenance.py", why)

    def test_conversation_log_append_outside_jurisdiction(self):
        ok, why = self.verdict("CONVERSATION-LOG.md", "append")
        self.assertTrue(ok, why)
        self.assertIn("outside raw/", why)

    def test_wiki_log_append_outside_jurisdiction(self):
        ok, _why = self.verdict("wiki/log.md", "append")
        self.assertTrue(ok)

    def test_delete_of_absent_file_is_a_noop_pass(self):
        ok, _why = self.verdict("raw/sources/absent.md", "delete")
        self.assertTrue(ok)

    def test_cli_exit_codes(self):
        code, out = quiet(G.cmd_raw_guard, self.root,
                          "raw/sources/x.md", "overwrite", False)
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", out)
        code, out = quiet(G.cmd_raw_guard, self.root,
                          "raw/sources/x.md", "append", False)
        self.assertEqual(code, 0)
        self.assertIn("ALLOWED", out)


class RepoFixture(unittest.TestCase):
    PREBUILT_NAME = "golden"

    @classmethod
    def setUpClass(cls):
        if os.environ.get("GUARDS_FIXTURES_READY"):
            base = (Path(os.environ["GUARDS_FIXTURES_READY"])
                    / cls.__name__)
            cls.tmp = str(base)
            cls.root = base / "repo"
            return
        if os.environ.get("GUARDS_FIXTURES"):
            dst = copy_prebuilt(cls.PREBUILT_NAME, cls.__name__)
            cls.tmp = str(dst.parent)
            cls.root = dst / "repo"
            git(cls.root, "remote", "set-url", "azure",
                str(dst / "remote.git"))
            return
        cls.tmp = mkdtemp_retry(cls.__name__)
        cls.root = make_repo(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestRawAudit(RepoFixture):
    def tearDown(self):
        restore_raw(self.root)

    def audit(self):
        return G.raw_audit_report(self.root)

    def test_untouched_raw_passes(self):
        rep = self.audit()
        self.assertFalse(rep["fires"])
        self.assertEqual(rep["verdicts"], [])

    def test_pure_append_passes(self):
        p = self.root / "raw" / "sources" / "x.md"
        p.write_text("line one\nline two\nline three\n",
                     encoding="utf-8")
        rep = self.audit()
        self.assertFalse(rep["fires"], rep["violations"])
        self.assertEqual(rep["verdicts"][0]["kind"], "append")

    def test_rewrite_fires_and_names_file(self):
        p = self.root / "raw" / "sources" / "x.md"
        p.write_text("line one EDITED\nline two\n",
                     encoding="utf-8")
        rep = self.audit()
        self.assertTrue(rep["fires"])
        self.assertEqual(rep["violations"][0]["path"],
                         "raw/sources/x.md")
        self.assertEqual(rep["violations"][0]["kind"], "rewrite")
        code, out = quiet(G.cmd_raw_audit, self.root, False)
        self.assertEqual(code, 1)
        self.assertIn("raw/sources/x.md", out)
        self.assertIn("git checkout", out)

    def test_delete_fires(self):
        (self.root / "raw" / "sources" / "x.md").unlink()
        rep = self.audit()
        self.assertTrue(rep["fires"])
        self.assertEqual(rep["violations"][0]["kind"], "delete")

    def test_mirror_refresh_passes_as_exception(self):
        p = (self.root / "raw" / "sources" / "claude-memory"
             / "2026-10-22.md")
        p.write_text("mirror v2 — recopied by the sweep\n",
                     encoding="utf-8")
        rep = self.audit()
        self.assertFalse(rep["fires"], rep["violations"])
        self.assertEqual(rep["verdicts"][0]["kind"],
                         "mirror-refresh")

    def test_provenance_regen_passes_as_exception(self):
        p = self.root / "raw" / "sources" / "provenance-manifest.json"
        p.write_text('{"regenerated": true}\n', encoding="utf-8")
        rep = self.audit()
        self.assertFalse(rep["fires"], rep["violations"])
        self.assertEqual(rep["verdicts"][0]["kind"],
                         "provenance-regen")

    def test_new_raw_file_passes(self):
        (self.root / "raw" / "filings" / "hark"
         / "2026-10-22-new.md").write_text("filing\n",
                                           encoding="utf-8")
        rep = self.audit()
        self.assertFalse(rep["fires"], rep["violations"])
        self.assertEqual(rep["verdicts"][0]["kind"], "new")


class TestSessionClean(RepoFixture):
    def tearDown(self):
        for name in ("loose.txt", "before.txt", "after.txt",
                     "note.txt"):
            p = self.root / name
            if p.exists():
                p.unlink()
        git(self.root, "reset", "--hard", "--quiet",
            "azure/master", check=False)
        marker = G.marker_path(self.root)
        if marker is not None and marker.exists():
            marker.unlink()

    def test_clean_and_pushed_passes(self):
        rep = G.session_clean_report(self.root)
        self.assertFalse(rep["fires"], rep)
        code, out = quiet(G.cmd_session_clean, self.root,
                          False, False)
        self.assertEqual(code, 0)
        self.assertIn("clean", out)

    def test_unpushed_commit_fires_and_is_named(self):
        (self.root / "note.txt").write_text("work\n",
                                            encoding="utf-8")
        git(self.root, "add", "note.txt")
        git(self.root, "commit", "-m", "session work not pushed")
        rep = G.session_clean_report(self.root)
        self.assertTrue(rep["fires"])
        subjects = [u["subject"] for u in rep["unpushed"]]
        self.assertIn("session work not pushed", subjects)
        code, out = quiet(G.cmd_session_clean, self.root,
                          False, False)
        self.assertEqual(code, 1)
        self.assertIn("session work not pushed", out)

    def test_dirty_path_fires_and_is_named(self):
        (self.root / "loose.txt").write_text("uncommitted\n",
                                             encoding="utf-8")
        rep = G.session_clean_report(self.root)
        self.assertTrue(rep["fires"])
        self.assertIn("loose.txt", rep["dirty"])

    def test_marker_separates_session_from_preexisting(self):
        (self.root / "before.txt").write_text("old\n",
                                              encoding="utf-8")
        code, _ = quiet(G.cmd_session_clean, self.root,
                        True, False)
        self.assertEqual(code, 0)
        (self.root / "after.txt").write_text("new\n",
                                             encoding="utf-8")
        rep = G.session_clean_report(self.root)
        self.assertTrue(rep["marker"])
        self.assertEqual(rep["preexisting_dirty"], ["before.txt"])
        self.assertEqual(rep["session_dirty"], ["after.txt"])

    def test_no_marker_says_separation_cannot_be_made(self):
        marker = G.marker_path(self.root)
        if marker is not None and marker.exists():
            marker.unlink()
        (self.root / "loose.txt").write_text("x\n", encoding="utf-8")
        rep = G.session_clean_report(self.root)
        self.assertFalse(rep["marker"])
        lines = G.render_session_clean(rep)
        self.assertIn("cannot be separated",
                      "\n".join(lines))

    def test_no_upstream_fires_as_cannot_determine(self):
        solo = Path(mkdtemp_retry("solo")) / "solo"

        def init_solo():
            r = subprocess.run(["git", "init", "--template=",
                                "-b", "master", str(solo)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise AssertionError(f"git init solo: {r.stderr}")
        retry_op(init_solo, tries=6, delay=1.5)
        git(solo, "config", "user.email", "t@e.c")
        git(solo, "config", "user.name", "T")
        (solo / "f.txt").write_text("x\n", encoding="utf-8")
        git(solo, "add", "f.txt")
        git(solo, "commit", "-m", "one")
        rep = G.session_clean_report(solo)
        self.assertTrue(rep["fires"])
        self.assertIsNone(rep["unpushed"])
        self.assertIn("CANNOT DETERMINE",
                      "\n".join(G.render_session_clean(rep)))


class TestPrecompact(RepoFixture):
    def tearDown(self):
        for p in (self.root / "work.txt",
                  self.root / "staging" / "captures"
                  / "2026-10-22-draft.md"):
            if p.exists():
                p.unlink()

    def test_clean_tree_passes_with_reminder(self):
        code, out = quiet(G.cmd_precompact, self.root, False)
        self.assertEqual(code, 0)
        self.assertIn("PRECOMPACT GUARD", out)
        self.assertIn("cannot see the conversation", out)

    def test_dirty_tree_halts_with_proposal_and_files_nothing(self):
        (self.root / "work.txt").write_text("substance\n",
                                            encoding="utf-8")
        code, out = quiet(G.cmd_precompact, self.root, False)
        self.assertEqual(code, 1)
        self.assertIn("PROPOSE FILING", out)
        self.assertIn("work.txt", out)
        self.assertIn("files NOTHING itself", out)
        # the guard proposed; it did not itself commit or file
        _rc, log = G.git(self.root, "log", "--format=%s")
        self.assertNotIn("work", log)

    def test_uningested_capture_draft_halts_and_is_named(self):
        d = self.root / "staging" / "captures"
        d.mkdir(parents=True, exist_ok=True)
        (d / "2026-10-22-draft.md").write_text("draft\n",
                                               encoding="utf-8")
        rep = G.precompact_report(self.root)
        self.assertTrue(rep["fires"])
        self.assertIn("staging/captures/2026-10-22-draft.md",
                      rep["drafts"])


class TestHookWiring(RepoFixture):
    """The guards as data in a register, run by wiki_hooks."""

    PREBUILT_NAME = "wiring"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if os.environ.get("GUARDS_FIXTURES") or \
                os.environ.get("GUARDS_FIXTURES_READY"):
            return  # the wiring tree is prebuilt shell-side
        scripts = cls.root / "scripts"
        mkdirp(scripts)
        retry_op(lambda: (scripts / "wiki_session_guards.py")
                 .write_bytes((SCRIPTS / "wiki_session_guards.py")
                              .read_bytes()))
        mkdirp(cls.root / "evaluation")
        hooks = [
            {"hook_id": "h-precompact-propose-filing",
             "step": "precompact", "phase": "pre",
             "check": {"kind": "command",
                       "argv": [sys.executable,
                                "scripts/wiki_session_guards.py",
                                "precompact"],
                       "surface_output": True},
             "on_fail": "halt"},
            {"hook_id": "h-session-end-clean-tree",
             "step": "session-end", "phase": "pre",
             "check": {"kind": "command",
                       "argv": [sys.executable,
                                "scripts/wiki_session_guards.py",
                                "session-clean"],
                       "surface_output": True},
             "on_fail": "halt"},
        ]
        wtext(cls.root / "evaluation" / "hooks.jsonl",
              "".join(json.dumps(h) + "\n" for h in hooks))
        # the wiring itself is committed and pushed, so the
        # fixture tree starts CLEAN for the guard runs
        git(cls.root, "add", "-A")
        git(cls.root, "commit", "-m", "wiring fixture")
        git(cls.root, "push", "azure", "master")

    def tearDown(self):
        p = self.root / "loose.txt"
        if p.exists():
            p.unlink()

    def test_precompact_hook_passes_clean_and_surfaces_reminder(self):
        code, report = H.run_stage(self.root, "precompact",
                                   lambda: 0)
        self.assertEqual(code, 0)
        detail = report["hooks"][0]["detail"]
        self.assertIn("PRECOMPACT GUARD", detail)

    def test_session_end_hook_halts_dirty_session_before_stage(self):
        (self.root / "loose.txt").write_text("x\n", encoding="utf-8")
        ran = []
        code, report = H.run_stage(
            self.root, "session-end", lambda: ran.append(1) or 0)
        self.assertEqual(code, 1)
        self.assertEqual(ran, [])
        detail = report["hooks"][0]["detail"]
        self.assertIn("SESSION-END GUARD", detail)
        self.assertIn("loose.txt", detail)

    def test_surface_output_absent_keeps_bare_detail(self):
        hook = {"hook_id": "plain", "step": "s", "phase": "pre",
                "check": {"kind": "command",
                          "argv": [sys.executable, "-c",
                                   "print('hello')"]},
                "on_fail": "halt"}
        root = Path(mkdtemp_retry("bare"))
        mkdirp(root / "evaluation")
        wtext(root / "evaluation" / "hooks.jsonl",
              json.dumps(hook) + "\n")
        code, report = H.run_stage(root, "s", lambda: 0)
        self.assertEqual(code, 0)
        self.assertEqual(report["hooks"][0]["detail"], "exit 0")


if __name__ == "__main__":
    unittest.main()
