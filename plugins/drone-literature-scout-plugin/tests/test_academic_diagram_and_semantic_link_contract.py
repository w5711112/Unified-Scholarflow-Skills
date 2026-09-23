from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
OBSIDIAN_SKILL = PLUGIN_ROOT / "skills" / "obsidian-note-style" / "SKILL.md"
DRAW_STYLE = PLUGIN_ROOT / "skills" / "draw-style" / "SKILL.md"
DRAW_VISUAL_LANGUAGE = (
    PLUGIN_ROOT / "skills" / "draw-style" / "references" / "visual-language.md"
)
DRAW_LAYOUT_PATTERNS = (
    PLUGIN_ROOT / "skills" / "draw-style" / "references" / "layout-patterns.md"
)
DRAW_OBSIDIAN = (
    PLUGIN_ROOT / "skills" / "draw-style" / "references" / "obsidian-knowledge-figures.md"
)
READ_PAPER_SKILL = (
    PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "SKILL.md"
)


class AcademicDiagramAndSemanticLinkContractTests(unittest.TestCase):
    def draw_contract(self) -> str:
        return "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                DRAW_STYLE,
                DRAW_VISUAL_LANGUAGE,
                DRAW_LAYOUT_PATTERNS,
                DRAW_OBSIDIAN,
            )
        )

    def test_draw_style_requires_restrained_academic_diagrams(self):
        text = self.draw_contract()
        for phrase in (
            "论文教材风",
            "科研浅色体系",
            "局部透明渐变",
            "裁切到语义边界",
            "实际 Obsidian 嵌入宽度",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_obsidian_skill_requires_semantic_missing_link_audit(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "新增技术名词",
            "已有唯一知识位置",
            "仍以纯文本出现",
            "链接检查器只能发现失效链接",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_read_paper_skill_requires_evidence_backed_author_contributions(self):
        text = READ_PAPER_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "`**作者贡献**`",
            "贡献核心短语",
            "作者声称的贡献",
            "真实增量",
            "只有字段名加粗",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


    def test_draw_style_requires_readable_dense_diagrams(self):
        text = self.draw_contract()
        for phrase in (
            "正常宽度可读",
            "紧凑但不拥挤",
            "标签保留安全距离",
            "不使用固定内容占比或边距百分比",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_author_research_stays_with_each_paper_and_pdf(self):
        text = READ_PAPER_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "不得创建独立作者/团队笔记",
            "论文折叠“作者与团队背景”",
            "PDF 作者姓名批注",
            "内部作者调研 JSON",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_obsidian_skill_has_only_two_paper_knowledge_hubs(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        self.assertIn("冻结为两个现有文件", text)
        self.assertNotIn("`无人机研究团队与作者.md`：", text)
        self.assertIn("作者履历不进入知识枢纽", text)


if __name__ == "__main__":
    unittest.main()
