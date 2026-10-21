#!/usr/bin/env python3
"""Unit tests for tools/mcp-read/workflows.py — the workflow
registry behind wiki_workflow (Langflow pattern, TB8 row 2).

Pins: a workflow may name ONLY the door's read tools (any other
verb — a write verb, the workflow tool itself, an unknown name —
is rejected at registration); step ids are unique; $input
references must be declared; $steps references must point at
earlier steps; runs substitute inputs, compose step results in
order, and stop at the first failing step.

Run:  python3 -m unittest discover -s tools/mcp-read/tests
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import workflows  # noqa: E402


def defn(**over):
    base = {"name": "w", "description": "", "inputs": {"page": {}},
            "required_inputs": ["page"],
            "steps": [{"id": "a", "tool": "wiki_census",
                       "args": {}}]}
    base.update(over)
    return base


class TestValidation(unittest.TestCase):
    def test_write_verb_rejected(self):
        with self.assertRaises(workflows.WorkflowError):
            workflows.validate_workflow(defn(steps=[
                {"id": "a", "tool": "wiki_stage_proposal",
                 "args": {}}]))

    def test_unknown_verb_rejected(self):
        with self.assertRaises(workflows.WorkflowError):
            workflows.validate_workflow(defn(steps=[
                {"id": "a", "tool": "wiki_delete_page",
                 "args": {}}]))

    def test_recursion_rejected(self):
        with self.assertRaises(workflows.WorkflowError):
            workflows.validate_workflow(defn(steps=[
                {"id": "a", "tool": "wiki_workflow", "args": {}}]))

    def test_duplicate_step_ids_rejected(self):
        with self.assertRaises(workflows.WorkflowError):
            workflows.validate_workflow(defn(steps=[
                {"id": "a", "tool": "wiki_census", "args": {}},
                {"id": "a", "tool": "wiki_claim", "args": {}}]))

    def test_undeclared_input_rejected(self):
        with self.assertRaises(workflows.WorkflowError):
            workflows.validate_workflow(defn(steps=[
                {"id": "a", "tool": "wiki_cite",
                 "args": {"page": "$input.nope"}}]))

    def test_forward_step_reference_rejected(self):
        with self.assertRaises(workflows.WorkflowError):
            workflows.validate_workflow(defn(steps=[
                {"id": "a", "tool": "wiki_cite",
                 "args": {"page": "$steps.b"}},
                {"id": "b", "tool": "wiki_census", "args": {}}]))

    def test_builtins_valid(self):
        reg = workflows.WorkflowRegistry()
        self.assertEqual(reg.names(),
                         ["census_and_cite", "page_context"])


class TestRun(unittest.TestCase):
    def fake_call(self, tool, args):
        return {"tool": tool, "args": args}

    def test_run_composes_and_substitutes(self):
        reg = workflows.WorkflowRegistry()
        out = workflows.run_workflow(
            reg, "census_and_cite", {"page": "alpha"},
            self.fake_call)
        self.assertEqual(out["steps"]["citations"]["args"],
                         {"page": "alpha"})
        self.assertEqual(out["steps"]["census"]["tool"],
                         "wiki_census")

    def test_step_failure_stops_run(self):
        calls = []

        def failing(tool, args):
            calls.append(tool)
            return {"error": "refused: gate"}

        reg = workflows.WorkflowRegistry()
        with self.assertRaises(workflows.WorkflowError) as cm:
            workflows.run_workflow(reg, "page_context",
                                   {"page": "alpha"}, failing)
        self.assertIn("step 'page'", str(cm.exception))
        self.assertEqual(calls, ["wiki_read_page"])

    def test_missing_input(self):
        reg = workflows.WorkflowRegistry()
        with self.assertRaises(workflows.WorkflowError):
            workflows.run_workflow(reg, "page_context", {},
                                   self.fake_call)


if __name__ == "__main__":
    unittest.main()
