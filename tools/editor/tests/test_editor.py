#!/usr/bin/env python3
"""Tests for tools/editor (the local wiki editor; 15-gap item 6).

Stdlib unittest only, against a temp wiki fixture -- the real
corpus is never touched. Core logic is tested directly; one
live-server smoke test runs on an ephemeral loopback port.

Run (from the repo root):
    python3 -m unittest tools.editor.tests.test_editor -v
or:
    python3 -m unittest discover -s tools/editor/tests -v
"""

import hashlib
import http.client
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.editor import core  # noqa: E402
from tools.editor import preview  # noqa: E402
from tools.editor import server as editor_server  # noqa: E402

TODAY = "2026-10-20"

ALPHA = """---
title: "Alpha  Page"
type: concept
created: 2026-10-12
updated: 2026-10-12
sources: ["raw/sources/alpha.md"]
tags: [alpha,  spaced]
stage: budding
x-custom: keep  me   exactly
---

# Alpha

Original body.
"""

ALPHA_FRONTMATTER = """---
title: "Alpha  Page"
type: concept
created: 2026-10-12
updated: 2026-10-12
sources: ["raw/sources/alpha.md"]
tags: [alpha,  spaced]
stage: budding
x-custom: keep  me   exactly
---
"""

BETA = """---
title: Beta
type: entity
created: 2026-10-13
updated: 2026-10-13
sources: []
tags: []
---

# Beta

Beta body.
"""

NO_UPDATED = """---
title: No Updated Field
type: query
created: 2026-10-14
sources: []
tags: []
---

# No Updated

Body without an updated field in frontmatter.
"""

PLAIN = "# Plain\n\nA page with no frontmatter at all.\n"


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.wiki = tmp / "wiki"
        (self.wiki / "concepts").mkdir(parents=True)
        (self.wiki / "entities").mkdir(parents=True)
        (self.wiki / "concepts" / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (self.wiki / "entities" / "beta.md").write_text(BETA, encoding="utf-8")
        (self.wiki / "no-updated.md").write_text(NO_UPDATED, encoding="utf-8")
        (self.wiki / "plain.md").write_text(PLAIN, encoding="utf-8")
        self.backups = tmp / "backups"
        self.outside = tmp / "outside.md"
        self.outside.write_text("outside the wiki\n", encoding="utf-8")


class TestListAndRead(FixtureCase):
    def test_list_pages_with_title_and_stage(self) -> None:
        pages = core.list_pages(self.wiki)
        by_path = {p["path"]: p for p in pages}
        self.assertEqual(
            set(by_path),
            {"concepts/alpha.md", "entities/beta.md", "no-updated.md", "plain.md"},
        )
        self.assertEqual(by_path["concepts/alpha.md"]["title"], "Alpha  Page")
        self.assertEqual(by_path["concepts/alpha.md"]["stage"], "budding")
        self.assertEqual(by_path["concepts/alpha.md"]["type"], "concept")
        self.assertEqual(by_path["entities/beta.md"]["title"], "Beta")
        self.assertEqual(by_path["entities/beta.md"]["stage"], "")
        # No frontmatter: title falls back to the file stem.
        self.assertEqual(by_path["plain.md"]["title"], "plain")
        # Sorted by relative path.
        self.assertEqual([p["path"] for p in pages], sorted(by_path))

    def test_read_page_round_trip_fields(self) -> None:
        page = core.read_page(self.wiki, "concepts/alpha.md")
        self.assertEqual(page["path"], "concepts/alpha.md")
        self.assertEqual(page["content"], ALPHA)
        self.assertEqual(page["frontmatter"], ALPHA_FRONTMATTER)
        self.assertEqual(page["body"], "\n# Alpha\n\nOriginal body.\n")
        self.assertEqual(page["title"], "Alpha  Page")
        self.assertEqual(page["stage"], "budding")
        expected = hashlib.sha256(ALPHA.encode("utf-8")).hexdigest()
        self.assertEqual(page["token"], expected)

    def test_read_missing_page(self) -> None:
        with self.assertRaises(core.PageNotFoundError):
            core.read_page(self.wiki, "concepts/missing.md")


class TestSave(FixtureCase):
    def test_save_round_trip(self) -> None:
        page = core.read_page(self.wiki, "entities/beta.md")
        result = core.save_page(
            self.wiki,
            self.backups,
            "entities/beta.md",
            "\n# Beta\n\nEdited body.\n",
            page["token"],
            today=TODAY,
        )
        reread = core.read_page(self.wiki, "entities/beta.md")
        self.assertEqual(reread["body"], "\n# Beta\n\nEdited body.\n")
        self.assertEqual(reread["token"], result["token"])
        self.assertIn(f"updated: {TODAY}", reread["frontmatter"])

    def test_frontmatter_preserved_byte_for_byte_except_updated(self) -> None:
        page = core.read_page(self.wiki, "concepts/alpha.md")
        core.save_page(
            self.wiki,
            self.backups,
            "concepts/alpha.md",
            "\n# Alpha\n\nNew body.\n",
            page["token"],
            today=TODAY,
        )
        new_content = (self.wiki / "concepts" / "alpha.md").read_text(
            encoding="utf-8"
        )
        new_frontmatter, new_body = core.split_frontmatter(new_content)
        self.assertEqual(new_body, "\n# Alpha\n\nNew body.\n")
        # Every line except `updated:` is byte-for-byte identical.
        old_lines = ALPHA_FRONTMATTER.splitlines()
        new_lines = new_frontmatter.splitlines()
        self.assertEqual(len(old_lines), len(new_lines))
        for old, new in zip(old_lines, new_lines):
            if old.startswith("updated:"):
                self.assertEqual(new, f"updated: {TODAY}")
            else:
                self.assertEqual(new, old)

    def test_save_without_updated_field_adds_none(self) -> None:
        page = core.read_page(self.wiki, "no-updated.md")
        core.save_page(
            self.wiki,
            self.backups,
            "no-updated.md",
            "\n# No Updated\n\nChanged.\n",
            page["token"],
            today=TODAY,
        )
        reread = core.read_page(self.wiki, "no-updated.md")
        self.assertNotIn("updated:", reread["frontmatter"])
        self.assertEqual(reread["body"], "\n# No Updated\n\nChanged.\n")

    def test_save_page_without_frontmatter(self) -> None:
        page = core.read_page(self.wiki, "plain.md")
        self.assertEqual(page["frontmatter"], "")
        core.save_page(
            self.wiki,
            self.backups,
            "plain.md",
            "# Plain\n\nRewritten.\n",
            page["token"],
            today=TODAY,
        )
        reread = core.read_page(self.wiki, "plain.md")
        self.assertEqual(reread["content"], "# Plain\n\nRewritten.\n")

    def test_concurrency_refusal(self) -> None:
        page = core.read_page(self.wiki, "concepts/alpha.md")
        # Someone else edits the file after we loaded it.
        target = self.wiki / "concepts" / "alpha.md"
        target.write_text(ALPHA + "Sneaky extra line.\n", encoding="utf-8")
        with self.assertRaises(core.ConcurrencyError):
            core.save_page(
                self.wiki,
                self.backups,
                "concepts/alpha.md",
                "\n# Alpha\n\nMy edit.\n",
                page["token"],
                today=TODAY,
            )
        # The on-disk (newer) version is untouched by the refused save.
        self.assertEqual(target.read_text(encoding="utf-8"), ALPHA + "Sneaky extra line.\n")
        # And no backup was made for a save that never happened.
        self.assertFalse((self.backups / "concepts" / "alpha.md").exists())

    def test_stale_token_after_first_save_refused(self) -> None:
        page = core.read_page(self.wiki, "entities/beta.md")
        core.save_page(
            self.wiki, self.backups, "entities/beta.md",
            "\n# Beta\n\nFirst.\n", page["token"], today=TODAY,
        )
        with self.assertRaises(core.ConcurrencyError):
            core.save_page(
                self.wiki, self.backups, "entities/beta.md",
                "\n# Beta\n\nSecond.\n", page["token"], today=TODAY,
            )

    def test_backup_written_with_original_bytes(self) -> None:
        page = core.read_page(self.wiki, "concepts/alpha.md")
        result = core.save_page(
            self.wiki,
            self.backups,
            "concepts/alpha.md",
            "\n# Alpha\n\nNew body.\n",
            page["token"],
            today=TODAY,
        )
        backup_path = Path(result["backup_path"])
        self.assertEqual(backup_path, self.backups / "concepts" / "alpha.md")
        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.read_bytes(), ALPHA.encode("utf-8"))

    def test_save_missing_page(self) -> None:
        with self.assertRaises(core.PageNotFoundError):
            core.save_page(
                self.wiki, self.backups, "concepts/missing.md",
                "body", "0" * 64, today=TODAY,
            )


class TestPathSafety(FixtureCase):
    def test_dotdot_escape_refused(self) -> None:
        for rel in ("../outside.md", "concepts/../../outside.md", "..\\outside.md"):
            # The backslash form is a plain filename on POSIX and the
            # file simply does not exist; the first two must be escapes.
            if "\\" in rel:
                continue
            with self.assertRaises(core.PathEscapeError, msg=rel):
                core.read_page(self.wiki, rel)
            with self.assertRaises(core.PathEscapeError, msg=rel):
                core.save_page(self.wiki, self.backups, rel, "x", "0" * 64)
            with self.assertRaises(core.PathEscapeError, msg=rel):
                core.create_page(self.wiki, rel, "Escapee")

    def test_absolute_path_refused(self) -> None:
        with self.assertRaises(core.PathEscapeError):
            core.read_page(self.wiki, str(self.outside))
        with self.assertRaises(core.PathEscapeError):
            core.create_page(self.wiki, "/tmp/evil.md", "Evil")

    def test_non_markdown_refused(self) -> None:
        for rel in ("concepts/alpha.txt", "concepts/alpha", "evil.py"):
            with self.assertRaises(core.PathEscapeError, msg=rel):
                core.read_page(self.wiki, rel)
            with self.assertRaises(core.PathEscapeError, msg=rel):
                core.create_page(self.wiki, rel, "Nope")

    def test_symlink_escaping_root_refused(self) -> None:
        link = self.wiki / "concepts" / "escape.md"
        try:
            link.symlink_to(self.outside)
        except OSError as exc:  # pragma: no cover - platform without symlinks
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaises(core.PathEscapeError):
            core.read_page(self.wiki, "concepts/escape.md")
        token = hashlib.sha256(b"irrelevant").hexdigest()
        with self.assertRaises(core.PathEscapeError):
            core.save_page(
                self.wiki, self.backups, "concepts/escape.md", "x", token
            )
        # Listing skips the escaping symlink instead of serving it.
        listed = {p["path"] for p in core.list_pages(self.wiki)}
        self.assertNotIn("concepts/escape.md", listed)
        # The outside file was never touched.
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "outside the wiki\n")

    def test_symlink_dir_escaping_root_refused(self) -> None:
        outside_dir = Path(self._tmp.name) / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "secret.md").write_text("secret\n", encoding="utf-8")
        linkdir = self.wiki / "linked"
        try:
            linkdir.symlink_to(outside_dir, target_is_directory=True)
        except OSError as exc:  # pragma: no cover
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaises(core.PathEscapeError):
            core.read_page(self.wiki, "linked/secret.md")
        with self.assertRaises(core.PathEscapeError):
            core.create_page(self.wiki, "linked/new.md", "New")

    def test_resolve_safe_path_inside_root_ok(self) -> None:
        resolved = core.resolve_safe_path(self.wiki, "concepts/alpha.md")
        self.assertEqual(resolved, (self.wiki / "concepts" / "alpha.md").resolve())


class TestCreate(FixtureCase):
    def test_create_page_skeleton(self) -> None:
        result = core.create_page(
            self.wiki, "concepts/gamma.md", "Gamma Page",
            "concept", today=TODAY,
        )
        content = (self.wiki / "concepts" / "gamma.md").read_text(encoding="utf-8")
        self.assertEqual(result["content"], content)
        for needle in (
            'title: "Gamma Page"',
            "type: concept",
            f"created: {TODAY}",
            f"updated: {TODAY}",
            "sources: []",
            "tags: []",
            "# Gamma Page",
        ):
            self.assertIn(needle, content)
        # The skeleton parses back through the editor's own reader.
        page = core.read_page(self.wiki, "concepts/gamma.md")
        self.assertEqual(page["title"], "Gamma Page")
        self.assertEqual(page["type"], "concept")
        # And the new page shows up in the listing.
        listed = {p["path"] for p in core.list_pages(self.wiki)}
        self.assertIn("concepts/gamma.md", listed)

    def test_create_in_new_subdirectory(self) -> None:
        core.create_page(
            self.wiki, "syntheses/deep/new-page.md", "Deep Page",
            "synthesis", today=TODAY,
        )
        self.assertTrue((self.wiki / "syntheses" / "deep" / "new-page.md").is_file())

    def test_create_with_tags_and_sources(self) -> None:
        core.create_page(
            self.wiki, "sources/note.md", "A Note", "source",
            today=TODAY, tags=["one"], sources=["raw/sources/note.md"],
        )
        content = (self.wiki / "sources" / "note.md").read_text(encoding="utf-8")
        self.assertIn('sources: ["raw/sources/note.md"]', content)
        self.assertIn('tags: ["one"]', content)

    def test_create_refuses_overwrite(self) -> None:
        with self.assertRaises(core.AlreadyExistsError):
            core.create_page(self.wiki, "concepts/alpha.md", "Alpha Again")
        # Original untouched.
        self.assertEqual(
            (self.wiki / "concepts" / "alpha.md").read_text(encoding="utf-8"),
            ALPHA,
        )
        # Second create of a just-created page is refused too.
        core.create_page(self.wiki, "concepts/once.md", "Once", today=TODAY)
        with self.assertRaises(core.AlreadyExistsError):
            core.create_page(self.wiki, "concepts/once.md", "Once", today=TODAY)

    def test_create_rejects_bad_type_and_empty_title(self) -> None:
        with self.assertRaises(ValueError):
            core.create_page(self.wiki, "concepts/x.md", "X", "banana")
        with self.assertRaises(ValueError):
            core.create_page(self.wiki, "concepts/x.md", "  ", "concept")
        self.assertFalse((self.wiki / "concepts" / "x.md").exists())

    def test_all_allowed_types_accepted(self) -> None:
        for idx, page_type in enumerate(core.ALLOWED_TYPES):
            rel = f"concepts/type-{idx}.md"
            core.create_page(self.wiki, rel, f"Type {page_type}", page_type, today=TODAY)
            self.assertIn(
                f"type: {page_type}",
                (self.wiki / rel).read_text(encoding="utf-8"),
            )


class TestFrontmatterHelpers(unittest.TestCase):
    def test_split_without_frontmatter(self) -> None:
        frontmatter, body = core.split_frontmatter(PLAIN)
        self.assertIsNone(frontmatter)
        self.assertEqual(body, PLAIN)

    def test_split_unclosed_frontmatter_is_body(self) -> None:
        text = "---\ntitle: dangling\n\nno closing delimiter\n"
        frontmatter, body = core.split_frontmatter(text)
        self.assertIsNone(frontmatter)
        self.assertEqual(body, text)

    def test_update_updated_field_no_field(self) -> None:
        raw = "---\ntitle: X\n---\n"
        self.assertEqual(core.update_updated_field(raw, TODAY), raw)


class TestLiveServer(FixtureCase):
    """One smoke test over a real socket on an ephemeral port."""

    def setUp(self) -> None:
        super().setUp()
        self.httpd = editor_server.create_server(
            self.wiki, self.backups, host="127.0.0.1", port=0
        )
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def _request(self, method: str, path: str, form: dict | None = None):
        body = None
        headers = {}
        if form is not None:
            body = urllib.parse.urlencode(form)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            conn.close()

    def test_bind_is_loopback_only(self) -> None:
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")
        with self.assertRaises(ValueError):
            editor_server.create_server(
                self.wiki, self.backups, host="0.0.0.0", port=0
            )

    def test_list_edit_save_create_flow(self) -> None:
        status, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Alpha  Page", body)
        self.assertIn("budding", body)
        self.assertNotIn("<script", body)

        status, body = self._request(
            "GET", "/edit?path=" + urllib.parse.quote("concepts/alpha.md")
        )
        self.assertEqual(status, 200)
        self.assertIn("Original body.", body)
        # Extract the concurrency token from the form.
        marker = 'name="token" value="'
        start = body.index(marker) + len(marker)
        token = body[start : body.index('"', start)]

        status, body = self._request(
            "POST", "/save",
            {"path": "concepts/alpha.md", "token": token,
             "body": "\n# Alpha\n\nEdited over HTTP.\n"},
        )
        self.assertEqual(status, 200)
        self.assertIn("Saved", body)
        reread = core.read_page(self.wiki, "concepts/alpha.md")
        self.assertEqual(reread["body"], "\n# Alpha\n\nEdited over HTTP.\n")
        self.assertTrue((self.backups / "concepts" / "alpha.md").is_file())

        # Replaying the same (now stale) token is a 409.
        status, _body = self._request(
            "POST", "/save",
            {"path": "concepts/alpha.md", "token": token, "body": "stale"},
        )
        self.assertEqual(status, 409)

        status, body = self._request(
            "POST", "/create",
            {"path": "concepts/http-made.md", "title": "HTTP Made",
             "page_type": "concept"},
        )
        self.assertEqual(status, 200)
        self.assertTrue((self.wiki / "concepts" / "http-made.md").is_file())

        # Re-creating it is a 409; escaping the root is a 400.
        status, _ = self._request(
            "POST", "/create",
            {"path": "concepts/http-made.md", "title": "Again",
             "page_type": "concept"},
        )
        self.assertEqual(status, 409)
        status, _ = self._request(
            "GET", "/edit?path=" + urllib.parse.quote("../outside.md")
        )
        self.assertEqual(status, 400)
        status, _ = self._request("GET", "/edit?path=concepts/missing.md")
        self.assertEqual(status, 404)


# ---------------------------------------------------------------------
# Lane E additions: safe preview, recent-pages log, create-from-template.
# ---------------------------------------------------------------------

TEMPLATE_CONCEPT = """---
title: ""
type: concept
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: []
tags: []
---

# <Concept>

## Definition (in our own words)

Template body marker.
"""

TEMPLATE_ENTITY = """---
title: ""
type: entity
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: []
tags: []
---

# <Name>

Entity template body.
"""


def _make_templates(root: Path) -> Path:
    templates = root / "templates"
    (templates / "capture").mkdir(parents=True)
    (templates / "presets" / "demo" / "files").mkdir(parents=True)
    (templates / "concept.md").write_text(TEMPLATE_CONCEPT, encoding="utf-8")
    (templates / "entity.md").write_text(TEMPLATE_ENTITY, encoding="utf-8")
    (templates / "capture" / "note.md").write_text(
        TEMPLATE_CONCEPT.replace("concept", "concept"), encoding="utf-8"
    )
    (templates / "presets" / "demo" / "preset.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (templates / "presets" / "demo" / "files" / "seed.md").write_text(
        "preset file, not a page template\n", encoding="utf-8"
    )
    return templates


class TestPreview(unittest.TestCase):
    def test_script_tag_renders_inert(self) -> None:
        out = preview.render_markdown("<script>alert(1)</script>")
        self.assertNotIn("<script", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("alert(1)", out)

    def test_img_onerror_renders_inert(self) -> None:
        out = preview.render_markdown('<img src=x onerror="alert(1)">')
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)

    def test_raw_html_in_heading_and_code_inert(self) -> None:
        out = preview.render_markdown("# Hi <b>there</b>\n\n`<i>x</i>`\n")
        self.assertNotIn("<b>", out)
        self.assertNotIn("<i>", out)
        self.assertIn("&lt;b&gt;", out)
        self.assertIn("<h1>", out)
        self.assertIn("<code>", out)

    def test_javascript_link_neutralised(self) -> None:
        out = preview.render_markdown("[click](javascript:alert(1))")
        self.assertNotIn("javascript:", out)
        self.assertNotIn("<a ", out)
        self.assertIn("click", out)

    def test_data_uri_link_neutralised(self) -> None:
        out = preview.render_markdown("[x](data:text/html;base64,AAAA)")
        self.assertNotIn("<a ", out)

    def test_https_and_relative_links_allowed(self) -> None:
        out = preview.render_markdown(
            "[site](https://example.org/a) and [page](concepts/beta.md)"
        )
        self.assertIn('<a href="https://example.org/a">site</a>', out)
        self.assertIn('<a href="concepts/beta.md">page</a>', out)

    def test_headings_paragraph_emphasis(self) -> None:
        out = preview.render_markdown(
            "# Title\n\nA **bold** and *calm* word, plus `code`.\n"
        )
        self.assertIn("<h1>Title</h1>", out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<em>calm</em>", out)
        self.assertIn("<code>code</code>", out)

    def test_lists(self) -> None:
        out = preview.render_markdown("- one\n- two\n\n1. first\n2. second\n")
        self.assertIn("<ul><li>one</li><li>two</li></ul>", out)
        self.assertIn("<ol><li>first</li><li>second</li></ol>", out)

    def test_fenced_code_block_escaped_no_inline(self) -> None:
        out = preview.render_markdown("```\n<b>**not bold**</b>\n```\n")
        self.assertIn("<pre><code>", out)
        self.assertIn("&lt;b&gt;**not bold**&lt;/b&gt;", out)
        self.assertNotIn("<strong>", out)

    def test_table(self) -> None:
        out = preview.render_markdown(
            "| Name | Kind |\n| --- | --- |\n| Alpha | concept |\n"
        )
        self.assertIn("<th>Name</th>", out)
        self.assertIn("<td>Alpha</td>", out)
        self.assertIn("<td>concept</td>", out)

    def test_wikilink_becomes_span_with_target(self) -> None:
        out = preview.render_markdown("See [[decision-register]] and [[owner|the owner]].")
        self.assertIn('data-target="decision-register"', out)
        self.assertIn('data-target="owner"', out)
        self.assertIn("the owner", out)
        self.assertNotIn("[[", out)

    def test_blockquote_and_rule(self) -> None:
        out = preview.render_markdown("> quoted words\n\n---\n\nAfter.\n")
        self.assertIn("<blockquote><p>quoted words</p></blockquote>", out)
        self.assertIn("<hr>", out)

    def test_ampersand_escaped_once(self) -> None:
        out = preview.render_markdown("Fish & chips < 3\n")
        self.assertIn("Fish &amp; chips &lt; 3", out)


class TestRecentLog(unittest.TestCase):
    def test_most_recent_first_and_deduped(self) -> None:
        log = core.RecentLog()
        log.record("open", "a.md", at="2026-10-20T01:00:00+00:00")
        log.record("open", "b.md", at="2026-10-20T02:00:00+00:00")
        log.record("save", "a.md", at="2026-10-20T03:00:00+00:00")
        entries = log.recent()
        self.assertEqual([e["path"] for e in entries], ["a.md", "b.md"])
        self.assertEqual(entries[0]["action"], "save")

    def test_limit_caps_entries(self) -> None:
        log = core.RecentLog(limit=5)
        for i in range(9):
            log.record("open", f"p{i}.md", at=f"2026-10-20T0{i}:00:00+00:00")
        self.assertEqual(len(log.recent(50)), 5)
        self.assertEqual(log.recent(1)[0]["path"], "p8.md")

    def test_persistence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "editor-state"
            log = core.RecentLog(data_dir)
            log.record("create", "concepts/new.md", at="2026-10-20T01:00:00+00:00")
            self.assertTrue((data_dir / "recent.json").is_file())
            again = core.RecentLog(data_dir)
            self.assertEqual(again.recent()[0]["path"], "concepts/new.md")
            self.assertEqual(again.recent()[0]["action"], "create")

    def test_corrupt_state_file_is_empty_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            (data_dir / "recent.json").write_text("{not json", encoding="utf-8")
            log = core.RecentLog(data_dir)
            self.assertEqual(log.recent(), [])

    def test_unknown_action_refused(self) -> None:
        with self.assertRaises(ValueError):
            core.RecentLog().record("delete", "a.md")


class TestCreateFromTemplate(FixtureCase):
    def setUp(self) -> None:
        super().setUp()
        self.templates = _make_templates(Path(self._tmp.name))

    def test_list_templates_offers_page_and_capture_not_presets(self) -> None:
        offered = core.list_page_templates(self.templates)
        names = [t["name"] for t in offered]
        self.assertEqual(names, ["capture/note.md", "concept.md", "entity.md"])
        by_name = {t["name"]: t for t in offered}
        self.assertEqual(by_name["concept.md"]["kind"], "page")
        self.assertEqual(by_name["capture/note.md"]["kind"], "capture")

    def test_list_templates_missing_dir_is_empty(self) -> None:
        self.assertEqual(core.list_page_templates(None), [])
        self.assertEqual(
            core.list_page_templates(Path(self._tmp.name) / "nope"), []
        )

    def test_create_from_template_body_and_skeleton(self) -> None:
        result = core.create_page_from_template(
            self.wiki, self.templates, "concept.md",
            "concepts/from-template.md", "Fresh Concept", today=TODAY,
        )
        content = Path(self.wiki / "concepts/from-template.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(result["content"], content)
        self.assertIn('title: "Fresh Concept"', content)
        self.assertIn(f"created: {TODAY}", content)
        self.assertIn("# Fresh Concept", content)  # heading placeholder filled
        self.assertIn("Template body marker.", content)
        self.assertNotIn("<Concept>", content)
        self.assertNotIn("YYYY-MM-DD", content)

    def test_template_type_is_default_and_explicit_type_wins(self) -> None:
        core.create_page_from_template(
            self.wiki, self.templates, "entity.md",
            "entities/from-template.md", "Some Entity", today=TODAY,
        )
        content = (self.wiki / "entities/from-template.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("type: entity", content)
        core.create_page_from_template(
            self.wiki, self.templates, "entity.md",
            "concepts/override.md", "Override", "concept", today=TODAY,
        )
        content = (self.wiki / "concepts/override.md").read_text(encoding="utf-8")
        self.assertIn("type: concept", content)

    def test_create_from_template_refuses_overwrite(self) -> None:
        with self.assertRaises(core.AlreadyExistsError):
            core.create_page_from_template(
                self.wiki, self.templates, "concept.md",
                "concepts/alpha.md", "Again", today=TODAY,
            )

    def test_template_escape_and_missing_refused(self) -> None:
        with self.assertRaises(core.PathEscapeError):
            core.create_page_from_template(
                self.wiki, self.templates, "../outside.md",
                "concepts/x.md", "X", today=TODAY,
            )
        with self.assertRaises(core.PageNotFoundError):
            core.create_page_from_template(
                self.wiki, self.templates, "no-such.md",
                "concepts/x.md", "X", today=TODAY,
            )
        with self.assertRaises(core.PathEscapeError):
            core.create_page_from_template(
                self.wiki, self.templates, "presets/demo/files/seed.md",
                "concepts/x.md", "X", today=TODAY,
            )


class TestLiveServerDepth(FixtureCase):
    """Lane E routes over a real socket: preview, templates, recent."""

    def setUp(self) -> None:
        super().setUp()
        tmp = Path(self._tmp.name)
        self.templates = _make_templates(tmp)
        self.data_dir = tmp / "editor-data"
        (self.wiki / "concepts" / "evil.md").write_text(
            "---\ntitle: Evil\ntype: concept\ncreated: 2026-10-20\n"
            "updated: 2026-10-20\nsources: []\ntags: []\n---\n\n"
            "# Evil\n\n<script>alert(1)</script>\n",
            encoding="utf-8",
        )
        self.httpd = editor_server.create_server(
            self.wiki, self.backups, host="127.0.0.1", port=0,
            templates_dir=self.templates, data_dir=self.data_dir,
        )
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def _request(self, method: str, path: str, form: dict | None = None):
        body = None
        headers = {}
        if form is not None:
            body = urllib.parse.urlencode(form)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            conn.close()

    def test_edit_page_has_inert_preview_pane(self) -> None:
        status, body = self._request(
            "GET", "/edit?path=" + urllib.parse.quote("concepts/evil.md")
        )
        self.assertEqual(status, 200)
        self.assertIn('class="preview"', body)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>alert", body)
        self.assertIn("<h1>Evil</h1>", body)

    def test_preview_routes_render_without_writing(self) -> None:
        status, body = self._request(
            "GET", "/preview?path=" + urllib.parse.quote("concepts/alpha.md")
        )
        self.assertEqual(status, 200)
        self.assertIn("<h1>Alpha</h1>", body)
        status, body = self._request(
            "POST", "/preview",
            {"path": "concepts/alpha.md", "body": "# Draft\n\n**New** text.\n"},
        )
        self.assertEqual(status, 200)
        self.assertIn("<strong>New</strong>", body)
        # Nothing was written: the saved page is unchanged.
        self.assertEqual(
            core.read_page(self.wiki, "concepts/alpha.md")["content"], ALPHA
        )

    def test_new_page_offers_templates_and_create_uses_one(self) -> None:
        status, body = self._request("GET", "/new")
        self.assertEqual(status, 200)
        self.assertIn("concept.md", body)
        self.assertIn("capture/note.md", body)
        status, _body = self._request(
            "POST", "/create",
            {"path": "concepts/templated.md", "title": "Templated",
             "page_type": "concept", "template": "concept.md"},
        )
        self.assertEqual(status, 200)
        content = (self.wiki / "concepts/templated.md").read_text(encoding="utf-8")
        self.assertIn("Template body marker.", content)
        self.assertIn('title: "Templated"', content)

    def test_recent_pages_flow_and_state_file(self) -> None:
        self._request(
            "GET", "/edit?path=" + urllib.parse.quote("concepts/alpha.md")
        )
        status, body = self._request("GET", "/recent")
        self.assertEqual(status, 200)
        self.assertIn("concepts/alpha.md", body)
        self.assertTrue((self.data_dir / "recent.json").is_file())
        status, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Recent pages", body)
        self.assertIn("concepts/alpha.md", body)



if __name__ == "__main__":
    unittest.main()
