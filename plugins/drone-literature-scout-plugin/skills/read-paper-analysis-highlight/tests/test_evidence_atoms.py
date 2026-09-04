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


def complete_item(quote: str) -> dict:
    return {
        "id": "paper-001-v3-a01",
        "page": 1,
        "annotation_type": "highlight",
        "quote": quote,
        "kind": "method",
        "color": "blue",
        "note_question": "该证据对理解或复现有什么作用？",
        "claim": "该证据明确承担本文方法、实验、比较或复现中的具体角色。",
        "reason": "选中的词、数据或语句能够独立索引一项重要技术事实。",
        "information_roles": ["method", "mechanism"],
        "evidence": "PDF第 1 页",
        "confidence": "high",
    }


class EvidenceAtomTests(unittest.TestCase):
    def test_accepts_single_token_named_baselines_with_context(self):
        for quote in ("Ego-PlannerV2", "NavRL", "YOPO"):
            with self.subTest(quote=quote):
                item = complete_item(quote)
                item.update({
                    "selection_mode": "key-term",
                    "kind": "related-work",
                    "information_roles": ["method", "baseline", "reference_role"],
                    "context_summary": (
                        "该名称在正文中承担相关方法或实验 baseline 角色。"
                    ),
                    "annotation_comment": (
                        "结论：这是本文直接讨论或比较的基线方法。\n"
                        "意义：需要结合相邻正文区分方法来源与实验对照角色。"
                    ),
                })
                self.assertEqual(
                    validate_semantic_annotation(item)["quote"],
                    quote,
                )

    def test_accepts_reproduction_scale_metrics(self):
        cases = (
            ("7.5 m/s", "实机报告速度"),
            ("1,000 quadrotors", "并行训练规模"),
            ("16 procedurally generated scenarios", "训练场景数量"),
            ("160 trials", "实验样本规模"),
        )
        for quote, metric_context in cases:
            with self.subTest(quote=quote):
                item = complete_item(quote)
                item.update({
                    "selection_mode": "key-metric",
                    "kind": "experiment",
                    "information_roles": [
                        "metric",
                        "condition",
                        "experiment_setting",
                        "training_scale",
                    ],
                    "metric_context": metric_context,
                    "condition": "以该数值所在段落的训练或实验条件为准。",
                    "annotation_comment": (
                        f"结论：{quote} 是决定本文能力或证据规模的关键量。\n"
                        "复现：必须与当前段落的速度、场景或试验条件一起解释。"
                    ),
                })
                self.assertEqual(
                    validate_semantic_annotation(item)["quote"],
                    quote,
                )

    def test_accepts_supporting_doi_url_as_key_link(self):
        url = "https://doi.org/10.1109/LRA.2026.3703580"
        item = complete_item(url)
        item.update({
            "selection_mode": "key-link",
            "kind": "supporting-material",
            "information_roles": ["support_link", "reproducibility"],
            "link_context": "论文声明补充材料可通过该 DOI 入口获取。",
            "annotation_comment": (
                "结论：这是论文给出的补充材料入口，而不只是普通 DOI 文本。\n"
                "复现：应检查该入口实际提供的视频、附件或其他支撑材料。"
            ),
        })
        self.assertEqual(
            validate_semantic_annotation(item)["selection_mode"],
            "key-link",
        )

    def test_rejects_key_link_without_public_http_url(self):
        item = complete_item("supplementary downloadable material")
        item.update({
            "selection_mode": "key-link",
            "information_roles": ["support_link"],
            "link_context": "补充材料入口。",
            "annotation_comment": "结论：这是补充材料入口。",
        })
        with self.assertRaises(SemanticSelectionError):
            validate_semantic_annotation(item)


if __name__ == "__main__":
    unittest.main()
