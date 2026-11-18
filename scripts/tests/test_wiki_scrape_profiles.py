#!/usr/bin/env python3
"""Tests for scripts/wiki_scrape_profiles.py + its wiring in
scripts/wiki_clip.py (implementation wave W4, 2026-10-22):
scrape profiles for feedless sites + fit-Markdown extraction.

Fully offline: profile fixtures are written into temp roots,
clip tests use the clip path's fake-fetcher seam, and nothing
in the repo is touched. Fixture pages: an article carrying
boilerplate (cookie banner, link-dense promo rail, short
footer), a feedless listing of .post-card items (one card
missing its required title), and a forum thread.

Run:  python3 -m unittest scripts.tests.test_wiki_scrape_profiles -v
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_clip as clip  # noqa: E402
import wiki_scrape_profiles as wsp  # noqa: E402

NOW = datetime(2026, 10, 22, 9, 30, tzinfo=timezone.utc)

ARTICLE = """<html><head><title>Fitting Markdown, Honestly</title></head>
<body>
<nav><a href="/">Home</a> <a href="/about">About</a> <a href="/c">Contact</a></nav>
<div class="cookie-banner">We use cookies. Accept?</div>
<article>
<h1>Fitting Markdown, Honestly</h1>
<p>The fitted conversion keeps the article's real paragraphs, with
their full sentences and qualifications, and drops the chrome that
surrounds them on the page. Nothing about the source bytes changes:
only the copy that is converted is fitted, and every removal is
recorded in the sidecar's fidelity record.</p>
<p>A second paragraph of substance, long enough to stand as content
under any density measure, with a <a href="/other">passing link</a>
inside running text rather than a rail of links.</p>
</article>
<div class="promo-rail"><a href="/a">An extremely long promotional anchor text</a><a href="/b">Another very long promotional anchor text</a><a href="/c">A third long promotional anchor text here</a></div>
<footer>© 2026 Example</footer>
</body></html>"""

LISTING = """<html><head><title>Notes Index</title></head><body>
<h1>Notes</h1>
<div class="post-card"><h3 class="post-title">First Post</h3>
<a class="post-link" href="/posts/first">Read</a>
<time datetime="2026-10-03">Oct 3, 2026</time>
<p class="post-summary">Summary of the first post, in full.</p></div>
<div class="post-card"><h3 class="post-title">Second Post</h3>
<a class="post-link" href="/posts/second">Read</a>
<time datetime="2026-10-10">Oct 10, 2026</time>
<p class="post-summary">Second summary, with a zero-width​ char.</p></div>
<div class="post-card">
<a class="post-link" href="/posts/third">Read</a>
<time datetime="2026-10-17">Oct 17, 2026</time>
<p class="post-summary">A card with no title: skipped, and the skip recorded.</p></div>
</body></html>"""

FORUM = """<html><head><title>Thread: Density</title></head><body>
<div class="post"><span class="post-author">ada</span>
<p class="post-body">First message of the thread, with enough text to
be a real post rather than a signature block or a chrome rail.</p></div>
<div class="post"><span class="post-author">mehmed</span>
<p class="post-body">A reply that also carries real content, answering
the first message at some length and in full sentences.</p></div>
</body></html>"""

ARTICLE_PROFILE = {
    "name": "article-fit",
    "note": "test profile: strip the banner, prune by density",
    "url_patterns": [],
    "strip": [".cookie-banner"],
    "fit": {"enabled": True, "min_text_chars": 25,
            "max_link_density": 0.6, "min_text_density": 0.2},
}

PROFILES_DOC = {"version": 1, "profiles": [
    ARTICLE_PROFILE,
    {"name": "listing-cards",
     "note": "test listing profile",
     "url_patterns": [],
     "shape": [{"selector": ".post-card", "min_count": 2}],
     "items": {"selector": ".post-card", "fields": {
         "title": {"selector": ".post-title", "required": True,
                   "transform": "collapse_ws"},
         "link": {"selector": "a.post-link", "attr": "href",
                  "required": True},
         "date": {"selector": "time", "attr": "datetime"},
         "summary": {"selector": ".post-summary",
                     "transform": "collapse_ws"}}}},
    {"name": "forum-thread",
     "note": "test forum profile",
     "url_patterns": ["://[^/]+/forum/"],
     "items": {"selector": ".post", "fields": {
         "author": {"selector": ".post-author",
                    "transform": "collapse_ws"},
         "body": {"selector": ".post-body", "required": True,
                  "transform": "collapse_ws"}}}},
]}


def validated(doc=PROFILES_DOC):
    return wsp.validate_profiles(json.loads(json.dumps(doc)))


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.root = wsp.parse_html(LISTING)

    def test_css_descendant_child_attr(self):
        self.assertEqual(
            len(wsp.css_select(self.root, ".post-card")), 3)
        self.assertEqual(
            len(wsp.css_select(self.root, "div.post-card > h3")),
            2)  # the third card has no heading — by fixture design
        self.assertEqual(
            len(wsp.css_select(self.root, "a[href]")), 3)
        self.assertEqual(
            len(wsp.css_select(
                self.root, 'time[datetime="2026-10-10"]')), 1)
        first = wsp.css_select(self.root, ".post-card .post-title")
        self.assertEqual(wsp.node_text(first[0]), "First Post")

    def test_xpath_subset(self):
        nodes = wsp.xpath_select(
            self.root, "//div[@class='post-card']")
        self.assertEqual(len(nodes), 3)
        href = wsp.xpath_value(
            nodes[0], ".//a[@class='post-link']/@href")
        self.assertEqual(href, "/posts/first")
        title = wsp.xpath_value(nodes[1], ".//h3/text()")
        self.assertEqual(title, "Second Post")
        second = wsp.xpath_select(self.root, "//div[@class="
                                    "'post-card'][2]")
        self.assertEqual(len(second), 1)
        self.assertIn("Second Post", wsp.node_text(second[0]))

    def test_outside_the_grammar_is_refused_by_name(self):
        for bad in ("div + p", "a:hover", "div ~ p"):
            with self.assertRaises(wsp.ProfileError) as ctx:
                wsp.css_select(self.root, bad)
            self.assertIn(bad, str(ctx.exception))
        for bad in ("//div | //p", "//div[position()=1]",
                    "div/a", "//a/@href/@x"):
            with self.assertRaises(wsp.ProfileError) as ctx:
                wsp.xpath_select(self.root, bad)
            self.assertIn(bad, str(ctx.exception))


class ProfileValidationTests(unittest.TestCase):
    def test_unknown_key_refused_by_name(self):
        doc = {"version": 1, "profiles": [
            {"name": "x", "trust": "high"}]}
        with self.assertRaises(wsp.ProfileError) as ctx:
            wsp.validate_profiles(doc)
        self.assertIn("'trust'", str(ctx.exception))

    def test_unknown_transform_and_bad_selector_refused(self):
        doc = {"version": 1, "profiles": [
            {"name": "x", "items": {"selector": ".i", "fields": {
                "t": {"selector": ".t", "transform": "shout"}}}}]}
        with self.assertRaises(wsp.ProfileError) as ctx:
            wsp.validate_profiles(doc)
        self.assertIn("shout", str(ctx.exception))
        doc2 = {"version": 1, "profiles": [
            {"name": "x", "strip": ["div + p"]}]}
        with self.assertRaises(wsp.ProfileError) as ctx:
            wsp.validate_profiles(doc2)
        self.assertIn("div + p", str(ctx.exception))

    def test_generic_name_reserved_and_duplicates_refused(self):
        for doc in ({"profiles": [{"name": "generic"}]},
                    {"profiles": [{"name": "a"}, {"name": "a"}]}):
            with self.assertRaises(wsp.ProfileError):
                wsp.validate_profiles(doc)

    def test_malformed_file_is_a_loud_error(self):
        root = Path(tempfile.mkdtemp(prefix="scrape-bad-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "templates").mkdir(parents=True)
        (root / "templates" / "scrape-profiles.json").write_text(
            "{not json", encoding="utf-8")
        with self.assertRaises(wsp.ProfileError):
            wsp.load_profiles(root)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.profiles = validated()

    def test_explicit_url_shape_and_fallback(self):
        profile, how = wsp.select_profile(
            "https://example.com/x", ARTICLE, self.profiles,
            explicit="article-fit")
        self.assertEqual((profile["name"], how),
                         ("article-fit", "explicit"))
        profile, how = wsp.select_profile(
            "https://example.com/forum/t-1", None, self.profiles)
        self.assertEqual((profile["name"], how),
                         ("forum-thread", "url"))
        profile, how = wsp.select_profile(
            "https://example.com/notes", LISTING, self.profiles)
        self.assertEqual((profile["name"], how),
                         ("listing-cards", "shape"))
        profile, how = wsp.select_profile(
            "https://example.com/plain", ARTICLE, self.profiles)
        self.assertEqual((profile["name"], how),
                         ("generic", "generic-fallback"))

    def test_unknown_explicit_name_refused(self):
        with self.assertRaises(wsp.ProfileError) as ctx:
            wsp.select_profile("https://example.com/", None,
                               self.profiles, explicit="nope")
        self.assertIn("nope", str(ctx.exception))


class FitTests(unittest.TestCase):
    def setUp(self):
        self.profiles = validated()
        self.profile = wsp.get_profile(self.profiles,
                                       "article-fit")

    def test_fit_prunes_and_records_everything(self):
        new_html, fidelity = wsp.fit_markdown(ARTICLE,
                                              self.profile)
        self.assertTrue(fidelity["applied"])
        self.assertEqual(fidelity["stripped"],
                         {".cookie-banner": 1})
        self.assertIn("fit:link-density",
                      fidelity["pruned_counts"])
        # Boilerplate is gone, by rule and recorded.
        self.assertNotIn("We use cookies", new_html)
        self.assertNotIn("promotional anchor", new_html)
        self.assertNotIn("© 2026 Example", new_html)
        self.assertNotIn("Contact", new_html)
        # Content survives.
        self.assertIn("Fitting Markdown, Honestly", new_html)
        self.assertIn("second paragraph of substance", new_html)
        for entry in fidelity["pruned"]:
            self.assertIn("rule", entry)
            self.assertIn("text_chars", entry)

    def test_generic_profile_is_byte_identical(self):
        new_html, fidelity = wsp.fit_markdown(
            ARTICLE, wsp.GENERIC_PROFILE)
        self.assertEqual(new_html, ARTICLE)
        self.assertFalse(fidelity["applied"])

    def test_rotted_keep_is_reported_not_emptied(self):
        profile = {"name": "k", "keep": ".does-not-exist",
                   "fit": {"enabled": False}}
        new_html, fidelity = wsp.fit_markdown(ARTICLE, profile)
        self.assertEqual(fidelity["keep"],
                         {"selector": ".does-not-exist",
                          "matched": False})
        self.assertIn("Fitting Markdown", new_html)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.profiles = validated()

    def test_items_extracted_skips_recorded(self):
        profile = wsp.get_profile(self.profiles, "listing-cards")
        items, record = wsp.extract_items(
            LISTING, profile, base_url="https://example.com/notes")
        self.assertEqual(record["found"], 3)
        self.assertEqual(record["extracted"], 2)
        self.assertEqual(record["skipped"],
                         [{"index": 2, "missing": "title"}])
        self.assertEqual(items[0]["title"], "First Post")
        self.assertEqual(items[0]["link"],
                         "https://example.com/posts/first")
        self.assertEqual(items[0]["date"], "2026-10-03")
        self.assertEqual(items[1]["summary"],
                         "Second summary, with a zero-width​ "
                         "char.")

    def test_xpath_items_schema(self):
        profile = {"name": "xp", "items": {
            "selector": "//div[@class='post-card']",
            "fields": {
                "title": {"selector": ".//h3",
                          "required": True},
                "link": {"selector": ".//a[@class='post-link']",
                         "attr": "href", "required": True}}}}
        wsp.validate_profiles({"profiles": [profile]})
        items, record = wsp.extract_items(
            LISTING, profile, base_url="https://example.com/")
        self.assertEqual(record["extracted"], 2)
        self.assertEqual(items[1]["link"],
                         "https://example.com/posts/second")

    def test_profile_without_items_schema_refused(self):
        with self.assertRaises(wsp.ProfileError):
            wsp.extract_items(ARTICLE, self.profiles[0])

    def test_forum_thread_extraction(self):
        profile = wsp.get_profile(self.profiles, "forum-thread")
        items, record = wsp.extract_items(FORUM, profile)
        self.assertEqual(record["extracted"], 2)
        self.assertEqual(items[0]["author"], "ada")
        self.assertTrue(items[1]["body"].startswith(
            "A reply that also carries"))


class ClipFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="scrape-root-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def write_profiles(self, doc=PROFILES_DOC):
        (self.root / "templates").mkdir(parents=True,
                                        exist_ok=True)
        (self.root / "templates"
         / "scrape-profiles.json").write_text(
            json.dumps(doc), encoding="utf-8")

    def sidecar(self, res):
        return json.loads((self.root / res["sidecar"]).read_text(
            encoding="utf-8"))


class ClipIntegrationTests(ClipFixture):
    def test_generic_fallback_recorded(self):
        res = clip.clip_url(
            "https://example.com/plain-article",
            root=self.root, fetcher=lambda u: ARTICLE.encode(),
            now=NOW, snapshot=False)
        rec = self.sidecar(res)["clip"]["scrape_profile"]
        self.assertEqual(rec["name"], "generic")
        self.assertEqual(rec["selection"], "generic-fallback")
        self.assertFalse(rec["fit"]["applied"])

    def test_no_matching_profile_is_byte_identical(self):
        # Root A: no profiles file at all. Root B: the full
        # profiles file, but this page matches none of them.
        other = Path(tempfile.mkdtemp(prefix="scrape-root-b-"))
        self.addCleanup(shutil.rmtree, other, True)
        (other / "templates").mkdir(parents=True)
        (other / "templates"
         / "scrape-profiles.json").write_text(
            json.dumps(PROFILES_DOC), encoding="utf-8")
        url = "https://example.com/plain-article"
        fetch = lambda u: ARTICLE.encode()  # noqa: E731
        res_a = clip.clip_url(url, root=self.root, fetcher=fetch,
                              now=NOW, snapshot=False)
        res_b = clip.clip_url(url, root=other, fetcher=fetch,
                              now=NOW, snapshot=False)
        self.assertEqual(
            (self.root / res_a["draft"]).read_bytes(),
            (other / res_b["draft"]).read_bytes())
        self.assertEqual(
            (self.root / res_a["preserved"]).read_bytes(),
            (other / res_b["preserved"]).read_bytes())
        side_a = json.loads((self.root / res_a["sidecar"])
                            .read_text(encoding="utf-8"))
        side_b = json.loads((other / res_b["sidecar"])
                            .read_text(encoding="utf-8"))
        # The ONLY sidecar difference is the record itself —
        # plus the converter's random temp-file name, which
        # differs between ANY two clip runs (pre-existing,
        # not this layer); normalise it before comparing.
        def scrub(obj):
            if isinstance(obj, dict):
                return {k: scrub(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [scrub(v) for v in obj]
            if isinstance(obj, str):
                return re.sub(r"wiki-clip-[A-Za-z0-9_]+", "TEMP",
                              obj)
            return obj

        side_a["clip"].pop("scrape_profile")
        side_b["clip"].pop("scrape_profile")
        self.assertEqual(scrub(side_a), scrub(side_b))

    def test_explicit_profile_fits_the_draft(self):
        self.write_profiles()
        res = clip.clip_url(
            "https://example.com/story",
            root=self.root, fetcher=lambda u: ARTICLE.encode(),
            now=NOW, snapshot=False,
            scrape_profile="article-fit")
        rec = self.sidecar(res)["clip"]["scrape_profile"]
        self.assertEqual(rec["name"], "article-fit")
        self.assertEqual(rec["selection"], "explicit")
        self.assertIn("fit:link-density",
                      rec["fit"]["pruned_counts"])
        draft = (self.root / res["draft"]).read_text(
            encoding="utf-8")
        self.assertNotIn("promotional anchor", draft)
        self.assertNotIn("We use cookies", draft)
        self.assertIn("second paragraph of substance", draft)
        # The preserved source is still the fetched bytes,
        # verbatim — boilerplate and all.
        self.assertEqual(
            (self.root / res["preserved"]).read_bytes(),
            ARTICLE.encode())

    def test_unknown_profile_refused_at_the_door(self):
        self.write_profiles()
        calls = []

        def counting_fetcher(url):
            calls.append(url)
            return ARTICLE.encode()

        with self.assertRaises(clip.ClipError) as ctx:
            clip.clip_url("https://example.com/story",
                          root=self.root, fetcher=counting_fetcher,
                          now=NOW, scrape_profile="nope")
        self.assertIn("nope", str(ctx.exception))
        self.assertEqual(calls, [])  # the door is before the fetch
        self.assertEqual(list(self.root.rglob("*")), [
            self.root / "templates",
            self.root / "templates" / "scrape-profiles.json"])

    def test_scrape_items_stages_each_item_through_the_gate(self):
        self.write_profiles()
        res = clip.clip_url(
            "https://example.com/notes",
            root=self.root, fetcher=lambda u: LISTING.encode(),
            now=NOW, snapshot=False,
            scrape_profile="listing-cards", scrape_items=True)
        self.assertEqual(res["kind"], "scrape-clip")
        self.assertEqual(res["count"], 2)
        record = res["scrape_profile"]["items"]
        self.assertEqual(record["found"], 3)
        self.assertEqual(record["skipped"],
                         [{"index": 2, "missing": "title"}])
        titles = sorted(item["title"] for item in res["items"])
        self.assertEqual(titles, ["First Post", "Second Post"])
        for item in res["items"]:
            self.assertTrue(
                (self.root / item["draft"]).exists())
            side = json.loads((self.root / item["sidecar"])
                              .read_text(encoding="utf-8"))
            self.assertEqual(side["clip"]["kind"], "scrape-clip")
            self.assertIn("sanitiser", side)  # the gate ran
        # The zero-width char in the second summary was caught
        # by the converter's gate on that item's capture.
        second = next(i for i in res["items"]
                      if i["title"] == "Second Post")
        kinds = {f["kind"] for f in second["findings"]}
        self.assertIn("invisible-chars", kinds)

    def test_scrape_items_with_no_items_is_a_door_failure(self):
        self.write_profiles()
        with self.assertRaises(clip.ClipError):
            clip.clip_url(
                "https://example.com/plain",
                root=self.root, fetcher=lambda u: ARTICLE.encode(),
                now=NOW, scrape_profile="listing-cards",
                scrape_items=True)
        staged = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertEqual(
            staged,
            [self.root / "templates" / "scrape-profiles.json"])

    def test_scrape_items_needs_an_explicit_profile(self):
        calls = []
        with self.assertRaises(clip.ClipError):
            clip.clip_url(
                "https://example.com/notes", root=self.root,
                fetcher=lambda u: calls.append(u) or LISTING
                .encode(),
                now=NOW, scrape_items=True)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
