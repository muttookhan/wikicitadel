"""Tests for scripts/wiki_markdown_dialect.py — the
CommonMark dialect pin and the RFC 7763 variant label
(Marathon Round 6, lane BA, items 1-2): the shipped pin and
subset validate; the tree cross-checks pass (AGENTS.md
states the pin and the label; the RO-Crate generator and
the Lens build carry the label); pin defects are caught;
the encoding-format helper labels .md files with the
variant and other files with plain MIME types; and the
RO-Crate generator's own output for a .md file carries the
variant label end to end.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_markdown_dialect", HERE.parents[1] / "wiki_markdown_dialect.py")
wmd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wmd)
spec_rc = importlib.util.spec_from_file_location(
    "wiki_ro_crate", HERE.parents[1] / "wiki_ro_crate.py")
rc = importlib.util.module_from_spec(spec_rc)
spec_rc.loader.exec_module(rc)

ROOT = HERE.parents[2]


class PinTest(unittest.TestCase):
    def test_shipped_pin_and_subset_validate_clean(self):
        pin = wmd.load_pin(ROOT / "evaluation" / "markdown-dialect.json")
        cases = wmd.load_cases(
            ROOT / "evaluation" / "commonmark-conformance.json")
        self.assertEqual(wmd.check_pin(pin, cases), [])

    def test_tree_declaration_sites_agree(self):
        self.assertEqual(wmd.check_tree_texts(), [])
        self.assertEqual(wmd.main(["check"]), 0)
        self.assertEqual(wmd.main(["show"]), 0)

    def test_pin_defects_are_caught(self):
        pin = wmd.load_pin(ROOT / "evaluation" / "markdown-dialect.json")
        cases = wmd.load_cases(
            ROOT / "evaluation" / "commonmark-conformance.json")

        wrong_version = copy.deepcopy(pin)
        wrong_version["spec_version"] = "0.30"
        self.assertTrue(any("spec_version" in p
                            for p in wmd.check_pin(wrong_version,
                                                   cases)))

        wrong_label = copy.deepcopy(pin)
        wrong_label["variant_label"] = "text/markdown"
        self.assertTrue(any("variant_label" in p
                            for p in wmd.check_pin(wrong_label,
                                                   cases)))

        unattributed = copy.deepcopy(cases)
        unattributed["attribution"] = "examples from a spec"
        self.assertTrue(any("attribution" in p
                            for p in wmd.check_pin(pin,
                                                   unattributed)))

        ghost = copy.deepcopy(cases)
        ghost["known_divergences"] = [{"id": "no-such-case",
                                       "observed": "x"}]
        self.assertTrue(any("unknown case" in p
                            for p in wmd.check_pin(pin, ghost)))


class VariantLabelTest(unittest.TestCase):
    def test_encoding_format_for_names(self):
        self.assertEqual(wmd.encoding_format_for("page.md"),
                         "text/markdown; variant=CommonMark")
        self.assertEqual(wmd.encoding_format_for("notes.txt"),
                         "text/plain")
        self.assertEqual(wmd.encoding_format_for("data.json"),
                         "application/json")

    def test_ro_crate_constant_agrees_with_canonical_label(self):
        self.assertEqual(rc.MARKDOWN_ENCODING_FORMAT,
                         wmd.VARIANT_LABEL)

    def test_ro_crate_output_labels_markdown_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            bundle.mkdir()
            (bundle / "page.md").write_text("# Page\n",
                                            encoding="utf-8")
            (bundle / "data.json").write_text("{}\n",
                                              encoding="utf-8")
            rc.write_crate(bundle, name="B")
            crate = json.loads(
                (bundle / "ro-crate-metadata.json")
                .read_text(encoding="utf-8"))
            by_id = {e["@id"]: e for e in crate["@graph"]}
            self.assertEqual(by_id["page.md"]["encodingFormat"],
                             "text/markdown; variant=CommonMark")
            self.assertEqual(by_id["data.json"]["encodingFormat"],
                             "application/json")
            self.assertEqual(rc.check_crate(bundle), [])


if __name__ == "__main__":
    unittest.main()
