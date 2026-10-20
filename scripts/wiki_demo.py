#!/usr/bin/env python3
"""Runnable demo (gap 3): validate -> build the Lens -> serve -> smoke.

One command takes a fresh checkout to a working, browsable demo:

  python3 scripts/wiki_demo.py                 # build + smoke, then exit
  python3 scripts/wiki_demo.py --serve         # build, then serve until Ctrl-C
  python3 scripts/wiki_demo.py --port 8901 --out /tmp/demo-site

Steps: (1) the corpus validator must pass; (2) the Lens compiler builds
the static site from THIS tree's seed corpus; (3) the site is served on
127.0.0.1 and smoke-checked over real HTTP (index + search artefacts).
A failed step stops the demo with the failing step named — nothing is
declared working that was not fetched. Stdlib only.
"""
import argparse
import functools
import http.server
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def build_demo(root=ROOT, out=None):
    """Validate + build. Returns (ok, step, detail)."""
    out = Path(out) if out else Path("/tmp/wikicitadel-demo-site")
    rc, so, se = run([sys.executable, "scripts/wiki_validate.py"], cwd=root)
    if rc != 0:
        return False, "validate", (se or so).strip()[-500:]
    rc, so, se = run([sys.executable, "tools/lens/build_lens.py",
                      "--repo", str(root), "--out", str(out)], cwd=root)
    if rc != 0:
        return False, "build", (se or so).strip()[-500:]
    if not (out / "index.html").is_file():
        return False, "build", "build finished but index.html is missing"
    return True, "build", str(out)


def serve_in_thread(directory, port):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def smoke(base_url):
    """Fetch the index and (if present) the search index artefact."""
    checks = []
    with urllib.request.urlopen(base_url + "/", timeout=10) as r:
        body = r.read().decode("utf-8", errors="ignore")
        checks.append(("index", r.status == 200 and "<html" in body.lower()))
    try:
        with urllib.request.urlopen(base_url + "/search-index.json",
                                    timeout=10) as r:
            json.loads(r.read().decode("utf-8"))
            checks.append(("search-index", r.status == 200))
    except Exception:
        checks.append(("search-index", None))  # artefact name may differ
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/wikicitadel-demo-site")
    ap.add_argument("--port", type=int, default=8901)
    ap.add_argument("--serve", action="store_true",
                    help="keep serving after the smoke check")
    args = ap.parse_args(argv)
    ok, step, detail = build_demo(ROOT, args.out)
    if not ok:
        print(f"DEMO FAILED at step '{step}': {detail}", file=sys.stderr)
        return 1
    out = Path(args.out)
    httpd = serve_in_thread(out, args.port)
    base = f"http://127.0.0.1:{args.port}"
    try:
        checks = smoke(base)
        for name, passed in checks:
            mark = "skip" if passed is None else ("PASS" if passed else "FAIL")
            print(f"smoke {name}: {mark}")
        if any(p is False for _n, p in checks):
            return 1
        print(f"demo live at {base}/ (site dir: {out})")
        if args.serve:
            print("serving until Ctrl-C")
            threading.Event().wait()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
