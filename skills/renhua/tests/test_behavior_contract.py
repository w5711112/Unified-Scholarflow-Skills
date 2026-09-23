from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRAFT_ROOT = Path(
    os.environ.get(
        "RENHUA_DRAFT_ROOT",
        r"C:\Users\w5711112\.zcode\workspace\default\humanize-compare\renhua-draft",
    )
)
REFS = ROOT / "references"
ENTRY = ROOT / "SKILL.md"

REFERENCE_FILES = (
    "core-authority-and-scenarios.md",
    "rewrite-rules-r1-r8.md",
    "rewrite-rules-r9-r17.md",
    "execution-and-delivery-contract.md",
    "document-table-format.md",
)


def combined() -> str:
    return "\n".join(
        [ENTRY.read_text(encoding="utf-8")]
        + [(REFS / name).read_text(encoding="utf-8") for name in REFERENCE_FILES]
    )


class BehaviorContractTests(unittest.TestCase):
    def test_s1_fact_strength_and_protected_content_are_preserved(self) -> None:
        text = combined()
        for token in (
            "事实与强度守恒",
            "人物、数字、时间、术语、引语、归因、限定词",
            "可能提升",
            "不得写成“提升”",
            "从 2.3% 降至 0.8%",
            "Q-learning",
            "epsilon-贪婪",
            "参考文献列表",
            "图表标题",
            "引用必须与被支持的陈述一起移动",
            "每个新增实词必须能回指原文",
        ):
            self.assertIn(token, text)

    def test_s2_five_scenes_keep_their_exemptions_and_precedence(self) -> None:
        text = combined()
        for token in (
            "paper-notes",
            "grant-proposal",
            "work-doc",
            "general-text",
            "dialogue",
            "目标—方案—可行性框架不动",
            "R6/R11 不得打散",
            "R9 只处理明显赘疣",
            "闭环整改",
            "可追溯",
            "论文结论章、摘要的总结句",
            "场景判定中的豁免条款",
            "规则之间冲突时，编号小者优先",
            "不卑不亢",
        ):
            self.assertIn(token, text)

    def test_s3_r1_to_r8_keep_exact_budgets_and_false_positive_guards(self) -> None:
        text = (REFS / "rewrite-rules-r1-r8.md").read_text(encoding="utf-8")
        self.assertEqual(
            {int(value) for value in re.findall(r"^### R(\d+)\b", text, re.M)},
            set(range(1, 9)),
        )
        for token in (
            "破折号（——、—）一律不用",
            "分号一律不用",
            "每 300 字 ≤1 个",
            "一个分句内 ≥3 项",
            "超过约 40 字",
            "同段同构 ≤2 处",
            "一眼就能看懂",
            "就等于掌握了",
            "不得虚构来源、机构、年份、DOI、链接",
        ):
            self.assertIn(token, text)

    def test_s4_r9_to_r17_keep_density_coherence_and_traceability(self) -> None:
        text = (REFS / "rewrite-rules-r9-r17.md").read_text(encoding="utf-8")
        self.assertEqual(
            {int(value) for value in re.findall(r"^### R(\d+)\b", text, re.M)},
            set(range(9, 18)),
        )
        for token in (
            "相邻三句长度接近（±20% 以内）",
            "同段 2+ 个才处理",
            "全文密度过高才处理",
            "改写稿中一个都不能有",
            "先定义后使用",
            "同物同名",
            "删句波及检查",
            "不得把不确定清洗成确定",
            "连续 ≥3 个同构标签段",
            "work-doc 的编号条款（4.1/5.2 等层级编号）除外",
        ):
            self.assertIn(token, text)

    def test_s5_single_pass_delivery_keeps_output_and_six_gates(self) -> None:
        text = (REFS / "execution-and-delivery-contract.md").read_text(encoding="utf-8")
        for token in (
            "主循环",
            "一轮通读",
            "对账输出",
            "禁止在此基础上再发起新一轮全文重扫",
            "【改写稿】",
            "【改动说明】",
            "【待确认】",
            "只要正文",
            "保真",
            "洁净",
            "连贯",
            "呈现",
            "语域",
            "可审计",
        ):
            self.assertIn(token, text)
        gate_section = text.split("## 交付门禁", 1)[1].split("## 最终判定", 1)[0]
        self.assertEqual(len(re.findall(r"^\d+\. \*\*", gate_section, re.M)), 6)

    def test_s6_document_table_contract_is_preserved_and_shared(self) -> None:
        main = (REFS / "document-table-format.md").read_text(encoding="utf-8")
        draft = (
            DRAFT_ROOT / "references" / "document-table-format.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(main, draft)
        for token in (
            "三线表默认",
            "约1.5pt",
            "约0.75pt",
            "无竖线、无内部横线",
            "水平居中、垂直居中",
            "读者在 Word/WPS 中看到的结果为准",
            "合并单元格",
            "多个段落的单元格",
            "保存后重新打开",
            "不用空格推齐",
            "w:ind firstLine=0",
            "firstLineChars=0",
            "相邻两张表格之间必须插入一个空段落",
            "document-skills:docx",
            "math-modeling-plugin-v2/skills/paper-writing",
            "python-docx",
        ):
            self.assertIn(token, main)

    def test_s7_obsidian_word_generation_and_compound_terms_have_a_language_gate(self) -> None:
        text = combined()
        for token in (
            "已有简体中文文件、段落或对话",
            "专业语义草稿 → renhua → 格式 Skill",
            "普通复合词",
            "对象归属",
            "动作主体",
            "用于比较的基准方法（baseline）",
            "输入来自哪里",
            "输出属于谁",
            "框架不自动下放到组件",
            "来源与承诺可追溯",
            "多文档功能去重",
        ):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
