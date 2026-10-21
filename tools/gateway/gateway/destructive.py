"""Env-flagged destructive tools for the gateway (Scrapbox MCP pattern).

Implements the Marathon Round 3 TB8 row "env-flagged destructive
tools for the gateway", from the Scrapbox/Cosense MCP find in
raw/sources/2026-10-20-global-landscape/r2-east-asia-finds.md:
destructive tools (delete_page / rewrite_page there) are NOT
REGISTERED AT ALL unless an env flag is set. Pattern re-implemented
from the idea; no Scrapbox code copied (that project is a separate
ecosystem; the find records the pattern only).

The gate, stated plainly:

  * The flag is the environment variable
    ``WIKI_GATEWAY_ENABLE_DESTRUCTIVE``. Only the exact value
    ``true`` (case-insensitive, surrounding whitespace ignored)
    enables anything. Unset, empty, ``1``, ``yes`` — all mean OFF.
    Refusal is the default and the tested default.
  * While the flag is off, destructive tools do not appear in
    ``tools/list`` at all — they are unregistered, not merely
    blocked at call time.
  * Every invocation ATTEMPT of a destructive tool name — flag off
    (refused), unknown target, escaping path, or allowed — is
    recorded exactly once through the ``record`` callback the
    server supplies (the Black Box ledger in production). A caller
    of this module that supplies no recorder gets a refusal:
    an unledgered destructive attempt never runs.
  * The gateway today ships NO real destructive tool. The single
    registered tool is a harmless fixture,
    ``wiki_fixture_delete_scratch``, which deletes one file
    strictly inside a stated scratch directory (the gateway state
    dir's ``destructive-scratch/``). It exists to prove the gate
    end to end. Real delete/overwrite tools may only ever be
    added behind this same gate, one at a time, on the record.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FLAG = "WIKI_GATEWAY_ENABLE_DESTRUCTIVE"

FIXTURE_TOOL = {
    "name": "wiki_fixture_delete_scratch",
    "description": (
        "DESTRUCTIVE (fixture) — delete one file inside the "
        "gateway's destructive-scratch directory. Registered ONLY "
        f"when ${ENV_FLAG}=true; every attempt is ledgered. "
        "Proves the env-flag gate; deletes nothing outside the "
        "scratch directory."),
    "inputSchema": {"type": "object", "properties": {
        "path": {"type": "string",
                 "description": "File name (or relative path) "
                                "inside the scratch directory."}},
        "required": ["path"]},
    "destructive_class": "delete",
}

DESTRUCTIVE_TOOLS = [FIXTURE_TOOL]
DESTRUCTIVE_NAMES = {t["name"] for t in DESTRUCTIVE_TOOLS}


def destructive_enabled(env=None) -> bool:
    """True only for the exact flag value 'true'. Default OFF."""
    env = os.environ if env is None else env
    return str(env.get(ENV_FLAG, "")).strip().lower() == "true"


def visible_tools(env=None) -> list:
    """The destructive tools to register — empty unless enabled."""
    if not destructive_enabled(env):
        return []
    return [dict(t) for t in DESTRUCTIVE_TOOLS]


def invoke(name, args, *, scratch_root, record, env=None):
    """Run (or refuse) one destructive invocation attempt.

    ``record(action, result, detail)`` is called exactly once per
    attempt, before any return. Returns (payload, is_error).
    Refusal is the outcome for: flag off, no recorder, unknown
    tool name, a path escaping the scratch root, and a missing
    target. Only a flag-on, in-scratch, existing file is deleted.
    """
    if record is None:
        # Without a ledger trail the attempt cannot be accounted
        # for, so it does not run — and there is nowhere to record
        # the refusal either; the caller (server) always supplies
        # a recorder, so this branch is defence in depth.
        return ({"error": "destructive tool refused: no ledger "
                          "recorder supplied"}, True)
    if name not in DESTRUCTIVE_NAMES:
        record("destructive_refused", "deny",
               {"reason": "unknown destructive tool", "tool": name})
        return ({"error": f"unknown destructive tool: {name}"}, True)
    if not destructive_enabled(env):
        record("destructive_refused", "deny",
               {"reason": f"${ENV_FLAG} is not 'true' — destructive "
                          "tools are unregistered by default",
                "tool": name})
        return ({"error": "destructive tool refused: "
                          f"{ENV_FLAG} is not set to 'true' "
                          "(destructive tools ship disabled)"}, True)

    # Flag on: the fixture tool may delete only inside scratch_root.
    scratch = Path(scratch_root).resolve()
    rel = str((args or {}).get("path", ""))
    target = (scratch / rel).resolve() if rel else scratch
    if target == scratch or scratch not in target.parents:
        record("destructive_refused", "deny",
               {"reason": "path escapes the scratch directory",
                "tool": name, "path": rel})
        return ({"error": "refused: path must name a file inside "
                          "the destructive-scratch directory"}, True)
    if not target.is_file():
        record("destructive_refused", "deny",
               {"reason": "no such scratch file", "tool": name,
                "path": rel})
        return ({"error": "not found in scratch directory"}, True)
    target.unlink()
    record("destructive_delete", "allow",
           {"tool": name, "path": rel,
            "destructive_class": "delete"})
    return ({"deleted": rel, "scratch": str(scratch)}, False)
