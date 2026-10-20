"""Scope model and path classification (design §4.6, §4.2, §4.3).

Default-deny: anything not explicitly allowed by an identity's scopes
and path prefixes is denied. Denied reads return the same response
shape as a missing object, so the caller cannot learn whether an
out-of-scope object exists (design §5.2 Door A).

Path classes:
  wiki      wiki/**/*.md pages
  decision  wiki/decisions/** (subset of wiki, listed separately)
  access    wiki/access/** — Black Box ledgers; admin scope only
  raw       raw/** — requires an explicit source prefix grant
  staging   staging area (gateway-managed, never a read target)
  other     anything else — always denied for reads
"""
from __future__ import annotations

SCOPE_READ = "wiki:read"
SCOPE_PROPOSE = "wiki:propose"
SCOPE_PUBLISH = "wiki:publish"
SCOPE_ADMIN = "wiki:admin"


def normalise(rel: str) -> str | None:
    """Normalise a repo-relative path; None if it escapes or is malformed."""
    if not rel or rel.startswith("/") or "\\" in rel:
        return None
    parts = []
    for seg in rel.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            return None
        parts.append(seg)
    if not parts:
        return None
    return "/".join(parts)


def classify(rel: str) -> str:
    if rel.startswith("wiki/access/"):
        return "access"
    if rel.startswith("wiki/decisions/"):
        return "decision"
    if rel.startswith("wiki/"):
        return "wiki"
    if rel.startswith("raw/"):
        return "raw"
    if rel.startswith("staging/"):
        return "staging"
    return "other"


def _under_prefix(rel: str, prefixes) -> bool:
    if prefixes is None:
        return False
    return any(rel == p.rstrip("/") or rel.startswith(p.rstrip("/") + "/") for p in prefixes)


def can_read(entry: dict, rel: str) -> bool:
    """Whether the identity record may read repo-relative path `rel`."""
    scopes = set(entry.get("scopes", []))
    if SCOPE_READ not in scopes and SCOPE_ADMIN not in scopes:
        return False
    cls = classify(rel)
    if cls == "access":
        return SCOPE_ADMIN in scopes
    if cls in ("wiki", "decision"):
        if SCOPE_ADMIN in scopes:
            return True
        prefixes = entry.get("read_prefixes")
        if prefixes is None:
            # Read scope without prefix restriction covers the wiki
            # tree but never raw (raw needs an explicit source grant).
            return True
        return _under_prefix(rel, prefixes)
    if cls == "raw":
        if SCOPE_ADMIN in scopes:
            return True
        return _under_prefix(rel, entry.get("source_prefixes"))
    return False


def can_propose(entry: dict) -> bool:
    return SCOPE_PROPOSE in set(entry.get("scopes", [])) or SCOPE_ADMIN in set(entry.get("scopes", []))


def can_publish(entry: dict) -> bool:
    return SCOPE_PUBLISH in set(entry.get("scopes", [])) or SCOPE_ADMIN in set(entry.get("scopes", []))


# Paths whose promotion changes meaning at the G5 level (decision,
# schema, purpose). Promotion into them requires an owner decision
# reference in the authorisation record (design §4.3 G5).
def is_gate5_target(rel: str) -> bool:
    return (
        classify(rel) == "decision"
        or rel in ("AGENTS.md", "purpose.md")
        or rel.startswith("wiki/access/")
    )
