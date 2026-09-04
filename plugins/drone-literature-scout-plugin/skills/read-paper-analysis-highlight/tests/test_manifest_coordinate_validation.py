from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

import fitz


SKILL_ROOT = Path(__file__).parents[1]
SCRIPT_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from annotate_pdf import annotate_pdf  # noqa: E402
from test_support import writable_test_directory  # noqa: E402
from verify_annotation_manifest import verify_manifest  # noqa: E402


class ManifestCoordinateValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = writable_test_directory()
        self.case = Path(self.temporary_directory.__enter__())

    def tearDown(self):
        self.temporary_directory.__exit__(None, None, None)

    def _manifest(self) -> Path:
        source = self.case / "paper.pdf"
        document = fitz.open()
        document.new_page(width=300, height=300)
        document.save(source)
        document.close()
        manifest = self.case / "manifest.json"
        annotate_pdf(
            source,
            self.case / "annotated.pdf",
            self.case / "backup.pdf",
            manifest,
            [{
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
            }],
        )
        return manifest

    def test_manifest_verifier_accepts_valid_dual_coordinates(self):
        self.assertTrue(verify_manifest(self._manifest()))

    def test_manifest_verifier_rejects_tampered_zotero_rectangle(self):
        manifest = self._manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["annotations"][0]["zotero_rect"] = [20.0, 140.0, 200.0, 220.0]
        manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "zotero_rect"):
            verify_manifest(manifest)


    def test_manifest_verifier_accepts_final_zotero_native_schema(self):
        backup = self.case / "backup.pdf"
        current = self.case / "current.pdf"
        for path in (backup, current):
            document = fitz.open()
            document.new_page(width=300, height=300)
            document.save(path)
            document.close()

        plan = self.case / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "annotations": [
                        {
                            "id": "native-1",
                            "page": 1,
                            "annotation_type": "highlight",
                        },
                        {
                            "id": "native-area",
                            "page": 1,
                            "annotation_type": "area",
                            "rect": [20.0, 140.0, 200.0, 220.0],
                            "visual_object": "Figure 1",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        digest = hashlib.sha256(backup.read_bytes()).hexdigest().upper()
        manifest = self.case / "native-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "storage_mode": "zotero-native",
                    "source_pdf": str(backup),
                    "annotated_pdf": str(current),
                    "backup_pdf": str(backup),
                    "original_sha256": digest,
                    "current_pdf_sha256": hashlib.sha256(
                        current.read_bytes()
                    ).hexdigest().upper(),
                    "page_count": 1,
                    "annotation_count": 2,
                    "native_annotation_keys": ["ABC123", "AREA123"],
                    "annotation_plan": str(plan),
                    "locked_annotation_count": 0,
                    "external_annotation_count": 0,
                    "embedded_pdf_annotation_count": 0,
                    "editable_verified": True,
                    "deletable_verified": True,
                    "staging_verification": {
                        "coordinate_manifest_valid": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(verify_manifest(manifest))


if __name__ == "__main__":
    unittest.main()
