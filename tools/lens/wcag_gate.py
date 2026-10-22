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

Build-list W2 (2026-10-22) extends the lane with the typography
assertions proper — see typography_results(): §1.4.8's
paragraph-spacing term on the reading surface, §1.4.12's override
VALUES as stylesheet properties, §1.4.4 / §1.4.10 resize-and-
reflow PROXIES (labelled proxies — rendered behaviour at 200% is
a browser measurement this lane does not perform), the print
template (the tree's one PDF/print surface: the @media print
blocks of this same stylesheet), and the shipped reading presets
— including the BDA Comfort preset's values — read off the built
app.js.
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


def media_blocks(css, needle):
    """Inner text of every @media block whose prelude contains
    `needle` (balanced-brace scan, the strip_media pattern)."""
    blocks, i, n = [], 0, len(css)
    while True:
        j = css.find("@media", i)
        if j < 0:
            return blocks
        brace = css.index("{", j)
        depth, k = 0, brace
        while k < n:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if needle in css[j:brace]:
            blocks.append(css[brace + 1:k])
        i = k + 1


def merged_rules(css):
    """selector -> concatenated declaration bodies. Unlike
    parse_rules (last rule wins), this unions every rule for a
    selector: the reading surface styles one selector across
    several rules (font on one line, margin on the next), and a
    typography check needs the union."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    merged = {}
    for sel, body in re.findall(r"([^{}]+){([^{}]*)}", css):
        for s in sel.split(","):
            s = s.strip()
            if s and not s.startswith("@"):
                merged[s] = merged.get(s, "") + ";" + body
    return merged


def _var_fallback(value, var_name):
    """The numeric fallback of var(--x, N) in a declaration
    value, or None."""
    m = re.search(r"var\(\s*" + re.escape(var_name) +
                  r"\s*,\s*([\d.]+)", value or "")
    return float(m.group(1)) if m else None


def _line_height_of(body):
    """(raw, numeric) for a rule body's line-height: a var()
    fallback wins, then a unitless literal. A fixed px value
    returns numeric None with the raw string kept for the
    report — fixed is exactly what the §1.4.12 check hunts."""
    m = re.search(r"line-height\s*:\s*([^;]+)", body or "")
    if not m:
        return None, None
    raw = m.group(1).strip()
    fb = _var_fallback(raw, "--read-lh")
    if fb is not None:
        return raw, fb
    if re.fullmatch(r"[\d.]+", raw):
        return raw, float(raw)
    return raw, None


def typography_results(css, app_js):
    """The build-list W2 typography assertions over the built
    stylesheet (+ the built app.js for the preset checks).
    Returns (level, name, ok, detail) rows in run()'s shape.

    Honesty discipline, same as the rest of the lane: §1.4.8 is
    the AAA standard the survey adopted, so its rows are WARN and
    never fail the gate; the §1.4.4 / §1.4.10 rows are PROXIES —
    they establish that the stylesheet carries none of the static
    patterns that force horizontal scrolling or defeat zoom, and
    are named as proxies because a stylesheet cannot prove
    rendered behaviour; a stylesheet number that misses is a
    FINDING with its numbers printed, never fixed here."""
    results = []

    def check(level, name, ok, detail):
        results.append((level, name, ok, detail))

    base = merged_rules(strip_media(css))
    read_p = base.get(".reading-body p", "")

    # ---- §1.4.8 on the reading surface itself ----
    raw_lh, read_lh = _line_height_of(read_p)
    fs_m = re.search(r"font-size\s*:\s*([^;]+)", read_p)
    read_fs = None
    if fs_m:
        read_fs = _var_fallback(fs_m.group(1), "--read-size")
        if read_fs is None:
            read_fs = _px(fs_m.group(1))
    check("WARN", "reading-surface line-height >= 1.5 (§1.4.8)",
          read_lh is not None and read_lh >= 1.5,
          f".reading-body p line-height: {raw_lh or 'unset'}")
    # Paragraph spacing: adjacent paragraphs collapse their
    # margins, so the gap is the single vertical margin; §1.4.8
    # wants paragraph spacing >= 1.5x the line spacing, read here
    # as the leading — (line-height - 1) x font-size, the space
    # actually added between lines. The interpretation is
    # printed with the numbers.
    mar = re.search(r"margin\s*:\s*([\d.]+)px", read_p)
    mar_b = re.search(r"margin-bottom\s*:\s*([\d.]+)px", read_p)
    gap = None
    if mar_b:
        gap = float(mar_b.group(1))
    elif mar:
        gap = float(mar.group(1))
    if gap is not None and read_lh is not None and read_fs:
        leading = (read_lh - 1.0) * read_fs
        need = 1.5 * leading
        check("WARN", "reading paragraph spacing >= 1.5x line spacing (§1.4.8)",
              gap >= need,
              f"collapsed paragraph margin {gap:.0f}px vs 1.5 x leading "
              f"({leading:.1f}px) = {need:.1f}px at the shipped default "
              f"(font {read_fs:.0f}px, line-height {read_lh}) — a finding "
              "for the owner; this lane does not change the stylesheet")
    else:
        check("WARN", "reading paragraph spacing >= 1.5x line spacing (§1.4.8)",
              False,
              f"inputs unset (margin gap: {gap}, line-height: {raw_lh}, "
              f"font-size: {read_fs})")

    # ---- §1.4.12 override values, as stylesheet properties ----
    # §1.4.12: no loss of content or functionality when a user
    # sets line-height >= 1.5, paragraph spacing >= 2em,
    # letter-spacing >= 0.12em, word-spacing >= 0.16em. What a
    # stylesheet can prove statically: it must not DEFEAT the
    # overrides (!important on the spacing properties) and must
    # not CLIP under them (fixed heights — the Phase-8 check in
    # run() — or nowrap single-line truncation of reading text),
    # and its own line-heights must be relative so enlarged
    # spacing scales instead of overflowing a fixed box.
    imp = re.findall(
        r"(letter-spacing|word-spacing|line-height)\s*:[^;}]*!important", css)
    check("WARN", "no !important on text-spacing properties (§1.4.12, inspected)",
          not imp,
          f"properties forced with !important: {sorted(set(imp)) or 'none'}")
    nowrap = [sel for sel, b in base.items()
              if sel.startswith(".reading-body")
              and "white-space: nowrap" in b]
    check("WARN", "no white-space: nowrap in the reading body (§1.4.12, inspected)",
          not nowrap, f"offenders: {nowrap or 'none'}")
    fixed_lh = []
    for sel in ("body", ".reading-body p"):
        raw, num = _line_height_of(base.get(sel, ""))
        if raw is not None and num is None:
            fixed_lh.append(f"{sel}: {raw}")
    check("WARN", "reading line-heights relative, not fixed px (§1.4.12, inspected)",
          not fixed_lh, f"fixed line-heights: {fixed_lh or 'none'}")

    # ---- §1.4.4 (200% resize) / §1.4.10 (reflow) PROXIES ----
    mw = [sel for sel in ("html", "body") if "min-width" in base.get(sel, "")]
    check("WARN", "PROXY no min-width on html/body (§1.4.10 reflow)",
          not mw, f"offenders: {mw or 'none'}")
    narrow = "\n".join(media_blocks(css, "max-width: 820px"))
    check("WARN", "PROXY narrow-viewport single-column restack (§1.4.10 reflow)",
          "#app" in narrow and "grid-template-columns: 1fr" in narrow
          and "#rail" in narrow and "display: none" in narrow,
          "the <=820px block restacks #app to one column and hides the rail")
    wide = [sel for sel in (".reading-body table", ".reading-body pre")
            if "overflow-x: auto" not in base.get(sel, "")]
    check("WARN", "PROXY wide reading content scrolls internally (§1.4.10 reflow)",
          not wide,
          f"reading blocks without overflow-x: auto: {wide or 'none'}")
    img_ok = any(sel.startswith(".reading-body") and sel.endswith("img")
                 and "max-width: 100%" in b for sel, b in base.items())
    check("WARN", "PROXY reading images fluid (§1.4.10 reflow)",
          img_ok, "a .reading-body img rule carries max-width: 100%")

    # ---- Print template (the tree's PDF/print surface) ----
    print_css = "\n".join(media_blocks(css, "print"))
    if print_css:
        pm = re.search(r"body\s*{([^}]*)}", print_css)
        pbody = pm.group(1) if pm else ""
        check("WARN", "print: light page, dark text (print template)",
              "background: #fff" in pbody and "color: #111" in pbody,
              f"print body rule: {pbody.strip()[:80]}")
        check("WARN", "print: interactive chrome hidden (print template)",
              "#rail" in print_css and "#inspector" in print_css
              and "display: none" in print_css,
              "the print block's display:none list names the rail "
              "and the inspector")
        cm = re.search(r"#canvas\s*{([^}]*)}", print_css)
        pcanvas = cm.group(1) if cm else ""
        check("WARN", "print: reading canvas unclipped (print template)",
              "max-height: none" in pcanvas and "overflow: visible" in pcanvas,
              f"print #canvas rule: {pcanvas.strip()[:80]}")
        shrunk = re.findall(
            r"(?:body|\.reading-body)[^{]*{[^}]*font-size\s*:\s*([\d.]+)px",
            print_css)
        check("WARN", "print: reading text not shrunk below screen size "
                      "(print template)",
              all(float(v) >= 16 for v in shrunk),
              f"font sizes set on body/reading text in print: "
              f"{shrunk or 'none (print inherits the screen typography)'}")
    else:
        check("WARN", "print template present (print template)", False,
              "no @media print block in the built stylesheet")

    # ---- Shipped reading presets (built app.js) ----
    if app_js is None:
        check("AA", "Comfort (BDA) reading preset shipped (build-list W2)",
              False,
              "built app.js not found beside lens.css — the preset "
              "assertions did not run")
    else:
        pm = re.search(r"\{[^{}]*comfort-bda[^{}]*\}", app_js)
        obj = pm.group(0) if pm else ""

        def field(name, quoted=True):
            pat = (name + r':\s*"([^"]*)"') if quoted else \
                  (name + r":\s*([\d.]+)")
            fm = re.search(pat, obj)
            return fm.group(1) if fm else None

        bg = field("bg")
        lum = relative_luminance(bg) if bg and bg.startswith("#") else 0.0
        ok = (field("ls") == "0.35ch" and field("ws") == "1.225ch"
              and field("lig") == "none"
              and field("lh", quoted=False) is not None
              and float(field("lh", quoted=False)) == 2.0
              and bg is not None and lum >= 0.75)
        check("AA", "Comfort (BDA) reading preset shipped (build-list W2)",
              ok,
              f"comfort-bda: ls={field('ls')} ws={field('ws')} "
              f"lh={field('lh', quoted=False)} lig={field('lig')} "
              f"bg={bg} (luminance {lum:.2f}; BDA values: letter-spacing "
              "0.35ch, word-spacing 1.225ch, line-height 2.0, ligatures "
              "off, cream ground)")
        arr = re.search(r"READ_PRESETS\s*=\s*\[(.*?)\];", app_js, re.S)
        measures = [float(v) for v in re.findall(
            r"measure:\s*([\d.]+)", arr.group(1))] if arr else []
        check("WARN", "all shipped reading presets keep measure <= 80ch (§1.4.8)",
              bool(measures) and all(v <= 80 for v in measures),
              f"preset measures (ch): {measures or 'none parsed'}")
    return results


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

    # ---- Typography assertions (build-list W2, 2026-10-22) ----
    app_js_path = site / "app.js"
    app_js = (app_js_path.read_text(encoding="utf-8")
              if app_js_path.exists() else None)
    results.extend(typography_results(css, app_js))

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
