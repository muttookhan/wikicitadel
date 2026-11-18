#!/usr/bin/env python3
"""Build a throwaway fixture wiki + fixture token registry.

FIXTURES ONLY. The tokens created here protect a temporary test tree
in a temp directory; they are not credentials for anything real.
No real tokens are ever issued by this build (see BUILD-RECORD.md).

Usage (standalone):
  python3 fixtures/make_fixtures.py <target-dir>
  -> prints JSON {root, state_dir, tokens{identity: token}}

Tests import build_fixture() directly.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.config import Config  # noqa: E402
from gateway.registry import Registry  # noqa: E402

ALPHA = """---
title: Alpha Concept
type: concept
---

# Alpha Concept

The alpha concept links to [[beta]] and mentions the unique
token zqxjv-alphaseed for search tests.
"""

BETA = """---
title: Beta Entity
type: entity
---

# Beta Entity

Beta is an entity page that links back to [[alpha-concept]].
"""

ALPHA_PATH = "wiki/concepts/alpha.md"
BETA_PATH = "wiki/entities/beta.md"

SYNTH = """---
title: Fixture Synthesis
type: synthesis
---

# Fixture Synthesis

A synthesis over [[alpha]] and [[beta]].
"""

DECISION = """---
title: "Decision: fixture decision"
type: decision
id: decision-fixture
status: decided
decided_by: owner
decided_at: 2026-01-01
---

# Decision: fixture decision

Body of the fixture decision.
"""

FIELD_NOTES = "Raw field notes, in collaborator-a's source scope.\n"
RESTRICTED = "Restricted raw source, outside collaborator-a's source scope.\n"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def build_fixture(base: Path) -> dict:
    base = Path(base)
    root = base / "wiki-repo"
    state = base / "state"
    root.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    _write(root, ALPHA_PATH, ALPHA)
    _write(root, BETA_PATH, BETA)
    _write(root, "wiki/syntheses/synth.md", SYNTH)
    _write(root, "wiki/decisions/decision-fixture.md", DECISION)
    _write(root, "wiki/index.md", "# Index\n\n- [[alpha]]\n- [[beta]]\n")
    _write(root, "raw/sources/field-notes.md", FIELD_NOTES)
    _write(root, "raw/sources/restricted/mufti-only.md", RESTRICTED)
    _write(root, "AGENTS.md", "# Fixture schema\n")
    _write(root, "purpose.md", "# Fixture purpose\n")

    def git(*argv):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True, text=True)

    git("init", "-q")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "add", "-A")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-q", "-m", "fixture baseline")

    env = {
        "GATEWAY_WIKI_ROOT": str(root),
        "GATEWAY_STATE_DIR": str(state),
        "GATEWAY_GIT_COMMIT": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    cfg = Config(env={**env, "PATH": "/usr/bin:/bin"})  # Config reads only GATEWAY_* keys
    cfg.wiki_root = root
    cfg.state_dir = state
    cfg.registry_path = state / "registry.json"
    cfg.ledger_dir = state / "ledger"
    cfg.staging_dir = state / "staging"
    cfg.reviews_dir = state / "reviews"
    cfg.authorisations_dir = state / "authorisations"
    cfg.anchors_dir = state / "anchors"
    cfg.git_commit = True
    cfg.ensure_state_dirs()

    reg = Registry(cfg.registry_path)
    tokens = {
        "owner": reg.issue("owner", ["wiki:read", "wiki:propose", "wiki:publish", "wiki:admin"],
                           note="fixture owner"),
        "agent": reg.issue("agent", ["wiki:read", "wiki:propose", "wiki:publish"],
                            note="fixture maintainer"),
        "collaborator-a": reg.issue(
            "collaborator-a", ["wiki:read", "wiki:propose"],
            read_prefixes=["wiki/concepts", "wiki/entities", "wiki/syntheses", "wiki/index.md"],
            source_prefixes=["raw/sources/field-notes.md"],
            note="fixture scoped agent",
        ),
        "collaborator-b": reg.issue(
            "collaborator-b", ["wiki:read", "wiki:propose"],
            read_prefixes=["wiki/concepts", "wiki/entities"],
            note="fixture scoped agent",
        ),
    }
    return {"root": root, "state_dir": state, "tokens": tokens, "env": env, "config": cfg}


if __name__ == "__main__":
    out = build_fixture(Path(sys.argv[1]))
    print(json.dumps({"root": str(out["root"]), "state_dir": str(out["state_dir"]),
                      "tokens": out["tokens"]}, indent=2))
