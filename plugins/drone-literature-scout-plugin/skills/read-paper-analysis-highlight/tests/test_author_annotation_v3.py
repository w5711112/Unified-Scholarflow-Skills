from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from semantic_selection import (  # noqa: E402
    SemanticSelectionError,
    validate_semantic_annotation,
)


def author_item(comment: str) -> dict:
    return {
        "id": "paper-001-author-fei-gao",
        "page": 1,
        "annotation_type": "highlight",
        "annotation_schema_version": 3,
        "selection_mode": "author-name",
        "quote": "Fei Gao",
        "kind": "author-background",
        "color": "purple",
        "note_question": "通讯作者具有什么研究背景？",
        "claim": "该姓名对应论文明确标出的通讯作者，需要补充外部团队背景。",
        "reason": "作者姓名是外部履历批注唯一准确且不冒充论文方法证据的锚点。",
        "information_roles": ["author_context"],
        "evidence": "PDF第 1 页作者行",
        "confidence": "high",
        "author_context": "通讯作者；浙江大学 FAST Lab 研究团队负责人之一。",
        "external_evidence": "https://person.zju.edu.cn/fgaoaa",
        "external_sources": [
            "https://person.zju.edu.cn/fgaoaa",
            "https://www.cse.zju.edu.cn/2024/0729/c39283a2949751/page.htm",
        ],
        "verified_at": "2026-07-26",
        "annotation_comment": comment,
    }


class AuthorAnnotationV3Tests(unittest.TestCase):
    def test_v3_author_comment_uses_external_information_prefix(self):
        item = author_item(
            "外部信息：高飞为浙江大学控制学院长聘副教授、博士生导师，"
            "研究方向包括空中机器人、具身智能与群体智能。\n"
            "来源：https://person.zju.edu.cn/fgaoaa；核验日期：2026-07-26。"
        )
        self.assertEqual(
            validate_semantic_annotation(item)["selection_mode"],
            "author-name",
        )

    def test_v3_author_comment_rejects_legacy_prefix(self):
        item = author_item(
            "外部核验，不是论文正文事实：高飞为浙江大学教师。\n"
            "来源：https://person.zju.edu.cn/fgaoaa。"
        )
        with self.assertRaisesRegex(SemanticSelectionError, "外部信息"):
            validate_semantic_annotation(item)


if __name__ == "__main__":
    unittest.main()
