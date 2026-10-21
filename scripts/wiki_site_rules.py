#!/usr/bin/env python3
"""wiki_site_rules.py — per-site extraction rules for the clip
converter (Marathon Round 3, lane TA4; row: "per-site
extraction rules", pattern: wallabag's per-site extraction
rules — idea re-implemented, no code copied).

Some sites need extraction overrides the generic converter
cannot guess: a comments rail that is not marked as chrome, a
content wrapper with a site-specific class, a title that lives
in a byline element. Those overrides live in a RULES FILE —
templates/site-rules.json in the tree — one rule per domain:

    {"domain": "example.com",
     "keep": ".article-body",        (selector, or null)
     "strip": [".comments", "#paywall-banner"],
     "title_selector": "h2.headline", (selector, or null)
     "note": "why this site needs the override"}

A rule matches a URL whose host is the domain or a subdomain
of it. The clip path (scripts/wiki_clip.py) merges the matched
rule with the auto-selected clip template
(scripts/wiki_clip_templates.py): the rule's `keep` and
`title_selector` win when set (a per-site fact beats a generic
shape), and the strip lists are unioned. The rule that fired
is recorded in the clip's ingest sidecar.

SELECTOR VOCABULARY (deliberately small): `tag`, `.class`,
`#id`, `tag.class`, `tag#id`. apply_profile() rewrites an HTML
document under a profile {keep, strip, title_selector}:
elements matching a strip selector are dropped with their
subtrees; when `keep` is set, only the FIRST element matching
it is kept (everything outside it is dropped); the title is
the text of the first element matching `title_selector`. It
returns (html, applied) where applied says what actually
happened — strips that matched nothing are reported, so a
rotted rule is visible instead of silently doing nothing.

    python3 scripts/wiki_site_rules.py check [--root DIR]
    python3 scripts/wiki_site_rules.py match <url> [--root DIR]
    python3 scripts/wiki_site_rules.py apply <file.html> <url>

Exit codes: 0 ok · 1 refusal / invalid rules · 2 usage error.
"""
import argparse
import html as html_mod
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = Path("templates/site-rules.json")

_SELECTOR_RE = re.compile(
    r"^(?:(?P<tag>[a-zA-Z][a-zA-Z0-9]*))?"
    r"(?:\.(?P<cls>[a-zA-Z0-9_-]+)|#(?P<ident>[a-zA-Z0-9_-]+))?$")
VOID = {"br", "hr", "img", "meta", "link", "input", "wbr"}


class RuleError(Exception):
    pass


def parse_selector(selector):
    """'tag.class' -> (tag|None, class|None, id|None). Raises
    RuleError on anything outside the small vocabulary."""
    m = _SELECTOR_RE.match((selector or "").strip())
    if not m or not (m.group("tag") or m.group("cls")
                     or m.group("ident")):
        raise RuleError("unsupported selector %r — the "
                        "vocabulary is tag, .class, #id, "
                        "tag.class, tag#id" % selector)
    return (m.group("tag").lower() if m.group("tag") else None,
            m.group("cls"), m.group("ident"))


def validate_rules(data, source="rules"):
    if not isinstance(data, list):
        raise RuleError("%s must be a JSON list of rule objects"
                        % source)
    for rule in data:
        if not isinstance(rule, dict) or not rule.get("domain"):
            raise RuleError("%s: every rule needs a domain"
                            % source)
        for sel in rule.get("strip") or []:
            parse_selector(sel)
        for key in ("keep", "title_selector"):
            if rule.get(key):
                parse_selector(rule[key])
    return data


def load_rules(root=ROOT):
    """The tree's rules file; an absent file is an empty rule
    set (stated by check), a malformed one is a loud error."""
    path = Path(root) / RULES_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuleError("site rules %s are unreadable: %s"
                        % (path, exc)) from exc
    return validate_rules(data, source=str(path))


def match_rule(url, rules):
    """The first rule whose domain is the URL's host or a
    parent of it; None when no rule covers the site."""
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return None
    for rule in rules:
        domain = str(rule.get("domain", "")).lower()
        if host == domain or host.endswith("." + domain):
            return rule
    return None


def merge_profiles(template_profile, rule):
    """Merge a clip template's profile with a site rule: the
    rule's keep / title_selector win when set; strip lists are
    unioned (template order first)."""
    profile = {"keep": (template_profile or {}).get("keep"),
               "strip": list((template_profile or {}).get("strip")
                             or []),
               "title_selector": (template_profile or {}).get(
                   "title_selector")}
    if rule:
        if rule.get("keep"):
            profile["keep"] = rule["keep"]
        if rule.get("title_selector"):
            profile["title_selector"] = rule["title_selector"]
        for sel in rule.get("strip") or []:
            if sel not in profile["strip"]:
                profile["strip"].append(sel)
    return profile


def _matches(tag, attrs, selector):
    want_tag, want_cls, want_id = parse_selector(selector)
    if want_tag and tag != want_tag:
        return False
    if want_id and attrs.get("id") != want_id:
        return False
    if want_cls and want_cls not in (attrs.get("class") or "").split():
        return False
    return True


class _ProfileParser(HTMLParser):
    """Event parser that rebuilds the document under a
    profile: strip subtrees dropped, and — with a keep
    selector — only the first matching subtree retained.
    Emitting rule for any event: no ancestor is dropped, and
    either there is no keep selector or a keep ancestor is
    open."""

    def __init__(self, profile):
        super().__init__(convert_charrefs=True)
        self.strip = list(profile.get("strip") or [])
        self.keep = profile.get("keep")
        self.title_selector = profile.get("title_selector")
        self.out = []
        self.stack = []        # (tag, mode): emit|drop|keep|hold
        self.keep_found = False
        self.stripped = []
        self.title_parts = []
        self._title_depth = 0

    def _emitting(self, stack=None):
        modes = [m for _t, m in (stack if stack is not None
                                 else self.stack)]
        if "drop" in modes:
            return False
        if self.keep and "keep" not in modes:
            return False
        return True

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        modes = [m for _t, m in self.stack]
        if "drop" in modes:
            self.stack.append((tag, "drop"))
            return
        matched_strip = next((s for s in self.strip
                              if _matches(tag, attrs, s)), None)
        if matched_strip:
            self.stripped.append(matched_strip)
            self.stack.append((tag, "drop"))
            return
        if self.keep and not self.keep_found \
                and _matches(tag, attrs, self.keep):
            self.keep_found = True
            self.out = []  # held content before the keep root
            self.stack.append((tag, "keep"))
        elif self.keep and "keep" not in modes:
            self.stack.append((tag, "hold"))
            return
        else:
            self.stack.append((tag, "emit"))
        if self.title_selector and self._emitting():
            if not self._title_depth and _matches(
                    tag, attrs, self.title_selector):
                self._title_depth = 1
            elif self._title_depth:
                self._title_depth += 1
        attr_text = "".join(
            ' %s="%s"' % (k, html_mod.escape(v or "", quote=True))
            for k, v in attrs.items())
        self.out.append("<%s%s>" % (tag, attr_text))

    def handle_endtag(self, tag):
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                idx = i
                break
        if idx is None:
            return
        was_emitting = self._emitting()
        del self.stack[idx:]
        if self._title_depth:
            self._title_depth -= 1
        if was_emitting and tag not in VOID:
            self.out.append("</%s>" % tag)

    def handle_data(self, data):
        if self._title_depth and self._emitting():
            self.title_parts.append(data)
        if self._emitting():
            self.out.append(html_mod.escape(data, quote=False))


def apply_profile(html_text, profile):
    """Rewrite `html_text` under a profile. Returns
    (new_html, applied) — applied records the keep selector
    used (or None), whether it matched, the strip selectors
    that actually matched, and the extracted title (or None).
    A keep selector that matches nothing leaves the document
    otherwise intact except strips — a rotted keep rule must
    not produce an empty capture."""
    parser = _ProfileParser(profile or {})
    parser.feed(html_text or "")
    parser.close()
    title = " ".join("".join(parser.title_parts).split()) or None
    applied = {"keep": (profile or {}).get("keep"),
               "keep_matched": parser.keep_found,
               "stripped": parser.stripped,
               "title": title}
    if profile and profile.get("keep") and not parser.keep_found:
        # re-run without keep: strips + title only
        fallback = dict(profile)
        fallback["keep"] = None
        parser2 = _ProfileParser(fallback)
        parser2.feed(html_text or "")
        parser2.close()
        applied["stripped"] = parser2.stripped
        applied["title"] = (" ".join(
            "".join(parser2.title_parts).split()) or None)
        return "".join(parser2.out), applied
    return "".join(parser.out), applied


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("match")
    p.add_argument("url")
    p = sub.add_parser("apply")
    p.add_argument("file")
    p.add_argument("url")
    args = ap.parse_args(argv)
    try:
        rules = load_rules(args.root)
        if args.cmd == "check":
            print("site rules: %d rule(s) in %s"
                  % (len(rules), args.root / RULES_FILE))
            for rule in rules:
                print("  %s — %s" % (rule["domain"],
                                      rule.get("note") or ""))
        elif args.cmd == "match":
            rule = match_rule(args.url, rules)
            print(json.dumps(rule, indent=2, sort_keys=True)
                  if rule else "no site rule for %s" % args.url)
        else:
            rule = match_rule(args.url, rules)
            profile = merge_profiles(None, rule)
            text = Path(args.file).read_text(encoding="utf-8",
                                             errors="replace")
            new_html, applied = apply_profile(text, profile)
            print(json.dumps(applied, indent=2, sort_keys=True),
                  file=sys.stderr)
            sys.stdout.write(new_html)
    except RuleError as exc:
        print("wiki_site_rules: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
