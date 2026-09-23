from __future__ import annotations

import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PLUGIN_ROOT.parents[1]
VAULT_ROOT = WORKSPACE_ROOT.parent
OBSIDIAN_SKILL = PLUGIN_ROOT / "skills" / "obsidian-note-style" / "SKILL.md"
FORMULA_REFERENCE = (
    PLUGIN_ROOT
    / "skills"
    / "obsidian-note-style"
    / "references"
    / "formula-explanation-patterns.md"
)
CROSS_COURSE_REFERENCE = (
    PLUGIN_ROOT
    / "skills"
    / "obsidian-note-style"
    / "references"
    / "cross-course-concept-bridges.md"
)
READ_PAPER_SKILL = (
    PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "SKILL.md"
)
BSPLINE_KNOWLEDGE_NOTE = VAULT_ROOT / "路径规划与环境表示.md"
CORB_PAPER_NOTE = WORKSPACE_ROOT / "01-核心论文精读.md"
ALGORITHM_KNOWLEDGE_NOTE = VAULT_ROOT / "深度强化学习.md"


def unescaped_pipe_count(line: str) -> int:
    return sum(
        1
        for index, char in enumerate(line)
        if char == "|" and (index == 0 or line[index - 1] != "\\")
    )


def heading_section(text: str, heading: str) -> str:
    marker = f"### {heading}\n"
    start = text.index(marker)
    end = text.find("\n### ", start + len(marker))
    return text[start : len(text) if end == -1 else end]


class ObsidianVisualKnowledgeContractTests(unittest.TestCase):
    def test_table_wikilink_aliases_are_escaped_without_splitting_columns(self):
        text = ALGORITHM_KNOWLEDGE_NOTE.read_text(encoding="utf-8")
        rows = [
            line
            for line in text.splitlines()
            if line.startswith("| [[深度强化学习#")
            and any(name in line for name in ("贪心算法", "动态规划", "模拟退火"))
        ]
        self.assertEqual(3, len(rows))
        for row in rows:
            with self.subTest(row=row):
                self.assertEqual(6, unescaped_pipe_count(row))
                self.assertRegex(
                    row,
                    r"\[\[深度强化学习#[^\]]+\\\|[^\]]+\]\]",
                )

    def test_new_algorithm_knowledge_points_each_have_one_figure_and_folded_legend(self):
        text = ALGORITHM_KNOWLEDGE_NOTE.read_text(encoding="utf-8")
        for heading in ("贪心算法", "动态规划", "模拟退火"):
            section = heading_section(text, heading)
            with self.subTest(heading=heading):
                self.assertEqual(1, section.count("![[AI绘图存放位置/"))
                self.assertEqual(1, section.count("> [!info]- **读图与图例**"))
                self.assertLess(section.index("#### 第一层｜直觉理解"), section.index("![["))
                self.assertLess(section.index("![["), section.index("> [!info]- **读图与图例**"))
                self.assertLess(section.index("> [!info]- **读图与图例**"), section.index("#### 第二层｜公式与原理"))

    def test_obsidian_skill_has_a_local_new_knowledge_visual_gate_and_table_link_rule(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "新增或扩充知识点本地门禁",
            "不能豁免本地门禁",
            "[[笔记名#标题\\|简短别名]]",
            "未转义的别名分隔符",
            "每个本轮新增或扩充的正式知识点",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_obsidian_skill_owns_prerequisite_formula_and_visual_contracts(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        required = (
            "知识前置链",
            "基础概念 → 扩展概念 → 论文特定用法",
            "完整的必要计算链",
            "逐符号人话翻译",
            "AI绘图存放位置",
            "每个知识点独立判断为 `0` 或 `1` 张",
            "八项硬质量门槛",
            "[!info]- **读图与图例**",
            "不设固定条数",
            "audit_obsidian_media.py",
            "audit_obsidian_visual_coverage.py",
            "Markdown 与 Canvas",
            "歧义引用",
            "默认只生成 dry-run",
            "插件根目录的 `references/skill-collaboration-contract.md`",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_read_paper_skill_hands_visual_knowledge_maintenance_to_obsidian(self):
        text = READ_PAPER_SKILL.read_text(encoding="utf-8")
        required = (
            "概念前置缺口",
            "示意图需求",
            "交给 `obsidian-note-style`",
            "不得自行创建零散知识文件",
            "基础概念、扩展概念与论文特定用法",
            "公式解释闭环",
            "Vault 全部正式知识点",
            "每篇论文只触发一次",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_read_paper_does_not_claim_media_cleanup_ownership(self):
        text = READ_PAPER_SKILL.read_text(encoding="utf-8")
        self.assertIn("媒体引用审计与孤儿图片清理由 `obsidian-note-style` 独占负责", text)

    def test_obsidian_delegates_generic_drawing_but_keeps_vault_lifecycle(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "调用 `draw-style`",
            "知识点语义要求、原文证据和输出约束",
            "每个知识点独立判断为 `0` 或 `1` 张",
            "AI绘图存放位置",
            "[!info]- **读图与图例**",
            "audit_obsidian_media.py",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("生成 Image2 前，必须", text)

    def test_formula_guided_narrative_keeps_the_complete_reader_contract(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        required = (
            "完整的必要计算链",
            "逐符号人话翻译",
            "例子、性质来源、误解和边界",
            "公式解释可以比直觉层更长",
            "formula-explanation-patterns.md",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertTrue(FORMULA_REFERENCE.is_file())
        self.assertNotIn("第二层只写关键公式、必要符号、最小计算链与边界", text)

    def test_guided_formula_reference_preserves_latex_and_reading_order(self):
        text = FORMULA_REFERENCE.read_text(encoding="utf-8")
        controls = sorted(
            {ord(char) for char in text if ord(char) < 32 and char not in "\r\n"}
        )
        self.assertEqual([], controls, f"unexpected control characters: {controls}")
        for token in (r"$\tau$", r"$\alpha$", r"$\beta$", r"\Delta\tau"):
            with self.subTest(token=token):
                self.assertIn(token, text)
        self.assertNotIn("$alpha$", text)
        for phrase in (
            "公式引导式解释模板",
            "一次只解释一个符号",
            "逐步解释递推",
            "重新合回完整公式",
            "符号速查表是否只放在完整引导式正文之后",
            "First In, First Out",
            "相邻两个 knot 之间的参数区间",
            "$a_t\\rightarrow v_t\\rightarrow p_t$",
            "$a_t$、$v_t$、$p_t$ 分别是第 $t$ 个加速度、速度和位置控制点",
            "两次离散累积或积分",
            "算法级采样规则",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_cross_course_concept_bridges_require_user_approval(self):
        skill = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "跨课程概念桥审计",
            "Agent 自主提出",
            "必须先经用户确认",
            "未确认不得写入",
            "用户主动提出并确认",
            "普通同领域计算例子",
            "references/cross-course-concept-bridges.md",
        ):
            with self.subTest(surface="skill", phrase=phrase):
                self.assertIn(phrase, skill)
        self.assertNotIn("禁止生活化、跨领域类比", skill)
        self.assertTrue(CROSS_COURSE_REFERENCE.is_file())

        reference = CROSS_COURSE_REFERENCE.read_text(encoding="utf-8")
        for phrase in (
            "C++ 程序设计",
            "离散数学",
            "数据结构",
            "线性代数",
            "计算机组成原理",
            "信息论基础",
            "概率论与数理统计",
            "信号与系统",
            "自动控制理论",
            "智能机器人与无人系统",
            "统计分析",
            "数据库概论",
            "计算机视觉与模式识别",
            "机器学习",
            "管理博弈论",
            "智能优化与控制技术",
            "fuzzy",
            "通信原理 C",
            "数学、物理、地理、生物",
            "不提出化学类比",
            "共同结构",
            "逐项映射",
            "具体区别",
            "拟解决疑问",
            "确认问题",
            "用户未确认",
            "B-spline 首先是曲线空间的基函数和重构核",
            "不等同于一般意义下",
            r"\operatorname{sinc}",
        ):
            with self.subTest(surface="reference", phrase=phrase):
                self.assertIn(phrase, reference)

        formula = FORMULA_REFERENCE.read_text(encoding="utf-8")
        self.assertIn("跨课程公式桥", formula)
        self.assertIn("仅在用户已明确批准", formula)

    def test_vault_bspline_formula_layers_are_complete_and_latex_safe(self):
        for path in (BSPLINE_KNOWLEDGE_NOTE, CORB_PAPER_NOTE):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                controls = sorted(
                    {ord(char) for char in text if ord(char) < 32 and char not in "\r\n"}
                )
                self.assertEqual([], controls, f"{path.name}: control characters {controls}")
                for token in (r"\tau", r"\Delta\tau", r"B_{t,k}", r"p(\tau)"):
                    self.assertIn(token, text)

        knowledge = BSPLINE_KNOWLEDGE_NOTE.read_text(encoding="utf-8")
        bspline_section = heading_section(knowledge, "B-spline 轨迹")
        for phrase in (
            "均匀三次 B-spline：公式解释闭环",
            "**人话公式**",
            "**正式定义**",
            "**符号—作用**",
            "**权重为什么可理解为 $0$ 到 $1$**",
            "**递推在做什么**",
            "**最小可算例子**",
            "**当前 span 怎样直接计算**",
            "**性质怎样从公式得到**",
            "**与低通滤波的联系**",
            "不等同于一般低通滤波器",
            "First In, First Out（先进先出）",
            "相邻两个 knot 之间的参数区间",
            "**系统作用与边界**",
        ):
            with self.subTest(note="knowledge", phrase=phrase):
                self.assertIn(phrase, bspline_section)
        image = re.search(
            r"!\[\[AI绘图存放位置/B-spline局部支撑与逐点生成\.png(?:\|[^\]]+)?\]\]",
            bspline_section,
        )
        self.assertIsNotNone(image)
        ordered_knowledge_markers = (
            "#### 第一层",
            "> [!info]- **读图与图例**",
            "#### 第二层",
            "> [!info]- **均匀三次 B-spline",
            "**一句话核心**",
            "**人话公式**",
            "**正式定义**",
            "**符号—作用**",
            "**权重为什么可理解为 $0$ 到 $1$**",
            "**递推在做什么**",
            "**最小可算例子**",
            "**当前 span 怎样直接计算**",
            "**性质怎样从公式得到**",
            "**与低通滤波的联系**",
            "**CORB 的逐点生成链**",
            "**易混淆点**",
            "**系统作用与边界**",
        )
        positions = [bspline_section.index(marker) for marker in ordered_knowledge_markers]
        positions.insert(1, image.start())
        self.assertEqual(sorted(positions), positions)
        self.assertIn("^bspline-trajectory", bspline_section)
        self.assertIsNotNone(image)

        paper = CORB_PAPER_NOTE.read_text(encoding="utf-8")
        for phrase in (
            "**论文公式（1）的任务**",
            "**公式（5a）给出新 span 起点**",
            "**公式（2）–（4）负责导数控制点**",
            "**公式（11）–（12）把策略动作接入曲线**",
            "卷积—傅里叶—低通平滑",
            "**论文边界**",
        ):
            with self.subTest(note="paper", phrase=phrase):
                self.assertIn(phrase, paper)
        self.assertIn("^paper-corb-planner", paper)
        self.assertIn(
            "[[路径规划与环境表示#B-spline 轨迹|B-spline 轨迹知识点]]",
            paper,
        )

    def test_obsidian_places_existing_figure_between_intuition_and_math_without_repetition(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        required = (
            "合格现图不修改",
            "图放在第一层正文之后",
            "第二层紧跟图例",
            "同一结论只保留一处",
            "解释闭环后不重复",
        )
        missing = [phrase for phrase in required if phrase not in text]
        self.assertFalse(missing, f"missing concise figure-placement rules: {missing}")

    def test_knowledge_heading_names_the_concept_and_intuition_heading_states_its_domain_essence(self):
        text = OBSIDIAN_SKILL.read_text(encoding="utf-8")
        required = (
            "知识点总标题只写标准名称",
            "第一层｜直觉理解 | 一句话本质",
            "跨课程概念桥",
            "必须先经用户确认",
            "不把通俗解释写进知识点总标题",
        )
        missing = [phrase for phrase in required if phrase not in text]
        self.assertFalse(missing, f"missing knowledge-heading contract: {missing}")
        self.assertNotIn("禁止生活化、跨领域类比", text)


if __name__ == "__main__":
    unittest.main()
