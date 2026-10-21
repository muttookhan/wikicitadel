#!/usr/bin/env python3
"""Khoj-pattern configured-agent objects (Marathon Round 3,
lane TB7, row 10b).

Pins: the shipped example object in evaluation/agent-objects/
validates clean; a valid minimal object passes; each stated
rule refuses what it must — wrong kind, non-slug name, empty
prompt, empty/escaping sources, an unknown tool, a model_slot
naming anything but "unwired" (the router gate), and unknown
keys.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_agent_object", ROOT / "scripts" / "wiki_agent_object.py")
AO = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AO)

GOOD = {"kind": "agent-object", "name": "reader-one",
        "prompt": "Answer from the wiki, citing pages.",
        "sources": ["wiki/"], "tools": ["search", "read", "cite"],
        "model_slot": "unwired"}


def bad(**over):
    obj = dict(GOOD)
    obj.update(over)
    return AO.validate_agent_object(obj)


class AgentObjectTests(unittest.TestCase):
    def test_good_object_passes(self):
        self.assertEqual(AO.validate_agent_object(GOOD), [])
        minimal = {"kind": "agent-object", "name": "mini",
                   "prompt": "Read.", "sources": ["wiki/"],
                   "tools": ["read"]}
        self.assertEqual(AO.validate_agent_object(minimal), [])

    def test_shipped_example_validates(self):
        files = sorted((ROOT / "evaluation" / "agent-objects")
                       .glob("*.agent.json"))
        self.assertTrue(files, "no shipped agent-object example")
        for f in files:
            self.assertEqual(AO.check_file(f), [], f.name)
            obj = json.loads(f.read_text())
            self.assertEqual(obj["model_slot"], "unwired")

    def test_each_rule_refuses(self):
        self.assertTrue(bad(kind="agent"))
        self.assertTrue(bad(name="Not A Slug"))
        self.assertTrue(bad(prompt="  "))
        self.assertTrue(bad(sources=[]))
        self.assertTrue(bad(sources=["../elsewhere"]))
        self.assertTrue(bad(sources=["/abs/path"]))
        self.assertTrue(bad(tools=["search", "teleport"]))
        self.assertTrue(bad(model_slot="some-provider"))
        self.assertTrue(bad(surprise_key=1))


if __name__ == "__main__":
    unittest.main()
