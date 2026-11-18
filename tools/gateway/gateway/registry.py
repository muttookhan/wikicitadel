"""Bearer-token registry — salted hashes only, stored outside git.

Implements design §4.6 steps 1-4: the Owner admin workflow issues one
bearer token per approved identity; the server stores only a salted
hash; every request re-resolves identity from the token and re-checks
revocation and scope (so a revoked or rotated token fails on the very
next request).

Identity is resolved from the token, never from a name asserted by
the client (design §5.2 Door A).

A reserved seat fails closed: while an identity's seat is
reserved (a governance decision recorded by the deployment), no
token can be issued for, or authenticated as, that identity. The
reference deployment reserves the seat named in DENY_IDENTITIES.

Token format: wct1.<identity>.<secret>  — only the identity segment
is non-secret routing information; the secret is verified against a
PBKDF2-HMAC-SHA256 salted hash with a constant-time comparison.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
from pathlib import Path

from .ledger import utcnow

PBKDF2_ITERATIONS = 200_000
DENY_IDENTITIES = {"reserved-agent"}  # a seat reserved by governance decision fails closed
ALL_SCOPES = {"wiki:read", "wiki:propose", "wiki:publish", "wiki:admin"}


class RegistryError(Exception):
    pass


def _hash_secret(secret: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    ).hex()


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)
        # Audit L3: set when the registry file exists but cannot be
        # parsed — the registry then denies everyone (empty identity
        # map) instead of crashing the server, and the server writes
        # this string into the ledger on every denial it causes.
        self.load_error: str | None = None
        self._error_reported: str | None = None

    # -- storage -----------------------------------------------------
    def _load(self) -> dict:
        if not self.path.exists():
            self.load_error = None
            return {"identities": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or \
                    not isinstance(data.get("identities", {}), dict):
                raise ValueError(
                    "registry root is not an object with an "
                    "'identities' map")
        except Exception as exc:
            # Deny-all, loudly: stderr once per distinct failure, and
            # `load_error` stays set for the ledger trail.
            err = f"{type(exc).__name__}: {exc}"
            if err != self._error_reported:
                print(f"gateway registry: FAILED to load {self.path} "
                      f"({err}); denying all identities until fixed",
                      file=sys.stderr, flush=True)
                self._error_reported = err
            self.load_error = err
            return {"identities": {}}
        self.load_error = None
        self._error_reported = None
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # -- admin operations (Owner ceremony; exercised by fixtures) ----
    def issue(self, identity: str, scopes: list[str], read_prefixes=None,
              source_prefixes=None, note: str = "") -> str:
        """Create or rotate the token for an identity. Returns the
        plaintext token exactly once; only its salted hash is kept."""
        if identity in DENY_IDENTITIES:
            raise RegistryError(
                f"identity '{identity}' is refused: seat reserved (governance decision), fails closed"
            )
        bad = set(scopes) - ALL_SCOPES
        if bad:
            raise RegistryError(f"unknown scopes: {sorted(bad)}")
        secret = secrets.token_hex(24)
        token = f"wct1.{identity}.{secret}"
        salt = secrets.token_hex(16)
        data = self._load()
        data["identities"][identity] = {
            "identity": identity,
            "salt": salt,
            "hash": _hash_secret(secret, salt),
            "scopes": sorted(scopes),
            "read_prefixes": read_prefixes,
            "source_prefixes": source_prefixes,
            "status": "active",
            "issued_at": utcnow(),
            "note": note,
        }
        self._save(data)
        return token

    def revoke(self, identity: str) -> None:
        data = self._load()
        entry = data["identities"].get(identity)
        if entry is None:
            raise RegistryError(f"unknown identity: {identity}")
        entry["status"] = "revoked"
        entry["revoked_at"] = utcnow()
        self._save(data)

    def get(self, identity: str) -> dict | None:
        return self._load()["identities"].get(identity)

    def list_identities(self) -> list[dict]:
        data = self._load()
        return [
            {k: v for k, v in e.items() if k not in ("salt", "hash")}
            for e in data["identities"].values()
        ]

    # -- per-request authentication ----------------------------------
    def authenticate(self, token: str | None) -> dict | None:
        """Resolve identity from a bearer token. Re-reads the registry
        on every call so revocation/rotation apply to the next request.
        Returns the identity record or None (default-deny)."""
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "wct1":
            return None
        identity, secret = parts[1], parts[2]
        if identity in DENY_IDENTITIES:
            return None
        entry = self.get(identity)
        if entry is None or entry.get("status") != "active":
            return None
        candidate = _hash_secret(secret, entry["salt"])
        if not hmac.compare_digest(candidate, entry["hash"]):
            return None
        return entry
