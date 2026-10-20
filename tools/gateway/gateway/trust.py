"""Trust tiers for sources, with weakest-link propagation.

Pattern (Phase-2 harvest item 1): NicoBleh/secure-llm-wiki (MIT)
auto-detects a trust tier for every source at ingest and propagates
the WEAKEST tier through everything derived from it — a claim is
only ever as trustworthy as the least trusted thing it rests on.

Our tiers, strongest first:

  owner     — the owner's own hand: his mirrored memory, material
              he handed over directly (the memory-vault mirror).
  curated   — material held in raw/ under the wiki's curation: it
              entered through the owner's ingest direction.
  project   — the wiki's own compiled pages: derived work, one step
              removed from sources.
  agent     — agent-produced staging material, not yet reviewed.
  external  — anything addressed by an outside URL.
  untrusted — anything we cannot classify at all. A proposal citing
              nothing carries this tier: no provenance, no trust.

The classification is by reference shape (path/URL), deterministic
and explainable — the same rule the ingest path stamps into the
conversion sidecar and the gateway stamps into proposal meta.

Standalone (stdlib only), loadable by path like profile.py.
"""
from __future__ import annotations

# Attribution: trust-tiering + weakest-link propagation adapted
# from NicoBleh/secure-llm-wiki (MIT). Implementation is original.

TIERS = ["owner", "curated", "project", "agent", "external", "untrusted"]
_RANK = {t: len(TIERS) - i for i, t in enumerate(TIERS)}


def rank(tier: str) -> int:
    return _RANK.get(tier, 0)


def classify(ref: str) -> str:
    """Tier for one source reference (repo-relative path or URL)."""
    r = (ref or "").strip()
    low = r.lower()
    if low.startswith(("http://", "https://")):
        return "external"
    if low.startswith("raw/sources/owner-records/"):
        return "owner"
    if low.startswith("raw/"):
        return "curated"
    if low.startswith("wiki/"):
        return "project"
    if low.startswith("staging/"):
        return "agent"
    return "untrusted"


def weakest(tiers) -> str:
    """The weakest tier of the set; empty set = untrusted."""
    tiers = list(tiers)
    if not tiers:
        return "untrusted"
    return min(tiers, key=rank)


def assess(cites) -> dict:
    """Trust assessment for a proposal's citations: per-cite tier
    plus the effective (weakest-link) tier that propagates."""
    per = {c: classify(c) for c in (cites or [])}
    return {"cites": per, "effective_tier": weakest(per.values())}
