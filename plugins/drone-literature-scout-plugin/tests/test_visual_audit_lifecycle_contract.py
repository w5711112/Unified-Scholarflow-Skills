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
READ_PAPER_SKILL = (
    PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "SKILL.md"
)
COLLABORATION = PLUGIN_ROOT / "references" / "skill-collaboration-contract.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def draw_contract() -> str:
    return "\n".join(
        read(path)
        for path in (DRAW_STYLE, DRAW_VISUAL_LANGUAGE, DRAW_LAYOUT_PATTERNS)
    )


class VisualAuditLifecycleContractTests(unittest.TestCase):
    def assert_contains_all(self, text: str, phrases: tuple[str, ...]) -> None:
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_each_knowledge_point_has_zero_or_one_image_without_total_cap(self):
        text = read(OBSIDIAN_SKILL)
        self.assert_contains_all(
            text,
            (
                "每个知识点独立判断为 `0` 或 `1` 张",
                "不限制整篇笔记或一次论文处理的总图数",
                "可视化知识点在没有合格现图时默认配 `1` 张",
                "组织性标题不属于知识点",
            ),
        )

    def test_each_paper_triggers_one_whole_vault_visual_coverage_audit(self):
        text = read(READ_PAPER_SKILL)
        self.assert_contains_all(
            text,
            (
                "笔记正文和知识链接全部写入完成后",
                "每篇论文只触发一次",
                "处理中不触发",
                "Vault 全部正式知识点",
                "不限于当前论文",
                "视觉审计和必要配图完成前，不得把本次论文处理标记为完成",
            ),
        )

    def test_whole_vault_audit_is_one_pass_and_only_deep_reads_missing_candidates(self):
        text = read(OBSIDIAN_SKILL)
        self.assert_contains_all(
            text,
            (
                "每篇论文只触发一次",
                "一次结构扫描",
                "Vault 全部正式知识点",
                "已有合格图快速跳过",
                "只深入无图候选",
                "不在论文阅读、逐段写入或单张图片完成时重复触发",
                "audit_obsidian_visual_coverage.py",
            ),
        )

    def test_draw_style_uses_lightweight_image2_first_route_tree(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "同等效果和质量下",
                "A. 权威原图",
                "B. Image2（默认）",
                "C. 确定性数据生产（数据图专用）",
                "D. 最小局部修正",
                "常规新图只走",
                "公式、数学符号、坐标轴、栅格或算法内容本身都不能触发代码路线",
                "不是与 Image2 平级的日常备选",
            ),
        )
        forbidden = (
            "算法步骤、搜索扩张、几何、距离场、轨迹、曲线、公式和精确约束使用代码绘制",
            "设备、环境、三维物理过程或直观场景使用无字或少字底图",
        )
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)

    def test_image2_prompt_contract_is_semantic_blueprint_first(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "先写可核验的语义蓝图，再写最终提示词",
                "知识点与单一视觉主张",
                "布局骨架与阅读顺序",
                "对象清单及位置关系",
                "过程编码",
                "精确夹具",
                "语义配色",
                "字体、间距与原生输出要求",
                "明确禁项",
            ),
        )
        self.assertLess(text.index("语义蓝图"), text.index("科研浅色体系"))

    def test_image2_requires_strong_in_figure_explanation_and_exact_audit(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "强视觉解释能力",
                "格子、节点、边、模块或几何对象内部或近旁",
                "移除标题、图注和正文后",
                "重复序号",
                "断裂路径",
                "逐字符核对",
                "结构性失败",
                "重写语义蓝图与提示词并整图重生成",
                "单一局部小错误",
            ),
        )

    def test_image2_keeps_original_native_png_without_fake_upscaling(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "最高原生分辨率",
                "工具直接返回的原始 PNG",
                "不重新压缩",
                "不插值放大",
                "实际 Obsidian 宽度",
            ),
        )

    def test_image2_uses_one_primary_candidate_and_bounded_revision(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "一个主候选",
                "不为比较而生成多个变体",
                "提示词预检",
                "纯审美轻微偏差",
                "禁止对已语义合格候选做大面积覆盖",
            ),
        )

    def test_multi_figure_image2_batch_is_independent_and_adaptively_concurrent(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "每个知识点一个独立 Image2 请求",
                "按当前可用安全并发槽同批发出",
                "不把无关知识点塞进同一画布",
                "合格图立即冻结",
                "只把失败图",
                "下一波并发",
            ),
        )

    def test_visual_review_uses_one_actual_width_pass_without_contact_sheet(self):
        text = read(OBSIDIAN_SKILL)
        self.assert_contains_all(
            text,
            (
                "不做独立联系表复核",
                "实际 Obsidian 宽度下一次完成八项检查",
                "全部引用写入后只运行一次媒体审计",
            ),
        )

    def test_figure_reading_notes_are_collapsed_by_default(self):
        text = read(OBSIDIAN_SKILL)
        self.assert_contains_all(
            text,
            (
                "[!info]- **读图与图例**",
                "不设固定条数",
                "怎么读",
                "名词",
                "箭头/编码",
                "来源",
                "边界",
                "核心原理、公式与成立边界仍在正文展开",
            ),
        )

    def test_formula_layer_is_complete_but_compact(self):
        text = read(OBSIDIAN_SKILL)
        self.assert_contains_all(
            text,
            (
                "完整的必要计算链",
                "公式解释可以比直觉层更长",
                "不在每个短句之间插空行",
                "等宽公式教学示意",
                "紧凑表格或单行变化链",
            ),
        )

    def test_image2_speedup_never_trades_away_highest_available_quality(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "公开质量档位时必须选择最高档",
                "未公开质量档位",
                "不得虚报",
                "提速不得降低质量档位、原生分辨率、提示词完整性或验收强度",
            ),
        )

    def test_scientific_visual_grammar_is_object_led_and_directly_annotated(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "视觉对象承担主要解释",
                "直接标注优先",
                "主因果链与主轨迹较粗",
                "辅助关系较细或虚线",
                "对齐、浅底色、留白和细分隔线",
                "公式、数字和状态贴近",
                "只改变被比较因素",
                "一个主场景加一个必要局部放大图",
                "图内总标题可省略或弱化",
            ),
        )

    def test_batch_image_migration_is_two_phase_and_deletes_last(self):
        text = read(OBSIDIAN_SKILL)
        self.assert_contains_all(
            text,
            (
                "先生成并验收全部新图",
                "再更新正式引用",
                "最后删除旧格式",
            ),
        )

    def test_draw_style_requires_eight_hard_gates_and_zero_quality_loss(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "八项硬质量门槛",
                "逻辑闭环与术语落地",
                "内容完整",
                "语义准确",
                "数学与文字准确",
                "正常宽度可读",
                "紧凑但不拥挤",
                "风格与颜色有意义",
                "来源与笔记集成正确",
                "原生宽度约为计划嵌入宽度的 2 倍",
                "新图全部通过八项门槛",
                "关键维度均不弱于旧图",
            ),
        )

    def test_algorithm_figures_require_semantic_closure_before_optical_qa(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "语义完整与解释准确是前置硬门槛",
                "对象是什么",
                "输入从哪里来",
                "箭头/变换做什么",
                "输出怎样得到",
                "结论的边界是什么",
                "孤儿元素审计",
                "读者复述测试",
                "不能通过删除必要语义换取清晰",
                "连线不得穿过标签、公式或数字",
            ),
        )
        semantic_gate = "语义完整与解释准确是前置硬门槛"
        if semantic_gate in text:
            self.assertLess(
                text.index(semantic_gate),
                text.index("正常宽度可读"),
            )

    def test_figures_preserve_paper_geometry_curve_and_update_definitions(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "先读取本地原文依据",
                "论文怎样定义就怎样画",
                "矩形、类长方体、一般多边形",
                "直线、折线、B-spline",
                "透视图可以出现斜边",
                "俯视宽度和侧视高度不能混成",
                "符号、下标、数量、维度、箭头和采样区间",
                "并入现有提示词预检和七项验收",
                "不增加第二次审图或重复扫描",
            ),
        )

    def test_view_dimension_matches_the_original_object_and_paper_role(self):
        text = draw_contract()
        self.assert_contains_all(
            text,
            (
                "先选择表达维度",
                "2D",
                "2.5D",
                "3D",
                "体积、上下高度、遮挡或空间穿越关系",
                "三维主图",
                "正交俯视图",
                "不能压成一条二维带状图",
                "每个面板承担不同核对职责",
                "视觉上易懂且准确",
                "不是装饰性 3D",
            ),
        )

    def test_old_universal_rendering_rules_are_removed_from_skill_policy(self):
        text = read(OBSIDIAN_SKILL)
        forbidden = (
            "数学、算法、几何与控制机制优先绘制**确定性 SVG**",
            "**禁止渐变、阴影**",
            "主要内容距画布边缘约 `4–5%`",
            "公式本体必须转为矢量路径",
        )
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)

    def test_collaboration_contract_splits_visual_creation_and_obsidian_lifecycle(self):
        text = read(COLLABORATION)
        self.assertIn(
            "| `draw-style` | 跨场景科研绘图/视觉验收 |",
            text,
        )
        self.assertIn(
            "| `obsidian-note-style` | 知识归属/视觉覆盖/Callout/WikiLink/媒体集成 |",
            text,
        )


if __name__ == "__main__":
    unittest.main()
