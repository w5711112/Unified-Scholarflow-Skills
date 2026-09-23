from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

from test_support import writable_test_directory


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PLUGIN_ROOT
    / "skills"
    / "obsidian-note-style"
    / "scripts"
    / "render_astar_dijkstra_comparison.py"
)


def load_renderer():
    spec = importlib.util.spec_from_file_location("astar_visual", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load renderer: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("not a PNG")
    return struct.unpack(">II", data[16:24])


class AstarDijkstraComparisonTests(unittest.TestCase):
    def test_searches_share_optimal_cost_but_astar_expands_less(self):
        renderer = load_renderer()
        dijkstra = renderer.solve_search("zero")
        astar = renderer.solve_search("manhattan")

        self.assertEqual(dijkstra.cost, astar.cost)
        self.assertEqual(dijkstra.cost, 26)
        self.assertEqual(len(dijkstra.expanded), 205)
        self.assertEqual(len(astar.expanded), 91)
        self.assertLess(len(astar.expanded), len(dijkstra.expanded))
        self.assertEqual(astar.path[0], renderer.START)
        self.assertEqual(astar.path[-1], renderer.GOAL)
        self.assertTrue(set(astar.path).isdisjoint(renderer.OBSTACLES))

    def test_worked_example_closes_the_decision_and_update_loop(self):
        renderer = load_renderer()
        required_api = (
            "worked_example",
            "HEURISTIC_FORMULA",
            "RELAXATION_FORMULA",
            "UPDATE_CONDITION",
        )
        missing_api = [name for name in required_api if not hasattr(renderer, name)]
        self.assertFalse(missing_api, f"missing renderer API: {missing_api}")
        example = renderer.worked_example()

        self.assertEqual(
            renderer.HEURISTIC_FORMULA,
            r"$h(n)=\left|x_n-x_G\right|+\left|y_n-y_G\right|$",
        )
        self.assertEqual(
            renderer.RELAXATION_FORMULA,
            r"$g'(m)=g(n)+c(n,m)$",
        )
        self.assertEqual(
            renderer.UPDATE_CONDITION,
            r"$g'(m)<g_{\mathrm{old}}(m)$",
        )
        self.assertEqual(example["current"], {"cell": (3, 6), "g": 2})
        self.assertEqual(
            example["right"],
            {
                "cell": (4, 6),
                "edge": 1,
                "tentative_g": 3,
                "h": 13,
                "f": 16,
            },
        )
        self.assertEqual(
            example["down"],
            {
                "cell": (3, 7),
                "edge": 1,
                "tentative_g": 3,
                "h": 15,
                "f": 18,
            },
        )

    def test_palette_and_formula_match_the_visual_contract(self):
        renderer = load_renderer()
        self.assertEqual(
            renderer.PALETTE,
            {
                "expanded_fill": "#DCEAF8",
                "expanded_line": "#4776A8",
                "frontier_fill": "#E8DFF3",
                "frontier_line": "#765A9B",
                "obstacle_fill": "#F6DDDD",
                "obstacle_line": "#B25C5C",
                "path_fill": "#DDEED8",
                "path_line": "#4F8A58",
                "cue_fill": "#FBE6CC",
                "cue_line": "#C47A2C",
                "context_fill": "#EEF1F4",
                "context_line": "#626B75",
            },
        )
        self.assertEqual(renderer.FORMULA, r"$f(n)=g(n)+h(n)$")

    def test_renderer_writes_one_high_resolution_png(self):
        renderer = load_renderer()
        with writable_test_directory() as tmp:
            output = Path(tmp) / "A星与Dijkstra搜索扩张对比.png"
            rendered = renderer.render_comparison(output)
            self.assertEqual(rendered, output)
            self.assertTrue(output.is_file())
            width, height = png_size(output)
            self.assertGreaterEqual(width, 2800)
            self.assertGreaterEqual(height, 2100)


if __name__ == "__main__":
    unittest.main()
