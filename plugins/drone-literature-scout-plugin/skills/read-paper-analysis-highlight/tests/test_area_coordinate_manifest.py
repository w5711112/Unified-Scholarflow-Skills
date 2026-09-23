from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

import fitz


SKILL_ROOT = Path(__file__).parents[1]
SCRIPT_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from annotate_pdf import annotate_pdf  # noqa: E402
from test_support import writable_test_directory  # noqa: E402


class AreaCoordinateManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = writable_test_directory()
        self.case = Path(self.temporary_directory.__enter__())

    def tearDown(self):
        self.temporary_directory.__exit__(None, None, None)

    def _make_pdf(self) -> Path:
        source = self.case / "paper.pdf"
        document = fitz.open()
        page = document.new_page(width=300, height=300)
        page.insert_text((30, 50), "This exact evidence phrase supports native coordinates.")
        document.save(source)
        document.close()
        return source

    def _highlight(self) -> dict:
        return {
            "id": "fixture-highlight-v3",
            "page": 1,
            "annotation_type": "highlight",
            "annotation_schema_version": 3,
            "quote": "This exact evidence phrase supports native coordinates",
            "kind": "method",
            "color": "yellow",
            "note_question": "Which phrase carries the evidence?",
            "claim": "The selected sentence carries the exact evidence needed for a native highlight.",
            "reason": "The complete phrase is unique and preserves the method relation without guessing a rectangle.",
            "information_roles": ["method", "mechanism"],
            "evidence": "PDF page 1",
            "confidence": "high",
            "annotation_comment": (
                "结论：这条唯一原文短语应能继续转换为 Zotero 原生高亮。\n"
                "机制：解析清单必须同时保留页框与旋转信息。"
            ),
        }

    def _area(self) -> dict:
        return {
            "id": "fixture-area-v3",
            "page": 1,
            "annotation_type": "area",
            "annotation_schema_version": 3,
            "rect": [20.0, 140.0, 200.0, 220.0],
            "coordinate_space": "pymupdf-page-top-left",
            "page_box": [0.0, 0.0, 300.0, 300.0],
            "page_rotation": 0,
            "visual_object": "Figure 1 policy architecture",
            "kind": "method",
            "color": "orange",
            "note_question": "How is the method connected?",
            "claim": "The visual region shows the ordered perception, policy, and control modules.",
            "reason": "The diagram topology is not recoverable from a single extracted text line.",
            "information_roles": ["method", "mechanism"],
            "evidence": "Figure 1",
            "confidence": "high",
            "annotation_comment": (
                "结论：该图展示感知、策略、安全过滤和控制器之间的实际数据流。\n"
                "定位：PDF第 1 页（图 1）。"
            ),
        }

    def test_manifest_stores_reading_and_zotero_coordinate_spaces(self):
        source = self._make_pdf()
        manifest = self.case / "manifest.json"
        result = annotate_pdf(
            source,
            self.case / "annotated.pdf",
            self.case / "backup.pdf",
            manifest,
            [self._area()],
        )

        annotation = result["annotations"][0]
        self.assertEqual(
            annotation["coordinate_space"],
            "pymupdf-page-top-left",
        )
        self.assertEqual(
            annotation["zotero_coordinate_space"],
            "pdf-page-bottom-left",
        )
        self.assertEqual(
            annotation["zotero_rect"],
            [20.0, 80.0, 200.0, 160.0],
        )
        self.assertLessEqual(annotation["coordinate_round_trip_error"], 0.01)

        on_disk = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            on_disk["annotations"][0]["zotero_rect"],
            [20.0, 80.0, 200.0, 160.0],
        )

    def test_v3_area_rejects_missing_or_wrong_coordinate_space(self):
        source = self._make_pdf()
        for invalid in (None, "pdf-page-bottom-left"):
            area = self._area()
            if invalid is None:
                del area["coordinate_space"]
            else:
                area["coordinate_space"] = invalid
            with self.subTest(coordinate_space=invalid):
                with self.assertRaisesRegex(ValueError, "coordinate_space"):
                    annotate_pdf(
                        source,
                        self.case / f"out-{invalid}.pdf",
                        self.case / f"backup-{invalid}.pdf",
                        self.case / f"manifest-{invalid}.json",
                        [area],
                    )

    def test_resolved_highlight_records_page_geometry_for_native_builder(self):
        source = self._make_pdf()
        result = annotate_pdf(
            source,
            self.case / "highlighted.pdf",
            self.case / "highlight-backup.pdf",
            self.case / "highlight-manifest.json",
            [self._highlight()],
        )

        highlight = result["annotations"][0]
        self.assertEqual(highlight["page_box"], [0.0, 0.0, 300.0, 300.0])
        self.assertEqual(highlight["page_rotation"], 0)


if __name__ == "__main__":
    unittest.main()
