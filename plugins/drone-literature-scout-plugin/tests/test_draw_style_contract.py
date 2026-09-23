from __future__ import annotations

import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DRAW_STYLE = PLUGIN_ROOT / "skills" / "draw-style" / "SKILL.md"
DRAW_AGENT = PLUGIN_ROOT / "skills" / "draw-style" / "agents" / "openai.yaml"
DRAW_REFS = PLUGIN_ROOT / "skills" / "draw-style" / "references"
RSS_LEDGER = DRAW_REFS / "rss2026-learning-ledger.md"
COLOR_FONT_ARCHIVE = DRAW_REFS / "color-font-archive.md"
DATA_CHART_SELECTOR = DRAW_REFS / "data-chart-selector.md"
COLLAB_CONTRACT = PLUGIN_ROOT / "references" / "skill-collaboration-contract.md"


class DrawStyleContractTests(unittest.TestCase):
    def test_draw_style_is_discoverable_from_its_canonical_directory(self):
        self.assertTrue(DRAW_STYLE.is_file())
        self.assertTrue(DRAW_AGENT.is_file())

    def test_main_skill_is_lightweight_and_routes_four_scenarios(self):
        text = DRAW_STYLE.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 500)
        for phrase in (
            "PPT 图",
            "Obsidian 知识点图",
            "正式论文方法/原理图",
            "正式论文数据图/表格",
            "按需加载",
            "不统一成一种风格",
        ):
            self.assertIn(phrase, text)

    def test_confirmed_personal_palette_is_available_without_rss_ledger(self):
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        self.assertTrue(COLOR_FONT_ARCHIVE.is_file())
        archive = COLOR_FONT_ARCHIVE.read_text(encoding="utf-8")
        combined = f"{visual}\n{archive}"
        self.assertIn("用户确认的稳定个人配色", skill)
        for color in (
            "#8062AA", "#4D94D8", "#839F39", "#FD7F0E", "#F14C4A",
            "#5F5F5F",
        ):
            self.assertIn(color, visual)
        for color in (
            "#8062AA", "#8B70B1", "#E4DEEC", "#F1EEF5", "#E3E9F3",
            "#D7E0EF", "#E6F3E5", "#FDF1E6", "#D8D8D8",
            "#F14C4A", "#DD8182", "#F58484", "#FAC0BE", "#FBE1E0",
            "#FCECEC", "#FFF5F4", "#00B050", "#FF0000", "#E2F0D9",
            "#4472C4", "#7E9ED6", "#BFCFEA", "#C00000", "#DF7F7F",
            "#EFBFBF", "#CFE5FE", "#9CCBFE", "#63B1FE", "#0096FE",
            "#EAD0D1", "#D6A0A3", "#C36A6F", "#AC3237", "#FBD35A",
            "#FECF16", "#2D0B63", "#FD7F0E", "#FE8418", "#FE8F2C",
            "#FE9A41", "#FEAC64", "#FECB9E", "#4F94C4", "#71A7CE",
            "#96BFDB", "#B8D4E6", "#0000FF", "#FF0000", "#E5F2F2",
            "#EDEDED", "#DBDBDB", "#464AA0", "#9AC7DF", "#BDE2ED",
            "#DCF1F7", "#EDF7E7", "#FAFDCE", "#FFF7BB", "#FDE09A",
            "#FDC37D", "#FAA267", "#F58359", "#E45744", "#C9343C",
            "#AE1A3C",
        ):
            self.assertIn(color, combined)
        for phrase in (
            "少量深紫＋大面积浅紫",
            "红线主体是纯红",
            "不把显示色阶当作离散类别色",
            "不能唯一反推作者源色和 alpha",
            "关系图纯色＋超浅上下文",
            "Optimization Potential 冷暖势场",
        ):
            self.assertIn(phrase, combined)

    def test_compact_color_selector_has_one_default_route_per_scene(self):
        self.assertTrue(COLOR_FONT_ARCHIVE.is_file())
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        archive = COLOR_FONT_ARCHIVE.read_text(encoding="utf-8")
        for phrase in (
            "六个核心色族",
            "四条连续数据色阶",
            "T1 高级紫",
            "T2 RSS060 柔和非对称流程",
            "T3 RSS067 抽象问题—方案对比",
            "只有精确复现才查询历史档案",
            "蓝色顺序色阶",
            "红色顺序色阶",
            "发散色阶",
            "冷暖势场色阶",
        ):
            self.assertIn(phrase, visual)
        self.assertIn("jet-like", archive)
        self.assertIn("不作为新图默认", archive)
        for phrase in (
            "六个核心色族",
            "四条连续数据色阶",
            "三套命名模板",
            "精确复现时才加载",
            "color-font-archive.md",
        ):
            self.assertIn(phrase, skill)

    def test_font_selector_routes_by_role_with_explicit_fallbacks(self):
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        for phrase in (
            "DejaVu Sans",
            "Arial",
            "Source Sans 3",
            "Source Han Sans SC",
            "Microsoft YaHei",
            "STIX Two Math",
            "Latin Modern Math",
            "Comic Sans MS",
            "Comic Neue",
            "手写感只用于短标签",
        ):
            self.assertIn(phrase, visual)

    def test_draw_style_owns_blueprint_generation_and_quality_review(self):
        text = DRAW_STYLE.read_text(encoding="utf-8")
        for phrase in (
            "语义蓝图",
            "单一视觉主张",
            "2D、2.5D、3D",
            "A. 权威原图",
            "B. Image2（默认）",
            "C. 确定性数据生产（数据图专用）",
            "D. 最小局部修正",
            "八项硬质量门槛",
            "最高原生分辨率",
            "公开质量档位时必须选择最高档",
            "不重新压缩",
            "逐字符核对",
        ):
            self.assertIn(phrase, text)

    def test_explanatory_figures_require_logical_closure_and_owned_legend_semantics(self):
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        obsidian = (DRAW_REFS / "obsidian-knowledge-figures.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "逻辑闭环与术语落地",
            "对象是什么 → 输入从哪里来 → 箭头/变换做什么 → 输出怎样得到 → 结论的边界是什么",
            "解释责任方",
            "孤儿元素审计",
            "读者复述测试",
        ):
            self.assertIn(phrase, f"{skill}\n{visual}")
        for phrase in (
            "阅读顺序与一句话机制",
            "术语、缩写与符号",
            "箭头、线型、颜色和编号",
            "数字、样本、阈值或中间状态",
            "图不能推出什么",
        ):
            self.assertIn(phrase, obsidian)

    def test_obsidian_figures_do_not_replace_formula_cards(self):
        text = (DRAW_REFS / "obsidian-knowledge-figures.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "不能替代公式卡",
            "同一套符号",
            "公式正文解释",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_draw_style_distinguishes_data_uncertainty(self):
        text = (DRAW_REFS / "paper-data-figures.md").read_text(encoding="utf-8")
        for phrase in (
            "标准差（SD）",
            "标准误（SE）",
            "95% CI",
            "未定义时不猜",
            "样本量",
            "灰度打印",
        ):
            self.assertIn(phrase, text)

    def test_required_reference_files_exist(self):
        expected = {
            "visual-language.md",
            "layout-patterns.md",
            "ppt-figures.md",
            "obsidian-knowledge-figures.md",
            "paper-method-figures.md",
            "paper-data-figures.md",
            "data-chart-selector.md",
        }
        self.assertTrue(expected.issubset({path.name for path in DRAW_REFS.glob("*.md")}))

    def test_rss_analysis_requires_exhaustive_reading_and_a_learning_focus(self):
        protocol = (DRAW_REFS / "rss2026-analysis-protocol.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "图的范式类别",
            "本图最值得学习什么",
            "逐元素账本",
            "箭头/连线账本",
            "起点 → 终点",
            "图—图关系",
            "文字—图形关系",
            "逐字符核对",
            "不得用“等”“若干”省略",
            "10 图审阅窗口",
            "底层仍按每 5 张",
            "用户重点采用完整核读",
            "重复技巧只记录差异",
            "绘制一般的部分只保留必要",
        ):
            self.assertIn(phrase, protocol)

        batch = (
            DRAW_REFS / "rss2026-batches" / "batch-001.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(batch.count("- 图的范式类别："), 5)
        self.assertEqual(batch.count("### 3. 逐元素与连接核读"), 5)
        self.assertEqual(
            batch.count("### 9. 本图最值得学习什么（收录理由）"), 5
        )

    def test_rss_learning_ledger_preserves_user_priorities_and_routes_analysis(self):
        self.assertTrue(RSS_LEDGER.is_file())
        ledger = RSS_LEDGER.read_text(encoding="utf-8")
        for phrase in (
            "用户个人学习重点",
            "补充核读",
            "RSS2026_001",
            "RSS2026_010",
            "Lidar Point Clouds",
            "2.5D",
            "Outer Loop - Collision refinement",
            "Inner Loop — Optimize each module",
            "完整的矩形",
            "主线深色加粗",
            "极简知识点图",
        ):
            self.assertIn(phrase, ledger)
        current = ledger.split("## 四、第 3–4 批", 1)[1].split(
            "## 五、第 5–6 批", 1
        )[0]
        self.assertEqual(current.count("- **定位信息**："), 10)
        self.assertEqual(current.count("- **用户个人学习重点**："), 10)

        protocol = (DRAW_REFS / "rss2026-analysis-protocol.md").read_text(
            encoding="utf-8"
        )
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        self.assertIn("rss2026-learning-ledger.md", protocol)
        self.assertIn("rss2026-analysis-protocol.md", skill)
        self.assertIn("rss2026-learning-ledger.md", skill)

    def test_rss_learning_ledger_registers_user_focus_for_011_to_020(self):
        ledger = RSS_LEDGER.read_text(encoding="utf-8")
        for phrase in (
            "RSS2026_011",
            "RSS2026_020",
            "Human to Robot Transfer on Generalization Tasks",
            "Task generalization performance scaling",
            "从白到紫",
            "韦恩图",
            "瓶子状",
            "TouchGuide",
            "正态分布样式",
            "柱顶置信",
            "+21%",
            "half 与非 half",
        ):
            self.assertIn(phrase, ledger)

    def test_rss_batch_002_has_five_exhaustive_frozen_cards(self):
        batch = (
            DRAW_REFS / "rss2026-batches" / "batch-002.md"
        ).read_text(encoding="utf-8")
        for logical_id in range(6, 11):
            self.assertIn(f"## RSS2026_{logical_id:03d}", batch)
        self.assertEqual(batch.count("- 图的范式类别："), 5)
        self.assertEqual(batch.count("- **用户个人学习重点**："), 5)
        self.assertEqual(batch.count("- **补充核读**："), 5)
        self.assertEqual(batch.count("### 3. 逐元素与连接核读"), 5)
        self.assertEqual(
            batch.count("### 9. 本图最值得学习什么（收录理由）"), 5
        )
        self.assertIn("状态：已确认并冻结", batch)

    def test_rss_batches_003_and_004_have_ten_focused_frozen_cards(self):
        combined = "\n".join(
            (
                DRAW_REFS / "rss2026-batches" / filename
            ).read_text(encoding="utf-8")
            for filename in ("batch-003.md", "batch-004.md")
        )
        for logical_id in range(11, 21):
            self.assertIn(f"## RSS2026_{logical_id:03d}", combined)
        self.assertEqual(combined.count("- 图的范式类别："), 10)
        self.assertEqual(combined.count("- **用户个人学习重点**："), 10)
        self.assertEqual(combined.count("- **补充核读**："), 10)
        self.assertEqual(combined.count("### 3. 逐元素与连接核读"), 10)
        self.assertEqual(
            combined.count("### 9. 本图最值得学习什么（收录理由）"), 10
        )
        self.assertEqual(combined.count("状态：已确认并冻结"), 2)
        for phrase in (
            "偏移背板",
            "统计口径未从截图确认",
            "±1 StdErr",
            "嵌套高度层",
            "小提琴图",
            "V = Visual Observation",
            "概念性分布示意",
            "95% finite-sample CI",
            "基线柱顶到本方法柱顶",
            "half 用虚线、非 half 用实线",
        ):
            self.assertIn(phrase, combined)

    def test_confirmed_rss_patterns_route_to_their_stable_references(self):
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        for phrase in (
            "近邻浅色",
            "统一轻阴影",
            "左窄标签区、右宽流程区",
            "异构分支使用不同视觉介质",
        ):
            self.assertIn(phrase, visual)

        layout = (DRAW_REFS / "layout-patterns.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("原位框选 → 虚线引线 → 极简放大窗", layout)
        self.assertIn("集合 → 过程 → 数据结果", layout)
        for phrase in (
            "M1 实施合同",
            "纯局部放大",
            "参数/尺度切换",
            "M8 空间事实合同",
        ):
            self.assertIn(phrase, layout)

        method = (DRAW_REFS / "paper-method-figures.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "完整但不过载",
            "并行输入 → 主视觉场景 → 必要公式 → 紧凑关系图 → 输出",
            "外部 I/O → 内部节点 → 框内子语义",
            "训练定义 → 推理插入 → 分布转向 → 现实结果",
            "2D 动作分布与 3D 可行性评分面",
            "M2 跨表示身份合同",
            "M3 箭头职责",
            "共享曲率语言",
            "孤立重阴影",
        ):
            self.assertIn(phrase, method)

        data = (DRAW_REFS / "paper-data-figures.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "3D 空间数据图",
            "半透明多面体",
            "内部散点",
            "半透明球体",
            "三轴名称与单位",
            "相机角度",
            "box aspect",
            "深粗中心趋势＋浅细个体样本",
            "固定偏移背板",
            "同色半透明不确定性带",
            "单色相明度序列",
            "嵌套高度层",
            "小提琴图",
            "柱顶比较括号",
            "颜色编码方法、线型编码变体",
            "small-multiple 热图",
            "M4 不确定性合同",
            "M7 响应面合同",
            "协方差椭圆",
            "等值线不是物理水波纹",
        ):
            self.assertIn(phrase, data)

        obsidian = (DRAW_REFS / "obsidian-knowledge-figures.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("同构最小例子", obsidian)
        self.assertIn("概念性分布示意", obsidian)

        protocol = (DRAW_REFS / "rss2026-analysis-protocol.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("标题只作定位", protocol)

    def test_rss_master_pattern_selector_is_available_without_loading_individual_cards(self):
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        archive = COLOR_FONT_ARCHIVE.read_text(encoding="utf-8")
        for pattern in (
            "M1 极简同构状态序列",
            "M2 跨表示方法链",
            "M3 有边界的系统流程",
            "M4 轨迹—不确定性—细节证据",
            "M5 离散比较与有序渐变",
            "M6 分布与多指标诊断",
            "M7 连续场、等值线与响应面",
            "M8 2.5D/3D 空间事实",
        ):
            self.assertIn(pattern, visual)
        self.assertIn("一个主母版", skill)
        self.assertIn("最多一个辅助母版", skill)
        self.assertIn("不直接模仿某一张 RSS 图的全部外观", skill)
        for color in ("#00007F", "#7AFF7D", "#7F0000"):
            self.assertIn(color, archive)
        self.assertIn("深蓝→蓝→青→绿→黄→橙→红→深红", archive)
        self.assertNotIn("jet-like", visual)
        self.assertIn("不作为新图默认", archive)

    def test_user_confirmed_batches_009_and_010_are_frozen(self):
        for filename in ("batch-009.md", "batch-010.md"):
            batch = (
                DRAW_REFS / "rss2026-batches" / filename
            ).read_text(encoding="utf-8")
            self.assertIn("状态：已确认并冻结", batch)
            self.assertNotIn("待用户确认，未冻结", batch)

        ledger = RSS_LEDGER.read_text(encoding="utf-8")
        for row in (
            "| 009 | RSS2026_041—045 | 已确认并冻结 |",
            "| 010 | RSS2026_046—050 | 已确认并冻结 |",
        ):
            self.assertIn(row, ledger)

    def test_confirmed_style_supports_dense_rounded_bars_and_asymmetric_process_layouts(self):
        data = (DRAW_REFS / "paper-data-figures.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "圆角条形",
            "高占空比",
            "条宽大于组间留白",
            "白色外圈端点",
        ):
            self.assertIn(phrase, data)

        method = (DRAW_REFS / "paper-method-figures.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "不规则但流程清晰",
            "非对称平衡",
            "大框、小框、层叠卡与梯形",
            "黄金分割只作构图候选",
        ):
            self.assertIn(phrase, method)

    def test_rss060_is_a_template_level_top_priority_master(self):
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        method = (DRAW_REFS / "paper-method-figures.md").read_text(
            encoding="utf-8"
        )
        ledger = (DRAW_REFS / "rss2026-learning-ledger.md").read_text(
            encoding="utf-8"
        )

        for phrase in ("M1—M9", "M9 非对称模块星座", "模板级优先判断"):
            self.assertIn(phrase, skill)
        for phrase in (
            "M9 非对称模块星座（模板级）",
            "最高优先级之一",
            "RSS2026_060",
        ):
            self.assertIn(phrase, visual)
        for phrase in (
            "### 3.3 M9 非对称模块星座",
            "模板级基准",
            "先判断是否适用 M9",
        ):
            self.assertIn(phrase, method)
        for phrase in ("模板级参考", "全库前列", "RSS2026_060"):
            self.assertIn(phrase, ledger)

    def test_flowchart_depth_and_data_occupancy_are_explicit_contracts(self):
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        method = (DRAW_REFS / "paper-method-figures.md").read_text(encoding="utf-8")
        data = (DRAW_REFS / "paper-data-figures.md").read_text(encoding="utf-8")
        for phrase in ("接触阴影", "扩散阴影", "外部右下"):
            self.assertIn(phrase, skill)
            self.assertIn(phrase, visual)
        for phrase in ("两层外部右下阴影", "视觉锚点", "禁止发光"):
            self.assertIn(phrase, method)
        for phrase in ("70%—85%", "有效绘图区", "10—11 pt", "无意义留白"):
            self.assertIn(phrase, data)

    def test_rss061_to_070_consolidate_into_existing_master_contracts(self):
        data = (DRAW_REFS / "paper-data-figures.md").read_text(encoding="utf-8")
        method = (DRAW_REFS / "paper-method-figures.md").read_text(
            encoding="utf-8"
        )
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        ledger = RSS_LEDGER.read_text(encoding="utf-8")

        for phrase in (
            "测量点＋插值曲面",
            "白色曲面网格",
            "黑色实测点",
            "有序密度支持序列",
            "图标化散点",
            "大号坐标文字",
        ):
            self.assertIn(phrase, data)
        for phrase in (
            "完整外框内错落",
            "有边界的非对称填充",
            "任务指令卡",
        ):
            self.assertIn(phrase, method)
        for phrase in (
            "RSS2026_061",
            "RSS2026_062",
            "RSS2026_065",
            "RSS2026_067",
            "RSS2026_068",
            "RSS2026_069",
            "RSS2026_070",
        ):
            self.assertIn(phrase, visual)

        combined = "\n".join(
            (
                DRAW_REFS / "rss2026-batches" / filename
            ).read_text(encoding="utf-8")
            for filename in ("batch-013.md", "batch-014.md")
        )
        for logical_id in range(61, 71):
            self.assertIn(f"## RSS2026_{logical_id:03d}", combined)
            self.assertIn(f"RSS2026_{logical_id:03d}", ledger)
        self.assertEqual(combined.count("- 图的范式类别："), 10)
        self.assertEqual(combined.count("### 3. 逐元素与连接核读"), 10)
        self.assertEqual(
            combined.count("### 9. 本图最值得学习什么（收录理由）"), 10
        )
        self.assertEqual(combined.count("状态：待用户确认，未冻结"), 2)
        self.assertNotIn("状态：已确认并冻结", combined)

        for phrase in (
            "#C87B60",
            "#839F39",
            "#F0D98C",
            "#B94E5E",
            "#F9F8F6",
            "#568BBF",
            "#DBE9F6",
            "#145F81",
            "#D8F1CF",
        ):
            self.assertIn(phrase, ledger)
        for row in (
            "| 013 | RSS2026_061—065 | 待用户确认，未冻结 |",
            "| 014 | RSS2026_066—070 | 待用户确认，未冻结 |",
        ):
            self.assertIn(row, ledger)

    def test_data_chart_selector_is_distribution_first_and_human_selected(self):
        self.assertTrue(DATA_CHART_SELECTOR.is_file())
        selector = DATA_CHART_SELECTOR.read_text(encoding="utf-8")
        for phrase in (
            "数据语义体检",
            "候选图型短名单",
            "优点",
            "缺点",
            "误读风险",
            "人工定型门",
            "2—4 个",
            "用户作最终选择",
            "准确、实用、高级、克制美观、排版合理",
        ):
            self.assertIn(phrase, selector)

    def test_data_chart_selector_routes_wps_python_matlab_and_mixed_panels(self):
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        selector = DATA_CHART_SELECTOR.read_text(encoding="utf-8")
        for phrase in (
            "数据结构 → 候选图型 → 人工定型 → 生产软件",
            "data-chart-selector.md",
            "visualizing-and-writing-modeling-papers",
        ):
            self.assertIn(phrase, skill)
        for phrase in (
            "WPS",
            "Python",
            "MATLAB",
            "逐面板混合路线",
            "WPS 能完成",
            "数据血缘",
            "可编辑",
        ):
            self.assertIn(phrase, selector)

    def test_draw_style_collaboration_contract_reference_resolves(self):
        self.assertTrue(COLLAB_CONTRACT.is_file())
        skill = DRAW_STYLE.read_text(encoding="utf-8")
        self.assertIn("../../references/skill-collaboration-contract.md", skill)
        self.assertNotIn(
            "读取 `references/skill-collaboration-contract.md`",
            skill,
        )

    def test_rss071_to_080_have_complete_pending_cards_and_ledger_entries(self):
        combined = "\n".join(
            (
                DRAW_REFS / "rss2026-batches" / filename
            ).read_text(encoding="utf-8")
            for filename in ("batch-015.md", "batch-016.md")
        )
        ledger = RSS_LEDGER.read_text(encoding="utf-8")
        for logical_id in range(71, 81):
            logical_name = f"RSS2026_{logical_id:03d}"
            self.assertIn(f"## {logical_name}", combined)
            self.assertIn(logical_name, ledger)
        self.assertEqual(combined.count("- 图的范式类别："), 10)
        self.assertEqual(combined.count("- **用户个人学习重点**："), 10)
        self.assertEqual(combined.count("- **补充核读**："), 10)
        self.assertEqual(combined.count("### 3. 逐元素与连接核读"), 10)
        self.assertEqual(
            combined.count("### 9. 本图最值得学习什么（收录理由）"),
            10,
        )
        self.assertEqual(combined.count("状态：待用户确认，未冻结"), 2)
        self.assertNotIn("状态：已确认并冻结", combined)
        for row in (
            "| 015 | RSS2026_071—075 | 待用户确认，未冻结 |",
            "| 016 | RSS2026_076—080 | 待用户确认，未冻结 |",
        ):
            self.assertIn(row, ledger)

    def test_rss071_to_080_strengthen_evidence_layers_without_new_hex_palette(self):
        data = (DRAW_REFS / "paper-data-figures.md").read_text(encoding="utf-8")
        method = (DRAW_REFS / "paper-method-figures.md").read_text(
            encoding="utf-8"
        )
        layout = (DRAW_REFS / "layout-patterns.md").read_text(encoding="utf-8")
        ledger = RSS_LEDGER.read_text(encoding="utf-8")
        for phrase in (
            "实物场景—定量诊断映射",
            "分位区间",
            "共享坐标域的算法轨迹比较",
            "差值解释层",
            "雷达灰色坐标骨架",
        ):
            self.assertIn(phrase, data)
        for phrase in (
            "极简对象几何＋变量夹具",
            "资源层级—并行计算映射",
            "渐变粗箭头",
        ):
            self.assertIn(phrase, method)
        for phrase in (
            "紧凑分区证据板",
            "共享几何逐层揭示",
            "圆形局部向量判别窗",
        ):
            self.assertIn(phrase, layout)
        rss_window = ledger.split(
            "## 十一、第 15–16 批", 1
        )[1].split("## 十二、第 17–18 批", 1)[0]
        self.assertIsNone(re.search(r"#[0-9A-Fa-f]{6}\b", rss_window))

    def test_rss081_to_090_have_complete_pending_cards_and_ledger_entries(self):
        combined = "\n".join(
            (
                DRAW_REFS / "rss2026-batches" / filename
            ).read_text(encoding="utf-8")
            for filename in ("batch-017.md", "batch-018.md")
        )
        ledger = RSS_LEDGER.read_text(encoding="utf-8")
        for logical_id in range(81, 91):
            logical_name = f"RSS2026_{logical_id:03d}"
            self.assertIn(f"## {logical_name}", combined)
            self.assertIn(logical_name, ledger)
        self.assertEqual(combined.count("- 图的范式类别："), 10)
        self.assertEqual(combined.count("- **用户个人学习重点**："), 10)
        self.assertEqual(combined.count("- **补充核读**："), 10)
        self.assertEqual(combined.count("### 3. 逐元素与连接核读"), 10)
        self.assertEqual(
            combined.count("### 9. 本图最值得学习什么（收录理由）"),
            10,
        )
        self.assertEqual(combined.count("状态：待用户确认，未冻结"), 2)
        self.assertNotIn("状态：已确认并冻结", combined)
        for row in (
            "| 017 | RSS2026_081—085 | 待用户确认，未冻结 |",
            "| 018 | RSS2026_086—090 | 待用户确认，未冻结 |",
        ):
            self.assertIn(row, ledger)

    def test_rss081_to_090_strengthen_pseudocode_spatial_and_coverage_contracts(self):
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        archive = COLOR_FONT_ARCHIVE.read_text(encoding="utf-8")
        method = (DRAW_REFS / "paper-method-figures.md").read_text(
            encoding="utf-8"
        )
        data = (DRAW_REFS / "paper-data-figures.md").read_text(
            encoding="utf-8"
        )
        layout = (DRAW_REFS / "layout-patterns.md").read_text(encoding="utf-8")
        selector = DATA_CHART_SELECTOR.read_text(encoding="utf-8")
        for phrase in (
            "#F2F2F2",
            "#3F3F3F",
            "最浅中性承载面",
            "#F4F8FB",
            "#D0E2F1",
            "#FEF4F2",
            "#F9DAC5",
        ):
            self.assertIn(phrase, archive)
        self.assertIn("#F2F2F2", visual)
        for phrase in (
            "伪代码算法卡",
            "语义分区的低对比渐变底",
            "阶段闭环证据卡",
            "高饱和色相轮换",
            "公式占位不等于视觉解释",
        ):
            self.assertIn(phrase, method)
        for phrase in (
            "3D 主景—正交核验—同刻度实景",
            "跨表示状态锚",
        ):
            self.assertIn(phrase, layout)
        for phrase in (
            "覆盖场＋阈值边界",
            "共享色条",
            "候选位置",
        ):
            self.assertIn(phrase, data)
            self.assertIn(phrase, selector)

    def test_rss091_to_103_have_complete_pending_cards_and_ledger_entries(self):
        combined = "\n".join(
            (
                DRAW_REFS / "rss2026-batches" / filename
            ).read_text(encoding="utf-8")
            for filename in ("batch-019.md", "batch-020.md", "batch-021.md")
        )
        ledger = RSS_LEDGER.read_text(encoding="utf-8")
        for logical_id in range(91, 104):
            logical_name = f"RSS2026_{logical_id:03d}"
            self.assertIn(f"## {logical_name}", combined)
            self.assertIn(logical_name, ledger)
        self.assertEqual(combined.count("- 图的范式类别："), 13)
        self.assertEqual(combined.count("- **用户个人学习重点**："), 13)
        self.assertEqual(combined.count("- **补充核读**："), 13)
        self.assertEqual(combined.count("### 3. 逐元素与连接核读"), 13)
        self.assertEqual(
            combined.count("### 9. 本图最值得学习什么（收录理由）"),
            13,
        )
        self.assertEqual(combined.count("状态：待用户确认，未冻结"), 3)
        self.assertNotIn("状态：已确认并冻结", combined)
        for row in (
            "| 019 | RSS2026_091—095 | 待用户确认，未冻结 |",
            "| 020 | RSS2026_096—100 | 待用户确认，未冻结 |",
            "| 021 | RSS2026_101—103 | 待用户确认，未冻结 |",
        ):
            self.assertIn(row, ledger)

    def test_rss091_to_103_consolidate_line_gray_data_and_lda_contracts(self):
        visual = (DRAW_REFS / "visual-language.md").read_text(encoding="utf-8")
        archive = COLOR_FONT_ARCHIVE.read_text(encoding="utf-8")
        method = (DRAW_REFS / "paper-method-figures.md").read_text(
            encoding="utf-8"
        )
        data = (DRAW_REFS / "paper-data-figures.md").read_text(
            encoding="utf-8"
        )
        layout = (DRAW_REFS / "layout-patterns.md").read_text(encoding="utf-8")
        selector = DATA_CHART_SELECTOR.read_text(encoding="utf-8")

        for phrase in (
            "极简线条知识点图的信息上限",
            "物理边界短排线",
            "操作性视觉落点",
            "蓝橙双主色竞争",
            "蓝紫双专家架构",
        ):
            self.assertIn(phrase, method)
        for phrase in (
            "包络带 small multiples",
            "组内倍率/差值 callout",
            "t-SNE 嵌入投影",
            "安全集场＋零水平边界＋梯度箭头",
            "共享色条",
        ):
            self.assertIn(phrase, data)
        for phrase in (
            "渐进灰阶阶段底板",
            "圆角重叠接缝",
        ):
            self.assertIn(phrase, layout)
        for phrase in (
            "t-SNE 嵌入投影",
            "安全集场＋零水平边界＋梯度箭头",
        ):
            self.assertIn(phrase, selector)
        for phrase in (
            "T1-B 蓝紫双专家",
            "RSS2026_103",
        ):
            self.assertIn(phrase, visual)
        for color in (
            "#F9F9F9",
            "#F1F1F1",
            "#D8D8D8",
            "#BEBEBE",
            "#F9F8F7",
            "#D9E2F2",
            "#9CC2E5",
            "#2F5395",
            "#702F9F",
            "#ECEEF7",
        ):
            self.assertIn(color, archive)


if __name__ == "__main__":
    unittest.main()
