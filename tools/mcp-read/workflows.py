"""Workflow-as-MCP-tool registry for the read door (Langflow pattern).

Implements the Marathon Round 3 TB8 row "workflow-as-MCP-tool",
from the Langflow find in
raw/sources/2026-10-20-global-landscape/r2-europe-india-academic-finds.md:
a workflow definition — stated steps over existing tools — is
itself exposed as a single MCP tool. Pattern re-implemented from
the idea (Langflow is MIT; nothing copied).

The read door's split is preserved absolutely:

  * A workflow step may name ONLY one of the door's existing
    read tools (READ_TOOLS below). Registration REJECTS any
    other verb — there is no write verb to smuggle in, and a
    workflow gains the door no new power: it composes reads.
  * Steps run in order through a caller-supplied ``call``
    function (the door's own dispatch), so every step passes
    the same gates a direct call would.
  * Step arguments may reference the workflow's inputs as
    ``$input.<key>`` and an earlier step's whole result as
    ``$steps.<step_id>`` — substitution is by exact string match
    only (a string that merely CONTAINS a reference is literal),
    so no expression language exists to abuse.

Built-in workflows live in BUILTIN_WORKFLOWS as data. The door
exposes them through one extra tool, ``wiki_workflow``.
"""
from __future__ import annotations

# The door's read verbs — the only verbs a workflow step may use.
READ_TOOLS = {
    "wiki_search", "wiki_read_page", "wiki_read_source",
    "wiki_neighbors", "wiki_path", "wiki_census",
    "wiki_claim", "wiki_cite",
}

BUILTIN_WORKFLOWS = [
    {
        "name": "census_and_cite",
        "description": (
            "Corpus census, then the citation-lock passages for "
            "one page: the composed 'how big is the corpus and "
            "what backs this page' briefing read."),
        "inputs": {"page": {"type": "string"}},
        "required_inputs": ["page"],
        "steps": [
            {"id": "census", "tool": "wiki_census", "args": {}},
            {"id": "citations", "tool": "wiki_cite",
             "args": {"page": "$input.page"}},
        ],
    },
    {
        "name": "page_context",
        "description": (
            "Read one page, then its wikilink neighbours: the "
            "composed 'page in context' read."),
        "inputs": {"page": {"type": "string"}},
        "required_inputs": ["page"],
        "steps": [
            {"id": "page", "tool": "wiki_read_page",
             "args": {"page": "$input.page"}},
            {"id": "neighbours", "tool": "wiki_neighbors",
             "args": {"page": "$input.page", "direction": "both"}},
        ],
    },
]


class WorkflowError(Exception):
    """A workflow definition or run failure."""


def validate_workflow(defn) -> dict:
    """Validate one workflow definition. Returns it unchanged.

    Rejects: missing/duplicate step ids, a step naming anything
    but a read tool (the no-write-verb pin), a step referencing
    the workflow tool itself (no recursion), and references to
    undeclared inputs or later/unknown steps.
    """
    if not isinstance(defn, dict) or not defn.get("name"):
        raise WorkflowError("workflow needs a name")
    steps = defn.get("steps")
    if not isinstance(steps, list) or not steps:
        raise WorkflowError(
            f"workflow {defn['name']!r}: steps must be a "
            "non-empty list")
    inputs = set((defn.get("inputs") or {}).keys())
    seen = set()
    for step in steps:
        sid = step.get("id")
        if not sid or sid in seen:
            raise WorkflowError(
                f"workflow {defn['name']!r}: step ids must be "
                "present and unique")
        tool = step.get("tool")
        if tool == "wiki_workflow":
            raise WorkflowError(
                f"workflow {defn['name']!r}: workflows may not "
                "call workflows (no recursion)")
        if tool not in READ_TOOLS:
            raise WorkflowError(
                f"workflow {defn['name']!r}: step {sid!r} names "
                f"{tool!r}, which is not one of the door's read "
                "tools — workflows compose reads only and gain "
                "the door no write verb")
        for value in (step.get("args") or {}).values():
            if isinstance(value, str) and value.startswith("$input."):
                if value[len("$input."):] not in inputs:
                    raise WorkflowError(
                        f"workflow {defn['name']!r}: step {sid!r} "
                        f"references undeclared input {value!r}")
            if isinstance(value, str) and value.startswith("$steps."):
                ref = value[len("$steps."):]
                if ref not in seen:
                    raise WorkflowError(
                        f"workflow {defn['name']!r}: step {sid!r} "
                        f"references unknown or later step {ref!r}")
        seen.add(sid)
    return defn


class WorkflowRegistry:
    def __init__(self, definitions=None):
        self._workflows = {}
        for defn in (BUILTIN_WORKFLOWS if definitions is None
                     else definitions):
            self.register(defn)

    def register(self, defn) -> None:
        validate_workflow(defn)
        if defn["name"] in self._workflows:
            raise WorkflowError(
                f"duplicate workflow name: {defn['name']!r}")
        self._workflows[defn["name"]] = defn

    def names(self) -> list:
        return sorted(self._workflows)

    def get(self, name) -> dict:
        try:
            return self._workflows[name]
        except KeyError:
            raise WorkflowError(
                f"unknown workflow: {name!r} (have: "
                f"{', '.join(self.names()) or 'none'})") from None

    def describe(self) -> list:
        return [{"name": d["name"],
                 "description": d.get("description", ""),
                 "inputs": sorted((d.get("inputs") or {}).keys()),
                 "steps": [s["tool"] for s in d["steps"]]}
                for d in (self._workflows[n] for n in self.names())]


def _substitute(value, inputs, results):
    if isinstance(value, str):
        if value.startswith("$input."):
            key = value[len("$input."):]
            if key not in inputs:
                raise WorkflowError(f"missing input: {key!r}")
            return inputs[key]
        if value.startswith("$steps."):
            ref = value[len("$steps."):]
            if ref not in results:
                raise WorkflowError(f"step result unavailable: {ref!r}")
            return results[ref]
    return value


def run_workflow(registry, name, inputs, call) -> dict:
    """Run one workflow. ``call(tool, args) -> payload dict`` is
    the door's own dispatch; a step payload carrying an 'error'
    key (or the caller raising) fails the workflow at that step —
    later steps do not run. Returns the composed result."""
    defn = registry.get(name)
    inputs = dict(inputs or {})
    for key in defn.get("required_inputs") or []:
        if key not in inputs:
            raise WorkflowError(
                f"workflow {name!r}: required input {key!r} missing")
    results = {}
    for step in defn["steps"]:
        args = {k: _substitute(v, inputs, results)
                for k, v in (step.get("args") or {}).items()}
        payload = call(step["tool"], args)
        if isinstance(payload, dict) and "error" in payload:
            raise WorkflowError(
                f"workflow {name!r}: step {step['id']!r} "
                f"({step['tool']}) failed: {payload['error']}")
        results[step["id"]] = payload
    return {"workflow": name, "steps": results}
