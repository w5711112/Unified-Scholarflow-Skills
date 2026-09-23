from __future__ import annotations

import hashlib
import importlib.util
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = (
    PLUGIN_ROOT
    / "skills"
    / "obsidian-note-style"
    / "scripts"
    / "render_academic_concept_diagrams.py"
)
from test_support import writable_test_directory
EXPECTED_NAMES = {
    "Dijkstra与代价场原理.svg",
    "SDF与ESDF原理.svg",
    "CBF到HOCBF安全过滤.svg",
}
FORBIDDEN_SVG_ELEMENTS = {
    "linearGradient",
    "radialGradient",
    "filter",
    "image",
    "text",
}


def load_renderer():
    spec = importlib.util.spec_from_file_location(
        "render_academic_concept_diagrams",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load renderer: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AcademicConceptDiagramTests(unittest.TestCase):
    def test_render_all_produces_restrained_vector_only_svg(self):
        renderer = load_renderer()
        with writable_test_directory() as tmp:
            rendered = renderer.render_all(Path(tmp))
            self.assertEqual({path.name for path in rendered}, EXPECTED_NAMES)
            for path in rendered:
                with self.subTest(path=path.name):
                    self.assertGreater(path.stat().st_size, 8_000)
                    root = ET.parse(path).getroot()
                    names = [local_name(element.tag) for element in root.iter()]
                    self.assertTrue(FORBIDDEN_SVG_ELEMENTS.isdisjoint(names))
                    self.assertGreaterEqual(names.count("path"), 25)
                    serialized = path.read_text(encoding="utf-8")
                    self.assertNotIn("url(#", serialized)
                    self.assertNotIn("<script", serialized.lower())

    def test_visual_constants_prevent_oversized_arrows_and_heavy_lines(self):
        renderer = load_renderer()
        self.assertLessEqual(renderer.ARROW_MUTATION_SCALE, 7)
        self.assertLessEqual(renderer.MAX_LINE_WIDTH, 2.5)
        self.assertLessEqual(len(renderer.SEMANTIC_ACCENTS), 2)
        self.assertEqual(renderer.BACKGROUND_COLOR.lower(), "#ffffff")

    def test_visual_constants_require_readable_type_and_dense_canvas(self):
        renderer = load_renderer()
        self.assertGreaterEqual(renderer.FONT_SCALE, 1.15)
        self.assertGreaterEqual(renderer.MIN_TEXT_SIZE, 9.0)
        self.assertGreaterEqual(renderer.PANEL_HEADING_SIZE, 12.0)
        self.assertGreaterEqual(renderer.MIN_MATH_SIZE, 12.5)
        self.assertLessEqual(renderer.OUTER_MARGIN, 0.05)
        self.assertLessEqual(renderer.PANEL_GAP, 0.035)
        self.assertLessEqual(renderer.SAVE_PAD_INCHES, 0.05)

    def test_render_all_can_write_png_previews(self):
        renderer = load_renderer()
        with writable_test_directory() as svg_tmp:
            with writable_test_directory() as png_tmp:
                renderer.render_all(Path(svg_tmp), preview_dir=Path(png_tmp))
                previews = sorted(Path(png_tmp).glob("*.png"))
                self.assertEqual(len(previews), 3)
                for preview in previews:
                    with self.subTest(preview=preview.name):
                        self.assertTrue(
                            preview.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
                        )

    def test_rendering_is_byte_deterministic(self):
        renderer = load_renderer()
        with writable_test_directory() as first_tmp:
            with writable_test_directory() as second_tmp:
                first = {
                    path.name: sha256(path)
                    for path in renderer.render_all(Path(first_tmp))
                }
                second = {
                    path.name: sha256(path)
                    for path in renderer.render_all(Path(second_tmp))
                }
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
