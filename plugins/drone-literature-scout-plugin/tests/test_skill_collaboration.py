from __future__ import annotations

import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PLUGIN_ROOT / "skills"
CONTRACT = PLUGIN_ROOT / "references" / "skill-collaboration-contract.md"


RESPONSIBILITIES = {
    "zotero-obsidian-paper-import": "正式身份与 PDF 前置核验、唯一性导入、原生合并及 Zotero/Obsidian 引用一致性",
    "read-paper-analysis-highlight": "全文证据/作者/PDF 批注",
    "obsidian-note-style": "知识归属/视觉覆盖/Callout/WikiLink/媒体集成",
    "draw-style": "跨场景科研绘图/视觉验收",
    "drone-literature-scout": "文献脉络与外部来源",
    "searching-at-scale": "通用大规模网页发现/动态字段采集/跨来源核验与调研收敛",
}


def discover_current_skill_names() -> list[str]:
    return sorted(
        path.name
        for path in SKILLS_ROOT.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def contract_skill_rows(text: str) -> list[tuple[str, str]]:
    return [
        (name, responsibility.strip())
        for name, responsibility in re.findall(
            r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*$",
            text,
            flags=re.MULTILINE,
        )
    ]


class SkillCollaborationContractTests(unittest.TestCase):
    def test_contract_table_matches_dynamic_skill_inventory_exactly(self):
        self.assertTrue(CONTRACT.is_file(), CONTRACT)
        text = CONTRACT.read_text(encoding="utf-8")
        discovered = discover_current_skill_names()
        listed = [name for name, _ in contract_skill_rows(text)]

        self.assertEqual(sorted(listed), discovered)
        self.assertEqual(len(listed), len(set(listed)))
        for name in discovered:
            self.assertGreaterEqual(text.count(f"`{name}`"), 1)

    def test_responsibility_registry_matches_dynamic_skill_inventory(self):
        self.assertEqual(
            set(RESPONSIBILITIES),
            set(discover_current_skill_names()),
        )

    def test_contract_table_maps_every_skill_to_exact_responsibility(self):
        self.assertTrue(CONTRACT.is_file(), CONTRACT)
        text = CONTRACT.read_text(encoding="utf-8")
        rows = contract_skill_rows(text)

        self.assertEqual(len(rows), len(dict(rows)))
        self.assertEqual(dict(rows), RESPONSIBILITIES)

    def test_contract_records_coordination_rules(self):
        self.assertTrue(CONTRACT.is_file(), CONTRACT)
        text = CONTRACT.read_text(encoding="utf-8")

        required_rules = (
            "插件任务开始",
            "动态枚举 `skills/` 下全部含 `SKILL.md` 的目录",
            "同一任务内拓扑未变时不重复枚举",
            "正常成功路径不写故障库",
            "候选非空才通过 `global.collect-bug-update-accelerate` 加载 `promotion_audit.py`",
            "未来新增 Skill 必须同步登记职责",
            "global.workspace-hygiene",
            "按批准范围清理",
            "笔记语义合并、WikiLink、最终媒体归属和 Zotero 数据判断仍交给各自领域负责人",
        )
        for rule in required_rules:
            self.assertIn(rule, text)

    def test_every_skill_declares_the_shared_collaboration_preflight(self):
        required_rules = (
            "## 插件级轻量故障协作",
            "references/skill-collaboration-contract.md",
            "正常成功路径不写故障库",
            "任意异常、非零退出、权限拒绝、结果缺失或验证失败",
            "promotion_audit.py",
        )
        for name in discover_current_skill_names():
            text = (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
            for rule in required_rules:
                with self.subTest(skill=name, rule=rule):
                    self.assertIn(rule, text)

    def test_contract_records_broad_to_deep_research_governance(self):
        text = CONTRACT.read_text(encoding="utf-8").replace("**", "")
        required_rules = (
            "研究方法、研究方向或解决方案选择",
            "4–10 个真正可行候选",
            "少于 4 个",
            "不得凑数",
            "收敛到 3–5 个短名单",
            "最终保留真正独立的 2 个",
            "跨学科迁移",
            "新颖性服从适用性",
            "最小满足架构",
            "不得删除、弱化或绕过",
            "不得充当任何专业领域",
        )
        for rule in required_rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_contract_title_is_exact(self):
        self.assertTrue(CONTRACT.is_file(), CONTRACT)
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "# 六领域 Skill 自动协作合同")

    def test_obsolete_skill_name_has_no_residual_directory(self):
        residual = SKILLS_ROOT / "obsidian-research-voice"
        self.assertFalse(residual.exists())
        self.assertNotIn(residual.name, discover_current_skill_names())


if __name__ == "__main__":
    unittest.main()
