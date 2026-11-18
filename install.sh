#!/bin/sh
# WikiCitadel — one-command setup check.
# Verifies your Python, then proves the seed installation is sound:
# the corpus validates and every citation resolves against its lockfile.
set -e
cd "$(dirname "$0")"

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit("WikiCitadel needs Python 3.11 or newer (found %s)" % sys.version.split()[0])
print("python %s OK" % sys.version.split()[0])
PY

python3 scripts/wiki_validate.py
python3 scripts/wiki_cite_lock.py check
echo
echo "WikiCitadel is ready. Build the reading portal with:"
echo "  tools/lens/rebuild.sh"
echo "or run the demo container:"
echo "  docker build -t wikicitadel . && docker run -p 8000:8000 wikicitadel"
