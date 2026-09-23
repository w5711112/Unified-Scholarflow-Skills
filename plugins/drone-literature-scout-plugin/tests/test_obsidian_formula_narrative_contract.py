from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
STYLE = PLUGIN_ROOT / "skills" / "obsidian-note-style" / "SKILL.md"
REFERENCE = (
    PLUGIN_ROOT
    / "skills"
    / "obsidian-note-style"
    / "references"
    / "formula-explanation-patterns.md"
)

GUIDED_HEADINGS = (
    "### 先问两个具体问题",
    "### 先给一句最核心的话",
    "### 把整条公式翻译成人话",
    "### 用一组具体数字建立感觉",
    "### 一次只解释一个符号",
    "### 再看正式定义",
    "### 逐步解释递推",
    "### 纠正最容易出现的误解",
    "### 重新合回完整公式",
    "### 性质为什么会出现",
    "### 系统作用、成立条件与边界",
    "### 符号速查表",
)


class ObsidianFormulaNarrativeContractTests(unittest.TestCase):
    def assert_heading_has_prose(
        self, text: str, heading: str, next_heading: str
    ) -> str:
        start = text.index(heading) + len(heading)
        end = text.index(next_heading, start)
        section = text[start:end]
        prose_lines = [
            line.strip()
            for line in section.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(prose_lines, f"{heading} must contain non-heading content")
        return section

    def test_complex_formulas_use_a_guided_narrative_chain(self):
        text = STYLE.read_text(encoding="utf-8")
        required = (
            "理解优先于紧凑",
            "引导式推导链",
            "一次只引入一个新概念",
            "先给具体例子，再推广到一般形式",
            "这一步意味着什么",
            "重新合回完整公式",
            "符号表放在引导式正文之后",
            "不能为了紧凑删除必要的认知台阶",
            "误解纠正后，下一语义阶段必须是重新合回完整公式",
            "不得在二者之间插入性质、系统作用、边界、跨课程公式桥或记忆句",
        )
        for phrase in required:
            self.assertIn(phrase, text)

    def test_formula_explanation_has_long_and_short_applicability_gates(self):
        text = STYLE.read_text(encoding="utf-8")
        for phrase in (
            "强制长版",
            "允许短版",
            "复杂公式的解释可以明显长于直觉层",
            "第一遍讲解不得用一张大符号表代替",
        ):
            self.assertIn(phrase, text)

    def test_bspline_k_distinction_is_mandatory_at_first_appearance(self):
        text = STYLE.read_text(encoding="utf-8")
        for phrase in (
            "首次出现 $k$ 附近",
            "$k$ 是当前基函数的次数（degree），也是当前递推层",
            "$k$ 不是控制点索引，也不是 knot 索引",
            "$B_{t,3}$ 中的 $3$ 是 $k=3$ 的特例",
            "不得推迟到符号速查表",
        ):
            self.assertIn(phrase, text)

    def test_reference_orders_guidance_before_lookup_table(self):
        text = REFERENCE.read_text(encoding="utf-8")
        headings = ("## 公式引导式解释模板",) + GUIDED_HEADINGS
        positions = [text.find(heading) for heading in headings]
        for heading, position in zip(headings, positions):
            self.assertNotEqual(-1, position, f"missing guided heading: {heading}")
        self.assertEqual(positions, sorted(positions))
        section_ends = GUIDED_HEADINGS[1:] + ("## 验收清单",)
        for heading, next_heading in zip(GUIDED_HEADINGS, section_ends):
            self.assert_heading_has_prose(text, heading, next_heading)

        questions = self.assert_heading_has_prose(
            text, GUIDED_HEADINGS[0], GUIDED_HEADINGS[1]
        )
        self.assertIn("这条公式究竟在算什么？", questions)
        self.assertIn(
            "给定一个具体的 $\\tau$，怎样从控制点得到当前位置？",
            questions,
        )
        self.assertIn("不是把前一段轨迹和后一段轨迹直接相加", text)
        self.assertIn("B-spline 不等同于一般意义的低通滤波器", text)

    def test_bspline_symbols_are_taught_before_the_lookup_table(self):
        text = REFERENCE.read_text(encoding="utf-8")
        narrative_start = text.index("### 一次只解释一个符号")
        narrative_end = text.index("### 再看正式定义", narrative_start)
        symbol_narrative = text[narrative_start:narrative_end]
        symbol_headings = (
            "**$p(\\tau)$**",
            "**$p_t$**",
            "**$B_{t,k}(\\tau)$**",
            "**$t$**",
            "**$k$**",
            "**$\\tau$**",
            "**$\\tau_t$**",
            "**$\\Delta\\tau$**",
        )
        positions = [symbol_narrative.find(heading) for heading in symbol_headings]
        for heading, position in zip(symbol_headings, positions):
            self.assertNotEqual(-1, position, f"missing symbol teaching block: {heading}")
        self.assertEqual(positions, sorted(positions))
        for index, heading in enumerate(symbol_headings):
            end = positions[index + 1] if index + 1 < len(positions) else len(symbol_narrative)
            block = symbol_narrative[positions[index]:end]
            with self.subTest(symbol=heading):
                self.assertIn("是", block, f"{heading} needs an identity/role explanation")
                self.assertRegex(
                    block,
                    r"不是|不要|不等于|不必",
                    f"{heading} needs an explicit confusion boundary",
                )

    def test_bspline_recurrence_preserves_all_layers_and_immediate_translation(self):
        text = REFERENCE.read_text(encoding="utf-8")
        recurrence = self.assert_heading_has_prose(
            text,
            "### 逐步解释递推",
            "### 纠正最容易出现的误解",
        )
        layer_markers = tuple(
            f"**第{('一', '二', '三', '四')[layer]}步：$k={layer}$"
            for layer in (0, 1, 2, 3)
        )
        positions = [recurrence.find(marker) for marker in layer_markers]
        for marker, position in zip(layer_markers, positions):
            self.assertNotEqual(-1, position, f"missing recurrence layer: {marker}")
        self.assertEqual(positions, sorted(positions))
        for index, marker in enumerate(layer_markers):
            end = positions[index + 1] if index + 1 < len(positions) else recurrence.find("```text", positions[index])
            if end == -1:
                end = len(recurrence)
            layer_block = recurrence[positions[index]:end]
            with self.subTest(layer=marker):
                self.assertIn(
                    "这一步意味着",
                    layer_block,
                    "each k stage needs its own immediate plain-language translation",
                )

    def test_bspline_derivatives_and_corb_sampling_boundary_remain_explicit(self):
        text = REFERENCE.read_text(encoding="utf-8")
        narrative_start = text.index("### 先问两个具体问题")
        narrative_end = text.index("### 符号速查表", narrative_start)
        guided_narrative = text[narrative_start:narrative_end]
        for marker in (
            "$v_t$",
            "$a_t$",
            "$j_t$",
            "span 是相邻两个 knot 之间的参数区间",
            "沿新 span 取 10 个点",
            "CORB-Planner 论文采用的**算法级采样规则**",
            "离散检查不等于整个连续 span 已获得形式化安全保证",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, guided_narrative)


if __name__ == "__main__":
    unittest.main()
