"""Lifecycle profiles — governance as data, checked mechanically.

Pattern (harvest item 7): atomicstrata/llm-wiki-compiler (MIT)
enforces a profile on the write path — entity schemas, typed
relations, lifecycle state machines — and refuses non-conforming
writes instead of trusting prompt convention. This module is the
profile machinery for our gateway + validator:

  - a profile is a JSON file declaring page types with their
    required frontmatter fields, and a status state machine
    (which status -> status transitions are legal);
  - mode "warn-legacy" (the shipped default) RECORDS violations
    and never refuses: legacy pages predate the profile and are
    warned about, not blocked;
  - mode "enforce" makes the gateway's write path refuse a
    non-conforming proposal at staging time.

Flipping the default profile to "enforce" is an Owner decision
(the build gate); the machinery ships warn-legacy and stays there
until he says otherwise.

Standalone (stdlib only, no gateway imports) so the validator can
load it by path and both surfaces apply ONE profile definition.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def load_profile(path) -> dict | None:
    """Load + minimally validate a profile; None when absent or
    malformed (machinery inert — a bad profile must never take the
    gateway down; the validator reports profile problems itself
    when run standalone against it)."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if data.get("mode") not in ("warn-legacy", "enforce"):
            data["mode"] = "warn-legacy"
        return data
    except Exception:
        return None


def frontmatter_of(text: str) -> dict | None:
    """Parse the YAML-subset frontmatter this wiki uses (flat
    scalars, flow lists, block lists) — enough for presence and
    status checks. None when there is no frontmatter block."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return None
    fields: dict = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        km = re.match(r"^([A-Za-z_]+):\s*(.*)$", lines[i])
        if not km:
            i += 1
            continue
        name, val = km.group(1), km.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            fields[name] = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()] \
                if inner else []
        elif val:
            fields[name] = val.strip("\"'")
        else:
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s*-\s+", lines[j]):
                items.append(re.sub(r"^\s*-\s+", "", lines[j]).strip().strip("\"'"))
                j += 1
            if items:
                fields[name] = items
                i = j - 1
            else:
                fields[name] = None
        i += 1
    return fields


def _field_specs(spec_list):
    """Yield (field_name, since_version|None) from a profile's
    required_fields list. Entries are plain strings (schema v1) or
    objects {"field": name, "since_version": n} (versioned fields,
    Phase-2 harvest item 5; pattern: pyrite-wiki/pyrite, MIT —
    versioned schemas with grandfathering)."""
    for entry in spec_list or []:
        if isinstance(entry, str):
            yield entry, None
        elif isinstance(entry, dict) and entry.get("field"):
            since = entry.get("since_version")
            yield entry["field"], (int(since) if since else None)


def page_schema_version(fields: dict, assume: int | None = None) -> int:
    """The schema version a page declares via `_schema_version`
    (absent = 1, the pre-versioning era). `assume` is the write
    path's override for NEW content: a fresh proposal that omits
    the declaration is judged at the current schema version, so
    the version cannot be dodged by leaving it out."""
    raw = (fields or {}).get("_schema_version")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return assume if assume is not None else 1


def violations_for(profile: dict, fields: dict | None,
                   current_fields: dict | None = None,
                   assume_version: int | None = None) -> list[dict]:
    """Check one page's frontmatter against the profile.

    `current_fields` is the frontmatter of the page already at
    the target (None for a new page) — status transitions are
    judged against it. Returns [{rule, detail, ...}]; violations
    for versioned fields carry severity: a page whose declared
    schema version PREDATES the field's since_version is
    grandfathered (severity "warn", rule "schema-grandfathered");
    a page at or past the field's version that lacks it is a
    plain required-field error (severity "error"). Unversioned
    fields carry no severity — the caller's profile mode decides
    (the Phase-1 behaviour)."""
    out: list[dict] = []
    if fields is None:
        return [{"rule": "frontmatter", "detail": "no frontmatter block"}]
    types = profile.get("page_types") or {}
    ptype = fields.get("type")
    if types:
        if ptype not in types:
            out.append({"rule": "page-type",
                        "detail": f"type {ptype!r} is not declared in the profile"})
        else:
            pver = page_schema_version(fields, assume_version)
            for f, since in _field_specs(
                    (types.get(ptype) or {}).get("required_fields")):
                v = fields.get(f)
                # Required means DECLARED (the schema convention in
                # AGENTS.md): an explicitly empty list is present —
                # its emptiness is a quality warning the validator
                # already raises separately, not a profile breach.
                if v is None or v == "":
                    if since is not None and pver < since:
                        out.append({
                            "rule": "schema-grandfathered",
                            "severity": "warn", "field": f,
                            "since_version": since,
                            "detail": f"{ptype} page is schema v{pver}; "
                                      f"field {f!r} is required only "
                                      f"from v{since} (grandfathered)"})
                    elif since is not None:
                        out.append({
                            "rule": "required-field",
                            "severity": "error", "field": f,
                            "since_version": since,
                            "detail": f"{ptype} page (schema v{pver}) is "
                                      f"missing field {f!r}, required "
                                      f"since v{since}"})
                    else:
                        out.append({"rule": "required-field",
                                    "detail": f"{ptype} page is missing required field {f!r}"})
    transitions = profile.get("status_transitions") or {}
    new_status = fields.get("status")
    if transitions and new_status:
        if current_fields and current_fields.get("status"):
            frm = str(current_fields["status"])
            if str(new_status) != frm and \
                    str(new_status) not in [str(t) for t in transitions.get(frm, [])]:
                out.append({"rule": "status-transition",
                            "detail": f"status {frm} -> {new_status} is not an "
                                      f"allowed transition"})
        else:
            states = set(transitions) | {str(t) for v in transitions.values() for t in v}
            if str(new_status) not in states:
                out.append({"rule": "status-transition",
                            "detail": f"initial status {new_status!r} is not a "
                                      f"declared state"})
    return out
