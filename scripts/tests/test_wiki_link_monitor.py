#!/usr/bin/env python3
"""Tests for the external-link monitor in
scripts/wiki_link_health.py (implementation wave W1.10):
on-demand liveness checks over CAPTURED source URLs, the
Bookmarker threshold discipline (broken = 404/410 only),
HEAD-then-GET, same-host pacing and the per-run cap.

Fully offline: the probe seam is faked, the clock/sleep are
fakes, and all fixtures live in a temp root — no live network
in tests.

Run:  python3 -m unittest scripts.tests.test_wiki_link_monitor -v
"""
import argparse
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

import wiki_link_health as wlh  # noqa: E402

NOW = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)

WEB_SIDECAR = {
    "source": "/tmp/wiki-clip-abc.html",
    "clip": {
        "tool": "wiki_clip.py", "kind": "web-clip",
        "url": "https://a.example/old",
        "final_url": "https://a.example/page",
    },
}
STAGED_SIDECAR = {
    "clip": {
        "tool": "wiki_clip.py", "kind": "web-clip",
        "url": "https://b.example/x",
        "final_url": "https://b.example/x",
    },
}
MEDIA_SIDECAR = {
    "source": "https://cdn.example/pic.png",
    "capture": {"tool": "wiki_clip.py", "kind": "web-clip"},
}
FEED_SIDECAR = {
    "clip": {
        "tool": "wiki_clip.py", "kind": "feed-clip",
        "feed": "https://feeds.example/rss",
        "item_link": "https://posts.example/1",
    },
}
LOCAL_SIDECAR = {"source": "/home/user/photo.png", "capture": {}}
MANIFEST = {"url": "https://a.example/page",
            "sha256": "0" * 64, "files": {}}


def build_root(root):
    web = root / "raw/captures/web"
    web.mkdir(parents=True)
    (web / "2026-10-22-a.html.ingest.json").write_text(
        json.dumps(WEB_SIDECAR), encoding="utf-8")
    (web / "2026-10-22-pic.png.ingest.json").write_text(
        json.dumps(MEDIA_SIDECAR), encoding="utf-8")
    (web / "2026-10-22-local.png.ingest.json").write_text(
        json.dumps(LOCAL_SIDECAR), encoding="utf-8")
    (web / "broken.ingest.json").write_text(
        "{not json", encoding="utf-8")
    bundle = web / "snapshots" / "a-example-page"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(
        json.dumps(MANIFEST), encoding="utf-8")
    staged = root / "staging/captures"
    staged.mkdir(parents=True)
    (staged / "2026-10-22-b.html.ingest.json").write_text(
        json.dumps(STAGED_SIDECAR), encoding="utf-8")
    (staged / "2026-10-22-feed.html.ingest.json").write_text(
        json.dumps(FEED_SIDECAR), encoding="utf-8")
    return root


class FakeProbe:
    """url -> ProbeResult | ProbeError, with a HEAD quirk:
    b.example refuses HEAD (405) and answers GET."""

    def __init__(self):
        self.calls = []
        self.table = {
            "https://a.example/page": wlh.ProbeResult(
                200, "https://a.example/page"),
            "https://a.example/old": wlh.ProbeResult(
                404, "https://a.example/old"),
            "https://cdn.example/pic.png": wlh.ProbeResult(
                403, "https://cdn.example/pic.png"),
            "https://feeds.example/rss": wlh.ProbeResult(
                429, "https://feeds.example/rss"),
            "https://posts.example/1": wlh.ProbeError("timeout"),
        }

    def __call__(self, url, method, timeout):
        self.calls.append((url, method))
        if url == "https://b.example/x":
            if method == "HEAD":
                return wlh.ProbeResult(405, url)
            return wlh.ProbeResult(200, url)
        outcome = self.table[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="monitor-root-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        build_root(self.root)


class CollectTests(Fixture):
    def test_collects_dedupes_and_names_sources(self):
        found = wlh.collect_captured_urls(self.root)
        self.assertEqual(set(found), {
            "https://a.example/page", "https://a.example/old",
            "https://b.example/x", "https://cdn.example/pic.png",
            "https://feeds.example/rss", "https://posts.example/1",
        })
        # The snapshot manifest corroborates the web sidecar.
        self.assertEqual(found["https://a.example/page"], [
            "raw/captures/web/2026-10-22-a.html.ingest.json",
            "raw/captures/web/snapshots/a-example-page/"
            "manifest.json",
        ])
        # url == final_url is collected once; local sources and
        # the malformed sidecar contributed nothing.
        self.assertEqual(found["https://b.example/x"], [
            "staging/captures/2026-10-22-b.html.ingest.json"])


class ClassifyTests(unittest.TestCase):
    def test_broken_is_404_and_410_only(self):
        self.assertEqual(wlh.classify_status(404), "broken")
        self.assertEqual(wlh.classify_status(410), "broken")
        for status, state in ((200, "ok"), (204, "ok"),
                              (301, "redirect-unfollowed"),
                              (401, "auth-required"),
                              (403, "forbidden"),
                              (418, "client-error"),
                              (429, "rate-limited"),
                              (500, "server-error"),
                              (503, "server-error")):
            self.assertEqual(wlh.classify_status(status), state,
                             status)


class RunMonitorTests(Fixture):
    def _run(self, **kw):
        kw.setdefault("probe", FakeProbe())
        kw.setdefault("delay", 0)
        kw.setdefault("now", NOW)
        kw.setdefault("sleep", lambda s: None)
        kw.setdefault("clock", lambda: 0.0)
        return wlh.run_monitor(self.root, **kw)

    def test_states_methods_and_summary(self):
        payload = self._run()
        urls = payload["urls"]
        self.assertEqual(urls["https://a.example/page"]["state"],
                         "ok")
        self.assertEqual(urls["https://a.example/old"]["state"],
                         "broken")
        self.assertEqual(
            urls["https://a.example/old"]["http_status"], 404)
        b = urls["https://b.example/x"]
        self.assertEqual(b["state"], "ok")
        self.assertEqual(b["method"], "GET")  # HEAD refused -> GET
        self.assertEqual(urls["https://cdn.example/pic.png"]
                         ["state"], "forbidden")
        self.assertEqual(urls["https://feeds.example/rss"]
                         ["state"], "rate-limited")
        posts = urls["https://posts.example/1"]
        self.assertEqual(posts["state"], "timeout")
        self.assertIsNone(posts["http_status"])
        self.assertEqual(posts["method"], "HEAD")
        for record in urls.values():
            self.assertEqual(record["checked_at"], NOW.isoformat())
            self.assertTrue(record["sources"])
        summary = payload["summary"]
        self.assertEqual(summary["captured_urls"], 6)
        self.assertEqual(summary["checked"], 6)
        self.assertEqual(summary["broken"], 1)
        self.assertEqual(summary["ok"], 2)
        self.assertEqual(summary["forbidden"], 1)
        self.assertEqual(summary["rate_limited"], 1)
        self.assertEqual(summary["timeout"], 1)
        self.assertEqual(summary["deferred_over_cap"], 0)
        self.assertEqual(payload["deferred"], [])

    def test_cap_defers_the_rest_deterministically(self):
        payload = self._run(limit=2)
        self.assertEqual(sorted(payload["urls"]), [
            "https://a.example/old", "https://a.example/page"])
        self.assertEqual(payload["deferred"], [
            "https://b.example/x", "https://cdn.example/pic.png",
            "https://feeds.example/rss", "https://posts.example/1"])
        self.assertEqual(payload["summary"]["deferred_over_cap"], 4)

    def test_same_host_pacing_only(self):
        sleeps = []
        state = {"t": 0.0}

        def clock():
            return state["t"]

        def sleep(seconds):
            sleeps.append(seconds)
            state["t"] += seconds

        self._run(delay=5.0, sleep=sleep, clock=clock)
        # Sorted order puts the two a.example URLs adjacent;
        # every other host is checked once and never paced.
        self.assertEqual(sleeps, [5.0])


class CmdMonitorTests(Fixture):
    def _args(self, out, **over):
        args = argparse.Namespace(
            out=str(out), limit=None, delay=0.0, timeout=None,
            json=False, strict=False)
        for key, value in over.items():
            setattr(args, key, value)
        return args

    def test_writes_artefact_in_emit_shape(self):
        out = self.root / "lens-data"
        with redirect_stdout(io.StringIO()):
            rc = wlh.cmd_monitor(
                self.root, self._args(out), probe=FakeProbe(),
                now=NOW, sleep=lambda s: None, clock=lambda: 0.0)
        self.assertEqual(rc, 0)
        payload = json.loads(
            (out / "external-link-health.json").read_text(
                encoding="utf-8"))
        self.assertTrue(payload["inspector_data"])
        self.assertEqual(payload["generated_by"],
                         "scripts/wiki_link_health.py monitor")
        self.assertEqual(payload["summary"]["broken"], 1)
        self.assertIn("https://a.example/old", payload["urls"])

    def test_strict_exits_1_when_anything_is_broken(self):
        out = self.root / "lens-data"
        with redirect_stdout(io.StringIO()):
            rc = wlh.cmd_monitor(
                self.root, self._args(out, strict=True),
                probe=FakeProbe(), now=NOW,
                sleep=lambda s: None, clock=lambda: 0.0)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
