"""Wave-2 item W2 (Mermaid rendering in the Lens build) unit tests
— run from anywhere:

    python3 -m unittest tools.lens.tests.test_mermaidview
    python3 tools/lens/tests/test_mermaidview.py

Covers: the subset parsers (flowchart shapes/edges/labels/state
pseudostates/pie slices), the deterministic SVG compilers (same
block -> same bytes, twice), the named fallback for unsupported
diagram types, the lift mechanics build_lens consumes (a body with
no Mermaid fence comes back byte-identical), and the security
posture: diagram source is page content, so a hostile block must
not be able to inject markup into the built site.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
sys.path.insert(0, str(LENS_DIR))

import mermaidview as MV  # noqa: E402

FLOW = """flowchart TD
  A[Start] --> B{Decision}
  B -->|yes| C([Done])
  B -.->|retry| A
  C ==> D[(Store)]
  E((Hub)) --> F[[Sub]] & G(Round)
  classDef hot fill:#f00"""

STATE = """stateDiagram-v2
  [*] --> Idle
  Idle --> Running : start
  Running --> [*]"""

PIE = """pie title Pets adopted
  "Dogs" : 40
  "Cats" : 35
  Birds : 25"""


class FlowchartParse(unittest.TestCase):
    def test_shapes_edges_labels(self):
        m = MV.parse_mermaid(FLOW)
        shapes = {n["id"]: n["shape"] for n in m["nodes"]}
        self.assertEqual(shapes["A"], "rect")
        self.assertEqual(shapes["B"], "diamond")
        self.assertEqual(shapes["C"], "stadium")
        self.assertEqual(shapes["D"], "cylinder")
        self.assertEqual(shapes["E"], "circle")
        self.assertEqual(shapes["F"], "subroutine")
        self.assertEqual(shapes["G"], "rounded")
        kinds = {(e["from"], e["to"]): (e["kind"], e["label"])
                 for e in m["edges"]}
        self.assertEqual(kinds[("B", "C")], ("arrow", "yes"))
        self.assertEqual(kinds[("B", "A")], ("dotted-arrow", "retry"))
        self.assertEqual(kinds[("C", "D")], ("thick-arrow", ""))
        self.assertIn(("E", "F"), kinds)   # & fan-out
        self.assertIn(("E", "G"), kinds)
        self.assertIn("classDef hot fill:#f00", m["unparsed"])
        self.assertEqual(m["direction"], "TD")

    def test_direction_from_head_and_statement(self):
        m = MV.parse_mermaid("graph LR\n  A --> B\n")
        self.assertEqual(m["direction"], "LR")
        m = MV.parse_mermaid("flowchart TD\n  direction LR\n"
                             "  A --> B\n")
        self.assertEqual(m["direction"], "LR")

    def test_inline_and_postfix_labels_agree(self):
        a = MV.parse_mermaid("flowchart TD\n  A -- go --> B\n")
        b = MV.parse_mermaid("flowchart TD\n  A -->|go| B\n")
        self.assertEqual(a["edges"][0]["label"], "go")
        self.assertEqual(b["edges"][0]["label"], "go")

    def test_subgraph_contents_render_boundary_warned(self):
        m = MV.parse_mermaid("flowchart LR\n  subgraph API\n"
                             "    X --> Y\n  end\n  Y --> Z\n")
        self.assertEqual({n["id"] for n in m["nodes"]},
                         {"X", "Y", "Z"})
        self.assertEqual(len(m["edges"]), 2)
        self.assertTrue(any("subgraph" in w and "not drawn" in w
                            for w in m["warnings"]))


class StateParse(unittest.TestCase):
    def test_pseudostates_and_transition_labels(self):
        m = MV.parse_mermaid(STATE)
        edges = {(e["from"], e["to"]): e["label"] for e in m["edges"]}
        self.assertEqual(edges[("[*]", "Idle")], "")
        self.assertEqual(edges[("Idle", "Running")], "start")
        self.assertEqual(edges[("Running", "[*]")], "")
        pseudo = next(n for n in m["nodes"] if n["id"] == "[*]")
        self.assertEqual(pseudo["shape"], "pseudo")
        self.assertEqual(m["unparsed"], [])

    def test_state_declarations(self):
        m = MV.parse_mermaid('stateDiagram\n'
                             '  state "Waiting Room" as WR\n'
                             '  WR : the lobby state\n'
                             '  WR --> Done\n')
        node = next(n for n in m["nodes"] if n["id"] == "WR")
        self.assertEqual(node["label"], "the lobby state")


class PieParse(unittest.TestCase):
    def test_slices_and_legend_numbers(self):
        m = MV.parse_mermaid(PIE)
        self.assertEqual([(s["label"], s["value"]) for s in m["slices"]],
                         [("Dogs", 40.0), ("Cats", 35.0),
                          ("Birds", 25.0)])
        self.assertEqual(m["title"], "Pets adopted")
        svg, warns = MV.mermaid_svg(m)
        self.assertIn("Dogs — 40 (40.0%)", svg)
        self.assertIn("Birds — 25 (25.0%)", svg)
        self.assertEqual(svg.count("<path"), 3)

    def test_single_slice_is_a_circle_and_zero_is_unparsed(self):
        m = MV.parse_mermaid('pie\n  "All" : 5\n  "None" : 0\n')
        svg, _ = MV.mermaid_svg(m)
        self.assertIn("<circle", svg)
        self.assertEqual(len(m["slices"]), 1)
        self.assertTrue(m["unparsed"])


class Determinism(unittest.TestCase):
    def test_figure_bytes_stable_across_calls(self):
        for src in (FLOW, STATE, PIE):
            first, _ = MV.figure_html(src)
            second, _ = MV.figure_html(src)
            self.assertEqual(first, second)

    def test_no_ids_or_timestamps_in_svg(self):
        for src in (FLOW, STATE, PIE):
            m = MV.parse_mermaid(src)
            svg, _ = MV.mermaid_svg(m)
            self.assertNotIn('id="', svg)
            self.assertNotIn("<defs", svg)
            self.assertNotIn("marker", svg)

    def test_direction_changes_geometry(self):
        td, _ = MV.mermaid_svg(MV.parse_mermaid(
            "flowchart TD\n  A --> B\n"))
        lr, _ = MV.mermaid_svg(MV.parse_mermaid(
            "flowchart LR\n  A --> B\n"))
        self.assertNotEqual(td, lr)
        for svg in (td, lr):
            self.assertIn("<svg", svg)


class Fallback(unittest.TestCase):
    def test_sequence_diagram_named_fallback(self):
        src = "sequenceDiagram\n  A->>B: hello\n"
        fig, info = MV.figure_html(src)
        self.assertFalse(info["rendered"])
        self.assertIn("not compiled", fig)
        self.assertIn("sequenceDiagram", fig)
        self.assertIn("hello", fig)         # source shown as-is
        self.assertNotIn("<svg", fig)

    def test_unknown_type_named_fallback(self):
        fig, info = MV.figure_html("waffleChart\n  a: 1\n")
        self.assertFalse(info["rendered"])
        self.assertIn("waffleChart", fig)

    def test_empty_flowchart_falls_back_not_blank(self):
        fig, info = MV.figure_html("flowchart TD\n")
        self.assertFalse(info["rendered"])
        self.assertIn("not compiled", fig)


class Security(unittest.TestCase):
    def test_script_in_label_is_escaped_text(self):
        src = ('flowchart LR\n'
               '  A["<script>alert(1)</script>"] --> B\n')
        fig, info = MV.figure_html(src)
        self.assertTrue(info["rendered"])
        self.assertNotIn("<script", fig)
        self.assertIn("&lt;script&gt;", fig)

    def test_event_handler_text_stays_inert(self):
        src = 'flowchart LR\n  A["x onerror=evil"] --> B\n'
        fig, info = MV.figure_html(src)
        self.assertTrue(info["rendered"])
        self.assertNotIn("<img", fig)
        # the words survive as visible label text, inside <text>
        self.assertIn("onerror=evil", fig)

    def test_sanitizer_trips_on_real_injection(self):
        self.assertEqual(
            MV.sanitize_svg("<svg><script>alert(1)</script></svg>"),
            "")
        self.assertEqual(
            MV.sanitize_svg(
                '<svg><text onload="evil()">hi</text></svg>'), "")
        self.assertEqual(
            MV.sanitize_svg('<svg><a href="https://x">y</a></svg>'),
            "")
        self.assertEqual(
            MV.sanitize_svg("<svg><text>raw < bracket</text></svg>"),
            "")

    def test_sanitizer_passes_generated_svg(self):
        for src in (FLOW, STATE, PIE):
            m = MV.parse_mermaid(src)
            svg, _ = MV.mermaid_svg(m)
            self.assertEqual(MV.sanitize_svg(svg), svg)


class Lift(unittest.TestCase):
    def test_body_without_mermaid_is_byte_identical(self):
        body = ("# Title\n\n```python\nx = 1\n```\n\n"
                "```argdown\n[A]\n```\n\nplain text\n")
        new_body, figs, infos = MV.lift_mermaid(body)
        self.assertEqual(new_body, body)
        self.assertEqual(figs, [])
        self.assertEqual(infos, [])

    def test_lift_replaces_fence_with_token_and_figure(self):
        body = "before\n\n```mermaid\nflowchart TD\n  A --> B\n```" \
               "\n\nafter\n"
        new_body, figs, infos = MV.lift_mermaid(body)
        self.assertIn("LENSMERMAIDFIG0", new_body)
        self.assertNotIn("```mermaid", new_body)
        self.assertEqual(len(figs), 1)
        self.assertIn("<svg", figs[0])
        self.assertIn("Mermaid source", figs[0])
        self.assertEqual(infos[0]["type"], "flowchart")
        self.assertTrue(infos[0]["rendered"])

    def test_source_block_travels_with_figure(self):
        fig, _ = MV.figure_html(FLOW)
        # the source rides along, html-escaped (> as &gt;)
        self.assertIn("B -.-&gt;|retry| A", fig)
        self.assertIn("classDef hot", fig)  # unparsed lines named


if __name__ == "__main__":
    unittest.main()
