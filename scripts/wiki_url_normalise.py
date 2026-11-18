#!/usr/bin/env python3
"""wiki_url_normalise.py - tracking-parameter stripping at capture
(Marathon R7, lane BA; Miniflux sub-mechanism, Apache-2.0, re-implemented).

The URL recorded for a capture is NORMALISED: tracking parameters
(utm_* and kin) are stripped and FeedBurner-style redirect wrappers are
unwrapped to the article they point at. The ORIGINAL url is never
discarded by this module - it returns both forms and the callers
(wiki_clip.py's sidecar/draft, wiki_snapshot.py's bundle manifest)
record the original verbatim beside the normalised form, so provenance
is stated, never falsified: the normalised URL is where the capture
points, the original is the record of how it was reached.

Stdlib only. Exit codes (CLI): 0 ok, 2 usage error.
"""
import sys
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

# Exact tracking parameter names (lower-cased) always stripped.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid",
    "mc_cid", "mc_eid", "igshid", "twclid", "li_fat_id",
    "_ga", "_gl", "_hsenc", "_hsmi", "hsctatracking",
    "vero_id", "oly_anon_id", "oly_enc_id",
    "ref_src", "ref_url", "spm", "scm", "wickedid",
}
# Prefixes: any parameter whose name starts with one of these goes.
TRACKING_PREFIXES = ("utm_",)
# FeedBurner-style wrappers: host suffix -> query parameter that
# carries the wrapped target URL.
WRAPPER_PARAMS = {
    "feedburner.com": "url",
    "feeds.feedburner.com": "url",
    "feedproxy.google.com": "url",
}


def _unwrap(url, depth=0):
    """Unwrap one FeedBurner-style redirect wrapper, recursively
    (bounded) - the wrapper's target parameter holds the real URL."""
    if depth > 3:
        return url
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    param = None
    for suffix, p in WRAPPER_PARAMS.items():
        if host == suffix or host.endswith("." + suffix):
            param = p
            break
    if param is None:
        return url
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() == param and val.startswith(("http://", "https://")):
            return _unwrap(val, depth + 1)
    return url


def normalise_url(url):
    """Return (normalised, original, changes).

    `original` is the input, byte-for-byte. `changes` names what
    was done: "unwrapped:<host>", "stripped:<param>" entries, in
    the order applied. A URL with nothing to strip returns
    (url, url, []). Non-http(s) or unparseable input is returned
    unchanged with no changes - this module never invents a URL.
    """
    original = url
    if not isinstance(url, str) or not url:
        return url, original, []
    changes = []
    unwrapped = _unwrap(url)
    if unwrapped != url:
        changes.append("unwrapped:%s" % (urlparse(url).hostname or ""))
        url = unwrapped
    try:
        parts = urlparse(url)
    except ValueError:
        return original, original, changes
    if parts.scheme not in ("http", "https"):
        return original, original, changes
    kept = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        lk = key.lower()
        if lk in TRACKING_PARAMS or lk.startswith(TRACKING_PREFIXES):
            changes.append("stripped:%s" % key)
            continue
        kept.append((key, val))
    normalised = urlunparse(parts._replace(
        query=urlencode(kept, quote_via=quote)))
    return normalised, original, changes


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: wiki_url_normalise.py <url>", file=sys.stderr)
        return 2
    normalised, original, changes = normalise_url(argv[0])
    print(json_out(normalised, original, changes))
    return 0


def json_out(normalised, original, changes):
    import json as _json
    return _json.dumps({"url": normalised, "original_url": original,
                        "changes": changes}, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
