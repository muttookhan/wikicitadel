#!/usr/bin/env python3
"""WCAG numeric gate for the Lens — a smoke lane of its own.

Consolidated the build programme (wave-10 synthesis §3, the surfaces build;
wave-7 surfaces lane, WCAG material): the accessibility checks
that can be done MECHANICALLY over the built artefact, done
mechanically — contrast ratios computed from the palette tokens
in the built lens.css, target sizes computed from the built
rules, focus visibility checked as a property of the CSS, and
the §1.4.8 / §1.4.12 reading-surface properties inspected in the
stylesheet (inspection, honestly labelled — a stylesheet cannot
prove rendered behaviour, and this lane does not claim it does;
axe-core's own literature puts automated detection at ~57% of
issues, so this lane is a floor, not a ceiling).

Usage: python3 tools/lens/wcag_gate.py [site-dir]
Exit code 0 iff every AA-required check passes. AAA and
inspection items report as WARN and never fail the lane.

The gate REPORTS failures; it does not fix the palette. A failing
pair is a finding for the owner, printed with the ratios of the
obvious remediations so the ruling is informed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AA_NORMAL = 4.5   # §1.4.3, normal text
AA_LARGE = 3.0    # §1.4.3, large text (>= 24px, or 18.66px bold)
AA_NONTEXT = 3.0  # §1.4.11, UI components / graphical objects
AA_TARGET = 24    # §2.5.8 (WCAG 2.2), minimum target size, px
AAA_TARGET = 44   # §2.5.5, enhanced target size, px


def _lin(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_colour):
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(fg, bg):
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def parse_tokens(css):
    m = re.search(r":root\s*{([^}]*)}", css, re.S)
    tokens = {}
    if m:
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)):
            tokens[name] = value.strip()
    return tokens


def resolve(tokens, value):
    """Resolve a var(--x) chain to a hex colour, or return the
    literal value."""
    seen = set()
    while value.startswith("var(") and value not in seen:
        seen.add(value)
        inner = value[value.index("(") + 1:value.rindex(")")]
        value = tokens.get(inner.strip(), value)
    return value


def parse_rules(css):
    """selector -> declaration body (last rule wins, as in CSS for
    equal specificity — good enough for our own stylesheet).
    Comments are stripped first so a comment block above a rule
    does not become part of its selector key."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = {}
    for sel, body in re.findall(r"([^{}]+){([^{}]*)}", css):
        for s in sel.split(","):
            rules[s.strip()] = body
    return rules


def strip_media(css):
    """The stylesheet with @media blocks removed (balanced-brace
    scan): the gate evaluates the default presentation, and the
    print block's `body { background: #fff }` must not shadow the
    real body rule. Phone-only rules (the tab bar) are read from
    the full parse instead — see run()."""
    out, i, n = [], 0, len(css)
    while i < n:
        if css.startswith("@media", i):
            j = css.index("{", i)
            depth, k = 0, j
            while k < n:
                if css[k] == "{":
                    depth += 1
                elif css[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            i = k + 1
        else:
            out.append(css[i])
            i += 1
    return "".join(out)


def _px(value):
    m = re.search(r"([\d.]+)px", value or "")
    return float(m.group(1)) if m else None


def rule_height(rules, selector):
    """Effective target height for a rule: min-height if set,
    else vertical padding + one line of text (font-size × the
    rule's line-height, defaulting to the body 1.55)."""
    body = rules.get(selector, "")
    mh = _px(re.search(r"min-height\s*:\s*([\d.]+)px", body).group(0)) \
        if "min-height" in body else None
    if mh:
        return mh
    pad = re.search(r"padding\s*:\s*([\d.]+)px", body)
    pad_v = 2 * float(pad.group(1)) if pad else 0.0
    fs = _px(re.search(r"font-size\s*:\s*([\d.]+)px", body).group(0)) \
        if "font-size" in body else 16.0
    lh_m = re.search(r"line-height\s*:\s*([\d.]+)", body)
    lh = float(lh_m.group(1)) if lh_m else 1.55
    return pad_v + (fs or 16.0) * lh


def run(site):
    site = Path(site)
    css_path = site / "lens.css"
    results = []  # (level, name, ok, detail)  level: AA | WARN

    def check(level, name, ok, detail):
        results.append((level, name, ok, detail))

    if not css_path.exists():
        print(f"WCAG GATE: built lens.css not found at {css_path}")
        return 1
    css = css_path.read_text(encoding="utf-8")
    tokens = parse_tokens(css)
    rules = parse_rules(css)
    base_rules = parse_rules(strip_media(css))

    def colour(token):
        return resolve(tokens, tokens.get(token, ""))

    # ---- Text contrast (§1.4.3, AA) ----
    text_pairs = [
        ("ink-1 on bg-canvas (body text)", "--ink-1", "--bg-canvas", AA_NORMAL),
        ("ink-1 on surface-1 (panel text)", "--ink-1", "--surface-1", AA_NORMAL),
        ("ink-1 on surface-2 (card text)", "--ink-1", "--surface-2", AA_NORMAL),
        ("ink-2 on surface-1 (secondary text)", "--ink-2", "--surface-1", AA_NORMAL),
        ("ink-2 on bg-canvas", "--ink-2", "--bg-canvas", AA_NORMAL),
        ("ink-3 on surface-1 (captions, 12.5px)", "--ink-3", "--surface-1", AA_NORMAL),
        ("ink-3 on bg-canvas (captions)", "--ink-3", "--bg-canvas", AA_NORMAL),
        ("gold-300 on surface-1 (link hover)", "--gold-300", "--surface-1", AA_NORMAL),
        ("ink-on-light on gold-500 (primary button)", "--ink-on-light", "--gold-500", AA_NORMAL),
        ("status-verified text on bg-canvas (verified line)", "--status-verified", "--bg-canvas", AA_NORMAL),
        ("status-stale text on surface-1 (missing-link)", "--status-stale", "--surface-1", AA_NORMAL),
    ]
    status_tokens = ["--status-decided", "--status-verified", "--status-open",
                     "--status-stale", "--status-atrisk", "--status-broken",
                     "--status-unattributed", "--status-info"]
    for tok in status_tokens:
        text_pairs.append((f"ink-on-light on {tok[2:]} (chip text, 12.5px bold)",
                           "--ink-on-light", tok, AA_NORMAL))
    for name, fg_t, bg_t, req in text_pairs:
        fg, bg = colour(fg_t), colour(bg_t)
        if not (fg.startswith("#") and bg.startswith("#")):
            check("AA", name, False, f"unresolvable colours {fg_t}={fg} {bg_t}={bg}")
            continue
        ratio = contrast_ratio(fg, bg)
        detail = f"{fg} on {bg} = {ratio:.2f}:1 (required {req}:1)"
        if ratio < req and bg_t in status_tokens:
            alt = contrast_ratio("#FFFFFF", bg)
            detail += (f" — remediation data: pure-white text would give "
                       f"{alt:.2f}:1; the token itself is the owner's "
                       "design system, this lane does not change it")
        check("AA", name, ratio >= req, detail)

    # ---- Non-text contrast (§1.4.11, AA) ----
    for name, fg_t, bg_t in [
            ("focus outline gold-300 on surface-1", "--gold-300", "--surface-1"),
            ("focus outline gold-300 on surface-2", "--gold-300", "--surface-2"),
            ("gold-500 on surface-1 (bullet bars / accents)", "--gold-500", "--surface-1"),
            ("status-atrisk on surface-1 (overdue block)", "--status-atrisk", "--surface-1")]:
        ratio = contrast_ratio(colour(fg_t), colour(bg_t))
        check("AA", name, ratio >= AA_NONTEXT,
              f"{colour(fg_t)} on {colour(bg_t)} = {ratio:.2f}:1 (required {AA_NONTEXT}:1)")

    # ---- Focus visibility (§2.4.7) ----
    fv = rules.get(":focus-visible", "")
    ow = _px(fv)
    check("AA", "focus-visible outline present (>= 2px, offset)",
          ow is not None and ow >= 2 and "outline-offset" in fv,
          f":focus-visible rule: {fv.strip()[:90]}")
    check("AA", "skip links reveal on focus",
          ".skip:focus" in rules and "left:" in rules.get(".skip:focus", ""),
          "the .skip links move on-screen under :focus")

    # ---- Target sizes (§2.5.8 AA / §2.5.5 AAA) ----
    for selector, label in [(".btn", "buttons"),
                            (".tab-item", "phone tab bar items"),
                            (".rail-item", "mode rail items"),
                            (".filter-chips .chip", "filter chips"),
                            (".graph-toolbar .chip", "graph toolbar chips"),
                            (".tree-tabs .chip", "tree tab chips"),
                            (".tab-more-panel a", "phone More links"),
                            (".legend-row", "graph legend rows"),
                            ("#tree a", "page tree links")]:
        h = rule_height(rules, selector)
        check("AA", f"target size {label} ({selector}) >= {AA_TARGET}px",
              h >= AA_TARGET, f"computed height {h:.0f}px")
        check("WARN", f"target size {label} ({selector}) >= {AAA_TARGET}px (AAA)",
              h >= AAA_TARGET, f"computed height {h:.0f}px")

    # ---- §1.4.8 reading presentation (AAA standard the survey adopted) ----
    wrap = base_rules.get(".reading-wrap", "")
    mw = re.search(r"max-width\s*:\s*(?:var\(--read-measure,\s*)?([\d.]+)ch", wrap)
    check("WARN", "reading measure <= 80ch (§1.4.8)",
          bool(mw) and float(mw.group(1)) <= 80,
          f".reading-wrap max-width: {mw.group(1) if mw else 'unset'}ch")
    body_rule = base_rules.get("body", "")
    lh = re.search(r"line-height\s*:\s*([\d.]+)", body_rule)
    check("WARN", "body line-height >= 1.5 (§1.4.8)",
          bool(lh) and float(lh.group(1)) >= 1.5,
          f"body line-height: {lh.group(1) if lh else 'unset'}")
    check("WARN", "no justified text anywhere (§1.4.8)",
          "text-align: justify" not in css.replace("text-align:justify", "text-align: justify"),
          "grep over the built stylesheet")

    # ---- §1.4.12 text-spacing resilience (INSPECTION) ----
    # The screen-reader-only utilities (.visually-hidden, .skip)
    # clip BY DESIGN — they are the accessibility feature, not a
    # text container — and are excluded by name.
    clipped = [sel for sel, body in rules.items()
               if sel not in (".visually-hidden", ".skip")
               and "overflow: hidden" in body
               and re.search(r"(?<!max-)height\s*:\s*\d+px", body)]
    check("WARN", "no fixed-height + overflow:hidden text containers (§1.4.12, inspected)",
          not clipped, f"inspected rules; offenders: {clipped or 'none'}")

    # ---- Self-hosted reading assets (item 64) ----
    fonts = site / "fonts"
    check("AA", "Atkinson Hyperlegible self-hosted (WOFF2 + OFL licence)",
          (fonts / "atkinson-hyperlegible-400-latin.woff2").exists()
          and (fonts / "LICENSE-atkinson-hyperlegible.txt").exists(),
          "fonts/ carries the candidate face and its licence")

    fails = [r for r in results if r[0] == "AA" and not r[2]]
    warns = [r for r in results if r[0] == "WARN" and not r[2]]
    for level, name, ok, detail in results:
        mark = "PASS" if ok else ("FAIL" if level == "AA" else "WARN")
        print(f"{mark} [{level}] {name} — {detail}")
    print(f"WCAG GATE: {len(results) - len(fails) - len(warns)}/{len(results)} "
          f"clean · {len(fails)} AA failure(s) · {len(warns)} warning(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1
                 else Path.home() / "workspace" / "lens-site"))
