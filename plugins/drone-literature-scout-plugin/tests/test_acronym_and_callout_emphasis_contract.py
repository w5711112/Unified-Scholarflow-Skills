from __future__ import annotations

import json
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
VAULT_ROOT = WORKSPACE_ROOT.parent
SKILLS_ROOT = PLUGIN_ROOT / "skills"


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class AcronymAndCalloutEmphasisContractTests(unittest.TestCase):
    def test_obsidian_skill_owns_general_initialism_format(self):
        text = read_utf8(SKILLS_ROOT / "obsidian-note-style" / "SKILL.md")

        self.assertIn("英文全称—简称的首字母映射", text)
        self.assertIn(
            "**H**igh-**O**rder **C**ontrol **B**arrier "
            "**F**unction（**HOCBF**）",
            text,
        )
        self.assertIn(
            "**P**roximal **P**olicy **O**ptimization（**PPO**）",
            text,
        )
        self.assertIn(
            "**E**uclidean **S**igned **D**istance **F**ield（**ESDF**）",
            text,
        )
        self.assertIn("后续只写加粗简称", text)
        self.assertIn("不得为了视觉效果篡改全称", text)

    def test_read_paper_skill_owns_four_callout_emphasis_roles(self):
        text = read_utf8(
            SKILLS_ROOT / "read-paper-analysis-highlight" / "SKILL.md"
        )

        self.assertIn("论文 Callout 强调语义合同", text)
        self.assertIn("短扫描锚点", text)
        self.assertIn("可独立复述", text)
        self.assertIn("有全文证据支撑的正面结果", text)
        self.assertIn("未提供链接、参数、硬件或解释", text)
        self.assertIn("颜色与 `==...==` 不叠加", text)
        self.assertIn("不得为了凑齐颜色", text)

    def test_import_skill_does_not_own_note_emphasis(self):
        text = read_utf8(
            SKILLS_ROOT / "zotero-obsidian-paper-import" / "SKILL.md"
        )

        self.assertNotIn("## 论文精读卡片的语义强调合同", text)
        self.assertIn("论文 Callout 的强调语义不属于本 skill", text)
        self.assertIn("read-paper-analysis-highlight", text)
        self.assertIn("obsidian-note-style", text)

    def test_template_documents_sibling_nested_callout_separator(self):
        text = read_utf8(
            SKILLS_ROOT
            / "read-paper-analysis-highlight"
            / "references"
            / "obsidian-callout-template.md"
        )

        self.assertIn("相邻的两个内层折叠", text)
        self.assertIn("父级空行 `>`", text)
        self.assertIn(
            "> > [!info]- **概念解释：第一部分**\n"
            "> > - 第一部分内容\n"
            ">\n"
            "> > [!info]- **概念解释：第二部分**",
            text,
        )

    def test_template_reserves_independent_empty_user_owned_personal_callout(self):
        text = read_utf8(
            SKILLS_ROOT
            / "read-paper-analysis-highlight"
            / "references"
            / "obsidian-callout-template.md"
        )
        self.assertIn(
            "\n\n"
            "> [!personal]+ 个人理解\n"
            "```",
            text,
        )
        self.assertNotIn("%% personal-reading-boundary %%", text)
        self.assertIn("新建时内部必须为空", text)
        self.assertIn("不得生成、润色、移动或覆盖", text)
        self.assertNotIn('<details class="personal-reading">', text)
        self.assertNotIn("训练期 CBF 启发奖励", text)

    def test_first_paper_has_one_leading_blank_and_no_trailing_blank(self):
        text = read_utf8(WORKSPACE_ROOT / "01-核心论文精读.md")
        first = text[text.index("### 1. ") : text.index("### 2. ")]
        marker = "\n\n> [!personal]+ 个人理解\n"
        self.assertEqual(first.count(marker), 1)
        personal = first[first.index(marker) + len(marker) :]
        ai = first[: first.index(marker)]
        self.assertNotIn("<details", first)
        self.assertNotIn("%% personal-reading-boundary %%", first)
        self.assertNotIn("概念解释：训练期与部署期的安全机制怎样分工", ai)
        self.assertIn(
            "> | 训练 | 完整仿真地图、Dijkstra、ESDF、真值状态 |",
            personal,
        )
        self.assertIn("CBF 启发的奖励", personal)
        self.assertIn("名义动作", personal)
        self.assertIn("实时动作安全过滤器", personal)
        self.assertTrue(personal.endswith("\n"), personal)
        self.assertFalse(personal.endswith("\n\n"), personal)

    def test_personal_training_deployment_table_stays_inside_callout(self):
        text = read_utf8(WORKSPACE_ROOT / "01-核心论文精读.md")
        lines = text.splitlines()
        self.assertIn("> **训练期/部署期分工**", lines)
        label_index = lines.index("> **训练期/部署期分工**")
        self.assertEqual(lines[label_index + 1], ">")
        self.assertEqual(
            lines[label_index + 2],
            "> | 阶段 | 使用的信息 | 安全方法 | 性质 |",
        )
        self.assertEqual(lines[label_index + 3], "> |---|---|---|---|")
        self.assertEqual(
            lines[label_index + 6],
            "> | Actor 输入 | 深度图、速度、姿态、目标等 | "
            "不直接读取 ESDF/全局地图 | 训练部署一致 |",
        )
        self.assertTrue(lines[label_index + 7].startswith("### 2. CORB-Planner"))

    def test_core_note_opts_out_of_sheets_extended_native_table_rewrite(self):
        text = read_utf8(WORKSPACE_ROOT / "01-核心论文精读.md")
        self.assertEqual(
            text.splitlines()[:3],
            ["---", "disable-sheet: true", "---"],
        )

    def test_read_paper_skill_records_spacing_and_sheets_compatibility(self):
        skill = read_utf8(
            SKILLS_ROOT / "read-paper-analysis-highlight" / "SKILL.md"
        )
        template = read_utf8(
            SKILLS_ROOT
            / "read-paper-analysis-highlight"
            / "references"
            / "obsidian-callout-template.md"
        )
        for text in (skill, template):
            self.assertIn("Sheets Extended", text)
            self.assertIn("disable-sheet: true", text)
            self.assertIn("不得全局禁用", text)
            self.assertIn("源码必须恰好保留一个真实空行", text)
            self.assertIn("可见间距必须为 0", text)
            self.assertIn("下一篇 `###` 标题前的源码空行必须为 0", text)

    def test_personal_callout_css_and_live_preview_are_enabled(self):
        appearance = json.loads(
            read_utf8(VAULT_ROOT / ".obsidian" / "appearance.json")
        )
        app = json.loads(read_utf8(VAULT_ROOT / ".obsidian" / "app.json"))
        self.assertIn("personal-reading", appearance["enabledCssSnippets"])
        self.assertTrue(app.get("livePreview", False))
        css = read_utf8(
            VAULT_ROOT / ".obsidian" / "snippets" / "personal-reading.css"
        )
        self.assertIn('.callout[data-callout="personal"]', css)
        self.assertIn(".markdown-preview-view", css)
        self.assertIn(".markdown-source-view.mod-cm6.is-live-preview", css)
        self.assertIn(".el-callout", css)
        self.assertIn(".cm-line:not(.cm-active)", css)
        self.assertIn("height: 0", css)
        self.assertIn("--callout-color: 46, 160, 67", css)
        self.assertIn(
            "background-color: rgba(46, 160, 67, 0.10) !important",
            css,
        )
        self.assertIn(
            "background-color: rgba(46, 160, 67, 0.08) !important",
            css,
        )
        self.assertIn("margin: 0", css)
        self.assertNotIn("details.personal-reading", css)

    def test_read_paper_skill_protects_user_owned_personal_callout(self):
        text = read_utf8(
            SKILLS_ROOT / "read-paper-analysis-highlight" / "SKILL.md"
        )
        self.assertIn("用户个人理解区强制合同", text)
        self.assertIn("`> [!personal]+ 个人理解`", text)
        self.assertIn("阅读模式默认展开", text)
        self.assertIn("真实空行", text)
        self.assertIn("下一篇 `###` 标题前不保留空行", text)
        self.assertNotIn("`%% personal-reading-boundary %%`", text)
        self.assertIn("不得拆分到单独笔记", text)
        self.assertIn("新建时内部必须为空", text)
        self.assertIn("不得生成、润色、移动或覆盖", text)
        self.assertIn("逐字保留", text)
        self.assertNotIn('<details class="personal-reading">', text)

if __name__ == "__main__":
    unittest.main()
