"""Configuration for the gateway build.

Everything stateful that is NOT wiki content lives outside git, in the
state directory (design §4.6: the server stores only salted token
hashes, in a secret registry outside git; §9: no token or credential
is stored in canonical wiki content or git).

Activation-time locations (wiki/access/ ledgers, repo staging/) are
owner-gate decisions (design §10). This build therefore defaults the
ledger, staging, registry and anchor output to the state directory;
the production configuration points them at the repo only after the
the build gate approvals recorded in BUILD-RECORD.md.
"""
from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    # tools/gateway/gateway/config.py -> repo root is parents[3].
    return Path(__file__).resolve().parents[3]


class Config:
    def __init__(self, env: dict | None = None):
        env = os.environ if env is None else env
        self.wiki_root = Path(env.get("GATEWAY_WIKI_ROOT", _repo_root())).resolve()
        self.state_dir = Path(
            env.get("GATEWAY_STATE_DIR", Path.home() / ".local/state/wikicitadel-gateway")
        ).resolve()
        self.registry_path = Path(
            env.get("GATEWAY_REGISTRY", self.state_dir / "registry.json")
        ).resolve()
        self.ledger_dir = Path(env.get("GATEWAY_LEDGER_DIR", self.state_dir / "ledger")).resolve()
        self.staging_dir = Path(env.get("GATEWAY_STAGING_DIR", self.state_dir / "staging")).resolve()
        self.reviews_dir = self.state_dir / "reviews"
        self.authorisations_dir = self.state_dir / "authorisations"
        self.eval_overrides_dir = self.state_dir / "eval-overrides"
        # Eval gate (the build): optional overrides for the report /
        # baseline locations; defaults live in gateway/evalgate.py
        # (evaluation/results/extended-latest.json and
        # evaluation/extended-baseline.json under the wiki root).
        _er = env.get("GATEWAY_EVAL_REPORT")
        _eb = env.get("GATEWAY_EVAL_BASELINE")
        self.eval_report_path = Path(_er).resolve() if _er else None
        self.eval_baseline_path = Path(_eb).resolve() if _eb else None
        self.anchors_dir = self.state_dir / "anchors"
        # Lifecycle profile (harvest item 7): defaults to the
        # profile shipped with the wiki; GATEWAY_PROFILE overrides.
        # Absent/malformed profile = machinery inert.
        self.profile_path = Path(
            env.get("GATEWAY_PROFILE",
                    self.wiki_root / "tools/gateway/profiles/wiki-default.json")
        ).resolve()
        # Promotion performs a git commit in the target wiki only when
        # explicitly enabled (production: the maintainer's git-mediated
        # workflow, design Door B). Default off; fixtures turn it on to
        # prove session -> proposal -> manifest -> commit linkage.
        self.git_commit = env.get("GATEWAY_GIT_COMMIT", "0") == "1"

    def ensure_state_dirs(self) -> None:
        for d in (
            self.state_dir,
            self.ledger_dir,
            self.staging_dir,
            self.reviews_dir,
            self.authorisations_dir,
            self.eval_overrides_dir,
            self.anchors_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
