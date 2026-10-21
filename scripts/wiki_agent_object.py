#!/usr/bin/env python3
"""wiki_agent_object.py — configured custom agents as configuration.

Marathon Round 3, lane TB7, row 10b. Pattern: Khoj's
configured-custom-agent object (re-implemented as configuration
from the idea): an agent is not code, it is a small declarative
OBJECT —

    {"kind": "agent-object", "name": "wiki-reader",
     "prompt": "Answer from the wiki, citing pages.",
     "sources": ["wiki/"],
     "tools": ["search", "read", "cite"],
     "model_slot": "unwired"}

— validated by this checker before anything may consume it.
Rules the checker enforces (each maps to a stated house gate):

  * kind must be "agent-object"; name a slug; prompt present and
    non-empty (an agent with no stated instruction is not an
    agent object, it is a name);
  * sources: a non-empty list of repo-relative paths, none
    absolute, none escaping the tree (no "..");
  * tools: a non-empty list drawn ONLY from the stated tool
    vocabulary below — an unknown tool is an error, never
    silently dropped;
  * model_slot, when present, must be the literal "unwired":
    the model router stays UNWIRED (a config may name the slot,
    it may not name a provider, a model, or a key).

    python3 scripts/wiki_agent_object.py check FILE [FILE ...]
    python3 scripts/wiki_agent_object.py check --root DIR
        (checks every evaluation/agent-objects/*.agent.json)

Exit 0 iff every checked object is valid. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OBJECTS_REL = "evaluation/agent-objects"
ALLOWED_TOOLS = {"search", "read", "cite", "graph", "ask",
                 "summarize", "export"}
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_agent_object(obj):
    """The checker: a list of error strings ([] = valid)."""
    errors = []
    if not isinstance(obj, dict):
        return ["agent object must be a JSON object"]
    if obj.get("kind") != "agent-object":
        errors.append('kind must be "agent-object"')
    name = obj.get("name")
    if not isinstance(name, str) or not SLUG_RE.match(name or ""):
        errors.append("name must be a slug (lowercase, hyphens)")
    prompt = obj.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("prompt must be a non-empty string")
    sources = obj.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list of paths")
    else:
        for src in sources:
            if not isinstance(src, str) or not src.strip():
                errors.append(f"source must be a path string: {src!r}")
                continue
            p = Path(src)
            if p.is_absolute() or ".." in p.parts:
                errors.append(
                    f"source escapes the tree or is absolute: {src!r}")
    tools = obj.get("tools")
    if not isinstance(tools, list) or not tools:
        errors.append("tools must be a non-empty list")
    else:
        for tool in tools:
            if tool not in ALLOWED_TOOLS:
                errors.append(
                    f"unknown tool {tool!r}; the vocabulary is "
                    f"{sorted(ALLOWED_TOOLS)}")
    slot = obj.get("model_slot", "unwired")
    if slot != "unwired":
        errors.append(
            'model_slot must be "unwired" — the model router stays '
            "unwired; a config names the slot, never a provider")
    unknown = set(obj) - {"kind", "name", "prompt", "sources",
                          "tools", "model_slot", "description"}
    if unknown:
        errors.append(f"unknown keys: {sorted(unknown)}")
    return errors


def check_file(path):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [f"unreadable JSON: {exc}"]
    return validate_agent_object(obj)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("cmd", choices=("check",))
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    files = [Path(f) for f in args.files]
    if not files:
        files = sorted((root / OBJECTS_REL).glob("*.agent.json"))
    results = []
    bad = 0
    for f in files:
        errors = check_file(f)
        if errors:
            bad += 1
        results.append({"file": str(f), "valid": not errors,
                        "errors": errors})
    print(json.dumps({"kind": "agent-object-check",
                      "checked": len(results), "invalid": bad,
                      "results": results}, indent=2,
                     ensure_ascii=False))
    return 1 if bad or not results else 0


if __name__ == "__main__":
    sys.exit(main())
