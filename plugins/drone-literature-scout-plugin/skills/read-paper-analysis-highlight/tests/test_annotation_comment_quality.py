from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from annotation_comment_quality import comment_quality_failures  # noqa: E402


class AnnotationCommentQualityTests(unittest.TestCase):
    def test_accepts_contextual_interpretation_with_separate_evidence_gap(self):
        item = {
            "annotation_schema_version": 3,
            "annotation_comment": (
                "结论：仿真步长为 0.01 s，因此论文明确设定策略输出和控制执行均为 100 Hz。\n"
                "复现：该值约束策略—控制更新周期；完整视觉链路延迟在全文中未报告。\n"
                "定位：PDF第 5 页。"
            ),
            "information_roles": [
                "implementation",
                "condition",
                "evidence_gap",
            ],
        }
        self.assertEqual(comment_quality_failures(item), [])

    def test_rejects_generic_or_translation_only_comment(self):
        comments = (
            "这是一个重要的方法。",
            "该句翻译为策略输出和控制执行都是 100 Hz。",
        )
        for comment in comments:
            with self.subTest(comment=comment):
                failures = comment_quality_failures({
                    "annotation_schema_version": 3,
                    "annotation_comment": comment,
                    "information_roles": ["method"],
                })
                self.assertTrue(failures)

    def test_evidence_gap_requires_explicit_boundary_language(self):
        failures = comment_quality_failures({
            "annotation_schema_version": 3,
            "annotation_comment": (
                "结论：论文给出了策略更新频率。\n"
                "意义：该指标很重要。"
            ),
            "information_roles": ["condition", "evidence_gap"],
        })
        self.assertTrue(
            any("evidence_gap" in failure for failure in failures),
            failures,
        )

    def test_comment_has_no_maximum_character_limit(self):
        long_detail = "该信息连接方法实现、实验条件与复现边界。" * 500
        failures = comment_quality_failures({
            "annotation_schema_version": 3,
            "annotation_comment": (
                "结论：该批注先给出可以快速扫读的核心判断。\n"
                f"意义：{long_detail}"
            ),
            "information_roles": ["method", "mechanism"],
        })
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
