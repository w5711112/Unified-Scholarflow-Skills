import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_zotero_native_annotation_plan.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "build_zotero_native_annotation_plan",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ZoteroNativeAnnotationPlanTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.plan = {
            "operation_id": "paper-001-native-v1",
            "library_id": 1,
            "page_label_start": 4070,
            "annotations": [
                {
                    "id": "paper-001-v001",
                    "page": 2,
                    "annotation_type": "area",
                    "rect": [38, 53, 552, 378],
                    "page_box": [0, 0, 594, 792],
                    "page_rotation": 0,
                    "color": "blue",
                    "annotation_comment": "结论：图 1 显示系统接口。\n定位：PDF 第 2 页，图 1。",
                },
                {
                    "id": "paper-001-a001",
                    "page": 1,
                    "annotation_type": "highlight",
                    "quote": "Evidence text",
                    "actual_text": "Evidence text",
                    "quads": [
                        [30, 50, 100, 50, 30, 65, 100, 65],
                        [30, 70, 90, 70, 30, 85, 90, 85],
                    ],
                    "page_box": [0, 0, 594, 792],
                    "page_rotation": 0,
                    "color": "yellow",
                    "annotation_comment": "结论：证据说明输入与输出。\n机制：原文给出完整关系。",
                },
            ],
            "allowed_native_keys": [],
            "deletions": [],
        }

    def test_build_plan_maps_area_and_highlight_without_javascript(self):
        request = self.module.build_plan(self.plan, "ABCD2345")

        self.assertEqual(request["schema_version"], 1)
        self.assertEqual(request["operation_id"], "paper-001-native-v1")
        self.assertEqual(request["library"], {"type": "user", "id": 1})
        self.assertEqual(
            request["attachment"],
            {"key": "ABCD2345", "content_type": "application/pdf"},
        )
        image, highlight = request["annotations"]
        self.assertEqual(image["stable_id"], "paper-001-v001")
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["page_index"], 1)
        self.assertEqual(image["page_label"], "4071")
        self.assertEqual(image["sort_index"], "00001|053000|00000")
        self.assertEqual(image["position"]["rects"], [[38, 414, 552, 739]])
        self.assertEqual(image["color"], "#3380ff")
        self.assertNotIn("text", image)

        self.assertEqual(highlight["stable_id"], "paper-001-a001")
        self.assertEqual(highlight["type"], "highlight")
        self.assertEqual(highlight["page_index"], 0)
        self.assertEqual(highlight["page_label"], "4070")
        self.assertEqual(highlight["sort_index"], "00000|050000|00001")
        self.assertEqual(
            highlight["position"]["rects"],
            [[30, 727, 100, 742], [30, 707, 90, 722]],
        )
        self.assertEqual(highlight["text"], "Evidence text")
        self.assertEqual(highlight["comment"], self.plan["annotations"][1]["annotation_comment"])
        self.assertFalse(hasattr(self.module, "build_run_javascript"))
        self.assertNotIn("javascript", repr(request).lower())
        self.assertNotIn("Zotero.", repr(request))

    def test_stable_ids_and_resolved_highlight_quads_are_mandatory(self):
        missing_id = {
            **self.plan,
            "annotations": [{key: value for key, value in self.plan["annotations"][0].items() if key != "id"}],
        }
        with self.assertRaisesRegex(ValueError, "stable"):
            self.module.build_plan(missing_id, "ABCD2345")

        unresolved = {
            **self.plan,
            "annotations": [{
                key: value
                for key, value in self.plan["annotations"][1].items()
                if key not in {"quads", "actual_text"}
            }],
        }
        with self.assertRaisesRegex(ValueError, "quads"):
            self.module.build_plan(unresolved, "ABCD2345")

    def test_native_keys_and_exact_deletions_are_passed_through(self):
        plan = {
            **self.plan,
            "annotations": [{
                **self.plan["annotations"][0],
                "native_key": "ANN00001",
            }],
            "allowed_native_keys": ["ANN00001", "OLD00001"],
            "deletions": [{
                "native_key": "OLD00001",
                "before_fingerprint": "a" * 64,
            }],
        }

        request = self.module.build_plan(plan, "ABCD2345")

        self.assertEqual(request["annotations"][0]["native_key"], "ANN00001")
        self.assertEqual(request["allowed_native_keys"], ["ANN00001", "OLD00001"])
        self.assertEqual(request["deletions"], plan["deletions"])


if __name__ == "__main__":
    unittest.main()
