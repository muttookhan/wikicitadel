#!/bin/sh
# One-command Lens rebuild — the freshness mechanism.
#
# The Lens is a static build of the canonical wiki repository.
# It is fresh exactly when it has been rebuilt after the latest
# wiki change: run this after every wiki push (the git remote is canonical,
# so the production pipeline runs the same command on push; this
# script is the local equivalent). Every artefact is stamped with
# the git HEAD it was built from, and the shell displays that
# stamp — a stale copy always says so.
#
# Usage: tools/lens/rebuild.sh [output-dir]
#
# CI: this script is the whole pipeline step — headless,
# non-interactive, idempotent (a rebuild over an existing output
# directory yields exactly the fresh-build result), and it exits
# non-zero if the search parity check against
# scripts/wiki_search.py fails, so a broken build never publishes.
# Requires: Python 3.12 + PyYAML (tools/lens/requirements.txt).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$HERE/../.." && pwd)
OUT=${1:-"$HOME/workspace/lens-site"}
exec python3 "$HERE/build_lens.py" --repo "$REPO" --out "$OUT"
